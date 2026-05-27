"""模型列表缓存管理 - 线程安全的文件缓存实现"""
import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("QwenServer")


class ModelCache:
    """模型列表缓存管理器 - 使用双重检查锁模式

    架构说明:
        authenticated_client 的所有权属于调用方 (app.py 的 lifespan),
        ModelCache 仅持有引用用于 API 请求。调用方负责在 ModelCache
        生命周期结束后关闭客户端。ModelCache.close() 不会关闭 authenticated_client。

        重要：authenticated_client 在初始化绑定后不再修改。401 降级时仅记录警告，
        不置 None，不添加状态标志。后续请求继续使用原引用（若仍 401，
        由调用方决定重新登录或替换客户端）。
    """

    CACHE_FILE = "model_cache.json"
    DEFAULT_TTL = 1800  # 默认缓存有效期 30 分钟
    API_TIMEOUT = 10.0  # API 调用超时时间（秒）
    BASE_URL = "https://chat.qwen.ai"

    def __init__(self, cache_dir: str = ".", ttl: int | None = None,
                 authenticated_client: httpx.AsyncClient | None = None):
        self.cache_dir = Path(cache_dir)
        self.cache_file = self.cache_dir / self.CACHE_FILE
        self.ttl = ttl or self.DEFAULT_TTL
        self._lock = asyncio.Lock()
        # 已认证的 httpx 客户端，用于获取完整模型列表。
        # 所有权属于调用方（app.py lifespan 中的 AsyncQwenClient），
        # ModelCache 仅持有引用，不会关闭此客户端。
        # 初始化绑定后不再修改此引用。401 降级仅记录警告。
        self.authenticated_client = authenticated_client

    def _get_cached_data(self) -> dict[str, Any] | None:
        """从文件读取缓存数据（同步操作，无锁）"""
        if not self.cache_file.exists():
            return None
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "data" not in data or "timestamp" not in data:
                return None
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取缓存文件失败：{e}")
            return None

    def _write_cache(self, models_data: dict[str, Any]) -> bool:
        """写入缓存文件（同步操作，无锁）"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(models_data, f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            logger.error(f"写入缓存文件失败：{e}")
            return False

    def _is_cache_expired(self, cached_data: dict[str, Any]) -> bool:
        """检查缓存是否过期（严格大于才过期）"""
        timestamp = cached_data.get("timestamp", 0)
        return time.time() - timestamp > self.ttl

    # Headers aligned with the browser client. x-request-id is generated per request.
    AUTH_HEADERS = {
        "accept": "application/json",
        "referer": "https://chat.qwen.ai/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    async def fetch_models_from_api(self) -> dict[str, Any] | None:
        """从 Qwen 官方 API 动态获取模型列表（网络请求，在锁外执行）

        优先使用已认证客户端获取完整模型列表（认证=20个模型），如果未提供或
        返回 401，则降级到未登录模式获取公开模型列表（未登录=3个模型）。

        认证客户端请求会携带与浏览器端一致的 headers，减少网页侧接口返回
        非 JSON 内容的概率。

        Returns:
            格式化后的模型列表数据，失败返回 None
        """
        try:
            # 优先使用已认证客户端获取完整模型列表
            if self.authenticated_client is not None:
                logger.info("使用已认证客户端获取模型列表")
                headers = {
                    **self.AUTH_HEADERS,
                    "x-request-id": str(uuid.uuid4()),
                }
                resp = await self.authenticated_client.get(
                    f"{self.BASE_URL}/api/models", headers=headers
                )
                logger.info(f"API 响应状态码：{resp.status_code}, 内容长度：{len(resp.text)}")

                # 网页接口返回 HTML 而非 JSON 时，content-type 通常为 text/html
                content_type = resp.headers.get("content-type", "")
                if resp.status_code == 200 and not content_type.startswith("application/json"):
                    logger.warning(f"认证客户端返回非 JSON 响应 (ct={content_type}), 降级到未登录模式")
                elif resp.status_code == 401:
                    logger.warning("已认证客户端 session 过期，降级到未登录模式")
                elif resp.status_code == 200 and content_type.startswith("application/json"):
                    if not resp.text or not resp.text.strip():
                        logger.warning("认证客户端返回空响应，降级到未登录模式")
                    else:
                        try:
                            data = resp.json()
                        except json.JSONDecodeError as e:
                            logger.warning(f"认证客户端返回非法 JSON（{e}），降级到未登录模式")
                        else:
                            return self._format_models(data)
                else:
                    logger.warning(f"已认证客户端获取失败 (status={resp.status_code}), 降级到未登录模式")

            # 未登录模式：使用独立客户端获取公开模型列表
            logger.info("使用未登录模式获取模型列表")
            unauth_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with httpx.AsyncClient(timeout=self.API_TIMEOUT, headers=unauth_headers) as client:
                resp = await client.get(f"{self.BASE_URL}/api/models")
                logger.info(f"API 响应状态码：{resp.status_code}")
                if resp.status_code == 200:
                    if not resp.text or not resp.text.strip():
                        logger.warning("API 返回空响应")
                        return None
                    try:
                        data = resp.json()
                    except json.JSONDecodeError as e:
                        logger.error(f"未登录模式 JSON 解析失败：{e}")
                        return None
                    return self._format_models(data)
        except httpx.TimeoutException:
            logger.error("获取模型列表超时")
        except httpx.RequestError as e:
            logger.error(f"网络请求失败：{e}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败：{e}")
        except Exception as e:
            logger.error(f"获取模型列表失败：{e}", exc_info=True)
        return None

    def _format_models(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """格式化 API 响应为标准 OpenAI 格式

        空模型列表返回 None，让路由层走 fallback 硬编码列表，
        避免向用户返回空列表。
        """
        models_list = data.get("data", [])
        if not models_list:
            return None
        return {
            "object": "list",
            "data": [
                {
                    "id": m.get("id", "unknown"),
                    "object": "model",
                    "created": m.get("info", {}).get("created_at", int(time.time())),
                    "owned_by": m.get("owned_by", "qwen"),
                }
                for m in models_list
            ],
        }

    async def get_models(self, force_refresh: bool = False) -> dict[str, Any] | None:
        """获取模型列表，优先使用缓存（双重检查锁模式）

        Args:
            force_refresh: 是否强制刷新缓存

        Returns:
            模型列表数据（不包含内部 timestamp 字段），所有缓存都不可用时返回 None

        核心逻辑:
            1. 无锁快速路径：检查缓存是否可用且未过期
            2. 需要刷新时加锁，双重检查防止锁等待期间已刷新
            3. API 获取失败时 fallback 到旧缓存数据
            4. 只有无缓存且 API 失败时才返回 None
        """
        # 第一次检查：无锁，快速路径
        cached = self._get_cached_data()
        if cached and not force_refresh and not self._is_cache_expired(cached):
            result = cached.copy()
            result.pop("timestamp", None)
            return result

        # 需要刷新：加锁，双重检查
        async with self._lock:
            # 双重检查：防止锁等待期间其他协程已刷新
            cached = self._get_cached_data()
            if cached and not force_refresh and not self._is_cache_expired(cached):
                result = cached.copy()
                result.pop("timestamp", None)
                return result

            # 网络请求（锁内，但这是防止并发请求的必要范围）
            logger.info("刷新模型缓存...")
            fresh_data = await self.fetch_models_from_api()

            if fresh_data:
                fresh_data["timestamp"] = int(time.time())
                self._write_cache(fresh_data)
                result = fresh_data.copy()
                result.pop("timestamp", None)
                return result

            # API 获取失败：fallback 到旧缓存数据
            if cached is not None:
                logger.warning("API 获取失败，使用过期缓存")
                result = cached.copy()
                result.pop("timestamp", None)
                return result

            # 无缓存且 API 失败：返回 None
            logger.warning("无缓存且 API 请求失败")
            return None

    async def initialize_cache(self) -> bool:
        """启动时初始化缓存（首次获取，不检查过期）

        Returns:
            初始化是否成功
        """
        logger.info("初始化模型缓存...")
        models_data = await self.fetch_models_from_api()
        if models_data:
            models_data["timestamp"] = int(time.time())
            return self._write_cache(models_data)
        return False

    async def refresh_cache_background(self) -> bool:
        """后台刷新缓存（用于定时任务，失败不修改旧缓存）

        Returns:
            刷新是否成功
        """
        logger.info("后台刷新模型缓存...")
        fresh_data = await self.fetch_models_from_api()
        if fresh_data:
            fresh_data["timestamp"] = int(time.time())
            success = self._write_cache(fresh_data)
            if success:
                logger.info("后台刷新模型缓存成功")
            else:
                logger.error("后台刷新模型缓存失败：写入文件错误")
            return success
        logger.error("后台刷新模型缓存失败：API 获取失败")
        return False

    async def close(self):
        """清理 ModelCache 赘源

        注意：此方法不会调用 authenticated_client.aclose()，因为其所有权属于调用方。
        httpx.AsyncClient 同时有 close()（同步）和 aclose()（异步），本方法均不调用。
        调用方需自行关闭客户端。
        """
        logger.debug("ModelCache 已关闭 (无需要清理的资源)")

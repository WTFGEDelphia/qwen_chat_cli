"""模型缓存模块测试"""
import asyncio
import json
import tempfile
import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from qwen_gateway.model_cache import ModelCache


@pytest.fixture
def temp_cache_dir():
    """创建临时缓存目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def model_cache(temp_cache_dir):
    """创建 ModelCache 实例"""
    return ModelCache(cache_dir=temp_cache_dir, ttl=1800)


@pytest.fixture
def mock_auth_client():
    """创建 mock 的 httpx.AsyncClient（模块级 fixture，供 TestModelCacheWithAuth 使用）"""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    return mock_client


class TestModelCacheBasic:
    """ModelCache 基础功能测试"""

    def test_init_default(self, temp_cache_dir):
        """测试默认初始化"""
        cache = ModelCache(cache_dir=temp_cache_dir)
        assert cache.ttl == 1800
        assert cache.cache_file.name == "model_cache.json"
        assert cache.API_TIMEOUT == 10.0

    def test_init_custom_ttl(self, temp_cache_dir):
        """测试自定义 TTL"""
        cache = ModelCache(cache_dir=temp_cache_dir, ttl=7200)
        assert cache.ttl == 7200

    def test_get_cached_data_no_file(self, model_cache):
        """测试无缓存文件时返回 None"""
        assert model_cache._get_cached_data() is None

    def test_get_cached_data_valid(self, model_cache, temp_cache_dir):
        """测试读取有效缓存"""
        data = {
            "object": "list",
            "data": [{"id": "qwen3.5", "object": "model"}],
            "timestamp": int(time.time())
        }
        with open(model_cache.cache_file, "w") as f:
            json.dump(data, f)

        result = model_cache._get_cached_data()
        assert result is not None
        assert result["object"] == "list"
        assert len(result["data"]) == 1

    def test_get_cached_data_invalid_format(self, model_cache):
        """测试无效格式缓存"""
        with open(model_cache.cache_file, "w") as f:
            f.write("invalid json")

        assert model_cache._get_cached_data() is None

    def test_get_cached_data_missing_fields(self, model_cache):
        """测试缺少必需字段"""
        data = {"object": "list"}  # 缺少 data 和 timestamp
        with open(model_cache.cache_file, "w") as f:
            json.dump(data, f)

        assert model_cache._get_cached_data() is None

    def test_write_cache(self, model_cache):
        """测试写入缓存"""
        data = {
            "object": "list",
            "data": [{"id": "qwen3.5", "object": "model"}],
            "timestamp": int(time.time())
        }
        assert model_cache._write_cache(data) is True
        assert model_cache.cache_file.exists()

    def test_is_cache_expired_strict_greater(self, model_cache):
        """测试缓存过期判断 - 严格大于才过期"""
        now = time.time()
        # 未过期
        fresh_data = {"timestamp": now}
        assert model_cache._is_cache_expired(fresh_data) is False

        # 已过期 (超过 1800 秒)
        old_data = {"timestamp": now - 2000}
        assert model_cache._is_cache_expired(old_data) is True

        # 刚好在 TTL 内 (1700 秒，留出缓冲)
        boundary_data = {"timestamp": now - 1700}
        assert model_cache._is_cache_expired(boundary_data) is False

        # 刚过期 (1900 秒)
        just_expired = {"timestamp": now - 1900}
        assert model_cache._is_cache_expired(just_expired) is True


class TestModelCacheAPI:
    """ModelCache API 功能测试（未登录模式路径）"""

    @pytest.mark.asyncio
    async def test_fetch_models_from_api_success(self, model_cache):
        """测试未登录模式 API 获取成功"""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"data": [{"id": "qwen3.5-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
            mock_response.json.return_value = {
                "data": [{"id": "qwen3.5-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}}]
            }
            mock_client.get = AsyncMock(return_value=mock_response)
            MockClient.return_value = mock_client

            result = await model_cache.fetch_models_from_api()

        assert result is not None
        assert result["object"] == "list"
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == "qwen3.5-plus"

    @pytest.mark.asyncio
    async def test_fetch_models_from_api_timeout(self, model_cache):
        """测试 API 超时"""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            MockClient.return_value = mock_client

            result = await model_cache.fetch_models_from_api()

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_models_from_api_request_error(self, model_cache):
        """测试 API 网络请求错误"""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.RequestError("connection failed"))
            MockClient.return_value = mock_client

            result = await model_cache.fetch_models_from_api()

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_models_from_api_non_200(self, model_cache):
        """测试 API 返回非 200 状态"""
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = Mock()
            mock_response.status_code = 500
            mock_client.get = AsyncMock(return_value=mock_response)
            MockClient.return_value = mock_client

            result = await model_cache.fetch_models_from_api()

        assert result is None


class TestModelCacheFallback:
    """ModelCache fallback 逻辑测试"""

    @pytest.mark.asyncio
    async def test_get_models_api_success(self, model_cache):
        """测试 API 成功时使用新数据"""
        async def mock_fetch():
            return {
                "object": "list",
                "data": [
                    {"id": "qwen3.5-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}}
                ]
            }

        with patch.object(model_cache, 'fetch_models_from_api', side_effect=mock_fetch):
            result = await model_cache.get_models()

        assert result is not None
        assert "timestamp" not in result

    @pytest.mark.asyncio
    async def test_get_models_api_fail_fallback_to_cache(self, model_cache):
        """测试 API 失败时 fallback 到过期缓存数据"""
        # 先写入一个过期缓存
        old_data = {
            "object": "list",
            "data": [{"id": "cached-model", "object": "model"}],
            "timestamp": int(time.time()) - 2000  # 已过期
        }
        model_cache._write_cache(old_data)

        # Mock API 返回失败
        with patch.object(model_cache, 'fetch_models_from_api', return_value=None):
            result = await model_cache.get_models()

        # 应该 fallback 到缓存数据
        assert result is not None
        assert result["data"][0]["id"] == "cached-model"
        assert "timestamp" not in result

    @pytest.mark.asyncio
    async def test_get_models_no_cache_api_fail_returns_none(self, model_cache):
        """测试无缓存且 API 失败时返回 None"""
        # 确保没有缓存文件
        if model_cache.cache_file.exists():
            model_cache.cache_file.unlink()

        # Mock API 返回失败
        with patch.object(model_cache, 'fetch_models_from_api', return_value=None):
            result = await model_cache.get_models()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_models_force_refresh_api_success(self, model_cache):
        """测试强制刷新且 API 成功"""
        # 写入一个新鲜缓存
        fresh_cache = {
            "object": "list",
            "data": [{"id": "old-model", "object": "model"}],
            "timestamp": int(time.time())
        }
        model_cache._write_cache(fresh_cache)

        # Mock API 返回新数据
        async def mock_fetch():
            return {
                "object": "list",
                "data": [
                    {"id": "new-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}
                ]
            }

        with patch.object(model_cache, 'fetch_models_from_api', side_effect=mock_fetch):
            result = await model_cache.get_models(force_refresh=True)

        # 应该返回新数据
        assert result is not None
        assert result["data"][0]["id"] == "new-model"

    @pytest.mark.asyncio
    async def test_get_models_force_refresh_api_fail_fallback(self, model_cache):
        """测试强制刷新但 API 失败时 fallback 到旧缓存"""
        # 写入一个缓存
        old_cache = {
            "object": "list",
            "data": [{"id": "fallback-model", "object": "model"}],
            "timestamp": int(time.time())
        }
        model_cache._write_cache(old_cache)

        # Mock API 返回失败
        with patch.object(model_cache, 'fetch_models_from_api', return_value=None):
            result = await model_cache.get_models(force_refresh=True)

        # 应该 fallback 到缓存数据
        assert result is not None
        assert result["data"][0]["id"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_get_models_with_valid_cache_no_api_call(self, model_cache):
        """测试有新鲜缓存时不调用 API（快速路径）"""
        # 写入一个新鲜缓存
        fresh_cache = {
            "object": "list",
            "data": [{"id": "cached-model", "object": "model"}],
            "timestamp": int(time.time())
        }
        model_cache._write_cache(fresh_cache)

        # Mock API 返回失败（如果调用的话）
        with patch.object(model_cache, 'fetch_models_from_api', return_value=None) as mock_api:
            result = await model_cache.get_models()

        # 应该返回缓存数据，且没有调用 API
        assert result is not None
        assert result["data"][0]["id"] == "cached-model"
        mock_api.assert_not_called()


class TestModelCacheConcurrency:
    """ModelCache 并发安全测试"""

    @pytest.mark.asyncio
    async def test_concurrent_get_models_no_duplicate_requests(self, model_cache):
        """测试并发获取模型不会导致重复请求"""
        # 写入过期缓存
        old_data = {
            "object": "list",
            "data": [{"id": "old-model", "object": "model"}],
            "timestamp": int(time.time()) - 2000
        }
        model_cache._write_cache(old_data)

        # Mock API，记录调用次数
        call_count = 0

        async def mock_fetch():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # 模拟网络延迟
            return {
                "object": "list",
                "data": [{"id": "fresh-model", "object": "model"}],
                "timestamp": int(time.time())
            }

        with patch.object(model_cache, 'fetch_models_from_api', side_effect=mock_fetch):
            # 并发调用 get_models
            results = await asyncio.gather(*[
                model_cache.get_models() for _ in range(10)
            ])

        # 所有结果都应该有效
        for result in results:
            assert result is not None
            assert "data" in result

        # 关键验证：API 只被调用一次（锁保护）
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_with_valid_cache(self, model_cache):
        """测试有新鲜缓存时并发调用走快速路径"""
        # 写入新鲜缓存
        fresh_cache = {
            "object": "list",
            "data": [{"id": "cached-model", "object": "model"}],
            "timestamp": int(time.time())
        }
        model_cache._write_cache(fresh_cache)

        # Mock API（不应该被调用）
        with patch.object(model_cache, 'fetch_models_from_api') as mock_api:
            results = await asyncio.gather(*[
                model_cache.get_models() for _ in range(10)
            ])

        # 所有结果都应该有效
        for result in results:
            assert result is not None
            assert result["data"][0]["id"] == "cached-model"

        # API 不应该被调用
        mock_api.assert_not_called()

    @pytest.mark.asyncio
    async def test_double_check_lock_prevents_race_condition(self, model_cache):
        """测试双重检查锁防止竞态条件"""
        # 写入过期缓存
        old_data = {
            "object": "list",
            "data": [{"id": "old-model", "object": "model"}],
            "timestamp": int(time.time()) - 2000
        }
        model_cache._write_cache(old_data)

        # Mock API，模拟慢速响应
        async def mock_fetch():
            await asyncio.sleep(0.05)  # 模拟较慢的网络
            return {
                "object": "list",
                "data": [{"id": "fresh-model", "object": "model"}],
                "timestamp": int(time.time())
            }

        with patch.object(model_cache, 'fetch_models_from_api', side_effect=mock_fetch):
            # 快速并发调用
            results = await asyncio.gather(*[
                model_cache.get_models() for _ in range(20)
            ])

        # 验证所有结果有效
        for result in results:
            assert result is not None
            assert result["data"][0]["id"] == "fresh-model"

        # 验证缓存文件只被写入一次
        cached = model_cache._get_cached_data()
        assert cached is not None
        assert cached["data"][0]["id"] == "fresh-model"


class TestModelCacheInit:
    """ModelCache 初始化和后台刷新测试"""

    @pytest.mark.asyncio
    async def test_initialize_cache_success(self, model_cache):
        """测试初始化缓存成功"""
        async def mock_fetch():
            return {
                "object": "list",
                "data": [
                    {"id": "qwen3.5", "owned_by": "qwen", "info": {"created_at": 1234567890}}
                ]
            }

        with patch.object(model_cache, 'fetch_models_from_api', side_effect=mock_fetch):
            result = await model_cache.initialize_cache()

        assert result is True
        assert model_cache.cache_file.exists()

    @pytest.mark.asyncio
    async def test_initialize_cache_fail(self, model_cache):
        """测试初始化缓存失败"""
        with patch.object(model_cache, 'fetch_models_from_api', return_value=None):
            result = await model_cache.initialize_cache()

        assert result is False
        assert not model_cache.cache_file.exists()

    @pytest.mark.asyncio
    async def test_refresh_cache_background_success(self, model_cache):
        """测试后台刷新成功"""
        # 先写入一个过期缓存
        old_data = {
            "object": "list",
            "data": [{"id": "old-model", "object": "model"}],
            "timestamp": int(time.time()) - 2000
        }
        model_cache._write_cache(old_data)

        # Mock API 返回新数据
        async def mock_fetch():
            return {
                "object": "list",
                "data": [
                    {"id": "new-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}
                ]
            }

        with patch.object(model_cache, 'fetch_models_from_api', side_effect=mock_fetch):
            result = await model_cache.refresh_cache_background()

        assert result is True

        # 验证缓存已更新
        cached = model_cache._get_cached_data()
        assert cached is not None
        assert cached["data"][0]["id"] == "new-model"

    @pytest.mark.asyncio
    async def test_refresh_cache_background_fail_no_modification(self, model_cache):
        """测试后台刷新失败时不修改旧缓存"""
        # 先写入一个过期缓存
        old_data = {
            "object": "list",
            "data": [{"id": "old-model", "object": "model"}],
            "timestamp": int(time.time()) - 2000
        }
        model_cache._write_cache(old_data)

        # Mock API 返回失败
        with patch.object(model_cache, 'fetch_models_from_api', return_value=None):
            result = await model_cache.refresh_cache_background()

        assert result is False

        # 验证旧缓存仍然存在且未被修改
        cached = model_cache._get_cached_data()
        assert cached is not None
        assert cached["data"][0]["id"] == "old-model"


class TestModelCacheWithAuth:
    """ModelCache 使用已认证客户端测试"""

    @pytest.mark.asyncio
    async def test_init_with_authenticated_client(self, temp_cache_dir, mock_auth_client):
        """测试传入 authenticated_client 初始化"""
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )
        assert cache.authenticated_client is mock_auth_client

    @pytest.mark.asyncio
    async def test_init_without_authenticated_client(self, temp_cache_dir):
        """测试不传 authenticated_client 时默认为 None"""
        cache = ModelCache(cache_dir=temp_cache_dir, ttl=1800)
        assert cache.authenticated_client is None

    @pytest.mark.asyncio
    async def test_fetch_with_authenticated_client_success(self, temp_cache_dir, mock_auth_client):
        """测试使用已认证客户端成功获取模型列表"""
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"data": [{"id": "qwen3.6-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
        mock_response.json.return_value = {"data": [{"id": "qwen3.6-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}
        mock_response.headers = {"content-type": "application/json"}
        mock_auth_client.get = AsyncMock(return_value=mock_response)

        result = await cache.fetch_models_from_api()

        mock_auth_client.get.assert_called_once()
        assert result is not None
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == "qwen3.6-plus"

    @pytest.mark.asyncio
    async def test_401_does_not_modify_authenticated_client_reference(self, temp_cache_dir, mock_auth_client):
        """测试 401 降级后 authenticated_client 引用保持不变

        关键设计：401 降级时不修改 authenticated_client 引用，
        由调用方决定重新登录或替换客户端。
        """
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )

        # 保存原始引用
        original_client = cache.authenticated_client

        # Mock 401 响应
        mock_401_response = Mock()
        mock_401_response.status_code = 401
        mock_401_response.text = '{"error": "unauthorized"}'
        mock_401_response.headers = {"content-type": "application/json"}
        mock_auth_client.get = AsyncMock(return_value=mock_401_response)

        # Mock 未登录客户端成功
        with patch("httpx.AsyncClient") as MockUnauthClient:
            mock_unauth_client = AsyncMock()
            mock_unauth_client.__aenter__ = AsyncMock(return_value=mock_unauth_client)
            mock_unauth_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
            mock_response.json.return_value = {"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}
            mock_unauth_client.get = AsyncMock(return_value=mock_response)
            MockUnauthClient.return_value = mock_unauth_client

            result = await cache.fetch_models_from_api()

        # 验证降级成功
        assert result is not None
        assert result["data"][0]["id"] == "fallback-model"

        # 关键验证：authenticated_client 引用保持不变
        assert cache.authenticated_client is original_client
        assert cache.authenticated_client is not None

    @pytest.mark.asyncio
    async def test_no_authenticated_client_uses_unauthenticated_mode(self, temp_cache_dir):
        """测试未提供 authenticated_client 时使用未登录模式"""
        cache = ModelCache(cache_dir=temp_cache_dir, ttl=1800)

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"data": [{"id": "public-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
            mock_response.json.return_value = {"data": [{"id": "public-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}
            mock_client.get = AsyncMock(return_value=mock_response)
            MockClient.return_value = mock_client

            result = await cache.fetch_models_from_api()

        assert result is not None
        assert result["data"][0]["id"] == "public-model"

    @pytest.mark.asyncio
    async def test_authenticated_client_200_empty_response_fallback(self, temp_cache_dir, mock_auth_client):
        """测试认证客户端返回 200 但空响应时降级到未登录模式"""
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )

        mock_empty_response = Mock()
        mock_empty_response.status_code = 200
        mock_empty_response.text = ""
        mock_empty_response.headers = {"content-type": "application/json"}
        mock_auth_client.get = AsyncMock(return_value=mock_empty_response)

        with patch("httpx.AsyncClient") as MockUnauthClient:
            mock_unauth_client = AsyncMock()
            mock_unauth_client.__aenter__ = AsyncMock(return_value=mock_unauth_client)
            mock_unauth_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
            mock_response.json.return_value = {"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}
            mock_unauth_client.get = AsyncMock(return_value=mock_response)
            MockUnauthClient.return_value = mock_unauth_client

            result = await cache.fetch_models_from_api()

        # 空响应降级到未登录模式
        assert result is not None
        assert result["data"][0]["id"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_close_does_not_close_authenticated_client(self, temp_cache_dir, mock_auth_client):
        """测试 close() 方法不关闭 authenticated_client"""
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )

        await cache.close()

        # 验证客户端没有被 aclose（httpx.AsyncClient 用 aclose 不是 close）
        mock_auth_client.aclose.assert_not_called()

    @pytest.mark.asyncio
    async def test_authenticated_client_other_status_fallback(self, temp_cache_dir, mock_auth_client):
        """测试认证客户端返回非 401/200 状态码时降级到未登录模式"""
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )

        mock_500_response = Mock()
        mock_500_response.status_code = 500
        mock_500_response.text = '{"error": "server error"}'
        mock_500_response.headers = {"content-type": "application/json"}
        mock_auth_client.get = AsyncMock(return_value=mock_500_response)

        with patch("httpx.AsyncClient") as MockUnauthClient:
            mock_unauth_client = AsyncMock()
            mock_unauth_client.__aenter__ = AsyncMock(return_value=mock_unauth_client)
            mock_unauth_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
            mock_response.json.return_value = {"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}
            mock_unauth_client.get = AsyncMock(return_value=mock_response)
            MockUnauthClient.return_value = mock_unauth_client

            result = await cache.fetch_models_from_api()

        assert result is not None
        assert result["data"][0]["id"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_authenticated_client_waf_html_response_fallback(self, temp_cache_dir, mock_auth_client):
        """测试认证客户端返回 200 但 content-type 为 text/html（WAF拦截）时降级到未登录模式

        真实场景：阿里云 WAF 拦截不带 accept/referer/x-request-id 的请求，
        返回 status=200 但 content-type=text/html 而非 application/json。
        """
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )

        mock_waf_response = Mock()
        mock_waf_response.status_code = 200
        mock_waf_response.text = '<!doctypehtml>...aliyun_waf_aa...'
        mock_waf_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_auth_client.get = AsyncMock(return_value=mock_waf_response)

        with patch("httpx.AsyncClient") as MockUnauthClient:
            mock_unauth_client = AsyncMock()
            mock_unauth_client.__aenter__ = AsyncMock(return_value=mock_unauth_client)
            mock_unauth_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
            mock_response.json.return_value = {"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}
            mock_unauth_client.get = AsyncMock(return_value=mock_response)
            MockUnauthClient.return_value = mock_unauth_client

            result = await cache.fetch_models_from_api()

        assert result is not None
        assert result["data"][0]["id"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_authenticated_client_empty_response_non_json_ct_fallback(self, temp_cache_dir, mock_auth_client):
        """测试认证客户端返回 200 空响应且 content-type 非 JSON 时降级到未登录模式

        补充盲区：空响应 + 非 JSON content-type 会先走到 WAF 检测分支
        （not content_type.startswith("application/json")），而非空响应分支。
        """
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )

        mock_empty_waf_response = Mock()
        mock_empty_waf_response.status_code = 200
        mock_empty_waf_response.text = ""
        mock_empty_waf_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_auth_client.get = AsyncMock(return_value=mock_empty_waf_response)

        with patch("httpx.AsyncClient") as MockUnauthClient:
            mock_unauth_client = AsyncMock()
            mock_unauth_client.__aenter__ = AsyncMock(return_value=mock_unauth_client)
            mock_unauth_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
            mock_response.json.return_value = {"data": [{"id": "fallback-model", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}
            mock_unauth_client.get = AsyncMock(return_value=mock_response)
            MockUnauthClient.return_value = mock_unauth_client

            result = await cache.fetch_models_from_api()

        assert result is not None
        assert result["data"][0]["id"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_format_models_empty_list_returns_none(self, temp_cache_dir):
        """测试 _format_models 对空模型列表返回 None（走 fallback）"""
        cache = ModelCache(cache_dir=temp_cache_dir, ttl=1800)
        result = cache._format_models({"data": []})
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticated_client_passes_waf_headers(self, temp_cache_dir, mock_auth_client):
        """测试认证客户端请求时传入 WAF bypass headers（accept, referer, x-request-id）"""
        cache = ModelCache(
            cache_dir=temp_cache_dir,
            ttl=1800,
            authenticated_client=mock_auth_client
        )

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"data": [{"id": "qwen3.6-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}'
        mock_response.json.return_value = {"data": [{"id": "qwen3.6-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}}]}
        mock_response.headers = {"content-type": "application/json"}
        mock_auth_client.get = AsyncMock(return_value=mock_response)

        result = await cache.fetch_models_from_api()

        assert result is not None
        # 验证 get() 调用时传入了 headers 参数
        call_args = mock_auth_client.get.call_args
        assert "headers" in call_args.kwargs
        headers = call_args.kwargs["headers"]
        assert headers["accept"] == "application/json"
        assert headers["referer"] == "https://chat.qwen.ai/"
        assert "x-request-id" in headers

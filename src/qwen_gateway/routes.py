"""API 路由定义"""
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import DEFAULT_API_KEY

if TYPE_CHECKING:
    from .model_cache import ModelCache

router = APIRouter()
security = HTTPBearer(auto_error=False)

# 全局缓存实例（由 app.py 初始化）
_model_cache: "ModelCache | None" = None

# 硬编码 fallback 模型列表（缓存和 API 都不可用时使用）
FALLBACK_MODELS = [
    {"id": "qwen3.6-plus", "object": "model", "owned_by": "qwen"},
    {"id": "qwen3.5-plus", "object": "model", "owned_by": "qwen"},
]


def _fallback_models_response() -> dict[str, Any]:
    """构建 fallback 模型列表响应"""
    return {
        "object": "list",
        "data": [
            {**m, "created": 0} for m in FALLBACK_MODELS
        ],
    }


def set_model_cache(cache: "ModelCache | None") -> None:
    """注入模型缓存实例"""
    global _model_cache
    _model_cache = cache


def extract_message_text(content: str | list[dict[str, Any]]) -> str:
    """安全提取消息文本内容，兼容多模态格式"""
    if isinstance(content, str):
        return content.strip()
    elif isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return " ".join(text_parts).strip()
    else:
        return str(content).strip()


async def verify_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    """验证 API Key"""
    expected_settings = getattr(request.app.state, "settings", None)
    expected_key = expected_settings.api_key if expected_settings else DEFAULT_API_KEY

    if credentials is None or credentials.credentials != expected_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")


@router.get("/health")
async def health_check(request: Request):
    """健康检查端点"""
    settings = getattr(request.app.state, "settings", None)
    mode = settings.run_mode if settings else "stateful"
    return {"status": "ok", "mode": mode}


@router.get("/v1/models")
async def list_models(
    _=Depends(verify_key),
    refresh: bool = Query(default=False, description="是否强制刷新缓存"),
):
    """返回可用模型列表（带缓存）

    查询参数:
        refresh: 是否强制刷新缓存，默认 False
    """
    global _model_cache

    if _model_cache is None:
        return _fallback_models_response()

    # 获取缓存的模型列表
    models_data = await _model_cache.get_models(force_refresh=refresh)

    # Fallback 2: 如果缓存和 API 都失败，返回硬编码数据
    if models_data is None:
        return _fallback_models_response()

    return models_data

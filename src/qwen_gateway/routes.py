"""API 路由定义"""
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import DEFAULT_API_KEY

router = APIRouter()
security = HTTPBearer(auto_error=False)


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
async def list_models(_=Depends(verify_key)):
    """返回可用模型列表"""
    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": "qwen3.6-plus", "object": "model", "created": created, "owned_by": "qwen"},
            {"id": "qwen3.5-plus", "object": "model", "created": created, "owned_by": "qwen"},
        ],
    }

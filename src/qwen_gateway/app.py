"""FastAPI 应用配置"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .browser import AsyncPlaywrightManager
from .client import AsyncQwenClient
from .routes import extract_message_text, router, verify_key
from .schemas import ChatCompletionReq
from .settings import Settings, load_settings

logger = logging.getLogger("QwenServer")

pm = AsyncPlaywrightManager()
qwen_client: AsyncQwenClient | Any | None = None


def _openai_error(message: str, error_type: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type}},
    )


def create_app(
    *,
    settings: Settings | None = None,
    client_factory: Callable[[str, str], AsyncQwenClient] = AsyncQwenClient,
) -> FastAPI:
    """创建 FastAPI 应用"""
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global qwen_client
        app.state.settings = resolved_settings
        app.state.qwen_ready = False

        if not resolved_settings.credentials_configured:
            logger.warning("Qwen credentials are not configured; chat endpoint will return 503.")
            qwen_client = None
            yield
            return

        qwen_client = client_factory(
            resolved_settings.qwen_email or "",
            resolved_settings.qwen_password or "",
        )
        try:
            app.state.qwen_ready = await qwen_client.login(pm)
            if not app.state.qwen_ready:
                logger.error("Qwen login failed; chat endpoint will return 503.")
            elif resolved_settings.run_mode == "stateful":
                chat_id = await qwen_client.create_new_chat(pm)
                if chat_id:
                    qwen_client.active_chat_id = chat_id
                    qwen_client.active_parent_id = None
        finally:
            try:
                yield
            finally:
                if qwen_client:
                    await qwen_client.close()
                qwen_client = None

    app = FastAPI(
        title="Qwen API Gateway",
        version="1.0.0",
        description="支持 /new 命令的 Qwen Studio API 网关",
        lifespan=lifespan,
    )

    if resolved_settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_allow_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.state.settings = resolved_settings
    app.state.qwen_ready = False
    app.include_router(router)
    app.post("/v1/chat/completions")(chat_completions)

    return app


async def chat_completions(
    req: ChatCompletionReq,
    request: Request,
    _=Depends(verify_key),
):
    """对话接口（兼容 OpenAI 格式）"""
    global qwen_client

    settings: Settings = request.app.state.settings
    run_mode = settings.run_mode
    req_id = f"chatcmpl-{uuid.uuid4()}"
    created_time = int(time.time())

    last_text = extract_message_text(req.messages[-1].content) if req.messages else ""

    if last_text == "/new":
        if run_mode == "stateful":
            if not request.app.state.qwen_ready or qwen_client is None:
                return _openai_error(
                    "Qwen client is not ready",
                    "service_unavailable",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            async with qwen_client.session_lock:
                new_chat_id = await qwen_client.create_new_chat(pm)
                if not new_chat_id:
                    return _openai_error(
                        "Failed to create Qwen chat",
                        "server_error",
                        status.HTTP_502_BAD_GATEWAY,
                    )
                qwen_client.active_chat_id = new_chat_id
                qwen_client.active_parent_id = None
            reply_text = "已创建新会话！之前的上下文已清除。"
        else:
            reply_text = "当前为 stateless 模式，每次请求都是独立会话，无需手动创建新会话。"

        if req.stream:
            async def fake_stream():
                openai_chunk = {
                    "id": req_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": req.model,
                    "choices": [{"index": 0, "delta": {"content": reply_text}}],
                }
                yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                fake_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            return JSONResponse({
                "id": req_id,
                "object": "chat.completion",
                "created": created_time,
                "model": req.model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": reply_text},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })

    if not request.app.state.qwen_ready or qwen_client is None:
        return _openai_error(
            "Qwen client is not ready",
            "service_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if run_mode == "stateless":
        formatted_prompt = ""
        for msg in req.messages[:-1]:
            content_str = extract_message_text(msg.content)
            formatted_prompt += f"[{msg.role}]: {content_str}\n\n"
        formatted_prompt += f"[{req.messages[-1].role}]: {last_text}"
    else:
        formatted_prompt = last_text

    async def stream_generator():
        is_thinking = False
        async for chunk in qwen_client.stream_chat(pm, run_mode, formatted_prompt, req.model):
            if "error" in chunk:
                error_payload = {
                    "error": {
                        "message": chunk["error"],
                        "type": "server_error",
                    }
                }
                yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
                return

            content = chunk.get("content", "")
            phase = chunk.get("phase", "")
            if not content:
                continue

            out_str = ""
            if phase == "thinking_summary":
                if not is_thinking:
                    out_str += "<think>\n"
                    is_thinking = True
                out_str += content
            else:
                if is_thinking:
                    out_str += "\n</think>\n\n"
                    is_thinking = False
                out_str += content

            openai_chunk = {
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": req.model,
                "choices": [{"index": 0, "delta": {"content": out_str}}],
            }
            yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"

        if is_thinking:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': '\n</think>\n\n'}}]})}\n\n"
        yield "data: [DONE]\n\n"

    if req.stream:
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    else:
        full_text = ""
        async for chunk in stream_generator():
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                try:
                    data = json.loads(chunk[6:])
                    if "error" in data:
                        return _openai_error(
                            data["error"].get("message", "Upstream chat failed"),
                            data["error"].get("type", "server_error"),
                            status.HTTP_502_BAD_GATEWAY,
                        )
                    if "choices" in data:
                        full_text += data["choices"][0]["delta"].get("content", "")
                except json.JSONDecodeError:
                    return _openai_error(
                        "Invalid stream payload from upstream",
                        "server_error",
                        status.HTTP_502_BAD_GATEWAY,
                    )

        return JSONResponse({
            "id": req_id,
            "object": "chat.completion",
            "created": created_time,
            "model": req.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full_text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

app = create_app()

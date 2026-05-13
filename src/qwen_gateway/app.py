"""FastAPI 应用配置"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .browser import AsyncPlaywrightManager
from .client import AsyncQwenClient
from .compat import (
    CompatibilityError,
    anthropic_to_chat_request,
    build_anthropic_message,
    build_openai_response,
    openai_response_to_chat_request,
)
from .model_cache import ModelCache
from .routes import extract_message_text, router, set_model_cache, verify_key
from .schemas import AnthropicMessagesReq, ChatCompletionReq, ResponseCreateReq
from .settings import Settings, load_settings

logger = logging.getLogger("QwenServer")

pm = AsyncPlaywrightManager()


async def _init_cache(cache: ModelCache, context: str) -> None:
    """初始化模型缓存，统一处理成功/失败/异常"""
    try:
        if await cache.initialize_cache():
            logger.info(f"模型缓存初始化成功（{context}）")
        else:
            logger.warning("模型缓存初始化失败，使用 fallback 数据")
    except Exception as e:
        logger.error(f"模型缓存初始化异常：{e}")


qwen_client: AsyncQwenClient | Any | None = None
model_cache: ModelCache | None = None
cache_refresh_task: Any | None = None


def _openai_error(message: str, error_type: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type}},
    )


def _compat_error(exc: CompatibilityError) -> JSONResponse:
    return _openai_error(exc.message, exc.error_type, exc.status_code)


def _anthropic_error(message: str, error_type: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "error", "error": {"type": error_type, "message": message}},
    )


def _make_chat_request_id() -> str:
    return f"chatcmpl-{uuid.uuid4()}"


def _make_response_id() -> str:
    return f"resp_{uuid.uuid4().hex}"


def _make_anthropic_message_id() -> str:
    return f"msg_{uuid.uuid4().hex}"


def _format_prompt(req: ChatCompletionReq, run_mode: str) -> str:
    last_text = extract_message_text(req.messages[-1].content) if req.messages else ""
    if run_mode == "stateful":
        formatted_prompt = ""
        for msg in req.messages[:-1]:
            content_str = extract_message_text(msg.content)
            formatted_prompt += f"[{msg.role}]: {content_str}\n\n"
        formatted_prompt += f"[{req.messages[-1].role}]: {last_text}"
        return formatted_prompt
    return last_text


def _is_new_command(req: ChatCompletionReq) -> bool:
    last_text = extract_message_text(req.messages[-1].content) if req.messages else ""
    return last_text == "/new"


async def _handle_new_command_text(request: Request) -> JSONResponse | str:
    global qwen_client

    settings: Settings = request.app.state.settings
    if settings.run_mode == "stateful":
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
        return "已创建新会话！之前的上下文已清除。"
    return "当前为 stateless 模式，每次请求都是独立会话，无需手动创建新会话。"


async def _iter_chat_text(req: ChatCompletionReq, request: Request) -> AsyncIterator[dict[str, str]]:
    global qwen_client

    settings: Settings = request.app.state.settings
    formatted_prompt = _format_prompt(req, settings.run_mode)
    is_thinking = False

    async for chunk in qwen_client.stream_chat(pm, settings.run_mode, formatted_prompt, req.model):
        if "error" in chunk:
            yield {"error": chunk["error"]}
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

        yield {"content": out_str}

    if is_thinking:
        yield {"content": "\n</think>\n\n"}


async def _collect_chat_text(req: ChatCompletionReq, request: Request) -> JSONResponse | str:
    if not request.app.state.qwen_ready or qwen_client is None:
        return _openai_error(
            "Qwen client is not ready",
            "service_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    full_text = ""
    async for chunk in _iter_chat_text(req, request):
        if "error" in chunk:
            return _openai_error(
                chunk.get("error", "Upstream chat failed"),
                "server_error",
                status.HTTP_502_BAD_GATEWAY,
            )
        full_text += chunk.get("content", "")
    return full_text


def create_app(
    *,
    settings: Settings | None = None,
    client_factory: Callable[[str, str], AsyncQwenClient] = AsyncQwenClient,
) -> FastAPI:
    """创建 FastAPI 应用"""
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global qwen_client, model_cache, cache_refresh_task
        app.state.settings = resolved_settings
        app.state.qwen_ready = False

        # 初始化模型缓存（不立即初始化数据，等登录后绑定认证客户端再初始化）
        model_cache = ModelCache(
            cache_dir=resolved_settings.model_cache_dir,
            ttl=resolved_settings.model_cache_ttl,
            authenticated_client=None,
        )
        set_model_cache(model_cache)

        # 启动后台定时刷新任务
        refresh_interval = resolved_settings.model_cache_refresh_interval

        async def cache_refresh_loop():
            # 首次刷新立即执行，避免启动失败后需等 30 分钟才重试
            if model_cache:
                await model_cache.refresh_cache_background()
            while True:
                await asyncio.sleep(refresh_interval)
                if model_cache:
                    await model_cache.refresh_cache_background()

        cache_refresh_task = asyncio.create_task(cache_refresh_loop())

        # 根据凭证配置决定初始化方式
        if not resolved_settings.credentials_configured:
            logger.warning("Qwen credentials are not configured; chat endpoint will return 503.")
            await _init_cache(model_cache, "未登录模式")
            qwen_client = None
        else:
            qwen_client = client_factory(
                resolved_settings.qwen_email or "",
                resolved_settings.qwen_password or "",
            )
            app.state.qwen_ready = await qwen_client.login(pm)
            if not app.state.qwen_ready:
                logger.error("Qwen login failed; chat endpoint will return 503.")
                await _init_cache(model_cache, "未登录模式，登录失败降级")
            else:
                # 绑定认证客户端（仅在登录成功后执行一次，后续不再修改）
                model_cache.authenticated_client = qwen_client.http_client
                logger.info("ModelCache 已绑定认证客户端")
                await _init_cache(model_cache, "认证模式")
                if resolved_settings.run_mode == "stateful":
                    chat_id = await qwen_client.create_new_chat(pm)
                    if chat_id:
                        qwen_client.active_chat_id = chat_id
                        qwen_client.active_parent_id = None

        # yield 只出现一次，不在 finally 中嵌套
        yield

        # 清理资源
        if cache_refresh_task:
            cache_refresh_task.cancel()
            try:
                await cache_refresh_task
            except asyncio.CancelledError:
                pass
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
    app.post("/v1/responses")(openai_responses)
    app.post("/v1/messages")(anthropic_messages)

    return app


async def chat_completions(
    req: ChatCompletionReq,
    request: Request,
    _=Depends(verify_key),
):
    """对话接口（兼容 OpenAI 格式）"""
    global qwen_client

    req_id = _make_chat_request_id()
    created_time = int(time.time())

    if _is_new_command(req):
        reply_or_error = await _handle_new_command_text(request)
        if isinstance(reply_or_error, JSONResponse):
            return reply_or_error

        if req.stream:
            async def fake_stream():
                openai_chunk = {
                    "id": req_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": req.model,
                    "choices": [{"index": 0, "delta": {"content": reply_or_error}}],
                }
                yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                fake_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        return JSONResponse({
            "id": req_id,
            "object": "chat.completion",
            "created": created_time,
            "model": req.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": reply_or_error},
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

    async def stream_generator():
        async for chunk in _iter_chat_text(req, request):
            if "error" in chunk:
                error_payload = {
                    "error": {
                        "message": chunk["error"],
                        "type": "server_error",
                    }
                }
                yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
                return

            openai_chunk = {
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": req.model,
                "choices": [{"index": 0, "delta": {"content": chunk.get("content", "")}}],
            }
            yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    if req.stream:
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    full_text = await _collect_chat_text(req, request)
    if isinstance(full_text, JSONResponse):
        return full_text

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


async def openai_responses(
    req: ResponseCreateReq,
    request: Request,
    _=Depends(verify_key),
):
    """OpenAI Responses API compatibility endpoint."""
    settings: Settings = request.app.state.settings
    try:
        chat_req = openai_response_to_chat_request(
            req, compat_mode=settings.compat_mode
        )
    except CompatibilityError as exc:
        return _compat_error(exc)

    response_id = _make_response_id()
    created_at = int(time.time())

    if _is_new_command(chat_req):
        reply_or_error = await _handle_new_command_text(request)
        if isinstance(reply_or_error, JSONResponse):
            return reply_or_error
        return JSONResponse(
            build_openai_response(
                response_id=response_id,
                created_at=created_at,
                model=req.model,
                text=reply_or_error,
            )
        )

    if not request.app.state.qwen_ready or qwen_client is None:
        return _openai_error(
            "Qwen client is not ready",
            "service_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if req.stream:
        async def stream_generator():
            created_payload = {
                "type": "response.created",
                "response": build_openai_response(
                    response_id=response_id,
                    created_at=created_at,
                    model=req.model,
                    text="",
                ),
            }
            yield f"event: response.created\ndata: {json.dumps(created_payload, ensure_ascii=False)}\n\n"

            full_text = ""
            async for chunk in _iter_chat_text(chat_req, request):
                if "error" in chunk:
                    error_payload = {
                        "type": "error",
                        "error": {
                            "message": chunk["error"],
                            "type": "server_error",
                        },
                    }
                    yield f"event: error\ndata: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
                    return

                delta = chunk.get("content", "")
                full_text += delta
                payload = {
                    "type": "response.output_text.delta",
                    "response_id": response_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": delta,
                }
                yield f"event: response.output_text.delta\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            completed_payload = {
                "type": "response.completed",
                "response": build_openai_response(
                    response_id=response_id,
                    created_at=created_at,
                    model=req.model,
                    text=full_text,
                ),
            }
            yield f"event: response.completed\ndata: {json.dumps(completed_payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    full_text = await _collect_chat_text(chat_req, request)
    if isinstance(full_text, JSONResponse):
        return full_text

    return JSONResponse(
        build_openai_response(
            response_id=response_id,
            created_at=created_at,
            model=req.model,
            text=full_text,
        )
    )


async def anthropic_messages(
    req: AnthropicMessagesReq,
    request: Request,
    _=Depends(verify_key),
):
    """Anthropic Messages API compatibility endpoint."""
    settings: Settings = request.app.state.settings
    try:
        chat_req = anthropic_to_chat_request(req, compat_mode=settings.compat_mode)
    except CompatibilityError as exc:
        return _anthropic_error(exc.message, exc.error_type, exc.status_code)

    message_id = _make_anthropic_message_id()

    if _is_new_command(chat_req):
        reply_or_error = await _handle_new_command_text(request)
        if isinstance(reply_or_error, JSONResponse):
            return reply_or_error
        return JSONResponse(
            build_anthropic_message(
                message_id=message_id,
                model=req.model,
                text=reply_or_error,
            )
        )

    if not request.app.state.qwen_ready or qwen_client is None:
        return _anthropic_error(
            "Qwen client is not ready",
            "service_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if req.stream:
        async def stream_generator():
            started_message = build_anthropic_message(
                message_id=message_id,
                model=req.model,
                text="",
            )
            started_message["content"] = []
            yield (
                "event: message_start\n"
                f"data: {json.dumps({'type': 'message_start', 'message': started_message}, ensure_ascii=False)}\n\n"
            )

            block = {"type": "text", "text": ""}
            yield (
                "event: content_block_start\n"
                f"data: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': block}, ensure_ascii=False)}\n\n"
            )

            async for chunk in _iter_chat_text(chat_req, request):
                if "error" in chunk:
                    payload = {
                        "type": "error",
                        "error": {
                            "type": "server_error",
                            "message": chunk["error"],
                        },
                    }
                    yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    return

                # Anthropic 不支持 thinking，过滤 OpenAI 格式的思考标签
                raw = chunk.get("content", "")
                # 移除思考阶段起始标签 "忽然\n" 和闭合标签 "\n忽然\n\n"
                delta = raw.replace("忽然\n", "").replace("\n忽然\n\n", "")
                if not delta:
                    continue
                payload = {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": delta},
                }
                yield f"event: content_block_delta\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            yield (
                "event: content_block_stop\n"
                f"data: {json.dumps({'type': 'content_block_stop', 'index': 0}, ensure_ascii=False)}\n\n"
            )
            delta_payload = {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 0},
            }
            yield f"event: message_delta\ndata: {json.dumps(delta_payload, ensure_ascii=False)}\n\n"
            yield "event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    full_text = await _collect_chat_text(chat_req, request)
    if isinstance(full_text, JSONResponse):
        # _collect_chat_text 返回的 JSONResponse 已包含正确的错误码和信息
        # 直接转换 OpenAI 格式为 Anthropic 格式，保留原始状态码和错误类型
        # JSONResponse.body 是 bytes，需先解析再转换
        error_content = full_text.body
        try:
            parsed = json.loads(error_content) if isinstance(error_content, bytes) else error_content
            err = parsed.get("error", {})
            return _anthropic_error(
                err.get("message", "Unknown error"),
                err.get("type", "server_error"),
                full_text.status_code,
            )
        except (json.JSONDecodeError, AttributeError):
            return _anthropic_error("Unknown error", "server_error", full_text.status_code)

    # Anthropic 不支持 thinking，过滤 OpenAI 格式的思考标签
    clean_text = full_text.replace("忽然\n", "").replace("\n忽然\n\n", "")
    return JSONResponse(
        build_anthropic_message(
            message_id=message_id,
            model=req.model,
            text=clean_text,
        )
    )


app = create_app()

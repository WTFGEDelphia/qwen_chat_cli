# API Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-side compatibility endpoints for OpenAI Responses API and Anthropic Messages API while preserving the existing `/v1/chat/completions` behavior.

**Architecture:** Keep the Qwen browser client and existing OpenAI Chat Completions endpoint as the stable backend path, then add thin protocol adapters around a shared text-generation core. New request schemas normalize OpenAI Responses and Anthropic Messages inputs into the existing `ChatCompletionReq`, and new response builders wrap the generated text back into each provider's expected JSON or SSE event shape.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, Starlette `StreamingResponse`, pytest, existing `qwen_gateway` package.

---

## Reference Notes

Official docs used while writing this plan:

- OpenAI states that Responses uses `POST /v1/responses`, accepts flexible `input`, returns a typed `response` object, and differs from Chat Completions by returning `output` items rather than `choices`.
  Source: https://platform.openai.com/docs/guides/migrate-to-responses
- OpenAI Responses streaming uses SSE when `stream=true` and emits typed events such as `response.created`, `response.output_text.delta`, and `response.completed`.
  Source: https://platform.openai.com/docs/guides/streaming-responses
- Anthropic Messages accepts `model`, `max_tokens`, and `messages`, returns a `message` object with `content` blocks, `stop_reason`, and `usage`.
  Source: https://docs.anthropic.com/en/api/messages
- Anthropic Messages streaming uses SSE events in this flow: `message_start`, content block events, `message_delta`, and `message_stop`.
  Source: https://docs.anthropic.com/claude/reference/messages-streaming

## Scope

This plan implements compatibility for the protocol surface most client libraries need to avoid 404s and parse responses:

- Existing endpoint remains unchanged: `POST /v1/chat/completions`.
- Add OpenAI-compatible endpoint: `POST /v1/responses`.
- Add Anthropic-compatible endpoint: `POST /v1/messages`.
- Support non-streaming text generation for both new endpoints.
- Support text-only SSE streaming for both new endpoints.
- Accept common text input forms:
  - Responses `input: "text"`.
  - Responses `input: [{"role": "user", "content": "..."}]`.
  - Responses item content parts with `input_text` or `text`.
  - Anthropic `messages: [{"role": "user", "content": "..."}]`.
  - Anthropic content blocks with `{"type": "text", "text": "..."}`.
- Accept but reject unsupported provider-native features with a deterministic 400:
  - OpenAI Responses `tools`, `file_search`, `web_search`, `computer_use`, `function_call`, `function_call_output`, `input_file`, and background mode.
  - Anthropic `tools`, `tool_choice`, `thinking`, document blocks, file blocks, and image blocks.

Images are explicitly rejected in this compatibility layer because the current Qwen backend path passes a single text prompt to `AsyncQwenClient.stream_chat()`. Accepting image blocks while silently dropping them would look compatible but lose user data.

## File Structure

- Create `src/qwen_gateway/compat.py`
  - Owns protocol-specific request normalization and response builders.
  - Exports functions that are pure and easy to test without FastAPI.
  - Defines `CompatibilityError` for deterministic 400 responses.
- Modify `src/qwen_gateway/schemas.py`
  - Adds Pydantic models for Responses and Anthropic request bodies.
  - Keeps existing `Message` and `ChatCompletionReq` unchanged for current clients.
- Modify `src/qwen_gateway/app.py`
  - Registers `POST /v1/responses` and `POST /v1/messages`.
  - Extracts shared chat text generation into helpers used by all three endpoints.
  - Keeps existing `/v1/chat/completions` JSON and stream payloads stable.
- Modify `src/qwen_gateway/routes.py`
  - Keeps auth behavior unchanged.
  - Adds no new routes here unless route listing tests need a helper.
- Create `tests/test_compat.py`
  - Unit tests for request normalization and response builders.
- Modify `tests/test_api.py`
  - Integration tests for the new endpoints using `FakeQwenClient`.
- Modify `tests/test_app.py`
  - Asserts both new routes are registered.
- Modify `README.md`
  - Adds usage examples for OpenAI Responses and Anthropic Messages compatibility.

---

### Task 1: Add Protocol Request Schemas

**Files:**
- Modify: `src/qwen_gateway/schemas.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write failing schema tests**

Append these tests to `tests/test_schemas.py`:

```python
from qwen_gateway.schemas import AnthropicMessagesReq, ResponseCreateReq


def test_response_create_accepts_string_input():
    req = ResponseCreateReq(model="qwen3.6-plus", input="hello")

    assert req.model == "qwen3.6-plus"
    assert req.input == "hello"
    assert req.stream is False
    assert req.instructions is None


def test_response_create_accepts_item_input():
    req = ResponseCreateReq(
        model="qwen3.6-plus",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
        stream=True,
    )

    assert req.stream is True
    assert req.input[0]["role"] == "user"


def test_anthropic_messages_requires_max_tokens_and_messages():
    req = AnthropicMessagesReq(
        model="qwen3.6-plus",
        max_tokens=1024,
        messages=[{"role": "user", "content": "hello"}],
    )

    assert req.model == "qwen3.6-plus"
    assert req.max_tokens == 1024
    assert req.stream is False
    assert req.system is None
```

- [ ] **Step 2: Run schema tests and verify they fail**

Run:

```bash
pytest tests/test_schemas.py -q
```

Expected: FAIL with an import error for `AnthropicMessagesReq` and `ResponseCreateReq`.

- [ ] **Step 3: Add schema models**

Replace `src/qwen_gateway/schemas.py` with this complete content:

```python
"""Pydantic 数据模型定义"""
from typing import Any

from pydantic import BaseModel, Field


class Message(BaseModel):
    """对话消息模型"""
    role: str
    content: str | list[dict[str, Any]]


class ChatCompletionReq(BaseModel):
    """对话请求模型"""
    model: str = "qwen3.6-plus"
    messages: list[Message] = Field(min_length=1)
    stream: bool = False


class ResponseCreateReq(BaseModel):
    """OpenAI Responses API 兼容请求模型"""
    model: str = "qwen3.6-plus"
    input: str | list[dict[str, Any]]
    instructions: str | list[dict[str, Any]] | None = None
    stream: bool = False
    store: bool | None = None
    previous_response_id: str | None = None
    background: bool | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None


class AnthropicMessagesReq(BaseModel):
    """Anthropic Messages API 兼容请求模型"""
    model: str = "qwen3.6-plus"
    max_tokens: int = Field(gt=0)
    messages: list[Message] = Field(min_length=1)
    system: str | list[dict[str, Any]] | None = None
    stream: bool = False
    stop_sequences: list[str] | None = None
    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
```

- [ ] **Step 4: Run schema tests and verify they pass**

Run:

```bash
pytest tests/test_schemas.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qwen_gateway/schemas.py tests/test_schemas.py
git commit -m "feat: add compatibility request schemas"
```

---

### Task 2: Add Pure Compatibility Adapter Functions

**Files:**
- Create: `src/qwen_gateway/compat.py`
- Create: `tests/test_compat.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_compat.py` with this content:

```python
import json

import pytest

from qwen_gateway.compat import (
    CompatibilityError,
    anthropic_to_chat_request,
    build_anthropic_message,
    build_openai_response,
    openai_response_to_chat_request,
)
from qwen_gateway.schemas import AnthropicMessagesReq, ResponseCreateReq


def test_openai_response_string_input_becomes_user_message():
    req = ResponseCreateReq(model="qwen3.6-plus", input="hello")

    chat_req = openai_response_to_chat_request(req)

    assert chat_req.model == "qwen3.6-plus"
    assert chat_req.messages[0].role == "user"
    assert chat_req.messages[0].content == "hello"


def test_openai_response_instructions_become_system_message():
    req = ResponseCreateReq(
        model="qwen3.6-plus",
        instructions="You are concise.",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
    )

    chat_req = openai_response_to_chat_request(req)

    assert [message.role for message in chat_req.messages] == ["system", "user"]
    assert chat_req.messages[0].content == "You are concise."
    assert chat_req.messages[1].content == "hello"


def test_openai_response_rejects_tools():
    req = ResponseCreateReq(
        model="qwen3.6-plus",
        input="hello",
        tools=[{"type": "web_search_preview"}],
    )

    with pytest.raises(CompatibilityError) as exc:
        openai_response_to_chat_request(req)

    assert exc.value.status_code == 400
    assert exc.value.error_type == "unsupported_feature"
    assert "tools" in exc.value.message


def test_openai_response_rejects_image_input():
    req = ResponseCreateReq(
        model="qwen3.6-plus",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": "https://example.com/image.png"},
                    {"type": "input_text", "text": "describe this"},
                ],
            }
        ],
    )

    with pytest.raises(CompatibilityError) as exc:
        openai_response_to_chat_request(req)

    assert "input_image" in exc.value.message


def test_anthropic_system_becomes_system_message():
    req = AnthropicMessagesReq(
        model="qwen3.6-plus",
        max_tokens=1024,
        system="You are concise.",
        messages=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
    )

    chat_req = anthropic_to_chat_request(req)

    assert [message.role for message in chat_req.messages] == ["system", "user"]
    assert chat_req.messages[0].content == "You are concise."
    assert chat_req.messages[1].content == "hello"


def test_anthropic_rejects_tools():
    req = AnthropicMessagesReq(
        model="qwen3.6-plus",
        max_tokens=1024,
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"name": "get_weather", "input_schema": {"type": "object"}}],
    )

    with pytest.raises(CompatibilityError) as exc:
        anthropic_to_chat_request(req)

    assert exc.value.error_type == "unsupported_feature"
    assert "tools" in exc.value.message


def test_build_openai_response_shape_contains_output_text():
    data = build_openai_response(
        response_id="resp_test",
        created_at=1715600000,
        model="qwen3.6-plus",
        text="pong",
    )

    assert data["id"] == "resp_test"
    assert data["object"] == "response"
    assert data["output_text"] == "pong"
    assert data["output"][0]["content"][0]["type"] == "output_text"
    assert data["output"][0]["content"][0]["text"] == "pong"


def test_build_anthropic_message_shape_contains_text_block():
    data = build_anthropic_message(
        message_id="msg_test",
        model="qwen3.6-plus",
        text="pong",
    )

    assert data["id"] == "msg_test"
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["content"] == [{"type": "text", "text": "pong"}]
    assert data["stop_reason"] == "end_turn"
    assert data["usage"] == {"input_tokens": 0, "output_tokens": 0}


def test_response_builder_json_serializable():
    data = build_openai_response(
        response_id="resp_test",
        created_at=1715600000,
        model="qwen3.6-plus",
        text="pong",
    )

    encoded = json.dumps(data, ensure_ascii=False)

    assert "pong" in encoded
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```bash
pytest tests/test_compat.py -q
```

Expected: FAIL because `qwen_gateway.compat` does not exist.

- [ ] **Step 3: Create the compatibility module**

Create `src/qwen_gateway/compat.py` with this content:

```python
"""Protocol adapters for OpenAI Responses and Anthropic Messages compatibility."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import AnthropicMessagesReq, ChatCompletionReq, Message, ResponseCreateReq


@dataclass(slots=True)
class CompatibilityError(Exception):
    """Client-visible compatibility error."""

    message: str
    error_type: str = "invalid_request_error"
    status_code: int = 400


def _text_from_system(system: str | list[dict[str, Any]] | None) -> str | None:
    if system is None:
        return None
    if isinstance(system, str):
        return system.strip() or None

    parts: list[str] = []
    for item in system:
        item_type = item.get("type")
        if item_type != "text":
            raise CompatibilityError(
                f"Unsupported system content block type: {item_type}",
                error_type="unsupported_feature",
            )
        text = str(item.get("text", "")).strip()
        if text:
            parts.append(text)
    return "\n".join(parts) or None


def _anthropic_content_to_text(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for item in content:
        item_type = item.get("type")
        if item_type == "text":
            parts.append(str(item.get("text", "")))
        else:
            raise CompatibilityError(
                f"Unsupported Anthropic content block type: {item_type}",
                error_type="unsupported_feature",
            )
    return "\n".join(part for part in parts if part)


def _response_content_to_text(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for item in content:
        item_type = item.get("type")
        if item_type in {"input_text", "text"}:
            parts.append(str(item.get("text", "")))
        else:
            raise CompatibilityError(
                f"Unsupported OpenAI Responses content block type: {item_type}",
                error_type="unsupported_feature",
            )
    return "\n".join(part for part in parts if part)


def _ensure_no_response_unsupported_features(req: ResponseCreateReq) -> None:
    if req.background:
        raise CompatibilityError(
            "OpenAI Responses background mode is not supported by this Qwen gateway.",
            error_type="unsupported_feature",
        )
    if req.tools:
        raise CompatibilityError(
            "OpenAI Responses tools are not supported by this Qwen gateway.",
            error_type="unsupported_feature",
        )
    if req.tool_choice:
        raise CompatibilityError(
            "OpenAI Responses tool_choice is not supported by this Qwen gateway.",
            error_type="unsupported_feature",
        )
    if req.previous_response_id:
        raise CompatibilityError(
            "OpenAI Responses previous_response_id is not supported; send full history in input.",
            error_type="unsupported_feature",
        )


def _ensure_no_anthropic_unsupported_features(req: AnthropicMessagesReq) -> None:
    if req.tools:
        raise CompatibilityError(
            "Anthropic tools are not supported by this Qwen gateway.",
            error_type="unsupported_feature",
        )
    if req.tool_choice:
        raise CompatibilityError(
            "Anthropic tool_choice is not supported by this Qwen gateway.",
            error_type="unsupported_feature",
        )
    if req.thinking:
        raise CompatibilityError(
            "Anthropic extended thinking is not supported by this Qwen gateway.",
            error_type="unsupported_feature",
        )


def openai_response_to_chat_request(req: ResponseCreateReq) -> ChatCompletionReq:
    """Normalize an OpenAI Responses request into the existing chat request."""
    _ensure_no_response_unsupported_features(req)

    messages: list[Message] = []
    instructions = _text_from_system(req.instructions)
    if instructions:
        messages.append(Message(role="system", content=instructions))

    if isinstance(req.input, str):
        messages.append(Message(role="user", content=req.input))
    else:
        for item in req.input:
            item_type = item.get("type", "message")
            if item_type != "message":
                raise CompatibilityError(
                    f"Unsupported OpenAI Responses input item type: {item_type}",
                    error_type="unsupported_feature",
                )
            role = str(item.get("role", "user"))
            content = item.get("content", "")
            messages.append(Message(role=role, content=_response_content_to_text(content)))

    if not messages:
        raise CompatibilityError("OpenAI Responses input must contain at least one message.")

    return ChatCompletionReq(model=req.model, messages=messages, stream=req.stream)


def anthropic_to_chat_request(req: AnthropicMessagesReq) -> ChatCompletionReq:
    """Normalize an Anthropic Messages request into the existing chat request."""
    _ensure_no_anthropic_unsupported_features(req)

    messages: list[Message] = []
    system = _text_from_system(req.system)
    if system:
        messages.append(Message(role="system", content=system))

    for message in req.messages:
        messages.append(
            Message(
                role=message.role,
                content=_anthropic_content_to_text(message.content),
            )
        )

    return ChatCompletionReq(model=req.model, messages=messages, stream=req.stream)


def build_openai_response(
    *,
    response_id: str,
    created_at: int,
    model: str,
    text: str,
) -> dict[str, Any]:
    message_id = response_id.replace("resp_", "msg_", 1)
    output_item = {
        "id": message_id,
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": text,
                "annotations": [],
            }
        ],
    }
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "model": model,
        "output": [output_item],
        "output_text": text,
        "error": None,
        "incomplete_details": None,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
    }


def build_anthropic_message(
    *,
    message_id: str,
    model: str,
    text: str,
) -> dict[str, Any]:
    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
```

- [ ] **Step 4: Run adapter tests and verify they pass**

Run:

```bash
pytest tests/test_compat.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qwen_gateway/compat.py tests/test_compat.py
git commit -m "feat: add provider compatibility adapters"
```

---

### Task 3: Extract Shared Text Generation Helpers

**Files:**
- Modify: `src/qwen_gateway/app.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Add regression tests for the current endpoint before refactor**

Append this test to `tests/test_api.py`:

```python
def test_chat_completion_stream_still_uses_chat_completion_chunks():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True,
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert '"object": "chat.completion.chunk"' in body
    assert '"content": "pong"' in body
    assert "data: [DONE]" in body
```

- [ ] **Step 2: Run the regression test and verify it passes**

Run:

```bash
pytest tests/test_api.py::test_chat_completion_stream_still_uses_chat_completion_chunks -q
```

Expected: PASS.

- [ ] **Step 3: Refactor app imports and add shared helpers**

Modify imports at the top of `src/qwen_gateway/app.py` so this block is present:

```python
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
```

Then add these helpers above `chat_completions`:

```python
def _make_chat_request_id() -> str:
    return f"chatcmpl-{uuid.uuid4()}"


def _make_response_id() -> str:
    return f"resp_{uuid.uuid4().hex}"


def _make_anthropic_message_id() -> str:
    return f"msg_{uuid.uuid4().hex}"


def _format_prompt(req: ChatCompletionReq, run_mode: str) -> str:
    last_text = extract_message_text(req.messages[-1].content) if req.messages else ""
    if run_mode == "stateless":
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
```

- [ ] **Step 4: Update `chat_completions` to use helpers**

Replace the full `chat_completions` function in `src/qwen_gateway/app.py` with:

```python
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
```

- [ ] **Step 5: Run existing API tests**

Run:

```bash
pytest tests/test_api.py tests/test_lifespan.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/qwen_gateway/app.py tests/test_api.py
git commit -m "refactor: share chat text generation"
```

---

### Task 4: Implement OpenAI Responses Endpoint

**Files:**
- Modify: `src/qwen_gateway/app.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Add route registration test**

Modify `test_app_routes_registered` in `tests/test_app.py` so it contains these assertions:

```python
def test_app_routes_registered():
    """测试路由已注册"""
    routes = [r.path for r in app.routes]
    assert "/health" in routes
    assert "/v1/models" in routes
    assert "/v1/chat/completions" in routes
    assert "/v1/responses" in routes
```

- [ ] **Step 2: Add OpenAI Responses integration tests**

Append these tests to `tests/test_api.py`:

```python
def test_openai_responses_non_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "input": "ping",
                "stream": False,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "response"
    assert data["status"] == "completed"
    assert data["model"] == "qwen3.6-plus"
    assert data["output_text"] == "pong"
    assert data["output"][0]["type"] == "message"
    assert data["output"][0]["content"][0]["text"] == "pong"


def test_openai_responses_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "input": [{"role": "user", "content": "ping"}],
                "stream": True,
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert "event: response.created" in body
    assert "event: response.output_text.delta" in body
    assert '"delta": "pong"' in body
    assert "event: response.completed" in body


def test_openai_responses_unsupported_feature_returns_400():
    with make_client() as client:
        resp = client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "input": "ping",
                "tools": [{"type": "web_search_preview"}],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "unsupported_feature"
```

- [ ] **Step 3: Run new tests and verify they fail**

Run:

```bash
pytest tests/test_app.py::test_app_routes_registered tests/test_api.py::test_openai_responses_non_stream_success tests/test_api.py::test_openai_responses_stream_success tests/test_api.py::test_openai_responses_unsupported_feature_returns_400 -q
```

Expected: FAIL because `/v1/responses` is not registered.

- [ ] **Step 4: Add imports and route registration**

Update imports in `src/qwen_gateway/app.py`:

```python
from .compat import (
    CompatibilityError,
    build_anthropic_message,
    build_openai_response,
    openai_response_to_chat_request,
)
from .schemas import AnthropicMessagesReq, ChatCompletionReq, ResponseCreateReq
```

In `create_app`, register the new route immediately after the existing chat route:

```python
    app.post("/v1/chat/completions")(chat_completions)
    app.post("/v1/responses")(openai_responses)
```

- [ ] **Step 5: Add OpenAI error helper**

Add this helper below `_openai_error`:

```python
def _compat_error(exc: CompatibilityError) -> JSONResponse:
    return _openai_error(exc.message, exc.error_type, exc.status_code)
```

- [ ] **Step 6: Add OpenAI Responses endpoint**

Add this function below `chat_completions` in `src/qwen_gateway/app.py`:

```python
async def openai_responses(
    req: ResponseCreateReq,
    request: Request,
    _=Depends(verify_key),
):
    """OpenAI Responses API compatibility endpoint."""
    try:
        chat_req = openai_response_to_chat_request(req)
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
```

- [ ] **Step 7: Run OpenAI Responses tests and verify they pass**

Run:

```bash
pytest tests/test_app.py::test_app_routes_registered tests/test_api.py::test_openai_responses_non_stream_success tests/test_api.py::test_openai_responses_stream_success tests/test_api.py::test_openai_responses_unsupported_feature_returns_400 -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/qwen_gateway/app.py tests/test_api.py tests/test_app.py
git commit -m "feat: add OpenAI Responses compatibility endpoint"
```

---

### Task 5: Implement Anthropic Messages Endpoint

**Files:**
- Modify: `src/qwen_gateway/app.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Add route registration assertion**

Modify `test_app_routes_registered` in `tests/test_app.py` so it contains these assertions:

```python
def test_app_routes_registered():
    """测试路由已注册"""
    routes = [r.path for r in app.routes]
    assert "/health" in routes
    assert "/v1/models" in routes
    assert "/v1/chat/completions" in routes
    assert "/v1/responses" in routes
    assert "/v1/messages" in routes
```

- [ ] **Step 2: Add Anthropic integration tests**

Append these tests to `tests/test_api.py`:

```python
def test_anthropic_messages_non_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/messages",
            headers={
                "Authorization": "Bearer sk-test",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["model"] == "qwen3.6-plus"
    assert data["content"] == [{"type": "text", "text": "pong"}]
    assert data["stop_reason"] == "end_turn"


def test_anthropic_messages_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/messages",
            headers={
                "Authorization": "Bearer sk-test",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True,
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert "event: message_start" in body
    assert "event: content_block_start" in body
    assert "event: content_block_delta" in body
    assert '"text": "pong"' in body
    assert "event: message_delta" in body
    assert "event: message_stop" in body


def test_anthropic_messages_unsupported_feature_returns_400():
    with make_client() as client:
        resp = client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
                "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
            },
        )

    assert resp.status_code == 400
    data = resp.json()
    assert data["type"] == "error"
    assert data["error"]["type"] == "unsupported_feature"
```

- [ ] **Step 3: Run Anthropic tests and verify they fail**

Run:

```bash
pytest tests/test_app.py::test_app_routes_registered tests/test_api.py::test_anthropic_messages_non_stream_success tests/test_api.py::test_anthropic_messages_stream_success tests/test_api.py::test_anthropic_messages_unsupported_feature_returns_400 -q
```

Expected: FAIL because `/v1/messages` is not registered.

- [ ] **Step 4: Add Anthropic imports and route registration**

Update the compat import in `src/qwen_gateway/app.py`:

```python
from .compat import (
    CompatibilityError,
    anthropic_to_chat_request,
    build_anthropic_message,
    build_openai_response,
    openai_response_to_chat_request,
)
```

In `create_app`, register the route immediately after `/v1/responses`:

```python
    app.post("/v1/chat/completions")(chat_completions)
    app.post("/v1/responses")(openai_responses)
    app.post("/v1/messages")(anthropic_messages)
```

- [ ] **Step 5: Add Anthropic error helper**

Add this helper below `_compat_error`:

```python
def _anthropic_error(message: str, error_type: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "error", "error": {"type": error_type, "message": message}},
    )
```

- [ ] **Step 6: Add Anthropic Messages endpoint**

Add this function below `openai_responses` in `src/qwen_gateway/app.py`:

```python
async def anthropic_messages(
    req: AnthropicMessagesReq,
    request: Request,
    _=Depends(verify_key),
):
    """Anthropic Messages API compatibility endpoint."""
    try:
        chat_req = anthropic_to_chat_request(req)
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

                delta = chunk.get("content", "")
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
        return _anthropic_error(
            "Qwen client is not ready",
            "service_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return JSONResponse(
        build_anthropic_message(
            message_id=message_id,
            model=req.model,
            text=full_text,
        )
    )
```

- [ ] **Step 7: Run Anthropic tests and verify they pass**

Run:

```bash
pytest tests/test_app.py::test_app_routes_registered tests/test_api.py::test_anthropic_messages_non_stream_success tests/test_api.py::test_anthropic_messages_stream_success tests/test_api.py::test_anthropic_messages_unsupported_feature_returns_400 -q
```

Expected: PASS.

- [ ] **Step 8: Run a focused compatibility suite**

Run:

```bash
pytest tests/test_compat.py tests/test_api.py tests/test_app.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/qwen_gateway/app.py tests/test_api.py tests/test_app.py
git commit -m "feat: add Anthropic Messages compatibility endpoint"
```

---

### Task 6: Normalize Error Behavior Across Compatibility Endpoints

**Files:**
- Modify: `src/qwen_gateway/app.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add tests for missing credentials errors on new endpoints**

Append these tests to `tests/test_api.py`:

```python
def test_openai_responses_returns_503_when_credentials_missing():
    app = create_app(settings=Settings(api_key="sk-test"))

    with TestClient(app) as client:
        response = client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={"model": "qwen3.6-plus", "input": "你好"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "message": "Qwen client is not ready",
            "type": "service_unavailable",
        }
    }


def test_anthropic_messages_returns_503_when_credentials_missing():
    app = create_app(settings=Settings(api_key="sk-test"))

    with TestClient(app) as client:
        response = client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "你好"}],
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "type": "error",
        "error": {
            "message": "Qwen client is not ready",
            "type": "service_unavailable",
        },
    }
```

- [ ] **Step 2: Run error tests and verify current behavior**

Run:

```bash
pytest tests/test_api.py::test_openai_responses_returns_503_when_credentials_missing tests/test_api.py::test_anthropic_messages_returns_503_when_credentials_missing -q
```

Expected: PASS if Task 4 and Task 5 implemented the endpoint-specific error shapes correctly. If the Anthropic test fails with OpenAI-shaped error JSON, continue to Step 3.

- [ ] **Step 3: Fix Anthropic JSONResponse passthrough in `anthropic_messages`**

In `src/qwen_gateway/app.py`, replace this block:

```python
    full_text = await _collect_chat_text(chat_req, request)
    if isinstance(full_text, JSONResponse):
        return _anthropic_error(
            "Qwen client is not ready",
            "service_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
```

With this block:

```python
    full_text = await _collect_chat_text(chat_req, request)
    if isinstance(full_text, JSONResponse):
        return _anthropic_error(
            "Qwen client is not ready",
            "service_unavailable",
            full_text.status_code,
        )
```

- [ ] **Step 4: Run error tests and verify they pass**

Run:

```bash
pytest tests/test_api.py::test_openai_responses_returns_503_when_credentials_missing tests/test_api.py::test_anthropic_messages_returns_503_when_credentials_missing -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/qwen_gateway/app.py tests/test_api.py
git commit -m "fix: normalize compatibility endpoint errors"
```

---

### Task 7: Document Compatibility Usage

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add README compatibility section**

Insert this section after the existing non-streaming chat example in `README.md`:

````markdown
### OpenAI Responses API 兼容

新版 OpenAI SDK 默认可能调用 `POST /v1/responses`。本服务提供文本生成兼容层，底层仍转发到 Qwen Studio 会话。

```bash
curl -X POST http://localhost:8000/v1/responses \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "input": "你好",
    "stream": false
  }'
```

流式请求：

```bash
curl -X POST http://localhost:8000/v1/responses \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -N -d '{
    "model": "qwen3.6-plus",
    "input": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

兼容范围：

- 支持文本输入、`instructions`、多轮 `input` message items、非流式响应、SSE 流式响应。
- 不支持 Responses 工具调用、后台任务、`previous_response_id`、文件输入、图片输入。传入这些字段会返回 400，并带有 `unsupported_feature` 错误类型。

### Anthropic Messages API 兼容

Anthropic SDK 可通过 `POST /v1/messages` 访问本服务的文本生成兼容层。

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Authorization: Bearer $API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

流式请求：

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Authorization: Bearer $API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -N -d '{
    "model": "qwen3.6-plus",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

兼容范围：

- 支持文本消息、`system`、多轮 `messages`、非流式响应、SSE 流式响应。
- 不支持 Anthropic 工具调用、extended thinking、图片、文档和文件块。传入这些字段会返回 400，并带有 `unsupported_feature` 错误类型。
````

- [ ] **Step 2: Verify README contains all endpoint paths**

Run:

```bash
rg -n "/v1/(chat/completions|responses|messages)" README.md
```

Expected: output contains `/v1/chat/completions`, `/v1/responses`, and `/v1/messages`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document compatibility endpoints"
```

---

### Task 8: Final Verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 2: Start the development server**

Run:

```bash
API_KEY=sk-test QWEN_EMAIL=dev@example.com QWEN_PASSWORD=plain-password uvicorn qwen_gateway.app:app --app-dir src --host 127.0.0.1 --port 8000
```

Expected: server starts and logs the FastAPI app startup. If local credentials are not valid for real Qwen Studio login, use the automated test suite as the authoritative verification for route behavior.

- [ ] **Step 3: Verify route visibility**

In another terminal, run:

```bash
curl -s http://127.0.0.1:8000/openapi.json | python -m json.tool | rg '"/v1/(chat/completions|responses|messages)"'
```

Expected:

```text
"/v1/chat/completions"
"/v1/responses"
"/v1/messages"
```

- [ ] **Step 4: Verify unsupported Responses tools return 400**

Run:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer sk-test" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-plus","input":"hi","tools":[{"type":"web_search_preview"}]}' \
  | python -m json.tool
```

Expected:

```json
{
  "error": {
    "message": "OpenAI Responses tools are not supported by this Qwen gateway.",
    "type": "unsupported_feature"
  }
}
```

- [ ] **Step 5: Verify unsupported Anthropic tools return 400**

Run:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/messages \
  -H "Authorization: Bearer sk-test" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-plus","max_tokens":1024,"messages":[{"role":"user","content":"hi"}],"tools":[{"name":"get_weather","input_schema":{"type":"object"}}]}' \
  | python -m json.tool
```

Expected:

```json
{
  "type": "error",
  "error": {
    "type": "unsupported_feature",
    "message": "Anthropic tools are not supported by this Qwen gateway."
  }
}
```

- [ ] **Step 6: Stop the development server**

Press `Ctrl-C` in the uvicorn terminal.

- [ ] **Step 7: Inspect final diff**

Run:

```bash
git status --short
git diff --stat HEAD
```

Expected: working tree contains only the intended compatibility endpoint, schema, adapter, tests, and README changes since the task branch started.

---

## Self-Review

- Spec coverage: The plan covers OpenAI Responses route registration, request normalization, non-streaming response shape, SSE event shape, unsupported feature errors, Anthropic Messages route registration, request normalization, non-streaming response shape, SSE event flow, docs, and full tests.
- Placeholder scan: No deferred implementation markers are present. Unsupported features have exact 400 behavior rather than silent acceptance.
- Type consistency: `ResponseCreateReq`, `AnthropicMessagesReq`, `CompatibilityError`, `openai_response_to_chat_request`, `anthropic_to_chat_request`, `build_openai_response`, and `build_anthropic_message` are introduced before use and referenced with consistent names.
- Scope check: This remains a single compatibility-layer project. Tool execution, files, images, provider-managed conversations, and persistent Responses state are rejected with explicit errors because the current Qwen backend only accepts text prompts.

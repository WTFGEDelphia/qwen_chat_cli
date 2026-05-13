"""Protocol adapters for OpenAI Responses and Anthropic Messages compatibility."""
from __future__ import annotations

from typing import Any

from .schemas import AnthropicMessagesReq, ChatCompletionReq, Message, ResponseCreateReq


class CompatibilityError(Exception):
    """Client-visible compatibility error."""

    def __init__(
        self,
        message: str,
        error_type: str = "invalid_request_error",
        status_code: int = 400,
    ):
        self.message = message
        self.error_type = error_type
        self.status_code = status_code
        super().__init__(message)


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


def openai_response_to_chat_request(
    req: ResponseCreateReq,
    *,
    compat_mode: str = "lenient",
) -> ChatCompletionReq:
    """Normalize an OpenAI Responses request into the existing chat request."""
    if compat_mode != "lenient":
        _ensure_no_response_unsupported_features(req)
    elif req.background or req.previous_response_id:
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


def anthropic_to_chat_request(
    req: AnthropicMessagesReq,
    *,
    compat_mode: str = "lenient",
) -> ChatCompletionReq:
    """Normalize an Anthropic Messages request into the existing chat request."""
    if compat_mode != "lenient":
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

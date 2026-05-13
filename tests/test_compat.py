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
        openai_response_to_chat_request(req, compat_mode="strict")

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
        openai_response_to_chat_request(req, compat_mode="strict")

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
        anthropic_to_chat_request(req, compat_mode="strict")

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


def test_openai_response_lenient_ignores_tools():
    """lenient 模式下 tools 字段被静默忽略"""
    req = ResponseCreateReq(
        model="qwen3.6-plus",
        input="hello",
        tools=[{"type": "web_search_preview"}],
    )

    chat_req = openai_response_to_chat_request(req, compat_mode="lenient")

    assert chat_req.messages[0].content == "hello"


def test_openai_response_lenient_ignores_tool_choice():
    """lenient 模式下 tool_choice 字段被静默忽略"""
    req = ResponseCreateReq(
        model="qwen3.6-plus",
        input="hello",
        tool_choice="auto",
    )

    chat_req = openai_response_to_chat_request(req, compat_mode="lenient")

    assert chat_req.messages[0].content == "hello"


def test_openai_response_strict_rejects_tools():
    """strict 模式下 tools 仍然被拒绝"""
    req = ResponseCreateReq(
        model="qwen3.6-plus",
        input="hello",
        tools=[{"type": "web_search_preview"}],
    )

    with pytest.raises(CompatibilityError) as exc:
        openai_response_to_chat_request(req, compat_mode="strict")

    assert exc.value.status_code == 400
    assert exc.value.error_type == "unsupported_feature"
    assert "tools" in exc.value.message


def test_anthropic_requests_lenient_ignores_tools():
    """lenient 模式下 Anthropic tools 被静默忽略"""
    req = AnthropicMessagesReq(
        model="qwen3.6-plus",
        max_tokens=1024,
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"name": "get_weather", "input_schema": {"type": "object"}}],
    )

    chat_req = anthropic_to_chat_request(req, compat_mode="lenient")

    assert chat_req.messages[0].content == "hello"


def test_anthropic_requests_lenient_ignores_thinking():
    """lenient 模式下 Anthropic thinking 被静默忽略"""
    req = AnthropicMessagesReq(
        model="qwen3.6-plus",
        max_tokens=1024,
        messages=[{"role": "user", "content": "hello"}],
        thinking={"type": "enabled", "budget_tokens": 16000},
    )

    chat_req = anthropic_to_chat_request(req, compat_mode="lenient")

    assert chat_req.messages[0].content == "hello"


def test_anthropic_requests_strict_rejects_tools():
    """strict 模式下 Anthropic tools 仍然被拒绝"""
    req = AnthropicMessagesReq(
        model="qwen3.6-plus",
        max_tokens=1024,
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"name": "get_weather", "input_schema": {"type": "object"}}],
    )

    with pytest.raises(CompatibilityError) as exc:
        anthropic_to_chat_request(req, compat_mode="strict")

    assert exc.value.error_type == "unsupported_feature"
    assert "tools" in exc.value.message


def test_openai_response_default_is_lenient():
    """不传 compat_mode 时默认为 lenient"""
    req = ResponseCreateReq(
        model="qwen3.6-plus",
        input="hello",
        tools=[{"type": "web_search_preview"}],
    )

    chat_req = openai_response_to_chat_request(req)

    assert chat_req.messages[0].content == "hello"


def test_anthropic_requests_default_is_lenient():
    """不传 compat_mode 时默认为 lenient"""
    req = AnthropicMessagesReq(
        model="qwen3.6-plus",
        max_tokens=1024,
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"name": "get_weather", "input_schema": {"type": "object"}}],
    )

    chat_req = anthropic_to_chat_request(req)

    assert chat_req.messages[0].content == "hello"

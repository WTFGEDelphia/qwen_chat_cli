"""Schemas 模块测试"""
import pytest
from qwen_gateway.schemas import AnthropicMessagesReq, ChatCompletionReq, Message, ResponseCreateReq


def test_message_string_content():
    """测试字符串内容"""
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_message_list_content():
    """测试列表内容"""
    msg = Message(
        role="user",
        content=[
            {"type": "text", "text": "hello"},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}}
        ]
    )
    assert len(msg.content) == 2


def test_chat_completion_default_stream():
    """测试默认 stream 值"""
    req = ChatCompletionReq(messages=[{"role": "user", "content": "hi"}])
    assert req.model == "qwen3.6-plus"
    assert req.stream is False


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

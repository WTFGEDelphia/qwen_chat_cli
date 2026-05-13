"""Schemas 模块测试"""
import pytest
from qwen_gateway.schemas import Message, ChatCompletionReq


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

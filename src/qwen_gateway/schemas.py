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

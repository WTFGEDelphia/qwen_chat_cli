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
    max_tokens: int = Field(gt=0, default=1024)
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

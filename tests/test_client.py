"""Client 模块测试"""
import asyncio

import pytest
from unittest.mock import AsyncMock

from qwen_gateway.client import AsyncQwenClient
from qwen_gateway.browser import AsyncPlaywrightManager


@pytest.mark.asyncio
async def test_client_initialization():
    """测试客户端初始化"""
    client = AsyncQwenClient("test@example.com", "password")
    assert client.email == "test@example.com"
    assert client.password == "password"
    assert client.active_chat_id is None
    assert client.active_parent_id is None


@pytest.mark.asyncio
async def test_get_headers_includes_auth():
    """测试请求头包含认证信息"""
    client = AsyncQwenClient("test@example.com", "password")
    client.token = "test-token-123"
    pm = AsyncPlaywrightManager()
    # Mock get_tokens 返回保底令牌
    pm.get_tokens = AsyncMock(return_value=("test-ua", "test-umid"))
    headers = await client._get_headers(pm)
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer test-token-123"
    assert "bx-ua" in headers
    assert "bx-umidtoken" in headers


@pytest.mark.asyncio
async def test_stateful_stream_chat_serializes_complete_request(monkeypatch):
    events = []
    active = 0

    async def fake_stream_chat_once(self, pm, run_mode, prompt, model):
        nonlocal active
        active += 1
        events.append(f"start:{prompt}:active={active}")
        await asyncio.sleep(0.01)
        yield {"phase": "", "content": prompt}
        events.append(f"end:{prompt}:active={active}")
        active -= 1

    monkeypatch.setattr(AsyncQwenClient, "_stream_chat_once", fake_stream_chat_once)

    client = AsyncQwenClient("test@example.com", "password")
    pm = AsyncPlaywrightManager()

    async def collect(prompt: str):
        return [
            chunk
            async for chunk in client.stream_chat(pm, "stateful", prompt, "qwen3.6-plus")
        ]

    results = await asyncio.gather(collect("first"), collect("second"))

    assert results == [
        [{"phase": "", "content": "first"}],
        [{"phase": "", "content": "second"}],
    ]
    assert events == [
        "start:first:active=1",
        "end:first:active=1",
        "start:second:active=1",
        "end:second:active=1",
    ]

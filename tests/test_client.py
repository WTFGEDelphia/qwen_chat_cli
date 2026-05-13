"""Client 模块测试"""
import asyncio

import pytest
from unittest.mock import AsyncMock, patch

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
async def test_headers_no_bx_ua_bx_umidtoken():
    """验证请求头不包含多余的 bx-ua 和 bx-umidtoken"""
    client = AsyncQwenClient("test@example.com", "password")
    pm = AsyncPlaywrightManager()

    headers = await client._get_headers(pm)

    assert "bx-ua" not in headers, "bx-ua 不应出现在请求头中"
    assert "bx-umidtoken" not in headers, "bx-umidtoken 不应出现在请求头中"
    assert "Authorization" not in headers, "不应使用 Bearer Token 认证"


@pytest.mark.asyncio
async def test_headers_includes_required_fields():
    """验证请求头包含必需的 bx-v 和 version 字段"""
    client = AsyncQwenClient("test@example.com", "password")
    pm = AsyncPlaywrightManager()

    headers = await client._get_headers(pm)

    assert "bx-v" in headers, "必须包含 bx-v 字段"
    assert headers["bx-v"] == "2.5.36", "bx-v 值应为 2.5.36"
    assert "version" in headers, "必须包含 version 字段"
    assert headers["version"] == "0.2.50", "version 值应为 0.2.50"
    assert "source" in headers, "必须包含 source 字段"
    assert headers["source"] == "web", "source 值应为 web"


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


@pytest.mark.asyncio
async def test_login_preserves_cookies():
    """验证登录响应中的所有 Cookie 都被保留"""
    client = AsyncQwenClient("test@example.com", "password")
    pm = AsyncPlaywrightManager()

    # 模拟登录响应
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.cookies = {
        "token": "session_token_123",
        "tfstk": "fake_tfstk_value",
        "isg": "fake_isg_value",
        "cna": "fake_cna_value",
    }

    with patch.object(client.http_client, 'post', return_value=mock_response):
        result = await client.login(pm)

    assert result is True
    assert client.token == "session_token_123"
    assert client._cookies.get("tfstk") == "fake_tfstk_value"
    assert client._cookies.get("isg") == "fake_isg_value"
    assert client._cookies.get("cna") == "fake_cna_value"

"""Browser 模块测试"""
import time

import pytest

from qwen_gateway.browser import AsyncPlaywrightManager


@pytest.mark.asyncio
async def test_get_tokens_returns_fallback_without_real_browser(monkeypatch):
    """测试无法抓取时返回保底令牌"""
    pm = AsyncPlaywrightManager()

    async def fake_refresh():
        pm._last_refresh = time.time()

    monkeypatch.setattr(pm, "_refresh_tokens_from_browser", fake_refresh)

    bx_ua, bx_umid = await pm.get_tokens()

    assert bx_ua == pm.FALLBACK_UA
    assert bx_umid == pm.FALLBACK_UMID


@pytest.mark.asyncio
async def test_get_tokens_returns_captured_tokens_without_real_browser(monkeypatch):
    """测试动态令牌存在时优先返回动态令牌"""
    pm = AsyncPlaywrightManager()

    async def fake_refresh():
        pm._bx_ua = "captured-ua"
        pm._bx_umid = "captured-umid"
        pm._last_refresh = time.time()

    monkeypatch.setattr(pm, "_refresh_tokens_from_browser", fake_refresh)

    bx_ua, bx_umid = await pm.get_tokens()

    assert bx_ua == "captured-ua"
    assert bx_umid == "captured-umid"


def test_user_agent_constant():
    """测试 USER_AGENT 常量存在"""
    pm = AsyncPlaywrightManager()
    assert pm.USER_AGENT.startswith("Mozilla/5.0")

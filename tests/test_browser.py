"""Request context compatibility tests."""
import pytest

from qwen_gateway.browser import AsyncPlaywrightManager


def test_no_fallback_tokens():
    pm = AsyncPlaywrightManager()

    assert not hasattr(pm, "FALLBACK_UA"), "FALLBACK_UA 应该被移除"
    assert not hasattr(pm, "FALLBACK_UMID"), "FALLBACK_UMID 应该被移除"


@pytest.mark.asyncio
async def test_get_tokens_returns_empty():
    pm = AsyncPlaywrightManager()
    legacy_token_a, legacy_token_b = await pm.get_tokens()

    assert legacy_token_a == ""
    assert legacy_token_b == ""


def test_user_agent_constant():
    pm = AsyncPlaywrightManager()
    assert pm.USER_AGENT.startswith("Mozilla/5.0")

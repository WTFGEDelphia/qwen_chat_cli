"""Browser 模块测试"""
import pytest

from qwen_gateway.browser import USER_AGENT, AsyncPlaywrightManager


def test_no_fallback_tokens():
    """验证保底令牌常量已被移除"""
    pm = AsyncPlaywrightManager()

    # 这些常量应该不存在
    assert not hasattr(pm, "FALLBACK_UA"), "FALLBACK_UA 应该被移除"
    assert not hasattr(pm, "FALLBACK_UMID"), "FALLBACK_UMID 应该被移除"


@pytest.mark.asyncio
async def test_get_tokens_returns_empty():
    """验证 get_tokens 返回空值"""
    pm = AsyncPlaywrightManager()
    bx_ua, bx_umid = await pm.get_tokens()

    assert bx_ua == "", "bx-ua 应返回空字符串"
    assert bx_umid == "", "bx-umid 应返回空字符串"


def test_user_agent_constant():
    """测试 USER_AGENT 常量存在"""
    assert USER_AGENT.startswith("Mozilla/5.0")
"""异步风控管理器 - bx-ua 和 bx-umidtoken 已废弃"""

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


class AsyncPlaywrightManager:
    """异步风控令牌管理器（bx-ua 和 bx-umidtoken 已废弃）"""

    def __init__(self):
        pass

    async def get_tokens(self) -> tuple[str, str]:
        """获取风控令牌（已废弃，返回空值）"""
        return "", ""
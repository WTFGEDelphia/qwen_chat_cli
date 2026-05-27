"""Request context compatibility helpers."""
import asyncio


class AsyncPlaywrightManager:
    """Compatibility shell that provides the browser-like user agent."""

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    def __init__(self):
        pass

    async def get_tokens(self) -> tuple[str, str]:
        """Return empty legacy token placeholders."""
        return "", ""

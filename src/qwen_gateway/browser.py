"""异步风控管理器 - 使用 Playwright 获取 bx-ua 和 bx-umidtoken"""
import asyncio
import logging
import time
from typing import Optional

from playwright.async_api import async_playwright, Request as PwRequest

logger = logging.getLogger("QwenServer")


class AsyncPlaywrightManager:
    """异步风控令牌管理器"""

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    # 保底令牌
    FALLBACK_UA = "231!DZA3j4mUfW4+j+oAFo2jZk8FEl2ZWfPwIPF92lBLek2KxVW/XJ2EwruCiDOX5b/I+quD3qBnFMKtmWiGAG/srKz9mnlnpaRiDsJMoqvGGy+FQX1Zr34G/4jDU06bY8PEmXuzvng+zV1BKc6OP2U5E/AE+oUjTOQUU1K78Fnk7eKHddhRGrgXYA+r+/Mep4Dqk+I9xGdFt9ytKHlCok+++4mWYi++6bFEjpc0rUGDj+8LwG3lUWsSB0pqLcaMPujK5gS3VxZuQnMoK+3V6//TR7fAOJs7vbFZXiwWZr25yu3ulMHHv1tw8f4LHtpSKK+FLgqn9CI7/D8aNtE//Fsi658Nbn0y620M2YlUa5I4e/Pa35WtGsYKWoZMceHgxPs+kaUergcvcqxU4zPjR4W3iqkAsFFE3jO43sK8iEyEDhRorsD+DLNlRr9q37/x/sDgW/F6suOHQt6dv1nQJwvGEZffKgf+XX5RO/3WDee2ImQB11+431mMvyCCbl5HPONAN1qge5UjnpT+r0PJ3wYjc6cSoSXQv1906aD6N1W0il70uWYzWsqoy5eFvR/jNHgORahVLL7czdToocn6l/QVZ19sdqxH0uR7Ez/bjZWmpBcyQshQN4SOf8p4Zj77iDzi1tsXBKptZBrlM+VXo78ytMr0DbC1Dcbv0iqlvpBojsOhIrr0KNT6vhuxeOH2y/2yFmwgN7bSv0bLicTANq8WwBv26FEuBK1onSA3YcR2PAA8bLN5Pfk/Hbli/BzOA35ZwhyXuOlPHZKxY+67aDz7x+JaO3v1fZyExrvznG0CaM+QIGnSWKW90dQivUB01CbdeC+kS34OzyiXVKWUBJI+SYJBnR0alG6JCqYs0O8ZC6934uvG33h8dHChXr3QiATjJUd/103yzoso5o+uQQP8QVhtGjD+84CxYGrEl+kvdk/foeLSHUVeG9x5fkfbqpGZ7UdIcI7YD7tEUlgdY9lR2NVU5zGUc4V19F8WLhsCTE7UH9rDzg7KqXBgI5rzBq2lxrAHpTMzg4IVzC4327PRoOjIyNmUFTvo9pdW6zI8n1CCBSAow/PESgs2UYcNrP+A3Ny1qBjpPOp7PzIF2KLNs0HmtvaWbnlTodOOc5bM4xEoxvGD2JYADjCCCTKjqJmoR+X2yAGrpNAJynYO7mMifPBI0oKzymmRI3+PnH/MjvPy+lNyJaiXqnmMLU/fPQSuB+815fUuVXUeUe2G9Mf7GuUHFlM7JtPst30gG8ay1a8C24HL9CjkV5GOk0777VI3opxHrPwKh8QJWlMsLjnRS25+MA1SuiWF2/y/6uKBwZ9WgQjIJQzpqRhqjrXBmnzRAXWZftA3ImflI3ZR0SAq+maHo"
    FALLBACK_UMID = "T2gAjE9z7cERJjDt1EtsNKIOHVosD-h0sHZrpPGly1vzfOJnLNAor9E_6M96EKi6bp0="

    def __init__(self):
        self._lock = asyncio.Lock()
        self._bx_ua: Optional[str] = None
        self._bx_umid: Optional[str] = None
        self._last_refresh: float = 0.0

    async def get_tokens(self) -> tuple[str, str]:
        """获取风控令牌，25 分钟刷新一次"""
        if time.time() - self._last_refresh > 1500:
            async with self._lock:
                if time.time() - self._last_refresh > 1500:
                    await self._refresh_tokens_from_browser()
        return self._bx_ua or self.FALLBACK_UA, self._bx_umid or self.FALLBACK_UMID

    async def _refresh_tokens_from_browser(self):
        """通过 Playwright 无头浏览器获取动态风控令牌"""
        logger.info("启动无头浏览器获取动态风控令牌...")
        captured_ua: Optional[str] = None
        captured_umid: Optional[str] = None

        async def handle_request(request: PwRequest):
            nonlocal captured_ua, captured_umid
            headers = request.headers
            if 'bx-ua' in headers:
                captured_ua = headers['bx-ua']
            if 'bx-umidtoken' in headers:
                captured_umid = headers['bx-umidtoken']

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox'
                    ]
                )
                context = await browser.new_context(user_agent=self.USER_AGENT)
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = await context.new_page()
                page.on("request", handle_request)

                try:
                    await page.goto(
                        "https://chat.qwen.ai/",
                        wait_until="domcontentloaded",
                        timeout=12000
                    )
                    await page.mouse.move(100, 100)
                    await asyncio.sleep(0.5)
                    await page.evaluate(
                        "() => { fetch('/api/v2/auths/signin', { method: 'POST', body: '{}' }).catch(e => {}); }"
                    )
                except Exception as e:
                    logger.warning(f"页面加载异常：{e}")

                for _ in range(24):
                    if captured_ua:
                        break
                    await asyncio.sleep(0.5)

                if captured_ua:
                    self._bx_ua, self._bx_umid = captured_ua, captured_umid
                    logger.info("动态风控令牌获取成功！")
                else:
                    logger.warning("风控抓取超时，启用保底令牌策略。")

                self._last_refresh = time.time()
        except Exception as e:
            logger.error(f"浏览器异常：{e}")
            self._last_refresh = time.time()

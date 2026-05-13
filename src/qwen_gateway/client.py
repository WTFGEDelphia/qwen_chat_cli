"""Qwen 核心客户端"""
import asyncio
import hashlib
import json
import time
import uuid
from typing import Any, AsyncGenerator, Optional

import httpx
import logging

from .browser import AsyncPlaywrightManager

from httpx import AsyncClient, Cookies

logger = logging.getLogger("QwenServer")


class AsyncQwenClient:
    """Qwen API 客户端 - 封装所有与通义千问 API 的交互"""

    BASE_URL = "https://chat.qwen.ai"

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.token: Optional[str] = None
        self._cookies = Cookies()
        self.http_client = AsyncClient(timeout=120.0, cookies=self._cookies)
        self.active_chat_id: Optional[str] = None
        self.active_parent_id: Optional[str] = None
        self.session_lock = asyncio.Lock()

    async def _get_headers(self, pm: AsyncPlaywrightManager) -> dict:
        """获取请求头，使用正确的认证方式"""
        headers = {
            "x-request-id": str(uuid.uuid4()),
            "bx-v": "2.5.36",
            "version": "0.2.50",
            "source": "web",
            "accept": "application/json",
            "content-type": "application/json",
            "referer": "https://chat.qwen.ai/",
            "user-agent": pm.USER_AGENT,
            "accept-language": "zh-CN,zh;q=0.9",
            "timezone": "GMT+8",
        }
        return headers

    async def login(self, pm: AsyncPlaywrightManager) -> bool:
        """登录 Qwen 并获取认证 token"""
        pwd_hash = hashlib.sha256(self.password.encode()).hexdigest()
        headers = await self._get_headers(pm)
        try:
            resp = await self.http_client.post(
                f"{self.BASE_URL}/api/v2/auths/signin",
                headers=headers,
                json={"email": self.email, "password": pwd_hash}
            )
            if resp.status_code == 200:
                # 保存所有响应中的 Cookie
                for cookie_name, cookie_value in resp.cookies.items():
                    self._cookies.set(cookie_name, cookie_value)
                self.token = self._cookies.get("token")
                if not self.token:
                    logger.warning("登录响应 200 但 cookie 中无 token")
                    return False
                return True
            logger.warning(f"登录失败：HTTP {resp.status_code}")
            return False
        except Exception as e:
            logger.error(f"登录失败：{e}")
            return False

    async def create_new_chat(self, pm: AsyncPlaywrightManager) -> Optional[str]:
        """创建新会话，返回 chat_id"""
        headers = await self._get_headers(pm)
        try:
            resp = await self.http_client.post(
                f"{self.BASE_URL}/api/v2/chats/new",
                headers=headers,
                json={}
            )
            if resp.status_code == 200:
                return resp.json().get('data', {}).get('id')
        except Exception as e:
            logger.error(f"创建会话失败：{e}")
        return None

    async def stream_chat(
        self,
        pm: AsyncPlaywrightManager,
        run_mode: str,
        prompt: str,
        model: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式对话 - 返回 SSE 格式的生成结果"""
        if run_mode == "stateful":
            async with self.session_lock:
                async for chunk in self._stream_chat_once(pm, run_mode, prompt, model):
                    yield chunk
            return

        async for chunk in self._stream_chat_once(pm, run_mode, prompt, model):
            yield chunk

    async def _stream_chat_once(
        self,
        pm: AsyncPlaywrightManager,
        run_mode: str,
        prompt: str,
        model: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run one Qwen streaming request. Caller owns stateful serialization."""
        if run_mode == "stateful":
            if not self.active_chat_id:
                self.active_chat_id = await self.create_new_chat(pm)
            chat_id, parent_id = self.active_chat_id, self.active_parent_id
        else:
            chat_id = await self.create_new_chat(pm)
            parent_id = None

        if not chat_id:
            yield {"error": "无法建立官方底层会话"}
            return

        headers = await self._get_headers(pm)
        timestamp = int(time.time())

        payload = {
            "stream": True,
            "version": "2.1",
            "incremental_output": True,
            "chat_id": chat_id,
            "chat_mode": "normal",
            "model": model,
            "parent_id": parent_id,
            "messages": [{
                "fid": str(uuid.uuid4()),
                "parentId": parent_id,
                "childrenIds": [str(uuid.uuid4())],
                "role": "user",
                "content": prompt,
                "user_action": "chat",
                "files": [],
                "timestamp": timestamp,
                "models": [model],
                "chat_type": "t2t",
                "feature_config": {
                    "thinking_enabled": True,
                    "output_schema": "phase",
                    "auto_thinking": True,
                    "thinking_mode": "Auto",
                    "thinking_format": "summary",
                    "auto_search": True,
                    "mcp_tools": ["code-interpreter"]
                },
                "sub_chat_type": "t2t"
            }],
            "timestamp": timestamp
        }

        try:
            async with self.http_client.stream(
                "POST",
                f"{self.BASE_URL}/api/v2/chat/completions?chat_id={chat_id}",
                headers=headers,
                json=payload
            ) as response:
                if response.status_code != 200:
                    yield {"error": f"Qwen 官方拒绝：{response.status_code}"}
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith('data:'):
                        continue
                    data_str = line.split('data:', 1)[1].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                        if run_mode == "stateful":
                            if "response.created" in data:
                                self.active_parent_id = data["response.created"].get("response_id")
                            elif "response_id" in data:
                                self.active_parent_id = data.get("response_id")

                        if 'choices' in data:
                            delta = data['choices'][0].get('delta', {})
                            yield {
                                "phase": delta.get('phase', ''),
                                "content": delta.get('content', '')
                            }
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            yield {"error": str(e)}

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.http_client.aclose()

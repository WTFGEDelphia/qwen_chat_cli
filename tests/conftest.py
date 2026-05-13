"""共享测试 fixtures 和 helper 类"""
import asyncio
from unittest.mock import AsyncMock, Mock

import httpx


def _make_mock_http_client():
    """创建 mock httpx.AsyncClient，使认证模式获取模型走 mock 而非真实 API"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = '{"data":[{"id":"qwen3.6-plus","owned_by":"qwen","info":{"created_at":1234567890}},{"id":"qwen3.5-plus","owned_by":"qwen","info":{"created_at":1234567890}}]}'
    mock_response.json.return_value = {
        "data": [
            {"id": "qwen3.6-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}},
            {"id": "qwen3.5-plus", "owned_by": "qwen", "info": {"created_at": 1234567890}},
        ]
    }
    mock_response.headers = {"content-type": "application/json"}
    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)
    return mock_http_client


class FakeQwenClient:
    """统一的 mock QwenClient，所有测试文件共享"""

    def __init__(self, chunks=None, email=None, password=None):
        self.chunks = chunks or [{"phase": "", "content": "你好，测试响应"}]
        self.email = email
        self.password = password
        self.active_chat_id = None
        self.active_parent_id = None
        self.session_lock = asyncio.Lock()
        self.closed = False
        self.login_called = False
        self.http_client = _make_mock_http_client()

    async def login(self, pm):
        self.login_called = True
        return True

    async def create_new_chat(self, pm):
        return "chat-test-1"

    async def stream_chat(self, pm, run_mode, prompt, model):
        for chunk in self.chunks:
            yield chunk

    async def close(self):
        self.closed = True
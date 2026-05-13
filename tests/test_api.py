"""
Qwen API Server 测试套件 - 模块化版本
"""
import asyncio

from fastapi.testclient import TestClient

from qwen_gateway.app import create_app
from qwen_gateway.settings import Settings


class FakeQwenClient:
    def __init__(self, chunks=None):
        self.chunks = chunks or [{"phase": "", "content": "你好，测试响应"}]
        self.active_chat_id = None
        self.active_parent_id = None
        self.session_lock = asyncio.Lock()
        self.closed = False

    async def login(self, pm):
        return True

    async def create_new_chat(self, pm):
        return "chat-api-1"

    async def stream_chat(self, pm, run_mode, prompt, model):
        for chunk in self.chunks:
            yield chunk

    async def close(self):
        self.closed = True


def make_client(fake_client: FakeQwenClient | None = None) -> TestClient:
    client_obj = fake_client or FakeQwenClient()

    def factory(email: str, password: str):
        return client_obj

    app = create_app(
        settings=Settings(
            qwen_email="dev@example.com",
            qwen_password="plain-password",
            api_key="sk-test",
            run_mode="stateful",
        ),
        client_factory=factory,
    )
    return TestClient(app)


def test_health_check():
    with make_client() as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_models():
    with make_client() as client:
        resp = client.get("/v1/models", headers={"Authorization": "Bearer sk-test"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) == 2


def test_chat_completion_non_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "pong"
    assert data["choices"][0]["finish_reason"] == "stop"


def test_chat_completion_non_stream_upstream_error_returns_502():
    with make_client(FakeQwenClient(chunks=[{"error": "Qwen 官方拒绝：401"}])) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
            },
        )

    assert resp.status_code == 502
    assert resp.json() == {
        "error": {
            "message": "Qwen 官方拒绝：401",
            "type": "server_error",
        }
    }


def test_new_command_non_stream():
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": "/new"}],
                "stream": False,
            },
        )

    assert resp.status_code == 200
    assert "已创建新会话" in resp.json()["choices"][0]["message"]["content"]


def test_new_command_multimodal_text():
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "/new"}]}],
                "stream": False,
            },
        )

    assert resp.status_code == 200
    assert "已创建新会话" in resp.json()["choices"][0]["message"]["content"]


def test_empty_messages_returns_422():
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={"model": "qwen3.6-plus", "messages": [], "stream": False},
        )

    assert resp.status_code == 422


def test_missing_api_key_returns_401():
    with make_client() as client:
        resp = client.get("/v1/models")

    assert resp.status_code == 401

from fastapi.testclient import TestClient

from qwen_gateway.app import create_app
from qwen_gateway.settings import Settings


class FakeQwenClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.login_called = False
        self.close_called = False
        self.active_chat_id = None
        self.active_parent_id = None

    async def login(self, pm):
        self.login_called = True
        return True

    async def create_new_chat(self, pm):
        return "chat-lifespan-1"

    async def close(self):
        self.close_called = True


def test_lifespan_logs_in_creates_initial_chat_and_closes():
    holder = {}

    def client_factory(email: str, password: str):
        holder["client"] = FakeQwenClient(email, password)
        return holder["client"]

    app = create_app(
        settings=Settings(
            qwen_email="dev@example.com",
            qwen_password="plain-password",
            api_key="sk-test",
            run_mode="stateful",
        ),
        client_factory=client_factory,
    )

    with TestClient(app):
        assert holder["client"].email == "dev@example.com"
        assert holder["client"].password == "plain-password"
        assert holder["client"].login_called is True
        assert holder["client"].active_chat_id == "chat-lifespan-1"
        assert app.state.qwen_ready is True

    assert holder["client"].close_called is True


def test_chat_returns_503_when_credentials_missing():
    app = create_app(settings=Settings(api_key="sk-test"))

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": "你好"}],
                "stream": False,
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "message": "Qwen client is not ready",
            "type": "service_unavailable",
        }
    }

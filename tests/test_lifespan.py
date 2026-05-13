from fastapi.testclient import TestClient

from conftest import FakeQwenClient
from qwen_gateway.app import create_app
from qwen_gateway.settings import Settings


def test_lifespan_logs_in_creates_initial_chat_and_closes():
    holder = {}

    def client_factory(email: str, password: str):
        holder["client"] = FakeQwenClient(email=email, password=password)
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
        assert holder["client"].active_chat_id == "chat-test-1"
        assert app.state.qwen_ready is True

    assert holder["client"].closed is True


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

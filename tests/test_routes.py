"""Routes 模块测试"""
from fastapi.testclient import TestClient

from conftest import FakeQwenClient
from qwen_gateway.app import create_app
from qwen_gateway.settings import Settings


def make_client() -> TestClient:
    def factory(email: str, password: str):
        return FakeQwenClient(email=email, password=password)

    app = create_app(
        settings=Settings(
            qwen_email="dev@example.com",
            qwen_password="plain-password",
            api_key="sk-test",
            run_mode="stateful",
        ),
        client_factory=factory,
        initialize_model_cache=False,
    )
    return TestClient(app)


def test_health_check():
    with make_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "mode" in data


def test_list_models():
    with make_client() as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer sk-test"})

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) > 0


def test_invalid_api_key():
    with make_client() as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer invalid-key"})

    assert response.status_code == 401

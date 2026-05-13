"""Routes 模块测试"""
from conftest import make_test_client


def test_health_check():
    with make_test_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "mode" in data


def test_list_models():
    with make_test_client() as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer sk-test"})

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) > 0


def test_invalid_api_key():
    with make_test_client() as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer invalid-key"})

    assert response.status_code == 401
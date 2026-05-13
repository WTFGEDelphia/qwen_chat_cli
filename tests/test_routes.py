"""Routes 模块测试"""
import pytest
from fastapi.testclient import TestClient
from qwen_gateway.app import app

client = TestClient(app)


def test_health_check():
    """测试健康检查端点"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "mode" in data


def test_list_models():
    """测试模型列表接口"""
    response = client.get("/v1/models", headers={"Authorization": "Bearer sk-qwen-studio-123456"})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) > 0


def test_invalid_api_key():
    """测试无效 API Key"""
    response = client.get("/v1/models", headers={"Authorization": "Bearer invalid-key"})
    assert response.status_code == 401
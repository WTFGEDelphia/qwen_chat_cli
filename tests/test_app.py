"""App 模块测试"""
import pytest
from fastapi.testclient import TestClient
from qwen_gateway.app import app


def test_app_exists():
    """测试 FastAPI 应用存在"""
    assert app is not None
    assert app.title == "Qwen API Gateway"


def test_app_routes_registered():
    """测试路由已注册"""
    routes = [r.path for r in app.routes]
    assert "/health" in routes
    assert "/v1/models" in routes
    assert "/v1/chat/completions" in routes
    assert "/v1/responses" in routes
    assert "/v1/messages" in routes

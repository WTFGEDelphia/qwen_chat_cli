"""App 模块测试"""
from fastapi.testclient import TestClient
from qwen_gateway.app import create_app


def test_app_exists():
    """测试 FastAPI 应用存在"""
    app = create_app()
    assert app is not None
    assert app.title == "Qwen API Gateway"


def test_app_routes_registered():
    """测试路由已注册"""
    app = create_app()
    routes = [r.path for r in app.routes]
    assert "/health" in routes
    assert "/v1/models" in routes
    assert "/v1/chat/completions" in routes
    assert "/v1/responses" in routes
    assert "/v1/messages" in routes

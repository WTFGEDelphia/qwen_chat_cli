"""
Qwen API Server 测试套件 - 模块化版本
"""
from fastapi.testclient import TestClient

from conftest import FakeQwenClient
from qwen_gateway.app import create_app
from qwen_gateway.settings import Settings


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
        initialize_model_cache=False,
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


def test_chat_completion_stream_still_uses_chat_completion_chunks():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True,
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert '"object": "chat.completion.chunk"' in body
    assert '"content": "pong"' in body
    assert "data: [DONE]" in body


def test_openai_responses_non_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "input": "ping",
                "stream": False,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "response"
    assert data["status"] == "completed"
    assert data["model"] == "qwen3.6-plus"
    assert data["output_text"] == "pong"
    assert data["output"][0]["type"] == "message"
    assert data["output"][0]["content"][0]["text"] == "pong"


def test_openai_responses_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "input": [{"role": "user", "content": "ping"}],
                "stream": True,
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert "event: response.created" in body
    assert "event: response.output_text.delta" in body
    assert '"delta": "pong"' in body
    assert "event: response.completed" in body


def test_openai_responses_unsupported_feature_returns_400():
    app = create_app(
        settings=Settings(
            qwen_email="dev@example.com",
            qwen_password="plain-password",
            api_key="sk-test",
            run_mode="stateful",
            compat_mode="strict",
        ),
        initialize_model_cache=False,
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "input": "ping",
                "tools": [{"type": "web_search_preview"}],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "unsupported_feature"


def test_anthropic_messages_non_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/messages",
            headers={
                "Authorization": "Bearer sk-test",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["model"] == "qwen3.6-plus"
    assert data["content"] == [{"type": "text", "text": "pong"}]
    assert data["stop_reason"] == "end_turn"


def test_anthropic_messages_stream_success():
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        resp = client.post(
            "/v1/messages",
            headers={
                "Authorization": "Bearer sk-test",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True,
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert "event: message_start" in body
    assert "event: content_block_start" in body
    assert "event: content_block_delta" in body
    assert '"text": "pong"' in body
    assert "event: message_delta" in body
    assert "event: message_stop" in body


def test_anthropic_messages_non_stream_removes_thinking_tags():
    chunks = [
        {"phase": "thinking_summary", "content": "hidden reasoning"},
        {"phase": "", "content": "visible answer"},
    ]
    with make_client(FakeQwenClient(chunks=chunks)) as client:
        resp = client.post(
            "/v1/messages",
            headers={
                "Authorization": "Bearer sk-test",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )

    assert resp.status_code == 200
    text = resp.json()["content"][0]["text"]
    assert "<think>" not in text
    assert "</think>" not in text
    assert "hidden reasoning" in text
    assert "visible answer" in text


def test_anthropic_messages_stream_removes_thinking_tags():
    chunks = [
        {"phase": "thinking_summary", "content": "hidden reasoning"},
        {"phase": "", "content": "visible answer"},
    ]
    with make_client(FakeQwenClient(chunks=chunks)) as client:
        resp = client.post(
            "/v1/messages",
            headers={
                "Authorization": "Bearer sk-test",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True,
            },
        )

    assert resp.status_code == 200
    body = resp.text
    assert "<think>" not in body
    assert "</think>" not in body
    assert "hidden reasoning" in body
    assert "visible answer" in body


def test_anthropic_messages_unsupported_feature_returns_400():
    app = create_app(
        settings=Settings(
            qwen_email="dev@example.com",
            qwen_password="plain-password",
            api_key="sk-test",
            run_mode="stateful",
            compat_mode="strict",
        ),
        initialize_model_cache=False,
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
                "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
            },
        )

    assert resp.status_code == 400
    data = resp.json()
    assert data["type"] == "error"
    assert data["error"]["type"] == "unsupported_feature"


def test_openai_responses_returns_503_when_credentials_missing():
    app = create_app(settings=Settings(api_key="sk-test"), initialize_model_cache=False)

    with TestClient(app) as client:
        response = client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={"model": "qwen3.6-plus", "input": "你好"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "message": "Qwen client is not ready",
            "type": "service_unavailable",
        }
    }


def test_anthropic_messages_returns_503_when_credentials_missing():
    app = create_app(settings=Settings(api_key="sk-test"), initialize_model_cache=False)

    with TestClient(app) as client:
        response = client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "你好"}],
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "type": "error",
        "error": {
            "message": "Qwen client is not ready",
            "type": "service_unavailable",
        },
    }


def test_anthropic_messages_upstream_error_returns_anthropic_format():
    with make_client(FakeQwenClient(chunks=[{"error": "Qwen upstream error"}])) as client:
        resp = client.post(
            "/v1/messages",
            headers={
                "Authorization": "Bearer sk-test",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )

    assert resp.status_code == 502
    data = resp.json()
    # Anthropic 端点应返回 Anthropic 格式错误，而非 OpenAI 格式
    assert data["type"] == "error"
    assert data["error"]["type"] == "server_error"
    assert "Qwen upstream error" in data["error"]["message"]


def test_responses_tools_accepted_in_lenient_mode():
    """lenient 模式下 /v1/responses 接受 tools 字段（默认）"""
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "hello"}])) as client:
        response = client.post(
            "/v1/responses",
            json={
                "model": "qwen3.6-plus",
                "input": "hi",
                "tools": [{"type": "web_search_preview"}],
            },
            headers={"Authorization": "Bearer sk-test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["output_text"] == "hello"


def test_messages_tools_accepted_in_lenient_mode():
    """lenient 模式下 /v1/messages 接受 tools 字段（默认）"""
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        response = client.post(
            "/v1/messages",
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
            },
            headers={"Authorization": "Bearer sk-test"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "message"


def test_messages_thinking_accepted_in_lenient_mode():
    """lenient 模式下 /v1/messages 接受 thinking 字段（默认）"""
    with make_client(FakeQwenClient(chunks=[{"phase": "", "content": "pong"}])) as client:
        response = client.post(
            "/v1/messages",
            json={
                "model": "qwen3.6-plus",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "hi"}],
                "thinking": {"type": "enabled", "budget_tokens": 16000},
            },
            headers={"Authorization": "Bearer sk-test"},
        )

    assert response.status_code == 200

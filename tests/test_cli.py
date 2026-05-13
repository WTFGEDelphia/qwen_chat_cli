"""CLI 模块测试"""
import pytest

from qwen_gateway.cli import build_parser, main


def test_parser_default_values(monkeypatch):
    """测试默认值"""
    monkeypatch.delenv("RUN_MODE", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("HOST", raising=False)

    parser = build_parser()
    args = parser.parse_args([])

    assert args.mode == "stateful"
    assert args.port == 8000
    assert args.host == "127.0.0.1"


def test_parser_override_values():
    """测试覆盖值"""
    parser = build_parser()
    args = parser.parse_args(["--mode", "stateless", "--port", "9000", "--host", "0.0.0.0"])

    assert args.mode == "stateless"
    assert args.port == 9000
    assert args.host == "0.0.0.0"


def test_main_rejects_public_host_with_default_api_key(monkeypatch):
    """默认 API Key 不允许绑定公网地址"""
    monkeypatch.delenv("API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc:
        main(["--host", "0.0.0.0"])

    assert exc.value.code == 2


def test_main_passes_valid_args_to_uvicorn(monkeypatch):
    """CLI 将参数传给 uvicorn"""
    calls = {}

    def fake_run(app_path, *, host, port, reload):
        calls["app_path"] = app_path
        calls["host"] = host
        calls["port"] = port
        calls["reload"] = reload

    monkeypatch.setenv("API_KEY", "sk-custom-local-secret")
    monkeypatch.setattr("uvicorn.run", fake_run)

    main(["--host", "0.0.0.0", "--port", "9001", "--mode", "stateless", "--reload"])

    assert calls == {
        "app_path": "qwen_gateway.app:app",
        "host": "0.0.0.0",
        "port": 9001,
        "reload": True,
    }

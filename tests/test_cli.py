"""CLI 模块测试"""
import os

import pytest

from qwen_gateway.cli import build_parser, main
from qwen_gateway.settings import Settings


DEFAULT_SETTINGS = Settings()


def test_parser_default_values(monkeypatch):
    """测试默认值"""
    monkeypatch.setattr("qwen_gateway.cli.load_settings", lambda: DEFAULT_SETTINGS)

    parser = build_parser()
    args = parser.parse_args([])

    assert args.mode == "stateful"
    assert args.port == 8000
    assert args.host == "127.0.0.1"


def test_parser_override_values(monkeypatch):
    """测试覆盖值"""
    monkeypatch.setattr("qwen_gateway.cli.load_settings", lambda: DEFAULT_SETTINGS)

    parser = build_parser()
    args = parser.parse_args(["--mode", "stateless", "--port", "9000", "--host", "0.0.0.0"])

    assert args.mode == "stateless"
    assert args.port == 9000
    assert args.host == "0.0.0.0"


def test_main_rejects_public_host_with_default_api_key(monkeypatch):
    """默认 API Key 不允许绑定公网地址"""
    # main() 中 load_settings 被调用两次：
    # 1. build_parser() 内 — 需要返回默认值用于 argparse defaults
    # 2. 参数解析后 — 需要反映 --host 0.0.0.0 覆盖以触发 validate_network_exposure
    monkeypatch.setattr("qwen_gateway.cli.load_settings", lambda: Settings(host="0.0.0.0"))

    with pytest.raises(SystemExit) as exc:
        main(["--host", "0.0.0.0"])

    assert exc.value.code == 2


def test_main_passes_valid_args_to_uvicorn(monkeypatch):
    """CLI 将参数传给 uvicorn"""
    calls = {}

    def fake_run(app, *, host, port, reload):
        calls["app_title"] = app.title
        calls["host"] = host
        calls["port"] = port
        calls["reload"] = reload

    monkeypatch.setenv("API_KEY", "sk-custom-local-secret")
    monkeypatch.setattr("uvicorn.run", fake_run)

    main(["--host", "0.0.0.0", "--port", "9001", "--mode", "stateless", "--reload"])

    assert calls == {
        "app_title": "Qwen API Gateway",
        "host": "0.0.0.0",
        "port": 9001,
        "reload": True,
    }


def test_parser_compat_mode_default():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.compat_mode == "lenient"


def test_parser_compat_mode_strict():
    parser = build_parser()
    args = parser.parse_args(["--compat-mode", "strict"])
    assert args.compat_mode == "strict"


def test_main_passes_compat_mode_to_env(monkeypatch):
    """--compat-mode 设置 COMPAT_MODE 环境变量"""
    seen_env = {}
    calls = {}

    def fake_run(app, *, host, port, reload):
        calls["called"] = True

    monkeypatch.setenv("API_KEY", "sk-custom-local-secret")
    monkeypatch.setattr("uvicorn.run", fake_run)

    main(["--compat-mode", "strict"])

    assert os.environ.get("COMPAT_MODE") == "strict"


def test_main_compat_mode_propagates_to_settings(monkeypatch):
    """验证 main() 中 load_settings 在环境变量设置后被调用，compat_mode 正确传递"""
    captured_settings = {}

    def fake_load_settings():
        s = Settings(compat_mode=os.environ.get("COMPAT_MODE", "lenient"))
        captured_settings["compat_mode"] = s.compat_mode
        return s

    def fake_run(app, *, host, port, reload):
        pass

    monkeypatch.setattr("qwen_gateway.cli.load_settings", fake_load_settings)
    monkeypatch.setattr("uvicorn.run", fake_run)

    main(["--compat-mode", "strict"])

    assert captured_settings["compat_mode"] == "strict", (
        "load_settings 应在 os.environ 设置 COMPAT_MODE 之后被调用，"
        "以确保 CLI 参数正确传递到 settings"
    )

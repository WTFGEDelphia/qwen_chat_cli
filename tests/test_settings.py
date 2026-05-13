import pytest

from qwen_gateway.settings import (
    DEFAULT_API_KEY,
    DEFAULT_HOST,
    Settings,
    load_settings,
    parse_cors_origins,
    validate_network_exposure,
)


def test_load_settings_defaults_to_localhost():
    settings = load_settings(env={}, load_env=False)

    assert settings.host == DEFAULT_HOST
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.run_mode == "stateful"
    assert settings.api_key == DEFAULT_API_KEY
    assert settings.cors_allow_origins == ()


def test_load_settings_reads_env_mapping():
    settings = load_settings(
        env={
            "QWEN_EMAIL": "dev@example.com",
            "QWEN_PASSWORD": "plain-password",
            "API_KEY": "sk-local-strong",
            "RUN_MODE": "stateless",
            "HOST": "localhost",
            "PORT": "9000",
            "CORS_ALLOW_ORIGINS": "http://localhost:3000, http://127.0.0.1:5173",
        },
        load_env=False,
    )

    assert settings.qwen_email == "dev@example.com"
    assert settings.qwen_password == "plain-password"
    assert settings.credentials_configured is True
    assert settings.run_mode == "stateless"
    assert settings.host == "localhost"
    assert settings.port == 9000
    assert settings.cors_allow_origins == (
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    )


def test_parse_cors_origins_drops_empty_items():
    assert parse_cors_origins(" http://a.test, ,http://b.test ") == (
        "http://a.test",
        "http://b.test",
    )


def test_public_host_rejects_default_api_key():
    settings = Settings(host="0.0.0.0", api_key=DEFAULT_API_KEY)

    with pytest.raises(ValueError, match="Refusing to bind public host"):
        validate_network_exposure(settings)


def test_public_host_allows_custom_api_key():
    settings = Settings(host="0.0.0.0", api_key="sk-custom-local-secret")

    validate_network_exposure(settings)


def test_compat_mode_defaults_to_lenient():
    settings = load_settings(env={}, load_env=False)
    assert settings.compat_mode == "lenient"


def test_compat_mode_reads_env():
    settings = load_settings(
        env={"COMPAT_MODE": "strict"},
        load_env=False,
    )
    assert settings.compat_mode == "strict"


def test_compat_mode_rejects_invalid_value():
    with pytest.raises(ValueError, match="COMPAT_MODE must be 'strict' or 'lenient'"):
        load_settings(
            env={"COMPAT_MODE": "invalid"},
            load_env=False,
        )

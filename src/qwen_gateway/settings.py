"""Runtime settings for Qwen Gateway."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from dotenv import load_dotenv

DEFAULT_API_KEY = "sk-qwen-studio-123456"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_RUN_MODE = "stateful"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def parse_cors_origins(raw_value: str | None) -> tuple[str, ...]:
    """Parse comma-separated CORS origins."""
    if not raw_value:
        return ()
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    qwen_email: str | None = None
    qwen_password: str | None = None
    api_key: str = DEFAULT_API_KEY
    run_mode: str = DEFAULT_RUN_MODE
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    cors_allow_origins: tuple[str, ...] = ()

    # 模型缓存配置
    model_cache_dir: str = ""
    """模型缓存文件存储目录，空字符串表示使用 ~/.cache/qwen_gateway"""

    model_cache_ttl: int = 1800
    """模型缓存有效期（秒），默认 30 分钟"""

    model_cache_refresh_interval: int = 1800
    """后台刷新间隔（秒），默认 30 分钟"""

    compat_mode: str = "lenient"
    """兼容模式：strict(拒绝不支持字段返回400) | lenient(静默忽略不支持字段)"""

    @property
    def credentials_configured(self) -> bool:
        return bool(self.qwen_email and self.qwen_password)

    @property
    def uses_default_api_key(self) -> bool:
        return self.api_key == DEFAULT_API_KEY

    @property
    def binds_public_host(self) -> bool:
        return self.host not in LOCAL_HOSTS


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    load_env: bool = True,
) -> Settings:
    """Load settings from .env and environment variables."""
    if load_env:
        load_dotenv()

    source = os.environ if env is None else env

    run_mode = source.get("RUN_MODE", DEFAULT_RUN_MODE)
    if run_mode not in {"stateless", "stateful"}:
        raise ValueError("RUN_MODE must be 'stateless' or 'stateful'")

    port_raw = source.get("PORT", str(DEFAULT_PORT))
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError("PORT must be an integer") from exc

    # 模型缓存配置
    model_cache_dir = source.get("MODEL_CACHE_DIR", "")

    model_cache_ttl_raw = source.get("MODEL_CACHE_TTL", "1800")
    try:
        model_cache_ttl = int(model_cache_ttl_raw)
        if model_cache_ttl <= 0:
            raise ValueError("MODEL_CACHE_TTL must be positive")
    except ValueError as exc:
        raise ValueError(f"MODEL_CACHE_TTL must be a positive integer: {exc}") from exc

    model_cache_refresh_interval_raw = source.get("MODEL_CACHE_REFRESH_INTERVAL", "1800")
    try:
        model_cache_refresh_interval = int(model_cache_refresh_interval_raw)
        if model_cache_refresh_interval <= 0:
            raise ValueError("MODEL_CACHE_REFRESH_INTERVAL must be positive")
    except ValueError as exc:
        raise ValueError(f"MODEL_CACHE_REFRESH_INTERVAL must be a positive integer: {exc}") from exc

    compat_mode = source.get("COMPAT_MODE", "lenient")
    if compat_mode not in {"strict", "lenient"}:
        raise ValueError("COMPAT_MODE must be 'strict' or 'lenient'")

    return Settings(
        qwen_email=source.get("QWEN_EMAIL") or None,
        qwen_password=source.get("QWEN_PASSWORD") or None,
        api_key=source.get("API_KEY", DEFAULT_API_KEY),
        run_mode=run_mode,
        host=source.get("HOST", DEFAULT_HOST),
        port=port,
        cors_allow_origins=parse_cors_origins(source.get("CORS_ALLOW_ORIGINS")),
        # 模型缓存配置
        model_cache_dir=model_cache_dir,
        model_cache_ttl=model_cache_ttl,
        model_cache_refresh_interval=model_cache_refresh_interval,
        compat_mode=compat_mode,
    )


def validate_network_exposure(settings: Settings) -> None:
    """Reject public binds when the API key is still the documented default."""
    if settings.binds_public_host and settings.uses_default_api_key:
        raise ValueError(
            "Refusing to bind public host with the default API_KEY. "
            "Set API_KEY to a strong secret or bind to 127.0.0.1."
        )

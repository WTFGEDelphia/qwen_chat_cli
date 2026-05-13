"""CLI 入口点"""
import argparse
import os
from collections.abc import Sequence

from .settings import DEFAULT_API_KEY, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_RUN_MODE, load_settings, validate_network_exposure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qwen-gateway",
        description="Qwen Studio API Gateway with /new command support",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["stateless", "stateful"],
        default=DEFAULT_RUN_MODE,
        help="运行模式：stateless(无状态) | stateful(有状态，支持 /new 命令)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="监听端口 (默认：8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help="监听地址 (默认：127.0.0.1)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式：启用自动重载",
    )
    parser.add_argument(
        "--compat-mode",
        type=str,
        choices=["strict", "lenient"],
        default="lenient",
        help="兼容模式：strict(拒绝不支持的字段返回400) | lenient(静默忽略，默认)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """CLI 入口点"""
    parser = build_parser()
    args = parser.parse_args(argv)

    os.environ["RUN_MODE"] = args.mode
    os.environ["PORT"] = str(args.port)
    os.environ["HOST"] = args.host
    os.environ["COMPAT_MODE"] = args.compat_mode

    settings = load_settings()
    try:
        validate_network_exposure(settings)
    except ValueError as exc:
        parser.error(str(exc))

    from .app import create_app as _create_app

    app = _create_app(settings=settings)

    import uvicorn

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )

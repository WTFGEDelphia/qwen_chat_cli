"""CLI 入口点"""
import argparse
import os
from collections.abc import Sequence

from .settings import load_settings, validate_network_exposure


def build_parser() -> argparse.ArgumentParser:
    settings = load_settings()
    parser = argparse.ArgumentParser(
        prog="qwen-gateway",
        description="Qwen Studio API Gateway with /new command support",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["stateless", "stateful"],
        default=settings.run_mode,
        help="运行模式：stateless(无状态) | stateful(有状态，支持 /new 命令)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help="监听端口 (默认：8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=settings.host,
        help="监听地址 (默认：127.0.0.1)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式：启用自动重载",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """CLI 入口点"""
    parser = build_parser()
    args = parser.parse_args(argv)

    os.environ["RUN_MODE"] = args.mode
    os.environ["PORT"] = str(args.port)
    os.environ["HOST"] = args.host

    settings = load_settings()
    try:
        validate_network_exposure(settings)
    except ValueError as exc:
        parser.error(str(exc))

    import uvicorn

    uvicorn.run(
        "qwen_gateway.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )

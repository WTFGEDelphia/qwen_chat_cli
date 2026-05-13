#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT_DIR"
rm -rf build dist

python -m pip install -U pip
python -m pip install -U build twine
python -m build
python -m twine check dist/*

python - <<'PY'
from pathlib import Path
import tarfile
import zipfile

dist_dir = Path("dist")
wheel_path = next(dist_dir.glob("qwen_gateway-*.whl"))
sdist_path = next(dist_dir.glob("qwen_gateway-*.tar.gz"))

expected_modules = {
    "qwen_gateway/__init__.py",
    "qwen_gateway/__main__.py",
    "qwen_gateway/app.py",
    "qwen_gateway/browser.py",
    "qwen_gateway/cli.py",
    "qwen_gateway/client.py",
    "qwen_gateway/routes.py",
    "qwen_gateway/schemas.py",
    "qwen_gateway/settings.py",
}

with zipfile.ZipFile(wheel_path) as wheel_file:
    wheel_names = set(wheel_file.namelist())

missing_from_wheel = expected_modules - wheel_names
assert not missing_from_wheel, f"Missing from wheel: {sorted(missing_from_wheel)}"

with tarfile.open(sdist_path, "r:gz") as sdist_file:
    sdist_names = set(sdist_file.getnames())

for module in expected_modules:
    assert any(name.endswith(f"src/{module}") for name in sdist_names), module
PY

python -m venv "$TMP_DIR/venv"
"$TMP_DIR/venv/bin/python" -m pip install -U pip
"$TMP_DIR/venv/bin/pip" install "$ROOT_DIR"/dist/*.whl
"$TMP_DIR/venv/bin/python" - <<'PY'
from qwen_gateway.app import app
from qwen_gateway.cli import build_parser

assert app.title == "Qwen API Gateway"
assert build_parser().parse_args([]).host == "127.0.0.1"
assert build_parser().parse_args([]).port == 8000
assert build_parser().parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"
PY
"$TMP_DIR/venv/bin/qwen-gateway" --help >/dev/null

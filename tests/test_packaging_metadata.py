"""Packaging metadata tests."""
from pathlib import Path


def test_playwright_is_not_a_runtime_dependency():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "playwright" not in pyproject.lower()
    assert "playwright" not in requirements.lower()

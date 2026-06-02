"""Python 3.11 portability check.

`pyproject.toml` declares ``requires-python = ">=3.11"``. The whole source
tree must therefore parse on a 3.11 interpreter — that is, no PEP 701
(Python 3.12) idioms such as backslashes inside f-string expression parts.

We test this with ``ast.parse`` (syntax-only, no execution) because:
  * the running interpreter may be 3.13 (PEP 701 already in effect) where
    such syntax is legal and would silently slip through `py_compile`;
  * we want a portability gate independent of the current interpreter
    version.

The check below walks every ``.py`` under ``src/`` and re-parses it with
``feature_version=(3, 11)`` — that flag asks the AST parser to enforce
3.11-era restrictions, including the no-backslash-in-f-string rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def _python_files() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(SRC_ROOT)))
def test_source_parses_under_python_311(path: Path) -> None:
    """Every src/ module must be syntactically valid Python 3.11."""
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(path), feature_version=(3, 11))
    except SyntaxError as exc:
        pytest.fail(
            f"{path.relative_to(SRC_ROOT)} contains syntax requiring Python > 3.11:\n"
            f"  line {exc.lineno}: {exc.text!r}\n  {exc.msg}"
        )

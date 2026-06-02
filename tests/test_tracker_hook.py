"""Unit tests for the tracker-discipline decision logic.

The git hook in `scripts/pre-commit.sh` mirrors `cmp_ensemble.tracker.decide`;
these tests cover every branch of the rule.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cmp_ensemble.tracker import HookDecision, decide


# ──────────────────────────────────────────────────────────────────────────
# decide() — the rule
# ──────────────────────────────────────────────────────────────────────────


def test_empty_commit_does_not_block() -> None:
    out = decide([])
    assert out == HookDecision(block=False, touched_src=False, touched_tracker=False)


def test_only_tracker_does_not_block() -> None:
    out = decide(["feature_list.json", "claude-progress.md"])
    assert not out.block
    assert not out.touched_src and out.touched_tracker


def test_only_docs_does_not_block() -> None:
    """Docs / configs / tests changes alone are fine — no src/ touched."""
    out = decide(["README.md", "docs/methodology.md", "tests/test_metrics.py"])
    assert not out.block


def test_src_and_tracker_together_passes() -> None:
    out = decide(["src/cmp_ensemble/foo.py", "feature_list.json"])
    assert not out.block
    assert out.touched_src and out.touched_tracker


def test_src_alone_blocks() -> None:
    out = decide(["src/cmp_ensemble/foo.py"])
    assert out.block
    assert out.touched_src and not out.touched_tracker
    assert "feature_list.json" in out.reason
    assert "claude-progress.md" in out.reason
    assert "ALLOW_SRC_ONLY=1" in out.reason


def test_bypass_returns_block_false() -> None:
    out = decide(["src/cmp_ensemble/foo.py"], allow_src_only=True)
    assert not out.block
    assert "bypassed" in out.reason


def test_multiple_src_files_still_blocks_without_tracker() -> None:
    out = decide([
        "src/cmp_ensemble/foo.py",
        "src/cmp_ensemble/bar/baz.py",
        "tests/test_foo.py",
    ])
    assert out.block


def test_windows_style_paths_normalised() -> None:
    """Caller may pass paths with backslashes (e.g. on Windows shells); we
    normalise to POSIX before checking the rule."""
    out = decide([r"src\cmp_ensemble\foo.py"])
    assert out.touched_src is True
    out2 = decide([r"src\cmp_ensemble\foo.py", "feature_list.json"])
    assert not out2.block


def test_partial_match_does_not_count_as_src() -> None:
    """A file whose name starts with 'src' but is not under 'src/' must not
    trigger the rule (e.g. a top-level 'srclient.txt' nonsense file)."""
    out = decide(["srclient.txt"])
    assert not out.touched_src
    assert not out.block


def test_partial_match_does_not_count_as_tracker() -> None:
    """Tracker match is exact filename — 'feature_list.json.bak' must not
    count, and a path like 'docs/feature_list.json' must not count either."""
    out = decide(["src/x.py", "feature_list.json.bak"])
    assert not out.touched_tracker
    assert out.block
    out2 = decide(["src/x.py", "docs/feature_list.json"])
    assert not out2.touched_tracker
    assert out2.block


# ──────────────────────────────────────────────────────────────────────────
# Shell hook smoke test (syntax + bypass branch)
# ──────────────────────────────────────────────────────────────────────────


def _hook_path() -> Path:
    return Path(__file__).resolve().parent.parent / "scripts" / "pre-commit.sh"


def test_hook_script_exists_and_is_non_empty() -> None:
    p = _hook_path()
    assert p.exists()
    assert p.stat().st_size > 100


def test_hook_script_has_bypass_logic() -> None:
    text = _hook_path().read_text(encoding="utf-8")
    assert "ALLOW_SRC_ONLY" in text
    assert "feature_list.json" in text
    assert "claude-progress.md" in text


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_hook_script_parses_as_bash() -> None:
    """`bash -n` is a syntax check — does not execute the script."""
    p = _hook_path()
    result = subprocess.run(
        ["bash", "-n", str(p)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


# ──────────────────────────────────────────────────────────────────────────
# Installer scripts
# ──────────────────────────────────────────────────────────────────────────


def test_installer_scripts_exist() -> None:
    base = Path(__file__).resolve().parent.parent / "scripts"
    assert (base / "install_hooks.sh").exists()
    assert (base / "install_hooks.ps1").exists()

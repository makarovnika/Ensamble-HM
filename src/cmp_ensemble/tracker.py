"""Tracker discipline (ТЗ §13, audit recommendation from session 005).

Enforces that any commit touching ``src/`` also updates one of the tracker
files (``feature_list.json`` or ``claude-progress.md``). The decision is
shared between the git hook (``scripts/pre-commit.sh``) and the tests so we
can unit-test the rule without forking a real git operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

# Files that count as tracker updates. Add to this list with care — every
# entry weakens the discipline.
TRACKER_FILES: tuple[str, ...] = (
    "feature_list.json",
    "claude-progress.md",
)

# Path prefixes that REQUIRE a tracker file in the same commit.
SRC_PREFIXES: tuple[str, ...] = (
    "src/",
)


@dataclass(frozen=True)
class HookDecision:
    block: bool
    touched_src: bool
    touched_tracker: bool
    reason: str = ""


def _normalize(path: str) -> str:
    """Normalize to POSIX style — git always emits forward slashes, but be
    defensive in case the caller passed a Windows backslash list."""
    return str(PurePosixPath(path.replace("\\", "/")))


def decide(
    staged_files: list[str],
    *,
    allow_src_only: bool = False,
) -> HookDecision:
    """Return a HookDecision for the given staged file list.

    Block iff:
      * at least one staged file is under any of ``SRC_PREFIXES``;
      * AND no staged file matches any of ``TRACKER_FILES``;
      * AND ``allow_src_only`` is False.
    """
    files = [_normalize(p) for p in staged_files]
    touched_src = any(
        any(f.startswith(prefix) for prefix in SRC_PREFIXES) for f in files
    )
    touched_tracker = any(f in TRACKER_FILES for f in files)

    if allow_src_only:
        return HookDecision(
            block=False, touched_src=touched_src, touched_tracker=touched_tracker,
            reason="bypassed via ALLOW_SRC_ONLY=1",
        )
    if touched_src and not touched_tracker:
        reason = (
            "src/ changes must include an update to feature_list.json "
            "or claude-progress.md. Set ALLOW_SRC_ONLY=1 to bypass."
        )
        return HookDecision(
            block=True, touched_src=True, touched_tracker=False, reason=reason,
        )
    return HookDecision(
        block=False, touched_src=touched_src, touched_tracker=touched_tracker,
    )

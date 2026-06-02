"""Reproducibility metadata for pipeline outputs.

Every artefact written under ``outputs/`` should have a sidecar
``<artefact>.meta.yaml`` listing the git SHA, timestamp, seed, and a hash of
the resolved config. Use ``write_sidecar(path, ...)`` after writing the
artefact itself.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _git_sha(repo_root: Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root) if repo_root else None,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def _git_dirty(repo_root: Path | None = None) -> bool:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root) if repo_root else None,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return bool(out.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def config_hash(cfg: dict[str, Any]) -> str:
    """Stable hash of a config dict — order-independent JSON serialisation."""
    s = json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def write_sidecar(
    artefact_path: Path,
    *,
    config: dict[str, Any] | None = None,
    seed: int | None = None,
    extra: dict[str, Any] | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Write a sidecar ``<artefact>.meta.yaml`` next to the artefact.

    Returns the sidecar path.
    """
    artefact_path = Path(artefact_path)
    sidecar = artefact_path.with_suffix(artefact_path.suffix + ".meta.yaml")
    payload: dict[str, Any] = {
        "artefact": artefact_path.name,
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(repo_root),
        "git_dirty": _git_dirty(repo_root),
    }
    if config is not None:
        payload["config_hash"] = config_hash(config)
    if seed is not None:
        payload["seed"] = int(seed)
    if extra:
        payload["extra"] = extra
    sidecar.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return sidecar

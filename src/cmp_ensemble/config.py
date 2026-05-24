"""Config loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    """Locate the project root: the directory holding `configs/default.yaml`.

    Walks up from this file until it finds the configs directory. Raises if
    not found — callers should pass an explicit path in that case.
    """
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "configs" / "default.yaml").exists():
            return parent
    raise FileNotFoundError("Could not locate project root (configs/default.yaml).")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_default_config(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    return load_yaml(root / "configs" / "default.yaml")


def load_theta_schema(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    return load_yaml(root / "configs" / "theta_schema.yaml")


def load_noise_spec(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    return load_yaml(root / "configs" / "noise_spec.yaml")


def load_well_layout(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    return load_yaml(root / "configs" / "well_layout.yaml")

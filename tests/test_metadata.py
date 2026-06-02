"""Tests for the reproducibility sidecar helper."""

from __future__ import annotations

import yaml

from cmp_ensemble.metadata import config_hash, write_sidecar


def test_config_hash_stable(tmp_path) -> None:
    h1 = config_hash({"a": 1, "b": [1, 2]})
    h2 = config_hash({"b": [1, 2], "a": 1})  # different order
    assert h1 == h2


def test_config_hash_changes_on_value_change() -> None:
    h1 = config_hash({"a": 1, "b": [1, 2]})
    h2 = config_hash({"a": 1, "b": [1, 3]})
    assert h1 != h2


def test_write_sidecar_basic(tmp_path) -> None:
    art = tmp_path / "foo.npy"
    art.write_bytes(b"placeholder")
    sidecar = write_sidecar(art, seed=42, config={"x": 1}, extra={"phase": 1})
    assert sidecar.exists()
    data = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    assert data["artefact"] == "foo.npy"
    assert data["seed"] == 42
    assert data["extra"]["phase"] == 1
    assert "config_hash" in data
    assert "written_at_utc" in data


def test_evaluation_mode_canonical_label(tmp_path) -> None:
    """The Phase 3 default `evaluation_mode` stamp must be the canonical value
    used everywhere: code, sidecars, docs, ТЗ, and the manuscript label.
    Cleanup-004 (session 014) chose `no_truth_baseline_only` as the canonical
    name — this test guards against accidental reintroduction of the older
    `forecast_no_truth_ensemble_comparison` alias.
    """
    canonical = "no_truth_baseline_only"
    # Source of truth: CLI default
    from pathlib import Path
    cli_text = (Path(__file__).resolve().parent.parent / "src" / "cmp_ensemble" / "cli.py").read_text(encoding="utf-8")
    assert canonical in cli_text, (
        f"CLI source must reference the canonical evaluation_mode {canonical!r}"
    )
    assert "forecast_no_truth_ensemble_comparison" not in cli_text, (
        "CLI source must NOT reference the retired alias "
        "'forecast_no_truth_ensemble_comparison'"
    )


def test_write_sidecar_no_config(tmp_path) -> None:
    art = tmp_path / "bar.csv"
    art.write_text("a,b\n1,2\n", encoding="utf-8")
    sidecar = write_sidecar(art)
    assert sidecar.exists()
    data = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    assert "config_hash" not in data
    assert "seed" not in data

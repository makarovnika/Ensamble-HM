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


def test_write_sidecar_no_config(tmp_path) -> None:
    art = tmp_path / "bar.csv"
    art.write_text("a,b\n1,2\n", encoding="utf-8")
    sidecar = write_sidecar(art)
    assert sidecar.exists()
    data = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    assert "config_hash" not in data
    assert "seed" not in data

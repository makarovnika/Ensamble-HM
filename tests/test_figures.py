"""Tests for the manuscript figures (ТЗ §4)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless backend for CI / pytest

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.viz.diagnostics import (
    fig01_pipeline,
    fig02_qc_spread,
    fig06_cluster3_migration,
    mirror_to_article_assets,
)


def _make_spread_csv(path: Path) -> Path:
    df = pd.DataFrame(
        {
            "component": ["THICK", "MAJ_R", "AZIMUTH", "NUMBER_CHANNELS",
                          "CHANNELS_WIDTH", "LEN", "AMPLITUDE", "RELATIVE", "PROP"],
            "sigma_prior": [3.75, 717.6, 6.8, 1.53, 2.18, 137.8, 374.7, 0.099, 0.032],
            "sigma_post": [3.65, 717.6, 6.6, 1.51, 2.18, 137.8, 374.7, 0.099, 0.032],
            "spread_retention": [0.97, 1.00, 0.97, 0.99, 1.00, 1.00, 1.00, 1.00, 1.00],
        }
    )
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def _make_migration_csv(path: Path) -> Path:
    rows = []
    for cl in [0, 1, 2]:
        for j, comp in enumerate(["THICK", "MAJ_R", "AZIMUTH"]):
            rows.append({
                "cluster": cl, "component": comp,
                "reference": 10.0 + j * 100,
                "prior_centroid": 10.0 + j * 100 + cl * 0.5,
                "post_centroid": 10.0 + j * 100 + cl * 0.5 + (cl - 1) * 1.0,
                "delta_prior_to_post": (cl - 1) * 1.0,
                "delta_ref_to_prior": cl * 0.5,
                "delta_ref_to_post": cl * 0.5 + (cl - 1) * 1.0,
            })
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def test_fig01_pipeline_writes_png_and_pdf(tmp_path) -> None:
    p = fig01_pipeline(tmp_path / "fig01_pipeline.png")
    assert p.exists()
    assert p.stat().st_size > 1000
    pdf = p.with_suffix(".pdf")
    assert pdf.exists() and pdf.stat().st_size > 500


def test_fig02_qc_spread_writes_png_and_pdf(tmp_path) -> None:
    spread = _make_spread_csv(tmp_path / "spread.csv")
    p = fig02_qc_spread(spread, tmp_path / "fig02_qc_spread.png")
    assert p.exists() and p.stat().st_size > 1000
    assert p.with_suffix(".pdf").exists()


def test_fig02_rejects_missing_columns(tmp_path) -> None:
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"foo": [1, 2]}).to_csv(bad, index=False)
    with pytest.raises(ValueError, match="component"):
        fig02_qc_spread(bad, tmp_path / "out.png")


def test_fig06_cluster_migration_writes_png_and_pdf(tmp_path) -> None:
    mig = _make_migration_csv(tmp_path / "mig.csv")
    p = fig06_cluster3_migration(mig, tmp_path / "fig06_cluster3_migration.png")
    assert p.exists() and p.stat().st_size > 1000
    assert p.with_suffix(".pdf").exists()


def test_mirror_to_article_assets(tmp_path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "fig01_pipeline.png").write_bytes(b"\x89PNG\r\n\x1a\n0123")
    (src / "fig01_pipeline.pdf").write_bytes(b"%PDF-1.4\n")
    (src / "not_a_figure.txt").write_text("skip me", encoding="utf-8")

    dst = tmp_path / "dst"
    copied = mirror_to_article_assets(src, dst)
    assert len(copied) == 2
    # Round-trip the contents
    assert (dst / "fig01_pipeline.png").read_bytes().startswith(b"\x89PNG")
    assert (dst / "fig01_pipeline.pdf").read_bytes().startswith(b"%PDF")
    assert not (dst / "not_a_figure.txt").exists()

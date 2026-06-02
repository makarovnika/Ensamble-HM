"""Tests for the cluster-migration plotly diagnostic (ТЗ §6 Task 1.4)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from cmp_ensemble.qc.cluster_migration import (
    build_cluster_migration_table,
    render_cluster_migration_html,
)


def _toy_inputs():
    rng = np.random.default_rng(0)
    Z_prior = rng.standard_normal((30, 4))
    Z_post = Z_prior + 0.2
    cluster_ids = np.array([0] * 10 + [1] * 10 + [2] * 10)
    theta_names = ["THICK", "MAJ_R", "AZIMUTH", "PROP"]
    reference = {
        0: {"THICK": 8.0, "MAJ_R": 4000.0, "AZIMUTH": 80.0, "PROP": 0.7},
        1: {"THICK": 17.0, "MAJ_R": 2900.0, "AZIMUTH": 70.0, "PROP": 0.7},
        2: {"THICK": 12.0, "MAJ_R": 3500.0, "AZIMUTH": 68.0, "PROP": 0.7},
    }
    return Z_prior, Z_post, cluster_ids, theta_names, reference


def test_migration_table_columns_and_rows() -> None:
    Z_p, Z_q, cl, names, ref = _toy_inputs()
    df = build_cluster_migration_table(Z_p, Z_q, cl, names, reference_centroids=ref)
    expected_cols = {
        "cluster", "component", "reference", "prior_centroid", "post_centroid",
        "delta_prior_to_post",
    }
    assert expected_cols <= set(df.columns)
    # 3 clusters × 4 components = 12 rows
    assert len(df) == 12


def test_rendered_html_is_light_theme(tmp_path: Path) -> None:
    """The plotly diagnostic must force light theme regardless of OS/browser."""
    Z_p, Z_q, cl, names, ref = _toy_inputs()
    df = build_cluster_migration_table(Z_p, Z_q, cl, names, reference_centroids=ref)
    out = tmp_path / "cluster3_diagnostic.html"
    render_cluster_migration_html(df, out)
    assert out.exists() and out.stat().st_size > 5000
    text = out.read_text(encoding="utf-8")
    assert 'color-scheme' in text and 'light' in text
    assert '#ffffff' in text
    assert 'prefers-color-scheme: dark' in text
    # Plotly fields we explicitly set for light mode
    assert 'paper_bgcolor' in text or '#ffffff' in text

"""Tests for geolval-004 — concept conformance, facies proportions, realism."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.geology.realism import (
    CLUSTER_BOXES,
    compute_concept_conformance,
    compute_facies_proportions,
    compute_realism_metrics,
)


# ──────────────────────────────────────────────────────────────────────────
# compute_concept_conformance
# ──────────────────────────────────────────────────────────────────────────


def test_concept_conformance_all_in_box():
    """Models whose θ exactly hits each box centre should all be in-box."""
    rows = []
    for cl in (0, 1, 2):
        for _ in range(5):
            mid = lambda lo, hi: 0.5 * (lo + hi)
            rows.append({
                "cluster": cl,
                "THICK":   mid(*CLUSTER_BOXES["THICK"][cl]),
                "MAJ_R":   mid(*CLUSTER_BOXES["MAJ_R"][cl]),
                "AZIMUTH": mid(*CLUSTER_BOXES["AZIMUTH"][cl]),
            })
    df = pd.DataFrame(rows)
    out = compute_concept_conformance(df)
    for cl in (0, 1, 2):
        all3 = out[(out["cluster"] == cl) & (out["parameter"] == "all_three")].iloc[0]
        assert all3["frac_in_box"] == 1.0


def test_concept_conformance_cluster_migration():
    """Models in cluster 2 whose θ matches cluster 1's box should fail."""
    # Construct cluster-2 models with cluster-1-flavoured θ values:
    rows = []
    for _ in range(10):
        rows.append({
            "cluster": 2,
            "THICK":   13.0,    # cluster 1 box is 10.9-17.0; cluster 2's is 13.9-18.2
            "MAJ_R":   3500.0,  # cluster 1: 2849-4086; cluster 2: 2198-2724
            "AZIMUTH": 90.0,    # all clusters share 65-105
        })
    df = pd.DataFrame(rows)
    out = compute_concept_conformance(df)
    thick_row = out[(out["cluster"] == 2) & (out["parameter"] == "THICK")].iloc[0]
    majr_row = out[(out["cluster"] == 2) & (out["parameter"] == "MAJ_R")].iloc[0]
    azim_row = out[(out["cluster"] == 2) & (out["parameter"] == "AZIMUTH")].iloc[0]
    assert thick_row["frac_in_box"] == 0.0   # 13.0 < 13.9
    assert majr_row["frac_in_box"] == 0.0    # 3500 > 2724
    assert azim_row["frac_in_box"] == 1.0
    all3 = out[(out["cluster"] == 2) & (out["parameter"] == "all_three")].iloc[0]
    assert all3["frac_in_box"] == 0.0


def test_concept_conformance_empty_returns_empty():
    assert compute_concept_conformance(pd.DataFrame()).empty


# ──────────────────────────────────────────────────────────────────────────
# compute_facies_proportions
# ──────────────────────────────────────────────────────────────────────────


def test_facies_proportions_basic():
    desc = pd.DataFrame({
        "experiment": [2, 2, 2, 1, 1],
        "seed":       [100, 100, 200, 100, 100],
        "cluster":    [0, 0, 0, 0, 0],
        "well":       ["A", "B", "A", "A", "B"],
        "frac_channel_cells": [0.5, 1.0, 0.0, 0.8, 0.6],
        "mean_ntg_along_well": [0.5, 0.8, 0.2, 0.7, 0.5],
    })
    out = compute_facies_proportions(desc)
    # Three (exp, seed) combinations
    assert len(out) == 3
    # exp=2, seed=100 → mean across [0.5, 1.0] = 0.75
    row = out[(out["experiment"] == 2) & (out["seed"] == 100)].iloc[0]
    assert row["mean_frac_channel"] == 0.75
    assert row["mean_frac_non_channel"] == 0.25
    assert row["n_wells"] == 2


# ──────────────────────────────────────────────────────────────────────────
# compute_realism_metrics
# ──────────────────────────────────────────────────────────────────────────


def test_realism_metrics_handles_missing_columns():
    conn = pd.DataFrame({
        "experiment": [1, 1, 2, 2],
        "cluster":    [0, 0, 0, 0],
        "seed":       [1, 2, 3, 4],
        # only frac_sand_in_largest_26 — no anisotropy / orientation columns
        "frac_sand_in_largest_26": [0.9, 0.8, 0.99, 0.95],
    })
    out = compute_realism_metrics(conn)
    assert "frac_sand_in_largest_26_median" in out.columns
    # Missing column metrics are simply omitted from the row
    assert "top1_anisotropy_median" not in out.columns


def test_realism_metrics_per_experiment_cluster():
    conn = pd.DataFrame({
        "experiment": [1, 1, 2, 2],
        "cluster":    [0, 1, 0, 1],
        "seed":       [1, 2, 3, 4],
        "top1_anisotropy": [5.0, 7.0, 6.0, 8.0],
        "top1_orientation_deg": [0.0, 90.0, 45.0, 30.0],
    })
    out = compute_realism_metrics(conn)
    assert len(out) == 4  # 2 experiments × 2 clusters
    r = out[(out["experiment"] == 1) & (out["cluster"] == 0)].iloc[0]
    assert r["top1_anisotropy_median"] == 5.0

"""Tests for geolval-005 — inter-model spread + geological width_ratio."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.geology.diversity import (
    _spread_block,
    connectivity_spread,
    descriptor_spread,
    geological_width_ratio,
)


def _fake_descriptors(seed_offset: int, exp: int, n_models: int,
                      net_sand_mu: float, net_sand_sigma: float) -> pd.DataFrame:
    """Generate a synthetic descriptor table for one experiment."""
    rng = np.random.default_rng(seed_offset)
    seeds = np.arange(seed_offset, seed_offset + n_models)
    wells = ["WELL1", "WELL2", "INJ1"]
    rows = []
    for sd in seeds:
        net = rng.normal(net_sand_mu, net_sand_sigma)
        for w in wells:
            rows.append({
                "experiment": exp,
                "seed": int(sd),
                "cluster": int(sd) % 3,
                "well": w,
                "net_sand_penetrated": float(max(0.0, net + rng.normal(0, 1))),
                "kh_penetrated": float(rng.normal(10_000, 2_000)),
                "frac_channel_cells": float(np.clip(rng.normal(0.7, 0.1), 0, 1)),
                "mean_ntg_along_well": float(np.clip(rng.normal(0.7, 0.1), 0, 1)),
            })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# _spread_block
# ──────────────────────────────────────────────────────────────────────────


def test_spread_block_basic():
    out = _spread_block(np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
    assert out["n"] == 5
    assert out["mean"] == 3.0
    assert out["p50"] == 3.0
    assert out["range"] == 4.0
    # std (ddof=1) of [1..5] = sqrt(2.5)
    assert abs(out["std"] - np.sqrt(2.5)) < 1e-9


def test_spread_block_singleton():
    out = _spread_block(np.array([7.0]))
    assert out["n"] == 1
    assert out["mean"] == 7.0
    assert out["std"] == 0.0


def test_spread_block_empty():
    out = _spread_block(np.array([]))
    assert np.isnan(out["mean"])


# ──────────────────────────────────────────────────────────────────────────
# descriptor_spread
# ──────────────────────────────────────────────────────────────────────────


def test_descriptor_spread_two_scopes_and_grouping():
    df = pd.concat([
        _fake_descriptors(0,   1, 20, net_sand_mu=20.0, net_sand_sigma=3.0),
        _fake_descriptors(200, 2, 20, net_sand_mu=20.0, net_sand_sigma=1.0),
    ], ignore_index=True)
    out = descriptor_spread(df, by_cluster=True)
    assert {"experiment", "cluster", "scope", "metric"}.issubset(out.columns)
    scopes = set(out["scope"].unique())
    assert scopes == {"all_wells", "model_mean"}
    # Each (exp, cluster, scope) block has 4 metrics
    # 2 experiments × 3 clusters × 2 scopes × 4 metrics = 48 rows
    assert len(out) == 48


def test_descriptor_spread_model_mean_smaller_than_all_wells_for_well_metric():
    """model_mean averages out well-level noise so std should be ≤ all_wells std."""
    df = _fake_descriptors(0, 1, 30, net_sand_mu=10.0, net_sand_sigma=2.0)
    out = descriptor_spread(df, by_cluster=False)
    aw = out[(out["metric"] == "net_sand_penetrated") & (out["scope"] == "all_wells")]
    mm = out[(out["metric"] == "net_sand_penetrated") & (out["scope"] == "model_mean")]
    assert mm["std"].iloc[0] <= aw["std"].iloc[0] + 1e-6


# ──────────────────────────────────────────────────────────────────────────
# connectivity_spread
# ──────────────────────────────────────────────────────────────────────────


def test_connectivity_spread_handles_missing_metrics():
    df = pd.DataFrame({
        "experiment": [1, 1, 2, 2],
        "cluster": [0, 0, 0, 0],
        "seed": [10, 20, 30, 40],
        "n_bodies_26": [5, 7, 6, 6],
        "frac_sand_in_largest_26": [0.99, 0.98, 0.97, 0.96],
    })
    out = connectivity_spread(df, by_cluster=False)
    metrics = set(out["metric"].unique())
    assert "n_bodies_26" in metrics
    assert "frac_sand_in_largest_26" in metrics
    # Missing metrics like top1_anisotropy must NOT appear silently
    assert "top1_anisotropy" not in metrics


# ──────────────────────────────────────────────────────────────────────────
# geological_width_ratio
# ──────────────────────────────────────────────────────────────────────────


def test_geological_width_ratio_directionality():
    """Construct two ensembles whose std on net_sand differs by a known factor."""
    df = pd.concat([
        _fake_descriptors(0,   1, 80, net_sand_mu=20.0, net_sand_sigma=4.0),
        _fake_descriptors(200, 2, 80, net_sand_mu=20.0, net_sand_sigma=1.0),
    ], ignore_index=True)
    spread = descriptor_spread(df, by_cluster=True)
    wr = geological_width_ratio(spread, scope="model_mean")
    row = wr[wr["metric"] == "net_sand_penetrated"].iloc[0]
    assert row["spread_a_exp1"] > row["spread_b_exp2"]
    assert row["width_ratio_geo"] < 1.0
    assert "tightens" in row["interpretation"]


def test_geological_width_ratio_skips_when_exp_missing():
    spread = descriptor_spread(
        _fake_descriptors(0, 1, 10, 20.0, 2.0), by_cluster=False)
    wr = geological_width_ratio(spread)
    # Only Exp1 → no ratio possible
    assert wr.empty

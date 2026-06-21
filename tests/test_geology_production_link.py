"""Tests for geolval-003 — R²-uplift, SRC², descriptor↔production correlations."""

from __future__ import annotations

import datetime
import types

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.geology.production_link import (
    aggregate_descriptors_per_model,
    descriptor_response_correlations,
    extract_year_end_responses,
    r2_uplift_with_bootstrap,
    src2_with_bootstrap,
)


# ──────────────────────────────────────────────────────────────────────────
# extract_year_end_responses
# ──────────────────────────────────────────────────────────────────────────


def _make_cum_index(metrics: list[str], wells: list[str],
                     years: list[int]) -> list[tuple]:
    out = []
    for m in metrics:
        for w in wells:
            for y in years:
                out.append((m, w, datetime.datetime(y, 12, 31)))
    return out


def test_extract_year_end_responses_per_well_layout():
    metrics = ["Накопл. нефть", "Накопл. вода"]
    wells = ["WELL5", "WELL7", "WELL_OTHER"]
    years = [2017, 2018]
    cum_index = _make_cum_index(metrics, wells, years)
    # 2 metrics × 3 wells × 2 years = 12 cols
    d_sim_cum = np.arange(2 * 12, dtype=float).reshape(2, 12)
    out = extract_year_end_responses(
        d_sim_cum, cum_index, year=2018,
        producers=("WELL5", "WELL7"),
    )
    assert "cum_oil_WELL5" in out.columns
    assert "cum_oil_WELL7" in out.columns
    assert "watercut_WELL5" in out.columns
    # WELL_OTHER not in producers → no column for it
    assert "cum_oil_WELL_OTHER" not in out.columns
    assert len(out) == 2


def test_extract_year_end_responses_watercut_in_unit_interval():
    metrics = ["Накопл. нефть", "Накопл. вода"]
    cum_index = _make_cum_index(metrics, ["WELL5"], [2018])
    # oil=10, water=30 → watercut = 30/40 = 0.75
    d_sim_cum = np.array([[10.0, 30.0]])
    out = extract_year_end_responses(d_sim_cum, cum_index, year=2018,
                                       producers=("WELL5",))
    assert abs(out["watercut_WELL5"].iloc[0] - 0.75) < 1e-9


def test_extract_year_end_responses_zero_total_is_nan():
    metrics = ["Накопл. нефть", "Накопл. вода"]
    cum_index = _make_cum_index(metrics, ["WELL5"], [2018])
    d_sim_cum = np.array([[0.0, 0.0]])
    out = extract_year_end_responses(d_sim_cum, cum_index, year=2018,
                                       producers=("WELL5",))
    assert pd.isna(out["watercut_WELL5"].iloc[0])


# ──────────────────────────────────────────────────────────────────────────
# aggregate_descriptors_per_model
# ──────────────────────────────────────────────────────────────────────────


def test_aggregate_descriptors_sums_and_means():
    desc = pd.DataFrame({
        "seed": [1, 1, 2, 2],
        "well": ["A", "B", "A", "B"],
        "net_sand_penetrated": [10, 20, 5, 5],
        "kh_penetrated": [100, 200, 50, 50],
        "frac_channel_cells": [0.5, 1.0, 0.0, 0.5],
        "mean_ntg_along_well": [0.6, 0.8, 0.2, 0.4],
    })
    conn = pd.DataFrame({
        "seed": [1, 2],
        "n_bodies_26": [5, 50],
        "frac_sand_in_largest_26": [0.99, 0.1],
        "mean_inj_connections_per_producer": [6, 1],
    })
    agg = aggregate_descriptors_per_model(desc, conn)
    a = agg[agg["seed"] == 1].iloc[0]
    assert a["total_net_sand"] == 30
    assert a["total_kh"] == 300
    assert a["mean_frac_channel"] == 0.75
    assert a["mean_ntg"] == 0.7
    assert a["frac_sand_in_largest_26"] == 0.99


# ──────────────────────────────────────────────────────────────────────────
# r2_uplift_with_bootstrap
# ──────────────────────────────────────────────────────────────────────────


def test_r2_uplift_positive_when_geo_adds_signal():
    rng = np.random.default_rng(0)
    n = 100
    X_theta = rng.normal(size=(n, 9))
    # Geo has 3 features; y depends mostly on geo[:,0] + small theta contribution
    X_geo = rng.normal(size=(n, 3))
    y = 0.2 * X_theta[:, 0] + 1.5 * X_geo[:, 0] + 0.3 * rng.normal(size=n)
    r = r2_uplift_with_bootstrap(X_theta, X_geo, y, B=50)
    assert r["R2_theta"] < r["R2_theta_geo"]
    assert r["uplift"] > 0
    # CI should bracket the point estimate
    assert r["ci_low"] <= r["uplift"] <= r["ci_high"] + 0.05


def test_r2_uplift_nan_when_too_few_samples():
    X_theta = np.random.randn(5, 9)
    X_geo = np.random.randn(5, 3)
    y = np.random.randn(5)
    r = r2_uplift_with_bootstrap(X_theta, X_geo, y, B=10)
    assert pd.isna(r["R2_theta"])


# ──────────────────────────────────────────────────────────────────────────
# src2_with_bootstrap
# ──────────────────────────────────────────────────────────────────────────


def test_src2_picks_up_strong_predictor():
    rng = np.random.default_rng(42)
    n = 100
    X = rng.normal(size=(n, 4))
    # X[:,0] is the only true predictor
    y = 2.0 * X[:, 0] + 0.1 * rng.normal(size=n)
    out = src2_with_bootstrap(X, y, ["A", "B", "C", "D"], B=50)
    assert out.iloc[0]["predictor"] == "A"
    # A's coefficient sign should be stable across bootstrap
    assert out[out["predictor"] == "A"]["stability_fraction"].iloc[0] > 0.95


# ──────────────────────────────────────────────────────────────────────────
# descriptor_response_correlations
# ──────────────────────────────────────────────────────────────────────────


def test_correlation_threshold_3_over_sqrt_N():
    rng = np.random.default_rng(0)
    n = 100
    df = pd.DataFrame({
        "d1": rng.normal(size=n),
        "d2": rng.normal(size=n),
        "y1": rng.normal(size=n),
    })
    # Make d1 strongly correlated with y1
    df["y1"] = 0.9 * df["d1"] + 0.1 * rng.normal(size=n)
    out = descriptor_response_correlations(df, ["d1", "d2"], ["y1"])
    d1_row = out[out["descriptor"] == "d1"].iloc[0]
    d2_row = out[out["descriptor"] == "d2"].iloc[0]
    assert d1_row["passes_3_over_sqrt_N"]
    # d2 random → low r → fails
    assert abs(d1_row["pearson_r"]) > abs(d2_row["pearson_r"])

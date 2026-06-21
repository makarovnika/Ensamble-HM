"""Tests for geolval-007 — summary_comparison.csv builder + figures."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from cmp_ensemble.geology.comparison import (
    _classify_status,
    _row,
    build_axis0,
    build_axis2,
    build_axis3,
    build_axis4,
    build_axis4_crossaxis,
    build_pending,
    build_summary_comparison,
)


# ──────────────────────────────────────────────────────────────────────────
# _classify_status
# ──────────────────────────────────────────────────────────────────────────


def test_classify_status_greater_is_better():
    assert _classify_status(0.3, 0.5, ">") == "BETTER"
    assert _classify_status(0.5, 0.3, ">") == "WORSE"


def test_classify_status_lower_is_better():
    assert _classify_status(50.0, 20.0, "<") == "BETTER"
    assert _classify_status(20.0, 50.0, "<") == "WORSE"


def test_classify_status_neutral_for_tilde_or_tiny_delta():
    assert _classify_status(0.5, 0.5, ">") == "NEUTRAL"
    assert _classify_status(0.5, 1.5, "~") == "NEUTRAL"


def test_classify_status_handles_nan():
    assert _classify_status(float("nan"), 0.5, ">") == "NEUTRAL"


# ──────────────────────────────────────────────────────────────────────────
# _row
# ──────────────────────────────────────────────────────────────────────────


def test_row_computes_delta_and_ratio():
    r = _row(2, "metric_A", "all", value_old=10.0, value_new=15.0,
              direction=">", evidence="t.csv", notes="hi")
    assert r["delta"] == 5.0
    assert r["ratio"] == 1.5
    assert r["status"] == "BETTER"


def test_row_ratio_nan_when_old_is_zero():
    r = _row(2, "metric_A", "all", value_old=0.0, value_new=15.0,
              direction=">", evidence="t.csv")
    assert pd.isna(r["ratio"])


# ──────────────────────────────────────────────────────────────────────────
# Per-axis builders (file-not-found → empty)
# ──────────────────────────────────────────────────────────────────────────


def test_axis_builders_handle_missing_files(tmp_path):
    assert build_axis0(tmp_path / "nope.csv") == []
    assert build_axis2(tmp_path / "nope.csv") == []
    assert build_axis3(tmp_path / "nope.csv") == []
    assert build_axis4(tmp_path / "nope.csv") == []
    assert build_axis4_crossaxis(tmp_path / "nope.json") == []


# ──────────────────────────────────────────────────────────────────────────
# build_axis0/2/3/4 with synthetic inputs
# ──────────────────────────────────────────────────────────────────────────


def test_build_axis0_emits_topology_metrics(tmp_path):
    p = tmp_path / "exp_diff.csv"
    pd.DataFrame({
        "seed": [1, 2, 3],
        "frac_netflag_changed": [0.4, 0.42, 0.41],
        "delta_mean_PORO": [0.001, -0.0005, 0.002],
        "delta_mean_PERMX": [5, -3, 4],
        "delta_mean_NTG": [0.001, 0, -0.001],
    }).to_csv(p, index=False)
    rows = build_axis0(p)
    assert {r["metric"] for r in rows} == {
        "frac_netflag_changed", "abs_mean_delta_PORO",
        "abs_mean_delta_PERMX", "abs_mean_delta_NTG",
    }
    nf = next(r for r in rows if r["metric"] == "frac_netflag_changed")
    assert abs(nf["value_new"] - 0.41) < 1e-3
    assert nf["direction"] == "~"


def test_build_axis2_picks_min_and_median(tmp_path):
    p = tmp_path / "conn.csv"
    pd.DataFrame({
        "experiment": [1, 1, 1, 2, 2, 2],
        "seed":       [10, 20, 30, 10, 20, 30],
        "frac_sand_in_largest_26": [0.1, 0.9, 0.8, 0.95, 0.99, 0.97],
        "mean_inj_connections_per_producer": [0.5, 6, 6, 6, 6, 6],
        "n_bodies_26": [200, 5, 7, 3, 4, 4],
    }).to_csv(p, index=False)
    rows = build_axis2(p)
    metrics = {r["metric"]: r for r in rows}
    assert metrics["min_frac_sand_in_largest_26"]["value_old"] == 0.1
    assert metrics["min_frac_sand_in_largest_26"]["value_new"] == 0.95
    assert metrics["min_frac_sand_in_largest_26"]["status"] == "BETTER"
    # 1 pathological model in exp 1, 0 in exp 2 → BETTER on a < metric
    n_pat = metrics["n_models_with_mean_inj_conn_lt_1"]
    assert n_pat["value_old"] == 1.0
    assert n_pat["value_new"] == 0.0
    assert n_pat["status"] == "BETTER"


def test_build_axis3_passes_through_width_ratios(tmp_path):
    p = tmp_path / "wr.csv"
    pd.DataFrame({
        "metric": ["A", "B"],
        "spread_a_exp1": [1.0, 1.0],
        "spread_b_exp2": [0.5, 2.0],
        "width_ratio_geo": [0.5, 2.0],
        "es_width_ratio_ref": [float("nan"), float("nan")],
        "interpretation": ["Exp2 tightens", "Exp2 broadens"],
    }).to_csv(p, index=False)
    rows = build_axis3(p)
    assert len(rows) == 2
    assert {r["metric"] for r in rows} == {"width_ratio_A", "width_ratio_B"}


# ──────────────────────────────────────────────────────────────────────────
# build_summary_comparison end-to-end on a temp project
# ──────────────────────────────────────────────────────────────────────────


def test_build_summary_comparison_handles_missing_sources(tmp_path):
    # With no source artefacts present, the builder returns an empty
    # DataFrame (build_pending no longer seeds rows once Q1 is defaulted).
    df = build_summary_comparison(tmp_path)
    assert isinstance(df, pd.DataFrame)
    # No PENDING rows anymore — Q1 was resolved via configs/geology.yaml
    if not df.empty:
        assert (df["status"] != "PENDING_USER_INPUT").all()


def test_build_pending_returns_empty_now():
    """After Q1 default in configs/geology.yaml, build_pending is a no-op."""
    assert build_pending() == []

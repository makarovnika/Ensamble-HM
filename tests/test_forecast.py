"""Unit tests for Phase 3 forecast aggregation + metrics + setups."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from cmp_ensemble.forecast.aggregation import (
    aggregate_forecast,
    field_total_quantiles,
    per_well_quantiles,
)
from cmp_ensemble.forecast.metrics import (
    coverage_p10p90_from,
    crps_per_column,
    median_shift,
    width_ratio,
)
from cmp_ensemble.forecast.setups import (
    run_setup1_naive,
    run_setup2_localized,
    run_setup3_full,
    build_metrics_summary,
)


def _make_index(metrics, wells, years):
    return [
        (m, w, datetime(y, 12, 1))
        for m in metrics for w in wells for y in years
    ]


# ---------------- aggregation ----------------


def test_aggregate_basic_shapes() -> None:
    rng = np.random.default_rng(0)
    M, n_d = 30, 8
    d = rng.standard_normal((M, n_d))
    idx = _make_index(["A"], ["W1", "W2"], [2020, 2021, 2022, 2023])
    out = aggregate_forecast(d, idx, quantiles=[0.1, 0.5, 0.9])
    assert out.values.shape == (3, n_d)
    # P10 ≤ P50 ≤ P90 elementwise
    assert (out.values[0] <= out.values[1]).all()
    assert (out.values[1] <= out.values[2]).all()


def test_field_total_sum_then_quantile() -> None:
    # 3 models, 2 wells, 1 year. d = [[1, 2], [3, 4], [5, 6]].
    # Field total per model: [3, 7, 11]. Median = 7.
    d = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    idx = [("oil", "W1", datetime(2020, 12, 1)), ("oil", "W2", datetime(2020, 12, 1))]
    df = field_total_quantiles(d, idx, quantiles=[0.1, 0.5, 0.9])
    assert len(df) == 1
    assert df.iloc[0]["p50"] == 7.0


def test_per_well_quantiles_columns() -> None:
    rng = np.random.default_rng(2)
    idx = _make_index(["A", "B"], ["W1"], [2020])
    d = rng.standard_normal((10, len(idx)))
    df = per_well_quantiles(d, idx)
    assert {"metric", "well", "time", "p10", "p50", "p90", "mean", "std"} <= set(df.columns)
    assert len(df) == len(idx)


# ---------------- metrics ----------------


def test_width_ratio_is_one_for_identical_distributions() -> None:
    rng = np.random.default_rng(1)
    d_prior = rng.standard_normal((40, 6))
    d_post = d_prior.copy()
    assert np.allclose(width_ratio(d_post, d_prior), 1.0)


def test_width_ratio_shrinks_with_post_contraction() -> None:
    rng = np.random.default_rng(2)
    d_prior = rng.standard_normal((100, 4)) * 2
    d_post = d_prior * 0.5
    wr = width_ratio(d_post, d_prior)
    assert np.allclose(wr, 0.5, atol=0.1)


def test_median_shift_zero_for_identity() -> None:
    rng = np.random.default_rng(3)
    d = rng.standard_normal((20, 5))
    assert np.allclose(median_shift(d, d), 0.0)


def test_crps_zero_when_truth_at_distribution_center() -> None:
    """For a degenerate distribution (all members identical), CRPS = |x − y|."""
    d = np.full((50, 3), 7.0)
    truth = np.array([7.0, 7.5, 8.0])
    crps = crps_per_column(d, truth)
    assert np.allclose(crps, [0.0, 0.5, 1.0])


def test_coverage_full_for_wide_forecast() -> None:
    rng = np.random.default_rng(4)
    d = rng.standard_normal((1000, 5)) * 100  # huge spread
    truth = np.array([0.0, 1.0, -1.0, 5.0, -5.0])
    cov = coverage_p10p90_from(d, truth)
    assert cov == 1.0


# ---------------- setups ----------------


def test_setup1_identity() -> None:
    rng = np.random.default_rng(5)
    d = rng.standard_normal((20, 4))
    idx = _make_index(["A"], ["W1", "W2"], [2020, 2021])
    cluster = np.array([0, 0, 1, 1] * 5)
    res = run_setup1_naive(d, idx, cluster)
    assert res.label == "setup1_naive"
    # width_ratio should be 1 across the board
    assert (res.metrics.summary_per_metric["mean_width_ratio"] - 1.0).abs().max() < 0.05


def test_setup2_drops_out_of_envelope() -> None:
    rng = np.random.default_rng(6)
    d_base = rng.standard_normal((10, 3))
    d_post = rng.standard_normal((12, 3))
    idx = _make_index(["A"], ["W1"], [2020, 2021, 2022])
    ce_base = np.zeros(10, dtype=int)
    ce_post = np.zeros(12, dtype=int)
    oo = np.array([False] * 6 + [True] * 6)
    res = run_setup2_localized(
        d_baseline=d_base, d_proxy_post=d_post,
        index=idx,
        cluster_ids_baseline=ce_base, cluster_ids_proxy=ce_post,
        out_of_envelope=oo,
    )
    assert res.d_forecast.shape[0] == 6   # dropped the 6 OOE
    assert any("dropped" in n for n in res.notes)


def test_setup3_degrades_when_no_controls() -> None:
    rng = np.random.default_rng(7)
    d_base = rng.standard_normal((10, 3))
    d_post = rng.standard_normal((10, 3))
    idx = _make_index(["A"], ["W1"], [2020, 2021, 2022])
    res = run_setup3_full(
        d_baseline=d_base, d_proxy_post=d_post,
        index=idx,
        cluster_ids_baseline=np.zeros(10), cluster_ids_proxy=np.zeros(10),
        out_of_envelope=np.zeros(10, dtype=bool),
        controls_available=False,
    )
    assert res.label == "setup3_full"
    assert any("degenerates to setup2" in n for n in res.notes)


def test_summary_table_concatenates_all_setups() -> None:
    rng = np.random.default_rng(8)
    d_base = rng.standard_normal((10, 4))
    d_post = rng.standard_normal((10, 4))
    idx = _make_index(["A", "B"], ["W1"], [2020, 2021])
    cluster = np.array([0, 1] * 5)
    s1 = run_setup1_naive(d_base, idx, cluster)
    s2 = run_setup2_localized(
        d_base, d_post, idx,
        cluster_ids_baseline=cluster, cluster_ids_proxy=cluster,
        out_of_envelope=np.zeros(10, dtype=bool),
    )
    s3 = run_setup3_full(
        d_base, d_post, idx,
        cluster_ids_baseline=cluster, cluster_ids_proxy=cluster,
        out_of_envelope=np.zeros(10, dtype=bool),
        controls_available=False,
    )
    df = build_metrics_summary([s1, s2, s3])
    assert set(df["setup"].unique()) == {"setup1_naive", "setup2_localized", "setup3_full"}

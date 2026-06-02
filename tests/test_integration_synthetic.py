"""End-to-end integration test on the synthetic mini-fixture (ТЗ §9).

Runs Phase 0 → Phase 1 → Phase 2 → Phase 3 in process (no Excel I/O, no CLI)
to verify that the modules compose correctly and that truth-dependent metrics
populate when d_truth is provided.

Wall-time budget per ТЗ §9: under 30 seconds.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from cmp_ensemble.ensemble.es_update import es_update
from cmp_ensemble.ensemble.localization import adaptive_correlation_localization
from cmp_ensemble.ensemble.state_vector import build_state_vector, unpack_state_vector
from cmp_ensemble.forecast.aggregation import (
    aggregate_forecast,
    field_total_quantiles,
)
from cmp_ensemble.forecast.metrics import compute_metrics
from cmp_ensemble.forecast.setups import (
    build_metrics_summary,
    run_setup1_naive,
    run_setup2_localized,
    run_setup3_full,
)
from cmp_ensemble.qc.checks import run_qc_checks
from cmp_ensemble.selection.linear_proxy import build_per_cluster_proxies
from cmp_ensemble.selection.mahalanobis import (
    mahalanobis_distance,
    rank_by_parameter_change,
)
from cmp_ensemble.selection.validation import validate_proxy
from tests.fixtures.synthetic import make_synthetic_fixture


def test_full_pipeline_phase0_to_phase3_under_30s() -> None:
    """The whole pipeline must execute end-to-end in < 30 seconds.

    The synthetic fixture is a textbook linear-Gaussian problem, so the
    posterior is mathematically guaranteed to contract — but the assertions
    below are deliberately loose. The point of this test is *pipeline
    composition*, not numerical optimality.
    """
    t_start = time.perf_counter()
    fx = make_synthetic_fixture()
    assert fx.N == 20 and fx.n_theta == 5 and fx.n_obs == 10

    # ── Phase 0 — state vector
    z, schema = build_state_vector(
        fx.theta_prior, theta_names=fx.theta_names, include_controls=False
    )
    assert z.shape == (fx.N, fx.n_theta)
    theta_back, u_back = unpack_state_vector(z, schema)
    assert np.array_equal(theta_back, fx.theta_prior)
    assert u_back is None

    # ── Phase 1 — localization + ES update + QC
    mask, corr, threshold = adaptive_correlation_localization(
        z, fx.d_sim, factor=2.0, method="hard"
    )
    assert mask.shape == (fx.n_theta, fx.n_obs)
    assert 0.0 < threshold < 1.0

    result = es_update(
        z, fx.d_sim, fx.d_obs, fx.C_dd,
        localization_mask=mask,
        subspace_energy=0.99,
        seed=42,
    )
    assert result.Z_post.shape == z.shape
    assert not np.isnan(result.Z_post).any()
    assert result.K.shape == (fx.n_theta, fx.n_obs)
    assert 1 <= result.n_components_kept <= min(fx.N, fx.n_obs)
    assert result.energy_kept >= 0.99

    # Loose convergence: median deviation < 2 σ_prior (this is a sanity check,
    # NOT a strict ES-quality assertion; the integration test prizes wiring).
    posterior_mean = result.Z_post.mean(axis=0)
    prior_std = fx.theta_prior.std(axis=0, ddof=1)
    deviation = np.abs(posterior_mean - fx.theta_truth) / prior_std
    assert float(np.median(deviation)) < 2.0, (
        f"Posterior mean far from truth: {deviation}"
    )

    qc = run_qc_checks(
        Z_prior=z,
        Z_post=result.Z_post,
        cluster_ids=fx.cluster_ids,
        theta_names=fx.theta_names,
        model_ids=fx.model_ids,
    )
    # Always returns a report; some warnings allowed but no hard errors.
    assert qc.spread_retention.shape[0] == fx.n_theta
    assert qc.rank_prior > 0 and qc.rank_post > 0
    assert qc.mahalanobis_migration.shape == (fx.N,)
    assert qc.duplicate_models_summary is not None  # empty df is fine

    # ── Phase 2 — Mahalanobis + linear proxy + validation
    maha = mahalanobis_distance(z, result.Z_post)
    assert maha.shape == (fx.N,) and (maha >= 0).all()
    order = rank_by_parameter_change(z, result.Z_post)
    assert order.shape == (fx.N,) and set(order.tolist()) == set(range(fx.N))

    proxies = build_per_cluster_proxies(
        fx.theta_prior, fx.d_forecast_baseline, fx.cluster_ids
    )
    assert set(proxies.keys()) == {0, 1, 2}
    for cl, p in proxies.items():
        assert p.S.shape == (fx.n_theta, fx.n_forecast)
        assert p.z_bar.shape == (fx.n_theta,)
        assert p.d_bar.shape == (fx.n_forecast,)

    val = validate_proxy(
        fx.theta_prior, fx.d_forecast_baseline, fx.cluster_ids,
        val_fraction=0.20, seed=7,
    )
    assert val.aggregate["median_rel_err"] >= 0.0
    # On the linear-Gaussian fixture (N=20 split across 3 small clusters)
    # the per-cluster proxy uses ~5-6 training samples per cluster, so PASS
    # is not guaranteed. A FAIL would indicate a real wiring problem, though.
    assert val.verdict in {"PASS", "WARN"}, f"unexpected FAIL verdict {val.verdict}"

    # Apply per-cluster proxy to θ_post to estimate d_forecast(θ_post).
    d_forecast_post = np.zeros_like(fx.d_forecast_baseline)
    out_of_envelope = np.zeros(fx.N, dtype=bool)
    for i in range(fx.N):
        cl = int(fx.cluster_ids[i])
        proxy = proxies[cl]
        d_forecast_post[i] = proxy.predict(result.Z_post[i])
        out_of_envelope[i] = not proxy.in_envelope(result.Z_post[i])
    assert d_forecast_post.shape == fx.d_forecast_baseline.shape

    # ── Phase 3 — three setups + metrics with d_truth supplied
    s1 = run_setup1_naive(
        d_baseline=fx.d_forecast_baseline,
        index=fx.forecast_index,
        cluster_ids=fx.cluster_ids,
        d_truth=fx.d_forecast_truth,
    )
    s2 = run_setup2_localized(
        d_baseline=fx.d_forecast_baseline,
        d_proxy_post=d_forecast_post,
        index=fx.forecast_index,
        cluster_ids_baseline=fx.cluster_ids,
        cluster_ids_proxy=fx.cluster_ids,
        out_of_envelope=out_of_envelope,
        d_truth=fx.d_forecast_truth,
        keep_out_of_envelope=True,
    )
    s3 = run_setup3_full(
        d_baseline=fx.d_forecast_baseline,
        d_proxy_post=d_forecast_post,
        index=fx.forecast_index,
        cluster_ids_baseline=fx.cluster_ids,
        cluster_ids_proxy=fx.cluster_ids,
        out_of_envelope=out_of_envelope,
        d_truth=fx.d_forecast_truth,
        controls_available=False,
        keep_out_of_envelope=True,
    )

    # Truth-dependent metrics MUST be populated when d_truth is supplied.
    for s in (s1, s2, s3):
        assert s.metrics.coverage_p10p90 is not None, f"coverage missing for {s.label}"
        assert s.metrics.crps_table is not None, f"CRPS missing for {s.label}"
        assert s.metrics.cumulative_error_table is not None, (
            f"cumulative_error missing for {s.label}"
        )
        assert 0.0 <= s.metrics.coverage_p10p90 <= 1.0

    summary = build_metrics_summary([s1, s2, s3])
    assert set(summary["setup"].unique()) == {
        "setup1_naive", "setup2_localized", "setup3_full"
    }

    # Aggregation tables
    fq = aggregate_forecast(fx.d_forecast_baseline, fx.forecast_index)
    assert fq.values.shape == (3, fx.n_forecast)
    assert (fq.values[0] <= fq.values[1]).all()  # P10 ≤ P50
    assert (fq.values[1] <= fq.values[2]).all()  # P50 ≤ P90

    ft = field_total_quantiles(fx.d_forecast_baseline, fx.forecast_index)
    assert {"metric", "time", "p10", "p50", "p90"} <= set(ft.columns)

    # Wall-time budget
    elapsed = time.perf_counter() - t_start
    assert elapsed < 30.0, f"Pipeline took {elapsed:.2f}s, expected < 30s"


def test_fixture_is_deterministic_and_reseeded() -> None:
    """Re-creating the fixture with the same seed must yield byte-identical
    arrays, so the integration test is reproducible."""
    a = make_synthetic_fixture(seed=42)
    b = make_synthetic_fixture(seed=42)
    assert np.array_equal(a.theta_prior, b.theta_prior)
    assert np.array_equal(a.theta_truth, b.theta_truth)
    assert np.array_equal(a.d_obs, b.d_obs)
    assert np.array_equal(a.d_sim, b.d_sim)
    assert np.array_equal(a.d_forecast_truth, b.d_forecast_truth)
    assert np.array_equal(a.d_forecast_baseline, b.d_forecast_baseline)
    # Different seed produces different data
    c = make_synthetic_fixture(seed=123)
    assert not np.array_equal(a.theta_truth, c.theta_truth)


def test_fixture_shape_matches_tz_spec() -> None:
    """ТЗ §9 explicitly mandates 20 models, 3 clusters, 5 params, 10 obs."""
    fx = make_synthetic_fixture()
    assert fx.N == 20
    assert set(fx.cluster_ids.tolist()) == {0, 1, 2}
    assert fx.n_theta == 5
    assert fx.n_obs == 10
    # 3 clusters of sizes [7, 7, 6]
    counts = [int((fx.cluster_ids == c).sum()) for c in (0, 1, 2)]
    assert counts == [7, 7, 6]

"""Unit tests for the Phase 1 QC checks (Task 1.3)."""

from __future__ import annotations

import numpy as np

from cmp_ensemble.qc.checks import run_qc_checks


def _make_prior(N: int = 100, n_z: int = 4, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal((N, n_z))


def test_collapse_flagged_on_artificial_shrink() -> None:
    Z_prior = _make_prior()
    Z_post = Z_prior.copy()
    Z_post[:, 0] *= 0.05    # collapse component 0
    cluster_ids = np.array([0] * 50 + [1] * 50)
    report = run_qc_checks(
        Z_prior, Z_post, cluster_ids,
        theta_names=["a", "b", "c", "d"],
    )
    assert report.n_collapse_components == 1
    assert not report.passed
    assert any("collapse" in m.lower() for _, m in report.messages)


def test_identity_passes() -> None:
    Z_prior = _make_prior()
    Z_post = Z_prior.copy()
    cluster_ids = np.zeros(Z_prior.shape[0])
    report = run_qc_checks(
        Z_prior, Z_post, cluster_ids, theta_names=["a", "b", "c", "d"],
    )
    assert report.n_collapse_components == 0
    assert report.n_blowup_components == 0
    assert report.passed


def test_spread_retention_values() -> None:
    Z_prior = _make_prior(seed=1)
    Z_post = Z_prior * 0.5
    cluster_ids = np.zeros(Z_prior.shape[0])
    report = run_qc_checks(
        Z_prior, Z_post, cluster_ids, theta_names=[f"p{i}" for i in range(4)],
    )
    ratios = report.spread_retention["spread_retention"].to_numpy()
    assert np.allclose(ratios, 0.5, atol=1e-12)


def test_centroid_shift_table_shape() -> None:
    Z_prior = _make_prior(seed=2)
    Z_post = Z_prior + 0.3
    cluster_ids = np.array([0] * 50 + [1] * 50)
    report = run_qc_checks(
        Z_prior, Z_post, cluster_ids, theta_names=[f"p{i}" for i in range(4)],
    )
    assert len(report.cluster_centroid_shift) == 2 * 4   # 2 clusters × 4 components
    assert np.allclose(report.cluster_centroid_shift["abs_shift"], 0.3, atol=1e-12)

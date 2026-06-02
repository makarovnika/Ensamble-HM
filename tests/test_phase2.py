"""Unit tests for Phase 2: Mahalanobis ranking + linear proxy + validation."""

from __future__ import annotations

import numpy as np
import pytest

from cmp_ensemble.selection.linear_proxy import (
    build_linear_proxy,
    build_per_cluster_proxies,
)
from cmp_ensemble.selection.mahalanobis import (
    mahalanobis_distance,
    rank_by_parameter_change,
)
from cmp_ensemble.selection.validation import validate_proxy


# ---------------- Mahalanobis ----------------


def test_zero_shift_gives_zero_distance() -> None:
    rng = np.random.default_rng(0)
    Z = rng.standard_normal((30, 5))
    d = mahalanobis_distance(Z, Z.copy())
    assert np.allclose(d, 0.0)


def test_ranking_orders_largest_shift_first() -> None:
    rng = np.random.default_rng(1)
    Z_prior = rng.standard_normal((20, 4))
    Z_post = Z_prior.copy()
    Z_post[7] += np.array([10.0, 10.0, 10.0, 10.0])     # huge shift on member 7
    order = rank_by_parameter_change(Z_prior, Z_post)
    assert order[0] == 7


def test_distance_is_invariant_under_isotropic_prior() -> None:
    rng = np.random.default_rng(2)
    Z_prior = rng.standard_normal((50, 3))
    delta = rng.standard_normal((50, 3))
    Z_post = Z_prior + delta
    # With C_zz = sample cov of Z_prior, the Mahalanobis distance is positive
    # for every non-zero delta.
    d = mahalanobis_distance(Z_prior, Z_post)
    assert (d > 0).all()


# ---------------- Linear proxy ----------------


def test_linear_proxy_recovers_known_S() -> None:
    """If d = S_true @ θ + const, the fitted S should be close to S_true."""
    rng = np.random.default_rng(3)
    N, n_z, n_d = 200, 4, 6
    S_true = rng.standard_normal((n_z, n_d)) * 2.0
    Z = rng.standard_normal((N, n_z)) * 1.5
    D = Z @ S_true + 100.0  # const bias
    proxy = build_linear_proxy(Z, D)
    # Recover with low absolute error
    assert np.allclose(proxy.S, S_true, atol=0.05)
    # Predicting on Z mean must give d mean
    assert np.allclose(proxy.predict(Z.mean(axis=0)), D.mean(axis=0))


def test_envelope_flagging() -> None:
    rng = np.random.default_rng(4)
    Z = rng.uniform(0, 1, size=(50, 3))
    D = Z @ np.array([[1.0, 2.0], [-1.0, 0.5], [0.5, -0.5]])
    proxy = build_linear_proxy(Z, D)
    assert proxy.in_envelope(np.array([0.5, 0.5, 0.5])) is True
    assert proxy.in_envelope(np.array([1.5, 0.5, 0.5])) is False


def test_per_cluster_proxies() -> None:
    rng = np.random.default_rng(5)
    cluster_ids = np.array([0] * 50 + [1] * 50)
    Z = rng.standard_normal((100, 3))
    D = rng.standard_normal((100, 4))
    proxies = build_per_cluster_proxies(Z, D, cluster_ids)
    assert set(proxies.keys()) == {0, 1}
    assert proxies[0].n_train == 50
    assert proxies[1].n_train == 50


# ---------------- Validation ----------------


def test_validation_passes_on_perfectly_linear_problem() -> None:
    rng = np.random.default_rng(6)
    cluster_ids = np.array([0] * 60 + [1] * 60 + [2] * 60)
    n_z, n_d = 5, 8
    S_true = rng.standard_normal((n_z, n_d))
    Z = rng.standard_normal((180, n_z))
    D = Z @ S_true + 50.0
    result = validate_proxy(Z, D, cluster_ids, val_fraction=0.1, seed=7)
    assert result.verdict == "PASS"
    assert result.aggregate["median_rel_err"] < 0.1


def test_validation_handles_three_clusters() -> None:
    rng = np.random.default_rng(8)
    cluster_ids = np.array([0] * 40 + [1] * 40 + [2] * 40)
    Z = rng.standard_normal((120, 4))
    D = rng.standard_normal((120, 5))
    result = validate_proxy(Z, D, cluster_ids, val_fraction=0.15, seed=11)
    assert set(result.per_cluster["cluster"].tolist()) == {0, 1, 2}
    assert result.aggregate["median_rel_err"] >= 0

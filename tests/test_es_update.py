"""Unit tests for the ES update (Task 1.2).

Strategy: build a synthetic ensemble where the truth-θ is known, the
forward operator is linear (`d = H θ + noise`), then verify that the
posterior ensemble mean lands within 1 σ_prior of truth.
"""

from __future__ import annotations

import numpy as np
import pytest

from cmp_ensemble.ensemble.es_update import es_update
from cmp_ensemble.ensemble.subspace import truncated_svd


def _make_synthetic(
    *,
    N: int = 200,
    n_theta: int = 5,
    n_obs: int = 12,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """Linear-Gaussian synthetic problem with a known truth."""
    rng = np.random.default_rng(seed)
    theta_truth = rng.standard_normal(n_theta) * 2.0
    H = rng.standard_normal((n_obs, n_theta)) * 0.5
    sigma_obs = 0.2
    # Prior: broad
    theta_prior = rng.standard_normal((N, n_theta)) * 1.5
    # Forward operator + per-member noise
    d_sim = theta_prior @ H.T + rng.standard_normal((N, n_obs)) * sigma_obs
    # Observation = truth + noise
    d_obs = H @ theta_truth + rng.standard_normal(n_obs) * sigma_obs
    C_dd = (sigma_obs**2) * np.eye(n_obs)
    return {
        "theta_truth": theta_truth,
        "theta_prior": theta_prior,
        "d_sim": d_sim,
        "d_obs": d_obs,
        "C_dd": C_dd,
        "H": H,
    }


def test_posterior_mean_within_one_prior_sigma_of_truth() -> None:
    s = _make_synthetic(seed=42)
    res = es_update(
        s["theta_prior"], s["d_sim"], s["d_obs"], s["C_dd"],
        subspace_energy=0.999, seed=7,
    )
    posterior_mean = res.Z_post.mean(axis=0)
    prior_std = s["theta_prior"].std(axis=0, ddof=1)
    deviation = np.abs(posterior_mean - s["theta_truth"]) / prior_std
    # Median deviation across components should be < 1 σ_prior
    assert float(np.median(deviation)) < 1.0


def test_posterior_spread_shrinks_versus_prior() -> None:
    s = _make_synthetic(seed=1)
    res = es_update(
        s["theta_prior"], s["d_sim"], s["d_obs"], s["C_dd"],
        subspace_energy=0.999, seed=2,
    )
    prior_var = s["theta_prior"].var(axis=0, ddof=1)
    post_var = res.Z_post.var(axis=0, ddof=1)
    # At least one component must contract; in this overdetermined linear
    # problem all of them typically do.
    assert (post_var < prior_var).sum() >= s["theta_prior"].shape[1] - 1


def test_localization_mask_constrains_gain() -> None:
    s = _make_synthetic(seed=5)
    n_z, n_d = s["theta_prior"].shape[1], s["d_obs"].shape[0]
    # Mask half the columns of K
    mask = np.ones((n_z, n_d))
    mask[:, :n_d // 2] = 0.0
    res = es_update(
        s["theta_prior"], s["d_sim"], s["d_obs"], s["C_dd"],
        localization_mask=mask, seed=3,
    )
    assert res.localization_applied is True
    # K must be exactly zero where the mask is zero
    assert np.allclose(res.K[:, : n_d // 2], 0.0)


def test_subspace_truncation_keeps_at_least_99_percent_energy() -> None:
    s = _make_synthetic(seed=11)
    res = es_update(
        s["theta_prior"], s["d_sim"], s["d_obs"], s["C_dd"],
        subspace_energy=0.99, seed=4,
    )
    assert res.energy_kept >= 0.99
    assert 1 <= res.n_components_kept <= len(res.singular_values)


def test_seeded_runs_are_deterministic() -> None:
    s = _make_synthetic(seed=9)
    a = es_update(s["theta_prior"], s["d_sim"], s["d_obs"], s["C_dd"], seed=123)
    b = es_update(s["theta_prior"], s["d_sim"], s["d_obs"], s["C_dd"], seed=123)
    assert np.array_equal(a.Z_post, b.Z_post)
    assert np.array_equal(a.perturbations, b.perturbations)


def test_truncated_svd_helper() -> None:
    rng = np.random.default_rng(0)
    # Construct a matrix with one dominant component
    u = rng.standard_normal(20)
    v = rng.standard_normal(7)
    A = np.outer(u, v) * 10 + rng.standard_normal((20, 7)) * 0.01
    out = truncated_svd(A, energy=0.99)
    assert out.r == 1
    assert out.energy_kept >= 0.99


def test_dimension_validation() -> None:
    Z = np.zeros((5, 3))
    D = np.zeros((5, 4))
    d_obs = np.zeros(4)
    C_dd = np.eye(4)
    # mismatched d_obs
    with pytest.raises(ValueError):
        es_update(Z, D, np.zeros(3), C_dd)
    # mismatched localization mask
    with pytest.raises(ValueError):
        es_update(Z, D, d_obs, C_dd, localization_mask=np.zeros((2, 4)))

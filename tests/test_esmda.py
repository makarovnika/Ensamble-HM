"""Unit tests for the ES-MDA closed-loop core (feature CL-B)."""
import numpy as np
import pytest

from cmp_ensemble.closed_loop import LinearGaussianForward, esmda, uniform_alphas
from cmp_ensemble.closed_loop.esmda import geometric_alphas
from cmp_ensemble.ensemble.es_update import es_update


def _setup(seed=0, N=400, n_z=3, n_d=4):
    rng = np.random.default_rng(seed)
    H = rng.normal(size=(n_d, n_z))
    m0 = rng.normal(size=n_z)
    P0 = np.diag(rng.uniform(0.5, 2.0, size=n_z))
    Theta0 = rng.multivariate_normal(m0, P0, size=N)
    x_true = m0 + rng.normal(size=n_z)
    C_dd = np.diag(rng.uniform(0.1, 0.5, size=n_d))
    d_obs = H @ x_true + rng.multivariate_normal(np.zeros(n_d), C_dd)
    fwd = LinearGaussianForward(H)
    return H, Theta0, C_dd, d_obs, fwd


def test_uniform_alphas_sum_to_one():
    for n in (1, 4, 8):
        a = uniform_alphas(n)
        assert len(a) == n
        assert np.isclose(sum(1.0 / x for x in a), 1.0)


def test_geometric_alphas_sum_to_one():
    a = geometric_alphas(6, ratio=0.5)
    assert np.isclose(sum(1.0 / x for x in a), 1.0)


def test_bad_alphas_rejected():
    H, Theta0, C_dd, d_obs, fwd = _setup()
    with pytest.raises(ValueError):
        esmda(Theta0, fwd, d_obs, C_dd, alphas=[3.0, 3.0])
    esmda(Theta0, fwd, d_obs, C_dd, alphas=[2.0, 2.0])


def test_esmda_one_step_equals_single_es_update():
    H, Theta0, C_dd, d_obs, fwd = _setup(seed=1)
    D = fwd(Theta0)
    ref = es_update(Theta0, D, d_obs, C_dd, seed=42)
    res = esmda(Theta0, fwd, d_obs, C_dd, n_alpha=1, seed=42)
    np.testing.assert_allclose(res.Theta_post, ref.Z_post, rtol=1e-12, atol=1e-12)


def test_esmda_recovers_analytic_posterior_mean():
    H, Theta0, C_dd, d_obs, fwd = _setup(seed=2, N=6000, n_z=6, n_d=4)
    m0 = Theta0.mean(axis=0)
    P0 = np.cov(Theta0, rowvar=False)
    S = H @ P0 @ H.T + C_dd
    Kgain = P0 @ H.T @ np.linalg.inv(S)
    m_post = m0 + Kgain @ (d_obs - H @ m0)
    res = esmda(Theta0, fwd, d_obs, C_dd, n_alpha=4, seed=7, subspace_energy=1.0)
    m_ens = res.Theta_post.mean(axis=0)
    np.testing.assert_allclose(m_ens, m_post, rtol=0.02, atol=0.02)


def test_esmda_misfit_decreases():
    H, Theta0, C_dd, d_obs, fwd = _setup(seed=3, N=2000)
    res = esmda(Theta0, fwd, d_obs, C_dd, n_alpha=4, seed=11)
    assert res.misfit_history[-1] < res.misfit_history[0]
    assert len(res.misfit_history) == 5


def test_esmda_with_localization_runs():
    H, Theta0, C_dd, d_obs, fwd = _setup(seed=4, N=300)
    res = esmda(Theta0, fwd, d_obs, C_dd, n_alpha=4, localize=True, seed=5)
    assert res.localization_applied
    assert res.Theta_post.shape == Theta0.shape

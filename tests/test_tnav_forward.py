"""CL-D: tnav interface ↔ results_reader, full ES-MDA cycle on a mock forward."""
import numpy as np
import pytest

from cmp_ensemble.closed_loop import TNavForward, esmda
from cmp_ensemble.closed_loop.forward import LinearGaussianForward


def test_tnav_forward_builds_theta_dicts_and_calls_run():
    names = ["THICK", "MAJ_R", "AZIMUTH"]
    submitted = {}

    def run_fn(thetas):
        submitted["thetas"] = thetas
        return {i: "ok" for i in range(len(thetas))}

    def read_fn(i, theta):                       # linear pseudo-simulator
        return np.array([theta["THICK"] * 2.0, theta["MAJ_R"] - theta["AZIMUTH"]])

    fwd = TNavForward(names, run_fn, read_fn)
    Theta = np.array([[10.0, 3000.0, 80.0], [12.0, 3200.0, 70.0]])
    D = fwd(Theta)
    assert D.shape == (2, 2)
    assert submitted["thetas"][0]["THICK"] == 10.0          # row→dict mapping
    np.testing.assert_allclose(D[0], [20.0, 2920.0])


def test_tnav_forward_rejects_wrong_width():
    fwd = TNavForward(["A", "B"], lambda t: None, lambda i, th: np.zeros(1))
    with pytest.raises(ValueError):
        fwd(np.zeros((3, 5)))


def test_full_esmda_cycle_through_tnav_forward_mock():
    """A full ES-MDA loop runs end-to-end through TNavForward without tNavigator."""
    rng = np.random.default_rng(0)
    n_z, n_d, N = 3, 4, 300
    names = [f"p{i}" for i in range(n_z)]
    H = rng.normal(size=(n_d, n_z))
    x_true = rng.normal(size=n_z)
    C_dd = np.diag(rng.uniform(0.1, 0.4, size=n_d))
    d_obs = H @ x_true + rng.multivariate_normal(np.zeros(n_d), C_dd)
    Theta0 = rng.multivariate_normal(np.zeros(n_z), np.eye(n_z), size=N)

    calls = {"n": 0}

    def run_fn(thetas):
        calls["n"] += 1                          # count simulator submissions

    def read_fn(i, theta):                       # linear forward d = H·θ
        return H @ np.array([theta[k] for k in names])

    fwd = TNavForward(names, run_fn, read_fn)
    res = esmda(Theta0, fwd, d_obs, C_dd, n_alpha=4, seed=3)

    # ES-MDA submitted the ensemble n_alpha + 1 times (4 updates + final eval).
    assert calls["n"] == 5
    assert res.misfit_history[-1] < res.misfit_history[0]
    # mock forward matches the analytic LinearGaussianForward result.
    ref = esmda(Theta0, LinearGaussianForward(H), d_obs, C_dd, n_alpha=4, seed=3)
    np.testing.assert_allclose(res.Theta_post, ref.Theta_post, rtol=1e-10, atol=1e-10)

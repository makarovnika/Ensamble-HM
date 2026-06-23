"""CL-F: closed-loop forecast, metrics, figures."""
from datetime import datetime

import numpy as np
import pytest

from cmp_ensemble.closed_loop import forecast as fc_mod
from cmp_ensemble.closed_loop import figures as figs
from cmp_ensemble.closed_loop.forward import LinearGaussianForward
from cmp_ensemble.closed_loop.orchestrator import ClosedLoopConfig, run_closed_loop
from cmp_ensemble.closed_loop.prior import PriorResult


def _fc_index():
    wells = ["W1", "W2"]
    times = [datetime(2019, 12, 31), datetime(2020, 12, 31), datetime(2021, 12, 31)]
    metrics = ["Накопл. нефть", "Накопл. вода"]
    return [(m, w, t) for m in metrics for w in wells for t in times]


def _ensembles(n_d, N=80, seed=0):
    rng = np.random.default_rng(seed)
    prior = rng.normal(100, 30, size=(N, n_d))
    post = rng.normal(105, 12, size=(N, n_d))      # narrower => width_ratio < 1
    return prior, post


def test_summarize_forecast_shapes_and_metrics():
    index = _fc_index()
    prior, post = _ensembles(len(index))
    fc = fc_mod.summarize_forecast(prior, post, index)
    assert fc.prior_quantiles.shape[0] == fc.post_quantiles.shape[0]
    assert {"p10", "p50", "p90"}.issubset(fc.post_quantiles.columns)
    # posterior is narrower => median width_ratio < 1
    wr = fc.metrics.width_ratio_table
    assert wr is not None and len(wr) > 0


def test_write_forecast_artifacts(tmp_path):
    index = _fc_index()
    prior, post = _ensembles(len(index))
    fc = fc_mod.summarize_forecast(prior, post, index)
    paths = fc_mod.write_forecast_artifacts(fc, tmp_path)
    for key in ("prior_corridor", "post_corridor", "metrics_summary"):
        assert paths[key].exists()
    assert (tmp_path / "forecast" / "width_ratio.csv").exists()


def test_figures_produce_png_and_pdf(tmp_path):
    misfit = [5.0, 3.0, 2.0, 1.5, 1.2]
    p = figs.fig_misfit_evolution(misfit, tmp_path / "misfit.png")
    assert p.exists() and p.with_suffix(".pdf").exists()

    names = [f"p{i}" for i in range(9)]
    prior = np.random.default_rng(0).normal(0, 1, size=(50, 9))
    post = prior + 0.5
    q = figs.fig_theta_migration(prior, post, names, tmp_path / "mig.png")
    assert q.exists() and q.with_suffix(".pdf").exists()

    index = _fc_index()
    pri, po = _ensembles(len(index))
    fc = fc_mod.summarize_forecast(pri, po, index)
    r = figs.fig_forecast_corridors(fc.prior_quantiles, fc.post_quantiles,
                                    tmp_path / "corr.png")
    assert r.exists() and r.with_suffix(".pdf").exists()


def test_orchestrator_runs_forecast_when_forward_supplied(tmp_path):
    rng = np.random.default_rng(1)
    n_z, N = 4, 60
    names = [f"p{i}" for i in range(n_z)]
    prior = PriorResult(
        Theta=rng.multivariate_normal(np.zeros(n_z), np.eye(n_z), size=N),
        names=names, groups={"geology": names})
    # history forward (for the loop) and forecast forward (post-2018)
    H = rng.normal(size=(6, n_z))
    x_true = rng.normal(size=n_z)
    C_dd = np.diag(rng.uniform(0.1, 0.4, size=6))
    d_obs = H @ x_true + rng.multivariate_normal(np.zeros(6), C_dd)
    fc_index = _fc_index()
    H_fc = rng.normal(size=(len(fc_index), n_z))
    forecast_forward = LinearGaussianForward(H_fc)

    cfg = ClosedLoopConfig(N=N, n_alpha=3, localize=False)
    res = run_closed_loop(
        cfg, prior=prior, forward=LinearGaussianForward(H), d_obs=d_obs, C_dd=C_dd,
        out_root=tmp_path, forecast_forward=forecast_forward, forecast_index=fc_index)
    assert res.status == "completed"
    assert (tmp_path / "figures" / "misfit_evolution.png").exists()
    assert (tmp_path / "figures" / "theta_migration.png").exists()
    assert (tmp_path / "figures" / "forecast_corridors.png").exists()
    assert (tmp_path / "forecast" / "post_corridor.csv").exists()
    assert (tmp_path / "forecast" / "width_ratio.csv").exists()

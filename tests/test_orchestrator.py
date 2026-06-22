"""CL-E: closed-loop orchestrator — plan-only path, full run, checkpoints, CLI."""
import numpy as np
import pytest

from cmp_ensemble.closed_loop import ClosedLoopConfig, run_closed_loop
from cmp_ensemble.closed_loop.forward import LinearGaussianForward
from cmp_ensemble.closed_loop.prior import PriorResult


def _small_prior(N=40, n_z=5, seed=0):
    rng = np.random.default_rng(seed)
    Theta = rng.multivariate_normal(np.zeros(n_z), np.eye(n_z), size=N)
    names = [f"p{i}" for i in range(n_z)]
    return PriorResult(Theta=Theta, names=names, groups={"geology": names})


def _cfg(**kw):
    base = dict(N=40, seed=42, n_alpha=4, localize=False, theta_schema=None)
    base.update(kw)
    return ClosedLoopConfig(**base)


def test_plan_only_writes_run_plan_and_stops(tmp_path):
    cfg = _cfg()
    res = run_closed_loop(cfg, prior=_small_prior(), out_root=tmp_path)
    assert res.status == "planned"
    assert res.Theta_post is None
    plan = tmp_path / "iter_0" / "run_plan.csv"
    assert plan.exists()
    assert (tmp_path / "iter_0" / "theta.npy").exists()
    rows = plan.read_text(encoding="utf-8").strip().splitlines()
    assert rows[0] == "member,model_id,cluster,workflow"
    assert len(rows) == 1 + 40                        # header + N members


def test_full_run_checkpoints_each_iter_and_decreases_misfit(tmp_path):
    prior = _small_prior(N=60, n_z=5, seed=1)
    rng = np.random.default_rng(2)
    n_d = 8
    H = rng.normal(size=(n_d, 5))
    x_true = rng.normal(size=5)
    C_dd = np.diag(rng.uniform(0.1, 0.4, size=n_d))
    d_obs = H @ x_true + rng.multivariate_normal(np.zeros(n_d), C_dd)
    fwd = LinearGaussianForward(H)

    cfg = _cfg(n_alpha=4)
    res = run_closed_loop(cfg, prior=prior, forward=fwd, d_obs=d_obs, C_dd=C_dd,
                          out_root=tmp_path)
    assert res.status == "completed"
    assert res.Theta_post.shape == (60, 5)
    # one checkpoint dir per MDA step
    for i in range(4):
        d = tmp_path / f"iter_{i}"
        assert (d / "Theta.npy").exists() and (d / "D.npy").exists()
        assert (d / "meta.yaml").exists()
    # posterior artifacts + sidecar
    assert (tmp_path / "Theta_post.npy").exists()
    assert (tmp_path / "Theta_post.npy.meta.yaml").exists()
    assert res.misfit_history[-1] < res.misfit_history[0]
    assert len(res.misfit_history) == 5               # n_alpha + final


def test_execute_reaches_session_and_fails_clearly_without_exe(tmp_path):
    """--execute now wires production; with a cluster but no tnav.exe it reaches
    open_production_session and raises a clear 'tnav.exe is unset' error."""
    cfg = _cfg()
    cfg.cluster_workflows = {0: "clust_0_4"}
    cfg.raw = {"tnav": {"exe": None, "project": "x.snp"}}
    with pytest.raises(ValueError, match="tnav.exe is unset"):
        run_closed_loop(cfg, prior=_small_prior(), execute=True, cluster=0,
                        out_root=tmp_path)


def test_cli_closed_loop_dry_run_plan(tmp_path):
    from click.testing import CliRunner
    from cmp_ensemble.cli import cli

    out = tmp_path / "cl"
    r = CliRunner().invoke(
        cli, ["closed-loop", "--dry-run", "--N", "8", "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert (out / "iter_0" / "run_plan.csv").exists()

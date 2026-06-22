"""CL-E.x: production wiring for the --execute path (mock-tested, no tNavigator)."""
import numpy as np
import pytest

from cmp_ensemble.closed_loop import production as prod
from cmp_ensemble.closed_loop.orchestrator import ClosedLoopConfig, run_closed_loop
from cmp_ensemble.closed_loop.forward import LinearGaussianForward
from cmp_ensemble.closed_loop.prior import PriorResult


def test_assign_model_ids():
    assert prod.assign_model_ids(3, base=1000) == [1000, 1001, 1002]
    assert prod.assign_model_ids(2, base=500) == [500, 501]


def test_build_cum_index_order_and_length():
    producers = ["WELL1", "WELL2"]
    from datetime import datetime
    anchors = [datetime(2012, 12, 31), datetime(2018, 12, 31)]
    idx = prod.build_cum_index(producers, anchors)
    assert len(idx) == 3 * 2 * 2                      # metrics × wells × anchors
    assert idx[0] == ("Накопл. нефть", "WELL1", datetime(2012, 12, 31))
    # metric is the slowest-varying axis, then well, then time
    assert idx[4][0] == "Накопл. вода"


def test_load_well_layout_counts():
    producers, injectors = prod.load_well_layout()
    assert len(producers) == 16 and len(injectors) == 6
    assert "WELL1" in producers and "INJ1" in injectors


def test_results_resolver_globs_smspec(tmp_path):
    run = tmp_path / "Models" / "51" / "1000" / "RESULTS" / "0_1-centroid"
    run.mkdir(parents=True)
    (run / "result.SMSPEC").write_bytes(b"stub")
    resolver = prod.ResultsResolver(tmp_path)
    assert resolver.smspec(1000).name == "result.SMSPEC"
    with pytest.raises(FileNotFoundError):
        resolver.smspec(9999)


def test_make_read_fn_uses_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(prod, "read_cumulative_dsim",
                        lambda smspec, cum_index, missing="raise": np.array([1.0, 2.0]))

    class FakeResolver:
        def smspec(self, mid):
            return tmp_path / f"{mid}.SMSPEC"

    read_fn = prod.make_read_fn(FakeResolver(), [1000, 1001], cum_index=[("m", "w", 0)])
    np.testing.assert_array_equal(read_fn(0, {}), [1.0, 2.0])


def test_open_production_session_requires_exe():
    cfg = ClosedLoopConfig(raw={"tnav": {"exe": None, "project": "p.snp"}})
    with pytest.raises(ValueError, match="tnav.exe is unset"):
        prod.open_production_session(cfg)


def test_orchestrator_execute_path_runs_loop_with_mocked_tnav(tmp_path, monkeypatch):
    """The --execute branch wires production + runs the full loop (mocked tNav)."""
    rng = np.random.default_rng(0)
    n_z, n_d, N = 4, 6, 50
    names = [f"p{i}" for i in range(n_z)]
    H = rng.normal(size=(n_d, n_z))
    x_true = rng.normal(size=n_z)
    C_dd = np.diag(rng.uniform(0.1, 0.4, size=n_d))
    d_obs = H @ x_true + rng.multivariate_normal(np.zeros(n_d), C_dd)
    prior = PriorResult(
        Theta=rng.multivariate_normal(np.zeros(n_z), np.eye(n_z), size=N),
        names=names, groups={"geology": names})

    monkeypatch.setattr(prod, "load_well_layout", lambda *a, **k: (["WELL1"], ["INJ1"]))
    monkeypatch.setattr(prod, "build_cum_index", lambda *a, **k: [("m", "w", 0)] * n_d)
    monkeypatch.setattr(prod, "load_closed_loop_observations",
                        lambda *a, **k: (d_obs, C_dd))
    monkeypatch.setattr(prod, "open_production_session", lambda cfg: (None, None))
    monkeypatch.setattr(prod, "build_tnav_forward",
                        lambda *a, **k: LinearGaussianForward(H))

    cfg = ClosedLoopConfig(
        N=N, n_alpha=3, localize=False,
        cluster_workflows={0: "clust_0_4"},
        raw={"tnav": {"model_id_base": 1000, "project": "x.snp"}})
    res = run_closed_loop(cfg, prior=prior, execute=True, cluster=0, out_root=tmp_path)
    assert res.status == "completed"
    assert (tmp_path / "Theta_post.npy").exists()
    for i in range(3):
        assert (tmp_path / f"iter_{i}" / "Theta.npy").exists()
    assert res.misfit_history[-1] < res.misfit_history[0]


def test_execute_requires_cluster(tmp_path):
    cfg = ClosedLoopConfig(N=10, raw={"tnav": {}})
    prior = PriorResult(Theta=np.zeros((10, 3)), names=["a", "b", "c"], groups={})
    with pytest.raises(ValueError, match="requires --cluster"):
        run_closed_loop(cfg, prior=prior, execute=True, cluster=None, out_root=tmp_path)


# ── Real-data test: empty-rate_index (cumulative-only) observation path ────────
def test_load_closed_loop_observations_real_cumulative_only():
    """d_obs/C_dd load with rate_index=[] (the closed-loop cumulative path)."""
    import os
    import numpy as np
    if not os.path.exists("Исторические значения.xlsx"):
        import pytest
        pytest.skip("history workbook not present")
    cfg = ClosedLoopConfig.from_yaml("configs/closed_loop.yaml")
    producers, injectors = prod.load_well_layout()
    cum_index = prod.build_cum_index(producers, prod.build_anchors(cfg))
    d_obs, C_dd = prod.load_closed_loop_observations(cfg, cum_index, producers, injectors)
    assert d_obs.shape == (len(cum_index),)            # 3 × 16 × 8 = 384
    assert C_dd.shape == (len(cum_index), len(cum_index))
    assert np.all(np.isfinite(d_obs))
    assert np.all(np.diag(C_dd) > 0)

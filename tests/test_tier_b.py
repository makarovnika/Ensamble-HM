"""Tests for the 8 Tier B diagnostic figures (viz-002).

Each function is tested with synthetic data so the tests are fast and
independent of the on-disk outputs/. The acceptance is per-figure: PNG
exists, is non-empty (> 5 KB), and renders without warnings escaping.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.viz.tier_b import (
    qc_history_match_quality,
    qc_locmask_heatmap,
    qc_mahalanobis_distribution,
    qc_per_well_misfit_heatmap,
    qc_proxy_validation_scatter,
    qc_singular_spectrum,
    qc_theta_pairgrid,
    qc_forecast_per_well,
    render_all_tier_b,
)


MIN_SIZE = 5_000   # very modest non-empty PNG floor


# ──────────────────────────────────────────────────────────────────────────
# B1 singular spectrum
# ──────────────────────────────────────────────────────────────────────────


def test_qc_singular_spectrum(tmp_path: Path) -> None:
    np.save(tmp_path / "sv.npy", np.linspace(10.0, 0.001, 50))
    p = qc_singular_spectrum(tmp_path / "sv.npy", tmp_path / "b1.png")
    assert p.exists() and p.stat().st_size > MIN_SIZE


# ──────────────────────────────────────────────────────────────────────────
# B2 locmask heatmap
# ──────────────────────────────────────────────────────────────────────────


def test_qc_locmask_heatmap(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    mask = (rng.uniform(size=(9, 384)) > 0.95).astype(float)
    np.save(tmp_path / "mask.npy", mask)
    p = qc_locmask_heatmap(tmp_path / "mask.npy", tmp_path / "b2.png")
    assert p.exists() and p.stat().st_size > MIN_SIZE


# ──────────────────────────────────────────────────────────────────────────
# B3 Mahalanobis distribution
# ──────────────────────────────────────────────────────────────────────────


def test_qc_mahalanobis_distribution(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "member": np.arange(60),
        "maha": rng.uniform(2.0, 4.0, size=60),
    })
    df.to_csv(tmp_path / "maha.csv", index=False)
    np.save(tmp_path / "cluster_ids.npy",
            np.repeat([0, 1, 2], 20).astype(np.int64))
    p = qc_mahalanobis_distribution(
        tmp_path / "maha.csv", tmp_path / "cluster_ids.npy", tmp_path / "b3.png"
    )
    assert p.exists() and p.stat().st_size > MIN_SIZE


def test_qc_mahalanobis_rejects_size_mismatch(tmp_path: Path) -> None:
    df = pd.DataFrame({"member": np.arange(5), "maha": np.zeros(5)})
    df.to_csv(tmp_path / "maha.csv", index=False)
    np.save(tmp_path / "cluster_ids.npy", np.zeros(10, dtype=np.int64))
    with pytest.raises(ValueError, match="cannot merge"):
        qc_mahalanobis_distribution(
            tmp_path / "maha.csv", tmp_path / "cluster_ids.npy", tmp_path / "b3.png"
        )


# ──────────────────────────────────────────────────────────────────────────
# B4 per-well misfit heatmap
# ──────────────────────────────────────────────────────────────────────────


def test_qc_per_well_misfit_heatmap(tmp_path: Path) -> None:
    rows = []
    for metric in ["oil", "water"]:
        for well in ["W1", "W2", "W3"]:
            for year in (2014, 2015, 2016):
                rows.append({"metric": metric, "well": well,
                             "time": f"{year}-12-01",
                             "d_obs": 1.0, "d_sim_mean": 1.0, "d_sim_std": 0.1,
                             "residual": 0.05, "residual_z": 0.5})
    pd.DataFrame(rows).to_csv(tmp_path / "misfit.csv", index=False)
    p = qc_per_well_misfit_heatmap(tmp_path / "misfit.csv", tmp_path / "b4.png")
    assert p.exists() and p.stat().st_size > MIN_SIZE


def test_qc_per_well_misfit_rejects_missing_column(tmp_path: Path) -> None:
    pd.DataFrame({"metric": ["a"], "well": ["W"], "time": ["2020-01-01"]}).to_csv(
        tmp_path / "bad.csv", index=False
    )
    with pytest.raises(ValueError, match="residual_z"):
        qc_per_well_misfit_heatmap(tmp_path / "bad.csv", tmp_path / "b4.png")


# ──────────────────────────────────────────────────────────────────────────
# B5 θ pairgrid
# ──────────────────────────────────────────────────────────────────────────


def test_qc_theta_pairgrid(tmp_path: Path) -> None:
    rng = np.random.default_rng(2)
    np.save(tmp_path / "prior.npy", rng.standard_normal((40, 4)))
    np.save(tmp_path / "post.npy", rng.standard_normal((40, 4)) * 0.7)
    p = qc_theta_pairgrid(
        tmp_path / "prior.npy", tmp_path / "post.npy", tmp_path / "b5.png",
        theta_names=["a", "b", "c", "d"],
    )
    assert p.exists() and p.stat().st_size > MIN_SIZE


# ──────────────────────────────────────────────────────────────────────────
# B6 proxy validation scatter
# ──────────────────────────────────────────────────────────────────────────


def test_qc_proxy_validation_scatter(tmp_path: Path) -> None:
    df = pd.DataFrame({
        "cluster": [0, 0, 1, 1, 2, 2],
        "member_index": [0, 1, 10, 11, 20, 21],
        "median_rel_err": [0.5, 0.8, 1.1, 0.9, 0.7, 1.2],
    })
    df.to_csv(tmp_path / "val.csv", index=False)
    p = qc_proxy_validation_scatter(tmp_path / "val.csv", tmp_path / "b6.png")
    assert p.exists() and p.stat().st_size > MIN_SIZE


# ──────────────────────────────────────────────────────────────────────────
# B7 / B8 — require h5py; synthesise minimal HDF5 caches
# ──────────────────────────────────────────────────────────────────────────


def _make_forecast_h5(path: Path) -> None:
    import h5py
    with h5py.File(path, "w") as f:
        f.create_dataset("model_ids", data=np.arange(6, dtype=np.int64))
        f.create_dataset("cluster_ids", data=np.repeat([0, 1, 2], 2).astype(np.int64))
        f.create_dataset("seeds", data=np.arange(100, 106, dtype=np.int64))
        sheets = np.array([s.encode() for s in [f"s{i}" for i in range(6)]])
        f.create_dataset("sheet_names", data=sheets)
        # 2 wells × 2 years = 4 cum entries per metric, × 3 metrics = 12 columns
        n_d_cum = 12
        rng = np.random.default_rng(3)
        f.create_dataset("d_forecast_cum",
                         data=(rng.uniform(1e5, 1e7, size=(6, n_d_cum))))
        f.create_dataset("d_forecast_rates", data=np.zeros((6, 2)))
        idx = []
        for metric in ("Накопл. нефть", "Накопл. вода", "Накопл. газ"):
            for well in ("W1", "W2"):
                for year in (2020, 2021):
                    idx.append((metric.encode(), well.encode(),
                                f"{year}-12-01T00:00:00".encode()))
        f.create_dataset("cum_index", data=np.array(idx))
        f.create_dataset("rate_index", data=np.array(idx[:2]))
        f.create_dataset("forecast_time_steps",
                         data=np.array([np.datetime64("2020-12-01"),
                                         np.datetime64("2021-12-01")],
                                        dtype="datetime64[ns]").astype("int64"))
        f.create_dataset("producer_wells",
                         data=np.array([b"W1", b"W2"]))
        f.attrs["history_cutoff"] = "2020-01-01T00:00:00"
        f.attrs["cumulative_anomaly"] = True


def _make_ensemble_h5(path: Path, n_d_cum: int = 12) -> None:
    import h5py
    with h5py.File(path, "w") as f:
        idx = []
        for metric in ("Накопл. нефть", "Накопл. вода", "Накопл. газ"):
            for well in ("W1", "W2"):
                for year in (2014, 2015):
                    idx.append((metric.encode(), well.encode(),
                                f"{year}-12-01T00:00:00".encode()))
        f.create_dataset("cum_index", data=np.array(idx))


def test_qc_forecast_per_well(tmp_path: Path) -> None:
    _make_forecast_h5(tmp_path / "forecast.h5")
    p = qc_forecast_per_well(tmp_path / "forecast.h5", tmp_path / "b7.png")
    assert p.exists() and p.stat().st_size > MIN_SIZE


def test_qc_history_match_quality(tmp_path: Path) -> None:
    n_d_cum = 12
    rng = np.random.default_rng(4)
    np.save(tmp_path / "d_sim.npy", rng.uniform(0, 1e6, size=(50, n_d_cum)))
    np.save(tmp_path / "d_obs.npy", rng.uniform(0, 1e6, size=n_d_cum))
    _make_ensemble_h5(tmp_path / "ensemble.h5", n_d_cum)
    p = qc_history_match_quality(
        tmp_path / "d_sim.npy", tmp_path / "d_obs.npy",
        tmp_path / "ensemble.h5", tmp_path / "b8.png",
    )
    assert p.exists() and p.stat().st_size > MIN_SIZE


# ──────────────────────────────────────────────────────────────────────────
# Dispatcher resilience: missing inputs must skip, not crash
# ──────────────────────────────────────────────────────────────────────────


def test_render_all_tier_b_on_empty_outputs(tmp_path: Path) -> None:
    (tmp_path / "outputs").mkdir()
    done = render_all_tier_b(tmp_path)
    assert isinstance(done, dict)
    assert len(done) == 0   # nothing to render — but it didn't crash

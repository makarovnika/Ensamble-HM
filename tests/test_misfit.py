"""Tests for the per-well misfit diagnostic."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from cmp_ensemble.qc.misfit import per_well_misfit_summary, per_well_misfit_table


def _index(n: int, metric: str = "Дебит нефти", well: str = "WELL1") -> list:
    return [(metric, well, datetime(2020, 1, 1)) for _ in range(n)]


def test_misfit_basic_shapes() -> None:
    rng = np.random.default_rng(0)
    d_sim = rng.standard_normal((20, 5)) + 100  # 5 obs
    d_obs = d_sim.mean(axis=0) + 0.1            # tiny residual
    idx = [
        ("Дебит нефти", "WELL1", datetime(2020, 1, 1)),
        ("Дебит нефти", "WELL2", datetime(2020, 1, 1)),
        ("Дебит воды", "WELL1", datetime(2020, 1, 1)),
        ("Дебит воды", "WELL2", datetime(2020, 1, 1)),
        ("Дебит газа", "WELL1", datetime(2020, 1, 1)),
    ]
    table = per_well_misfit_table(d_obs, d_sim, idx)
    assert len(table) == 5
    # residual is small, so abs(residual_z) should be modest
    assert (table["residual_z"].abs() < 1.0).all()
    summary = per_well_misfit_summary(table)
    assert set(summary.columns) >= {"metric", "well", "n_obs", "mean_abs_residual_z"}


def test_misfit_flags_large_residuals() -> None:
    d_sim = np.full((10, 1), 50.0) + np.linspace(-1, 1, 10).reshape(-1, 1)
    d_obs = np.array([0.0])  # big mismatch — sim ~50, obs = 0
    table = per_well_misfit_table(d_obs, d_sim, _index(1))
    assert table.iloc[0]["residual"] > 40
    assert abs(table.iloc[0]["residual_z"]) > 10

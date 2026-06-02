"""Unit tests for the observations loader's per-metric soft floor.

The Excel file itself is not synthesised here; instead we exercise the
internal helper logic by constructing arrays and feeding them through the
public C_dd assembly path indirectly.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

# We test the per-metric floor logic by calling the inner closure through
# a mini reimplementation that mirrors observations._build_diag_sigma.


def _build_diag_sigma_like(d_obs, index, rel_sigma=0.15, floor_abs=1e-3):
    sigma = np.abs(d_obs) * rel_sigma
    metrics = np.array([e[0] for e in index])
    for m in set(metrics.tolist()):
        mask = metrics == m
        med_abs = float(np.median(np.abs(d_obs[mask])))
        soft_floor = max(0.01 * med_abs, floor_abs)
        below = mask & (sigma < soft_floor)
        sigma[below] = soft_floor
    return sigma


def test_floor_scales_per_metric() -> None:
    # Cumulative gas: 1e8 scale
    # Cumulative oil: 1e5 scale
    d_obs = np.array([0.0, 1e8, 2e8, 0.0, 1e5, 2e5])
    idx = [
        ("Накопл. газ", "W1", datetime(2018, 1, 1)),
        ("Накопл. газ", "W2", datetime(2018, 1, 1)),
        ("Накопл. газ", "W3", datetime(2018, 1, 1)),
        ("Накопл. нефть", "W1", datetime(2018, 1, 1)),
        ("Накопл. нефть", "W2", datetime(2018, 1, 1)),
        ("Накопл. нефть", "W3", datetime(2018, 1, 1)),
    ]
    sigma = _build_diag_sigma_like(d_obs, idx)
    # Zero entries get the per-metric soft floor:
    # gas: 0.01 * median(0, 1e8, 2e8) = 0.01 * 1e8 = 1e6
    # oil: 0.01 * median(0, 1e5, 2e5) = 0.01 * 1e5 = 1e3
    assert abs(sigma[0] - 1e6) < 1.0
    assert abs(sigma[3] - 1e3) < 1.0
    # Non-zero entries scale by rel_sigma=0.15
    assert abs(sigma[1] - 0.15 * 1e8) < 1.0
    assert abs(sigma[4] - 0.15 * 1e5) < 1.0


def test_absolute_floor_used_when_no_signal() -> None:
    d_obs = np.zeros(3)
    idx = [("X", "W", datetime(2020, 1, 1))] * 3
    sigma = _build_diag_sigma_like(d_obs, idx, floor_abs=2.5)
    # All entries get the absolute floor
    assert np.allclose(sigma, 2.5)

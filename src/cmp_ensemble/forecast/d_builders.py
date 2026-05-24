"""Helpers that assemble the observation vector ``d`` for ES update.

Three modes match the three ablation setups in ТЗ §6 Task 3.1:

  * ``cumulative``  — yearly cumulative production per producer (default).
  * ``rates``       — full monthly rate history (large; mainly for diagnostics).
  * ``hybrid``      — concatenation of ``cumulative`` + annual rate snapshots
                      (year-end rate values per producer). Matches setup3.

Each builder returns ``(D_sim, d_obs, C_dd, index)`` with consistent shapes so
that ES update can swallow them directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd

from cmp_ensemble.io.schemas import EnsembleData, ObservationData

DObsType = Literal["cumulative", "rates", "hybrid"]

ANNUAL_RATE_METRICS = ("Дебит нефти", "Дебит воды", "Дебит газа")


def _annual_rate_snapshot_positions(
    rate_index: list[tuple[str, str, datetime]],
    metrics: tuple[str, ...] = ANNUAL_RATE_METRICS,
) -> tuple[list[int], list[tuple[str, str, datetime]]]:
    """Return positions (and the resulting sub-index) for the year-end rate of
    each (metric, well, year). Within each (metric, well) block the *last*
    monthly position in a calendar year is kept (matching the same convention
    used for cumulative aggregation in Phase 0)."""
    groups: dict[tuple[str, str, int], int] = {}
    for pos, (metric, well, ts) in enumerate(rate_index):
        if metric not in metrics:
            continue
        year = pd.Timestamp(ts).year
        groups[(metric, well, year)] = pos   # later position overrides earlier
    kept = sorted(groups.values())
    sub_index = [rate_index[p] for p in kept]
    return kept, sub_index


def build_d(
    ensemble: EnsembleData,
    observations: ObservationData,
    mode: DObsType,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[tuple[str, str, datetime]]]:
    """Return ``(D_sim, d_obs, C_dd, index)`` for the requested mode.

    `D_sim` is (N, n_d), `d_obs` is (n_d,), `C_dd` is diagonal (n_d, n_d).
    """
    if mode == "cumulative":
        return (
            ensemble.d_sim_cum,
            observations.d_obs_cum,
            observations.C_dd_cum,
            ensemble.cum_index,
        )
    if mode == "rates":
        return (
            ensemble.d_sim_rates,
            observations.d_obs_rates,
            observations.C_dd_rates,
            ensemble.rate_index,
        )
    if mode == "hybrid":
        positions, rate_sub_index = _annual_rate_snapshot_positions(ensemble.rate_index)
        D_rate = ensemble.d_sim_rates[:, positions]
        d_obs_rate = observations.d_obs_rates[positions]
        diag_rate = np.diag(observations.C_dd_rates)[positions]
        D_hybrid = np.hstack([ensemble.d_sim_cum, D_rate])
        d_obs_hybrid = np.concatenate([observations.d_obs_cum, d_obs_rate])
        diag_hybrid = np.concatenate([np.diag(observations.C_dd_cum), diag_rate])
        C_dd_hybrid = np.diag(diag_hybrid)
        index = list(ensemble.cum_index) + rate_sub_index
        return D_hybrid, d_obs_hybrid, C_dd_hybrid, index
    raise ValueError(f"Unknown d_obs mode: {mode!r}")

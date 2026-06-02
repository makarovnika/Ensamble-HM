"""Per-well, per-metric simulator vs observation misfit table.

For each (metric, well, time) entry, computes:

  d_obs              — observed value
  d_sim_mean         — ensemble mean of simulated values
  d_sim_std          — ensemble std of simulated values
  residual           — d_sim_mean - d_obs
  residual_z         — (d_sim_mean - d_obs) / d_sim_std
                        (>1 means simulator systematically off by >1σ of ensemble spread)

A summary aggregates absolute residual_z per (metric, well) so it is easy to
spot the worst-fitting wells.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd


def per_well_misfit_table(
    d_obs: np.ndarray,
    d_sim: np.ndarray,
    index: list[tuple[str, str, datetime]],
) -> pd.DataFrame:
    """Build the long-format misfit table from the matching (metric, well, time)
    index used for `d_obs` and the columns of `d_sim`.
    """
    d_sim_mean = d_sim.mean(axis=0)
    d_sim_std = d_sim.std(axis=0, ddof=1)
    safe_std = np.where(d_sim_std > 0, d_sim_std, 1.0)
    residual = d_sim_mean - d_obs
    residual_z = residual / safe_std

    rows = []
    for k, (m, w, t) in enumerate(index):
        rows.append(
            {
                "metric": m,
                "well": w,
                "time": pd.Timestamp(t).date(),
                "d_obs": float(d_obs[k]),
                "d_sim_mean": float(d_sim_mean[k]),
                "d_sim_std": float(d_sim_std[k]),
                "residual": float(residual[k]),
                "residual_z": float(residual_z[k]),
            }
        )
    return pd.DataFrame(rows)


def per_well_misfit_summary(table: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the misfit table to one row per (metric, well)."""
    grouped = table.groupby(["metric", "well"]).agg(
        n_obs=("d_obs", "size"),
        n_obs_nonzero=("d_obs", lambda s: int((s != 0).sum())),
        mean_abs_residual=("residual", lambda s: float(np.abs(s).mean())),
        median_abs_residual=("residual", lambda s: float(np.median(np.abs(s)))),
        mean_abs_residual_z=("residual_z", lambda s: float(np.abs(s).mean())),
        max_abs_residual_z=("residual_z", lambda s: float(np.abs(s).max())),
    ).reset_index()
    return grouped.sort_values("mean_abs_residual_z", ascending=False)

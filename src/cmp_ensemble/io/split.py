"""Train/val split of the historical time axis (ТЗ §6 Task 3.4).

The 8-year history (2011-2018) is split into a training window and a
held-out validation window by calendar year. ES update uses only the train
slice; the val slice supplies d_truth so Phase 3 can compute coverage,
CRPS, and cumulative_error.

The split is index-driven, not slice-driven: returns boolean masks over
the (metric, well, time) indexes used elsewhere in the pipeline. This
avoids re-running the heavy Excel ingest just to filter by year.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass
class HistorySplit:
    """Boolean masks separating train years from val years."""

    train_rate_mask: np.ndarray         # (n_d_rates,) bool
    val_rate_mask: np.ndarray
    train_cum_mask: np.ndarray          # (n_d_cum,) bool
    val_cum_mask: np.ndarray
    train_time_mask: np.ndarray         # (n_time,) bool over the canonical time grid
    val_time_mask: np.ndarray
    train_years: tuple[int, ...]
    val_years: tuple[int, ...]
    train_end_date: datetime            # last day in the train window
    val_start_date: datetime            # first day in the val window

    @property
    def n_train_time_steps(self) -> int:
        return int(self.train_time_mask.sum())

    @property
    def n_val_time_steps(self) -> int:
        return int(self.val_time_mask.sum())


def split_history(
    *,
    rate_index: list[tuple[str, str, datetime]],
    cum_index: list[tuple[str, str, datetime]],
    time_steps: np.ndarray,
    train_years: int = 6,
    val_years: int = 2,
) -> HistorySplit:
    """Build train / val masks over the rate index, cum index, and time grid.

    The cutoff is computed from the calendar years present in `time_steps`:
    the first `train_years` distinct years go to train, the next `val_years`
    distinct years go to val. Any additional years are ignored.

    Raises
    ------
    ValueError if there are not enough distinct years to honour the split.
    """
    if train_years < 1 or val_years < 1:
        raise ValueError("train_years and val_years must both be >= 1")
    years_in_grid = sorted({pd.Timestamp(t).year for t in time_steps})
    if len(years_in_grid) < train_years + val_years:
        raise ValueError(
            f"Only {len(years_in_grid)} distinct years in the time grid "
            f"({years_in_grid[0]}-{years_in_grid[-1]}), need at least "
            f"{train_years + val_years} for a {train_years}+{val_years} split."
        )
    train_set = tuple(years_in_grid[:train_years])
    val_set = tuple(years_in_grid[train_years : train_years + val_years])

    def _mask(index, years_set):
        years_set_set = set(years_set)
        return np.array(
            [pd.Timestamp(t).year in years_set_set for (_m, _w, t) in index],
            dtype=bool,
        )

    train_rate_mask = _mask(rate_index, train_set)
    val_rate_mask = _mask(rate_index, val_set)
    train_cum_mask = _mask(cum_index, train_set)
    val_cum_mask = _mask(cum_index, val_set)

    train_set_for_time = set(train_set)
    val_set_for_time = set(val_set)
    train_time_mask = np.array(
        [pd.Timestamp(t).year in train_set_for_time for t in time_steps],
        dtype=bool,
    )
    val_time_mask = np.array(
        [pd.Timestamp(t).year in val_set_for_time for t in time_steps],
        dtype=bool,
    )

    train_dates = [pd.Timestamp(t) for t in time_steps if pd.Timestamp(t).year in train_set_for_time]
    val_dates = [pd.Timestamp(t) for t in time_steps if pd.Timestamp(t).year in val_set_for_time]
    train_end_date = max(train_dates).to_pydatetime()
    val_start_date = min(val_dates).to_pydatetime()

    if not train_end_date < val_start_date:
        raise RuntimeError(
            f"Train end {train_end_date} is not strictly before val start "
            f"{val_start_date} — leakage."
        )

    return HistorySplit(
        train_rate_mask=train_rate_mask,
        val_rate_mask=val_rate_mask,
        train_cum_mask=train_cum_mask,
        val_cum_mask=val_cum_mask,
        train_time_mask=train_time_mask,
        val_time_mask=val_time_mask,
        train_years=train_set,
        val_years=val_set,
        train_end_date=train_end_date,
        val_start_date=val_start_date,
    )


def filter_index(
    index: list[tuple[str, str, datetime]],
    mask: np.ndarray,
) -> list[tuple[str, str, datetime]]:
    """Helper: filter (metric, well, time) entries by a boolean mask."""
    if mask.shape[0] != len(index):
        raise ValueError(f"mask length {mask.shape[0]} != index length {len(index)}")
    return [e for e, keep in zip(index, mask) if keep]

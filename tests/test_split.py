"""Unit tests for the train/val history split (ТЗ §6 Task 3.4)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.io.split import HistorySplit, filter_index, split_history


def _make_index_and_grid(year_start: int = 2011, n_years: int = 8):
    """Build a monthly grid + matching rate/cum indexes covering n_years."""
    time_steps = np.array(
        [
            pd.Timestamp(year_start + i // 12, (i % 12) + 1, 1).to_datetime64()
            for i in range(n_years * 12)
        ],
        dtype="datetime64[ns]",
    )
    wells = ["W1", "W2"]
    metrics = ["Дебит нефти", "Дебит воды"]
    rate_index = [
        (m, w, pd.Timestamp(t).to_pydatetime())
        for m in metrics for w in wells for t in time_steps
    ]
    cum_index = [
        (f"Накопл. {m.split()[-1]}", w, pd.Timestamp(time_steps[12 * (y - year_start + 1) - 1]).to_pydatetime())
        for m in metrics for w in wells for y in range(year_start, year_start + n_years)
    ]
    return time_steps, rate_index, cum_index


def test_default_6_2_split() -> None:
    time_steps, rate_index, cum_index = _make_index_and_grid(2011, 8)
    out = split_history(
        rate_index=rate_index,
        cum_index=cum_index,
        time_steps=time_steps,
        train_years=6,
        val_years=2,
    )
    assert out.train_years == (2011, 2012, 2013, 2014, 2015, 2016)
    assert out.val_years == (2017, 2018)
    # 6 years × 12 months = 72 train time steps; 2 × 12 = 24 val
    assert out.n_train_time_steps == 72
    assert out.n_val_time_steps == 24


def test_no_leakage() -> None:
    time_steps, rate_index, cum_index = _make_index_and_grid(2011, 8)
    out = split_history(
        rate_index=rate_index, cum_index=cum_index, time_steps=time_steps,
    )
    assert out.train_end_date < out.val_start_date
    # Per-index masks: disjoint and cover everything
    assert not (out.train_rate_mask & out.val_rate_mask).any()
    assert not (out.train_cum_mask & out.val_cum_mask).any()
    # The union equals "in any of train or val years" — we only requested 6+2=8
    # years out of the 8-year grid, so the union must cover the whole grid.
    assert (out.train_rate_mask | out.val_rate_mask).all()
    assert (out.train_cum_mask | out.val_cum_mask).all()


def test_per_metric_well_count_balanced() -> None:
    """Every (metric, well) pair must contribute the same number of train and val
    entries, since the split is purely temporal."""
    time_steps, rate_index, cum_index = _make_index_and_grid(2011, 8)
    out = split_history(rate_index=rate_index, cum_index=cum_index, time_steps=time_steps)
    # rate_index has 2 metrics × 2 wells × 96 months = 384 entries
    # train should keep 2 × 2 × 72 = 288, val 2 × 2 × 24 = 96
    assert int(out.train_rate_mask.sum()) == 288
    assert int(out.val_rate_mask.sum()) == 96


def test_insufficient_years_raises() -> None:
    time_steps, rate_index, cum_index = _make_index_and_grid(2011, 3)
    with pytest.raises(ValueError, match="distinct years"):
        split_history(
            rate_index=rate_index, cum_index=cum_index, time_steps=time_steps,
            train_years=6, val_years=2,
        )


def test_invalid_year_args() -> None:
    time_steps, rate_index, cum_index = _make_index_and_grid(2011, 8)
    with pytest.raises(ValueError, match=">= 1"):
        split_history(
            rate_index=rate_index, cum_index=cum_index, time_steps=time_steps,
            train_years=0, val_years=2,
        )


def test_filter_index_round_trip() -> None:
    time_steps, rate_index, cum_index = _make_index_and_grid(2011, 8)
    out = split_history(rate_index=rate_index, cum_index=cum_index, time_steps=time_steps)
    train_idx = filter_index(rate_index, out.train_rate_mask)
    val_idx = filter_index(rate_index, out.val_rate_mask)
    assert len(train_idx) + len(val_idx) == len(rate_index)
    # No element appears in both
    train_set = set((m, w, t) for m, w, t in train_idx)
    val_set = set((m, w, t) for m, w, t in val_idx)
    assert not (train_set & val_set)


def test_filter_index_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="mask length"):
        filter_index([("a", "b", datetime(2020, 1, 1))], np.array([True, False]))


def test_split_with_real_phase0_shapes() -> None:
    """Exercise the realistic shape from the project (97 months, 8 years, drift)."""
    # Real history is monthly with day-of-month drift (Jan 1, Feb 1, Mar 4, ...).
    # The split must group by calendar YEAR, not by step index.
    rng = pd.date_range("2011-01-01", "2018-12-13", periods=97)
    time_steps = rng.to_numpy(dtype="datetime64[ns]")
    rate_index = [
        ("Дебит нефти", "WELL1", pd.Timestamp(t).to_pydatetime()) for t in time_steps
    ]
    cum_index = [
        ("Накопл. нефть", "WELL1",
         pd.Timestamp(max(t for t in time_steps if pd.Timestamp(t).year == y)).to_pydatetime())
        for y in range(2011, 2019)
    ]
    out = split_history(
        rate_index=rate_index, cum_index=cum_index, time_steps=time_steps,
        train_years=6, val_years=2,
    )
    assert out.train_years == (2011, 2012, 2013, 2014, 2015, 2016)
    assert out.val_years == (2017, 2018)
    # cum_index has 8 entries; 6 train + 2 val
    assert int(out.train_cum_mask.sum()) == 6
    assert int(out.val_cum_mask.sum()) == 2

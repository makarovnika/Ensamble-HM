"""Historical observations loader — Task 0.2.

Reads ``Исторические значения.xlsx`` (long-format, 2231 × 50) and pivots to
(n_time, n_well) tables per metric. Builds the diagonal noise covariance C_dd
from ``configs/noise_spec.yaml`` (default: 15% relative Gaussian).

The same metric set as the dynamics loader is extracted, so that the d_sim and
d_obs vectors are dimensionally compatible.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cmp_ensemble.io.schemas import ObservationData

log = logging.getLogger(__name__)

# Column mapping from the long-format header to the metric labels used in the
# dynamics file. We keep the dynamics-side labels as canonical because the ES
# update compares d_obs[i] with d_sim[i] entry-by-entry.
HISTORY_TO_METRIC: dict[str, str] = {
    "Дебит нефти, ст.м3/сут": "Дебит нефти",
    "Дебит воды, ст.м3/сут": "Дебит воды",
    "Дебит газа, ст.м3/сут": "Дебит газа",
    "Забойное давление, бар абс.": "Забойное давление",
    "Приёмистость воды, ст.м3/сут": "Приёмистость воды",
}
CUM_HISTORY_TO_METRIC: dict[str, str] = {
    "Добыча нефти, ст.м3": "Накопл. нефть",
    "Добыча воды, ст.м3": "Накопл. вода",
    "Добыча газа, ст.м3": "Накопл. газ",
}

DUMMY_WELL = "B"


def _pivot_long_to_wide(
    df: pd.DataFrame, metric_col: str
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Pivot the long-format historical table to (n_time, n_well) for one metric.

    Returns
    -------
    matrix : (n_time, n_well) float array
    times  : (n_time,) datetime64 array
    wells  : list of well names matching matrix columns
    """
    sub = df[["Скважина", "Дата", metric_col]].copy()
    sub[metric_col] = pd.to_numeric(sub[metric_col], errors="coerce").fillna(0.0)
    wide = sub.pivot(index="Дата", columns="Скважина", values=metric_col).sort_index()
    return wide.to_numpy(dtype=np.float64), wide.index.to_numpy(), wide.columns.tolist()


def _build_diagonal_C_dd(
    d_obs: np.ndarray,
    relative_sigma: float,
    floor_abs: float,
) -> np.ndarray:
    """Diagonal C_dd with σ_i = max(relative_sigma * |d_obs_i|, floor_abs)."""
    sigma = np.maximum(np.abs(d_obs) * relative_sigma, floor_abs)
    return np.diag(sigma ** 2)


def _year_end_indices(times: np.ndarray) -> dict[int, int]:
    years = pd.to_datetime(times).year
    out: dict[int, int] = {}
    for i, y in enumerate(years):
        out[int(y)] = i
    return out


def load_observations(
    history_path: Path,
    *,
    noise_spec: dict[str, Any],
    producer_wells: list[str],
    injector_wells: list[str],
    rate_index: list[tuple[str, str, datetime]],
    cum_index: list[tuple[str, str, datetime]],
) -> ObservationData:
    """Load historical observations matching the dynamics index layout.

    The rate/cum indexes from the ensemble loader pin the exact (metric, well,
    time) ordering; this loader fills d_obs in the same order so that d_obs[i]
    aligns with d_sim[:, i].
    """
    log.info(f"Loading observations workbook: {history_path.name}")
    df = pd.read_excel(history_path, sheet_name="Sheet1")
    log.info(f"  raw shape: {df.shape}")
    # filter dummy well
    if DUMMY_WELL in df["Скважина"].unique():
        n_before = len(df)
        df = df[df["Скважина"] != DUMMY_WELL].copy()
        log.info(f"  dropped dummy well {DUMMY_WELL!r}: {n_before - len(df)} rows")

    # noise spec
    rel_sigma = float(noise_spec.get("relative_sigma", 0.15))
    floor_abs = float(noise_spec.get("floor_abs", 1.0e-3))
    bhp_drop_zero = noise_spec.get("bhp_handling", {}).get("drop_zero_entries", True)
    bhp_zero_threshold = float(
        noise_spec.get("bhp_handling", {}).get("zero_threshold", 1.0e-6)
    )

    # Build wide tables per metric
    rate_tables: dict[str, tuple[np.ndarray, np.ndarray, list[str]]] = {}
    for hist_col, metric in HISTORY_TO_METRIC.items():
        rate_tables[metric] = _pivot_long_to_wide(df, hist_col)
    cum_tables: dict[str, tuple[np.ndarray, np.ndarray, list[str]]] = {}
    for hist_col, metric in CUM_HISTORY_TO_METRIC.items():
        cum_tables[metric] = _pivot_long_to_wide(df, hist_col)

    # Use the first metric's time grid as the canonical historical grid
    canonical_times = next(iter(rate_tables.values()))[1]
    log.info(f"  canonical time grid: {len(canonical_times)} steps "
             f"({pd.Timestamp(canonical_times[0]).date()} → "
             f"{pd.Timestamp(canonical_times[-1]).date()})")
    year_ends = _year_end_indices(canonical_times)

    # Map (well, time) → row index in the wide tables.
    time_to_idx = {pd.Timestamp(t): i for i, t in enumerate(canonical_times)}

    def _lookup_rate(metric: str, well: str, t: datetime) -> float:
        matrix, times, wells = rate_tables[metric]
        if well not in wells:
            return 0.0
        # Match nearest historical timestamp by month+year (real dates drift by days).
        ts = pd.Timestamp(t)
        idx = time_to_idx.get(ts)
        if idx is None:
            # find same year-month
            year_month = (ts.year, ts.month)
            for k, v in enumerate(times):
                if (pd.Timestamp(v).year, pd.Timestamp(v).month) == year_month:
                    idx = k
                    break
            if idx is None:
                return 0.0
        return float(matrix[idx, wells.index(well)])

    def _lookup_cum(metric: str, well: str, t: datetime) -> float:
        matrix, times, wells = cum_tables[metric]
        if well not in wells:
            return 0.0
        ts = pd.Timestamp(t)
        # cumulative values are aggregated to year-end — match by year
        year = ts.year
        # find the last historical row of that year
        # We compute on demand to allow re-use even if year-end day differs.
        candidate_idx = None
        for k, v in enumerate(times):
            if pd.Timestamp(v).year == year:
                candidate_idx = k  # keep updating; last wins
        if candidate_idx is None:
            return 0.0
        return float(matrix[candidate_idx, wells.index(well)])

    # Assemble d_obs vectors matching the ensemble indexes
    log.info(f"  building d_obs_rates ({len(rate_index)} entries)")
    d_obs_rates = np.array(
        [_lookup_rate(m, w, t) for (m, w, t) in rate_index], dtype=np.float64
    )
    log.info(f"  building d_obs_cum ({len(cum_index)} entries)")
    d_obs_cum = np.array(
        [_lookup_cum(m, w, t) for (m, w, t) in cum_index], dtype=np.float64
    )

    # BHP handling: count zero entries; drop or inflate per config
    n_bhp_zero_dropped = 0
    n_bhp_zero_inflated = 0
    if bhp_drop_zero:
        bhp_mask = np.array(
            [m == "Забойное давление" for (m, _w, _t) in rate_index],
            dtype=bool,
        )
        zero_bhp = bhp_mask & (np.abs(d_obs_rates) <= bhp_zero_threshold)
        n_bhp_zero_dropped = int(zero_bhp.sum())
        # we don't actually drop entries from the vector (to keep d_sim/d_obs
        # alignment); instead we inflate σ on those entries so they contribute
        # negligibly to the ES update.
        n_bhp_zero_inflated = n_bhp_zero_dropped
        log.warning(
            f"  BHP-zero entries: {n_bhp_zero_dropped} of "
            f"{int(bhp_mask.sum())} BHP slots. Their C_dd diagonal will be inflated."
        )
    else:
        zero_bhp = np.zeros(len(d_obs_rates), dtype=bool)

    # Build diagonal C_dd.
    # The floor was previously a single absolute value (1e-3), which is
    # appropriate for rate metrics (sm³/day) but is wildly tight for cumulative
    # gas (10⁹ sm³). Replace with a per-metric relative floor:
    # σ_i ≥ max(rel_sigma · |d_obs_i|, 0.01 · median(|d_obs|) of the same metric).
    def _build_diag_sigma(
        d_obs: np.ndarray,
        index: list[tuple[str, str, datetime]],
    ) -> np.ndarray:
        sigma = np.abs(d_obs) * rel_sigma
        # group entries by metric and compute a per-metric soft floor
        metrics = np.array([e[0] for e in index])
        for m in set(metrics.tolist()):
            mask = metrics == m
            med_abs = float(np.median(np.abs(d_obs[mask])))
            soft_floor = max(0.01 * med_abs, floor_abs)
            below = mask & (sigma < soft_floor)
            sigma[below] = soft_floor
        return sigma

    log.info(f"  building C_dd (rel_sigma={rel_sigma}, floor_abs={floor_abs}, per-metric soft floor)")
    sigma_rates = _build_diag_sigma(d_obs_rates, rate_index)
    # inflate BHP-zero entries to make them effectively ignored
    sigma_rates[zero_bhp] = 1.0e6
    C_dd_rates = np.diag(sigma_rates ** 2)

    sigma_cum = _build_diag_sigma(d_obs_cum, cum_index)
    C_dd_cum = np.diag(sigma_cum ** 2)
    if C_dd_rates.size:        # empty when rate_index is empty (cumulative-only loop)
        log.info(f"  C_dd_rates condition: {np.diag(C_dd_rates).max() / max(np.diag(C_dd_rates).min(), 1e-30):.2e}")
    if C_dd_cum.size:
        log.info(f"  C_dd_cum condition:   {np.diag(C_dd_cum).max() / max(np.diag(C_dd_cum).min(), 1e-30):.2e}")

    return ObservationData(
        d_obs_rates=d_obs_rates,
        d_obs_cum=d_obs_cum,
        C_dd_rates=C_dd_rates,
        C_dd_cum=C_dd_cum,
        rate_index=rate_index,
        cum_index=cum_index,
        time_steps=canonical_times,
        producer_wells=producer_wells,
        injector_wells=injector_wells,
        n_bhp_zero_dropped=n_bhp_zero_dropped,
        n_bhp_zero_inflated=n_bhp_zero_inflated,
    )

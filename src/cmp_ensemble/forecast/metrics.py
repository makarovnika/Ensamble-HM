"""Forecast metrics — Task 3.3.

Two-tier metrics:

  * truth-independent (always computed)
      - width_post / width_prior   per (metric, time)
      - median shift               P50_post − P50_prior
      - n_in_envelope              how many ensemble members lie in [P10, P90]
      - per-cluster median forecast

  * truth-dependent (computed only if d_truth is supplied)
      - coverage_p10p90            fraction of truth observations in [P10, P90]
      - CRPS                       per timestep, averaged
      - cumulative_error           |∫d_pred − ∫d_truth| / ∫d_truth
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass
class ForecastMetrics:
    """All metrics produced for one setup."""

    width_ratio_table: pd.DataFrame              # per (metric, time)
    median_shift_table: pd.DataFrame             # per (metric, time)
    summary_per_metric: pd.DataFrame             # aggregate per metric

    coverage_p10p90: float | None = None
    crps_table: pd.DataFrame | None = None
    cumulative_error_table: pd.DataFrame | None = None


def width_ratio(
    d_post: np.ndarray,
    d_prior: np.ndarray,
) -> np.ndarray:
    """Per-column ratio (P90 − P10)_post / (P90 − P10)_prior."""
    p10_post, p90_post = np.nanquantile(d_post, [0.1, 0.9], axis=0)
    p10_pri, p90_pri = np.nanquantile(d_prior, [0.1, 0.9], axis=0)
    w_post = p90_post - p10_post
    w_prior = p90_pri - p10_pri
    safe = np.where(np.abs(w_prior) > 0, w_prior, 1.0)
    return w_post / safe


def median_shift(
    d_post: np.ndarray,
    d_prior: np.ndarray,
) -> np.ndarray:
    """Per-column P50_post − P50_prior."""
    return np.nanmedian(d_post, axis=0) - np.nanmedian(d_prior, axis=0)


def crps_per_column(
    d_forecast: np.ndarray,    # (M, n_d)
    d_truth: np.ndarray,       # (n_d,)
) -> np.ndarray:
    """Empirical CRPS estimator (Hersbach 2000 form) per column.

    CRPS(F, y) ≈ E|X − y| − 0.5 · E|X − X'|
    where X, X' are iid samples from F.
    """
    M, n_d = d_forecast.shape
    out = np.zeros(n_d)
    for j in range(n_d):
        x = d_forecast[:, j]
        y = float(d_truth[j])
        term1 = float(np.abs(x - y).mean())
        # 0.5 * mean |x_i - x_j| over all pairs i,j (including i=j adds 0).
        # Vectorised via sort: 2 * sum((2k - M - 1) * x_sorted[k]) / M²
        xs = np.sort(x)
        k = np.arange(1, M + 1)
        term2 = float((2 * k - M - 1).dot(xs) / (M * M))
        out[j] = term1 - 0.5 * term2
    return out


def coverage_p10p90_from(
    d_forecast: np.ndarray,
    d_truth: np.ndarray,
) -> float:
    """Fraction of truth entries that fall between P10 and P90 of forecast."""
    p10, p90 = np.nanquantile(d_forecast, [0.1, 0.9], axis=0)
    inside = (d_truth >= p10) & (d_truth <= p90)
    return float(inside.mean())


def compute_metrics(
    d_post: np.ndarray,
    d_prior: np.ndarray,
    index: list[tuple[str, str, datetime]],
    *,
    d_truth: np.ndarray | None = None,
) -> ForecastMetrics:
    """One-shot computation of all forecast metrics for a setup.

    `index` is the (metric, well, time) index aligning with the columns of
    `d_post` and `d_prior`. `d_truth` is optional; if None, truth-dependent
    metrics are returned as None.
    """
    wr = width_ratio(d_post, d_prior)
    ms = median_shift(d_post, d_prior)

    idx_df = pd.DataFrame(index, columns=["metric", "well", "time"])
    idx_df["pos"] = np.arange(len(index))

    # width ratio + median shift collapsed per (metric, time): mean across wells
    wr_rows = []
    ms_rows = []
    for (metric, time), g in idx_df.groupby(["metric", "time"]):
        cols = g["pos"].to_numpy()
        wr_rows.append(
            {"metric": metric, "time": pd.Timestamp(time).date(),
             "mean_width_ratio": float(np.nanmean(wr[cols]))}
        )
        ms_rows.append(
            {"metric": metric, "time": pd.Timestamp(time).date(),
             "mean_median_shift": float(np.nanmean(ms[cols]))}
        )
    wr_df = pd.DataFrame(wr_rows).sort_values(["metric", "time"]).reset_index(drop=True)
    ms_df = pd.DataFrame(ms_rows).sort_values(["metric", "time"]).reset_index(drop=True)

    summary_per_metric_rows = []
    for metric in idx_df["metric"].unique():
        wr_metric = wr_df[wr_df["metric"] == metric]["mean_width_ratio"]
        ms_metric = ms_df[ms_df["metric"] == metric]["mean_median_shift"]
        summary_per_metric_rows.append(
            {
                "metric": metric,
                "mean_width_ratio": float(wr_metric.mean()),
                "median_width_ratio": float(wr_metric.median()),
                "mean_median_shift": float(ms_metric.mean()),
            }
        )
    summary_per_metric = pd.DataFrame(summary_per_metric_rows)

    coverage = None
    crps_df = None
    cum_err_df = None
    if d_truth is not None:
        coverage = coverage_p10p90_from(d_post, d_truth)
        crps_vals = crps_per_column(d_post, d_truth)
        rows = []
        for (metric, time), g in idx_df.groupby(["metric", "time"]):
            cols = g["pos"].to_numpy()
            rows.append(
                {"metric": metric, "time": pd.Timestamp(time).date(),
                 "mean_crps": float(np.nanmean(crps_vals[cols]))}
            )
        crps_df = pd.DataFrame(rows).sort_values(["metric", "time"]).reset_index(drop=True)
        # cumulative error: integrate (mean post) and truth over the time axis
        cum_rows = []
        for metric in idx_df["metric"].unique():
            mask = idx_df["metric"] == metric
            pred = np.nanmedian(d_post[:, mask], axis=0)
            truth = d_truth[mask.to_numpy()]
            denom = np.abs(np.trapezoid(truth)) if np.trapezoid(truth) != 0 else 1.0
            rel = float(np.abs(np.trapezoid(pred) - np.trapezoid(truth)) / denom)
            cum_rows.append({"metric": metric, "cumulative_error": rel})
        cum_err_df = pd.DataFrame(cum_rows)

    return ForecastMetrics(
        width_ratio_table=wr_df,
        median_shift_table=ms_df,
        summary_per_metric=summary_per_metric,
        coverage_p10p90=coverage,
        crps_table=crps_df,
        cumulative_error_table=cum_err_df,
    )

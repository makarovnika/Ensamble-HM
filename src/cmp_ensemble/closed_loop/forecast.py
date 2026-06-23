"""Closed-loop forecast + metrics (CL-F, TZ_closed_loop_ESMDA.md section 9).

After ES-MDA produces the posterior ensemble Theta_post, we forecast the
post-2018 window (2019-01 .. 2024-10) for BOTH the prior and the posterior and
compare their P10/P50/P90 corridors. The forecast forward is the same
ForwardModel abstraction used by the loop: in production a TNavForward reading
WOPT/WWPT/WGPT on forecast anchors, in tests a LinearGaussianForward.

Metrics (reused from forecast.metrics): width_ratio (corridor narrowing),
median_shift (P50 move), and -- only if a forecast truth is supplied --
coverage_p10p90 / CRPS. For this dataset the forecast truth is principally
unavailable (history ends 2018-12), so width_ratio / median_shift are the
acceptance metrics, exactly as in the post-hoc experiment.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from cmp_ensemble.forecast.aggregation import field_total_quantiles
from cmp_ensemble.forecast.metrics import ForecastMetrics, compute_metrics

log = logging.getLogger(__name__)


@dataclass
class ClosedLoopForecast:
    d_prior_fc: np.ndarray                       # (N, n_d) prior-ensemble forecast
    d_post_fc: np.ndarray                        # (N, n_d) posterior-ensemble forecast
    index: list                                  # (metric, well, time) per column
    prior_quantiles: pd.DataFrame                # field-total P10/P50/P90
    post_quantiles: pd.DataFrame
    metrics: ForecastMetrics


def run_forecast(Theta: np.ndarray, forecast_forward) -> np.ndarray:
    """Map an ensemble through the forecast forward -> (N, n_d) forecast d."""
    return np.asarray(forecast_forward(Theta), dtype=float)


def summarize_forecast(
    d_prior_fc: np.ndarray,
    d_post_fc: np.ndarray,
    index: list,
    *,
    d_truth: np.ndarray | None = None,
    quantiles=(0.1, 0.5, 0.9),
) -> ClosedLoopForecast:
    """Field-total corridors (prior vs posterior) + comparison metrics."""
    prior_q = field_total_quantiles(d_prior_fc, index, quantiles=list(quantiles))
    post_q = field_total_quantiles(d_post_fc, index, quantiles=list(quantiles))
    metrics = compute_metrics(d_post_fc, d_prior_fc, index, d_truth=d_truth)
    log.info("forecast summarized: prior/post corridors over %d (metric,time) rows",
             len(post_q))
    return ClosedLoopForecast(
        d_prior_fc=d_prior_fc, d_post_fc=d_post_fc, index=list(index),
        prior_quantiles=prior_q, post_quantiles=post_q, metrics=metrics,
    )


def write_forecast_artifacts(fc: ClosedLoopForecast, out_dir: str | Path) -> dict:
    """Persist forecast corridors + metrics under out_dir/forecast/."""
    out = Path(out_dir) / "forecast"
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    fc.prior_quantiles.to_csv(out / "prior_corridor.csv", index=False, encoding="utf-8")
    fc.post_quantiles.to_csv(out / "post_corridor.csv", index=False, encoding="utf-8")
    paths["prior_corridor"] = out / "prior_corridor.csv"
    paths["post_corridor"] = out / "post_corridor.csv"
    fc.metrics.summary_per_metric.to_csv(
        out / "metrics_summary.csv", index=False, encoding="utf-8")
    paths["metrics_summary"] = out / "metrics_summary.csv"
    fc.metrics.width_ratio_table.to_csv(
        out / "width_ratio.csv", index=False, encoding="utf-8")
    fc.metrics.median_shift_table.to_csv(
        out / "median_shift.csv", index=False, encoding="utf-8")
    np.save(out / "d_prior_fc.npy", fc.d_prior_fc)
    np.save(out / "d_post_fc.npy", fc.d_post_fc)
    log.info("forecast artifacts written to %s", out)
    return paths


def compare_to_posthoc(
    closed_loop_metrics: pd.DataFrame,
    posthoc_metrics_csv: str | Path,
) -> pd.DataFrame:
    """Side-by-side width_ratio/median_shift: closed-loop vs the post-hoc setups.

    Returns a tidy comparison frame; the post-hoc CSV is the existing
    outputs/forecast/metrics_summary.csv. Missing file -> closed-loop only.
    """
    cl = closed_loop_metrics.copy()
    cl["source"] = "closed_loop_esmda"
    ph_path = Path(posthoc_metrics_csv)
    if not ph_path.exists():
        log.warning("post-hoc metrics not found at %s -- closed-loop only", ph_path)
        return cl
    ph = pd.read_csv(ph_path)
    ph["source"] = "post_hoc_" + ph.get("setup", pd.Series(["?"] * len(ph))).astype(str)
    common = [c for c in cl.columns if c in ph.columns]
    return pd.concat([cl[common], ph[common]], ignore_index=True)

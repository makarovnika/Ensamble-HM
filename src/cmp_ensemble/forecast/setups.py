"""Three setup orchestrator for the ablation study — Task 3.5.

The three setups defined in ТЗ §6 Task 3.1 are realized here as concrete
prediction matrices on a shared (metric, well, time) index:

  setup1_naive       — baseline forecast from the existing 123 tNavigator
                       runs in decoded_results.xlsx (no ES post-processing).

  setup2_localized   — proxy-projected forecast: for each ES-updated θ_post,
                       predict d_forecast via the per-cluster linear proxy.
                       Skips members flagged out-of-envelope (predictions
                       become unreliable extrapolations).

  setup3_full        — would add control uncertainty on top of setup2.
                       The required workflow_params.csv is absent for this
                       dataset, so setup3 degrades to a copy of setup2 with
                       a recorded warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from cmp_ensemble.forecast.aggregation import (
    field_total_quantiles,
    per_well_quantiles,
)
from cmp_ensemble.forecast.metrics import ForecastMetrics, compute_metrics

log = logging.getLogger(__name__)


@dataclass
class SetupResult:
    label: str
    description: str
    d_forecast: np.ndarray                       # (M, n_d)
    index: list[tuple[str, str, datetime]]
    cluster_ids: np.ndarray                      # (M,)
    metrics: ForecastMetrics
    notes: list[str]


def run_setup1_naive(
    d_baseline: np.ndarray,
    index: list[tuple[str, str, datetime]],
    cluster_ids: np.ndarray,
    d_truth: np.ndarray | None = None,
) -> SetupResult:
    """Baseline = identity. d_post == d_prior, so width_ratio == 1 etc."""
    metrics = compute_metrics(d_baseline, d_baseline, index, d_truth=d_truth)
    return SetupResult(
        label="setup1_naive",
        description="Baseline forecast — 123 tNavigator runs as-is, no ES post-processing.",
        d_forecast=d_baseline,
        index=index,
        cluster_ids=cluster_ids,
        metrics=metrics,
        notes=[],
    )


def run_setup2_localized(
    d_baseline: np.ndarray,
    d_proxy_post: np.ndarray,
    index: list[tuple[str, str, datetime]],
    cluster_ids_baseline: np.ndarray,
    cluster_ids_proxy: np.ndarray,
    out_of_envelope: np.ndarray,
    d_truth: np.ndarray | None = None,
    keep_out_of_envelope: bool = False,
) -> SetupResult:
    """Apply proxy-projected forecasts.

    By default rows flagged as out-of-envelope are dropped to avoid noisy
    extrapolation. Pass `keep_out_of_envelope=True` to retain them.
    """
    if keep_out_of_envelope:
        d_post = d_proxy_post
        clusters_post = cluster_ids_proxy
        notes = [f"kept all {d_proxy_post.shape[0]} proxy predictions including {int(out_of_envelope.sum())} extrapolations"]
    else:
        keep = ~out_of_envelope
        d_post = d_proxy_post[keep]
        clusters_post = cluster_ids_proxy[keep]
        notes = [
            f"dropped {int(out_of_envelope.sum())} of {d_proxy_post.shape[0]} "
            f"proxy predictions flagged out-of-envelope (extrapolation)"
        ]

    # Width ratio is post vs baseline (the meaningful comparison)
    metrics = compute_metrics(d_post, d_baseline, index, d_truth=d_truth)
    return SetupResult(
        label="setup2_localized",
        description="ES + adaptive correlation-based localization, forecast via per-cluster linear proxy.",
        d_forecast=d_post,
        index=index,
        cluster_ids=clusters_post,
        metrics=metrics,
        notes=notes,
    )


def run_setup3_full(
    d_baseline: np.ndarray,
    d_proxy_post: np.ndarray,
    index: list[tuple[str, str, datetime]],
    cluster_ids_baseline: np.ndarray,
    cluster_ids_proxy: np.ndarray,
    out_of_envelope: np.ndarray,
    d_truth: np.ndarray | None = None,
    controls_available: bool = False,
    keep_out_of_envelope: bool = False,
) -> SetupResult:
    """Full ablation: ES + localization + control uncertainty.

    `controls_available=False` for this study because the workflow_params.csv
    is absent. The function then degrades to setup2's predictions with a
    recorded note, so the ablation table can still publish a setup3 row.
    """
    base = run_setup2_localized(
        d_baseline=d_baseline,
        d_proxy_post=d_proxy_post,
        index=index,
        cluster_ids_baseline=cluster_ids_baseline,
        cluster_ids_proxy=cluster_ids_proxy,
        out_of_envelope=out_of_envelope,
        d_truth=d_truth,
        keep_out_of_envelope=keep_out_of_envelope,
    )
    if not controls_available:
        notes = [
            "Workflow controls (workflow_params.csv) absent from dataset — "
            "setup3 degenerates to setup2 (no control uncertainty applied).",
            *base.notes,
        ]
    else:
        notes = ["Control uncertainty applied. (TODO)", *base.notes]
    return SetupResult(
        label="setup3_full",
        description="Full setup: ES + localization + control uncertainty. Degenerates to setup2 if controls are unavailable.",
        d_forecast=base.d_forecast,
        index=base.index,
        cluster_ids=base.cluster_ids,
        metrics=base.metrics,
        notes=notes,
    )


def build_metrics_summary(results: list[SetupResult]) -> "pd.DataFrame":
    """Cross-setup summary table."""
    import pandas as pd

    rows = []
    for r in results:
        m = r.metrics
        coverage = m.coverage_p10p90 if m.coverage_p10p90 is not None else float("nan")
        for _, sr in m.summary_per_metric.iterrows():
            rows.append(
                {
                    "setup": r.label,
                    "phase": sr["metric"],
                    "M_members": int(r.d_forecast.shape[0]),
                    "mean_width_ratio": float(sr["mean_width_ratio"]),
                    "median_width_ratio": float(sr["median_width_ratio"]),
                    "mean_median_shift": float(sr["mean_median_shift"]),
                    "coverage_p10p90": coverage,
                }
            )
    return pd.DataFrame(rows)

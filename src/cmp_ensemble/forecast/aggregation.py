"""Ensemble forecast aggregation — Task 3.2.

Given an (M, n_d) matrix of per-model forecast values indexed by
``(metric, well, time)``, compute:

  * per-(metric, well, time) quantiles across the ensemble (the basic P10/P50/P90)
  * field-total aggregation: sum across wells per model, then quantile across
    models (so the field-level P10/P50/P90 reflects within-model coherence,
    not the sum of per-well quantiles)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass
class ForecastQuantiles:
    """Per (metric, well, time) quantiles across the ensemble."""

    quantiles: list[float]               # e.g. [0.1, 0.5, 0.9]
    values: np.ndarray                   # (len(quantiles), n_d)
    index: list[tuple[str, str, datetime]]  # (metric, well, time)


def aggregate_forecast(
    d_forecast: np.ndarray,
    index: list[tuple[str, str, datetime]],
    *,
    quantiles: list[float] = (0.1, 0.5, 0.9),
) -> ForecastQuantiles:
    """Quantile of each column of d_forecast across the ensemble.

    `d_forecast` shape (M, n_d). For each j in [0, n_d), compute
    ``np.nanquantile(d_forecast[:, j], q)`` for every q in `quantiles`.
    """
    q = np.asarray(quantiles, dtype=float)
    vals = np.nanquantile(d_forecast, q, axis=0)  # (len(q), n_d)
    return ForecastQuantiles(
        quantiles=list(q),
        values=vals,
        index=list(index),
    )


def field_total_quantiles(
    d_forecast: np.ndarray,
    index: list[tuple[str, str, datetime]],
    *,
    quantiles: list[float] = (0.1, 0.5, 0.9),
) -> pd.DataFrame:
    """Field-total time series: per (metric, time), sum across wells per model,
    then quantile across models.

    Returns a long-format DataFrame with columns
    ``[metric, time, p10, p50, p90, mean]``.
    """
    df = pd.DataFrame(index, columns=["metric", "well", "time"])
    df["pos"] = np.arange(len(index))
    rows = []
    q = np.asarray(quantiles, dtype=float)
    for (metric, time), g in df.groupby(["metric", "time"]):
        cols = g["pos"].to_numpy()
        # Sum across wells per model → (M,)
        per_model = d_forecast[:, cols].sum(axis=1)
        per_q = np.nanquantile(per_model, q)
        row = {
            "metric": metric,
            "time": pd.Timestamp(time).date(),
            "mean": float(per_model.mean()),
            "std": float(per_model.std(ddof=1)),
        }
        for qi, name in zip(per_q, [f"p{int(round(qq*100))}" for qq in q]):
            row[name] = float(qi)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["metric", "time"]).reset_index(drop=True)


def per_well_quantiles(
    d_forecast: np.ndarray,
    index: list[tuple[str, str, datetime]],
    *,
    quantiles: list[float] = (0.1, 0.5, 0.9),
) -> pd.DataFrame:
    """One row per (metric, well, time) with quantile values across the ensemble."""
    fq = aggregate_forecast(d_forecast, index, quantiles=quantiles)
    rows = []
    qnames = [f"p{int(round(q*100))}" for q in fq.quantiles]
    for k, (metric, well, t) in enumerate(fq.index):
        row = {"metric": metric, "well": well, "time": pd.Timestamp(t).date()}
        for j, name in enumerate(qnames):
            row[name] = float(fq.values[j, k])
        row["mean"] = float(d_forecast[:, k].mean())
        row["std"] = float(d_forecast[:, k].std(ddof=1))
        rows.append(row)
    return pd.DataFrame(rows)

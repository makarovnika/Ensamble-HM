"""Proxy validation — Task 2.4.

Holds out a small subset (default 10–15% of training members), retrains the
proxy on the rest, then compares proxy predictions vs ground-truth forecast on
the held-out set. Reports per-cluster and aggregate relative error metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from cmp_ensemble.selection.linear_proxy import build_linear_proxy

log = logging.getLogger(__name__)


@dataclass
class ProxyValidationResult:
    per_cluster: pd.DataFrame    # cluster, n_train, n_val, median_rel_err, mean_rel_err, max_rel_err
    aggregate: pd.Series         # median_rel_err, mean_rel_err, max_rel_err
    val_predictions: pd.DataFrame
    verdict: str                 # PASS / WARN / FAIL


def _stratified_split(
    cluster_ids: np.ndarray,
    val_fraction: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Pick a stratified validation subset (~equal fraction per cluster)."""
    rng = np.random.default_rng(seed)
    val_idx_list = []
    for cl in sorted({int(c) for c in cluster_ids.tolist()}):
        cl_idx = np.where(cluster_ids == cl)[0]
        n_val_cl = max(1, int(round(len(cl_idx) * val_fraction)))
        choice = rng.choice(cl_idx, size=n_val_cl, replace=False)
        val_idx_list.append(np.sort(choice))
    val_idx = np.concatenate(val_idx_list)
    all_idx = np.arange(cluster_ids.size)
    train_idx = np.setdiff1d(all_idx, val_idx)
    return train_idx, val_idx


def _relative_error(d_pred: np.ndarray, d_true: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """|d_pred - d_true| / sigma element-wise, with σ at least 1."""
    s = np.where(sigma > 1.0, sigma, 1.0)
    return np.abs(d_pred - d_true) / s


def validate_proxy(
    Z: np.ndarray,
    D: np.ndarray,
    cluster_ids: np.ndarray,
    *,
    val_fraction: float = 0.12,
    seed: int = 42,
    ridge: float = 1.0e-8,
) -> ProxyValidationResult:
    """Stratified hold-out validation of the per-cluster linear proxy."""
    train_idx, val_idx = _stratified_split(cluster_ids, val_fraction, seed)
    log.info(
        f"proxy validation: train={train_idx.size}, val={val_idx.size} "
        f"(seed={seed}, val_fraction={val_fraction})"
    )

    rows: list[dict] = []
    pred_rows: list[dict] = []
    aggregate_errors: list[float] = []
    for cl in sorted({int(c) for c in cluster_ids.tolist()}):
        train_cl = train_idx[cluster_ids[train_idx] == cl]
        val_cl = val_idx[cluster_ids[val_idx] == cl]
        if train_cl.size < 2 or val_cl.size == 0:
            log.warning(f"  cluster {cl}: insufficient train/val members — skip")
            continue
        proxy = build_linear_proxy(Z[train_cl], D[train_cl], cluster_id=cl, ridge=ridge)
        d_pred = proxy.predict(Z[val_cl])
        d_true = D[val_cl]
        sigma = D[train_cl].std(axis=0, ddof=1)
        rel_err = _relative_error(d_pred, d_true, sigma)
        # one number per member: median across the n_d_forecast components
        per_member = np.median(rel_err, axis=1)
        rows.append(
            {
                "cluster": cl,
                "n_train": int(train_cl.size),
                "n_val": int(val_cl.size),
                "median_rel_err": float(np.median(per_member)),
                "mean_rel_err": float(per_member.mean()),
                "max_rel_err": float(per_member.max()),
            }
        )
        aggregate_errors.extend(per_member.tolist())
        for j, vi in enumerate(val_cl):
            pred_rows.append(
                {
                    "cluster": cl,
                    "member_index": int(vi),
                    "median_rel_err": float(per_member[j]),
                }
            )

    per_cluster = pd.DataFrame(rows)
    aggregate = pd.Series(
        {
            "median_rel_err": float(np.median(aggregate_errors)),
            "mean_rel_err": float(np.mean(aggregate_errors)),
            "max_rel_err": float(np.max(aggregate_errors)),
        }
    )
    if aggregate["median_rel_err"] < 1.0:
        verdict = "PASS"
    elif aggregate["median_rel_err"] < 2.0:
        verdict = "WARN"
    else:
        verdict = "FAIL"
    log.info(
        f"proxy verdict: {verdict}  median={aggregate['median_rel_err']:.3f}, "
        f"mean={aggregate['mean_rel_err']:.3f}, max={aggregate['max_rel_err']:.3f}"
    )
    return ProxyValidationResult(
        per_cluster=per_cluster,
        aggregate=aggregate,
        val_predictions=pd.DataFrame(pred_rows),
        verdict=verdict,
    )

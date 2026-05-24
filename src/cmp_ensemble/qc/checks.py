"""QC checks for the ES update (Task 1.3).

Per ТЗ §6 Task 1.3 thresholds:
  - spread_retention < 0.1 for any component → ERROR (ensemble collapse)
  - spread_retention > 1.5 for the majority of components → WARNING (blew up)
  - rank_post < N - 1 → WARNING (loss of independence)
  - bimodality_score > 0.3 on the Mahalanobis migration distribution → INFO
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

Level = Literal["INFO", "WARNING", "ERROR"]


@dataclass
class QCReport:
    spread_retention: pd.DataFrame              # per-component std_post/std_prior
    rank_prior: int
    rank_post: int
    n_collapse_components: int
    n_blowup_components: int
    mahalanobis_migration: np.ndarray            # (N,)
    bimodality_score: float
    cluster_centroid_shift: pd.DataFrame         # per cluster × per component
    messages: list[tuple[Level, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(level == "ERROR" for level, _ in self.messages)

    @property
    def warnings(self) -> list[str]:
        return [m for lvl, m in self.messages if lvl == "WARNING"]


def _matrix_rank(X: np.ndarray, tol: float | None = None) -> int:
    """Numerical rank via SVD with default Numpy threshold."""
    s = np.linalg.svd(X, compute_uv=False)
    if tol is None:
        tol = s.max() * max(X.shape) * np.finfo(s.dtype).eps
    return int((s > tol).sum())


def _bimodality_coefficient(x: np.ndarray) -> float:
    """SAS-style bimodality coefficient based on skew and kurtosis.

        BC = (g₁² + 1) / (g₂ + 3 (n-1)² / ((n-2)(n-3)))

    BC > 5/9 ≈ 0.555 suggests bimodality. For the ТЗ threshold (>0.3) we
    keep this scale.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n < 4:
        return 0.0
    mu = x.mean()
    sd = x.std(ddof=1)
    if sd <= 0:
        return 0.0
    z = (x - mu) / sd
    g1 = (z**3).mean()
    g2 = (z**4).mean() - 3.0
    denom = g2 + 3.0 * ((n - 1) ** 2) / ((n - 2) * (n - 3))
    if denom <= 0:
        return 0.0
    return float((g1**2 + 1.0) / denom)


def _mahalanobis_migration(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    C_zz_prior: np.ndarray | None = None,
) -> np.ndarray:
    """Per-member Mahalanobis distance ‖Δz‖_M from the prior covariance."""
    if C_zz_prior is None:
        Zp = Z_prior - Z_prior.mean(axis=0, keepdims=True)
        C_zz_prior = Zp.T @ Zp / max(Z_prior.shape[0] - 1, 1)
    n_z = Z_prior.shape[1]
    C_zz = C_zz_prior + 1.0e-12 * np.eye(n_z)
    inv = np.linalg.pinv(C_zz)
    dz = Z_post - Z_prior                       # (N, n_z)
    return np.sqrt(np.einsum("ij,jk,ik->i", dz, inv, dz))


def run_qc_checks(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    cluster_ids: np.ndarray,
    theta_names: list[str],
    *,
    collapse_threshold: float = 0.1,
    blowup_threshold: float = 1.5,
    bimodality_threshold: float = 0.3,
) -> QCReport:
    """Run the full QC sweep on a pair of prior / posterior ensembles."""
    N, n_z = Z_prior.shape
    sigma_prior = Z_prior.std(axis=0, ddof=1)
    sigma_post = Z_post.std(axis=0, ddof=1)
    # Avoid division by zero
    safe_prior = np.where(sigma_prior > 0, sigma_prior, 1.0e-300)
    ratio = sigma_post / safe_prior

    spread = pd.DataFrame(
        {
            "component": theta_names,
            "sigma_prior": sigma_prior,
            "sigma_post": sigma_post,
            "spread_retention": ratio,
        }
    )

    n_collapse = int((ratio < collapse_threshold).sum())
    n_blowup = int((ratio > blowup_threshold).sum())

    rank_prior = _matrix_rank(Z_prior - Z_prior.mean(axis=0, keepdims=True))
    rank_post = _matrix_rank(Z_post - Z_post.mean(axis=0, keepdims=True))

    maha = _mahalanobis_migration(Z_prior, Z_post)
    bc = _bimodality_coefficient(maha)

    # Cluster-wise centroid shift
    centroid_rows = []
    for cl in sorted(set(int(c) for c in cluster_ids.tolist())):
        idx = cluster_ids == cl
        if idx.sum() == 0:
            continue
        prior_centroid = Z_prior[idx].mean(axis=0)
        post_centroid = Z_post[idx].mean(axis=0)
        for j, name in enumerate(theta_names):
            centroid_rows.append(
                {
                    "cluster": cl,
                    "component": name,
                    "prior_centroid": float(prior_centroid[j]),
                    "post_centroid": float(post_centroid[j]),
                    "abs_shift": float(post_centroid[j] - prior_centroid[j]),
                    "shift_in_prior_sigma": float(
                        (post_centroid[j] - prior_centroid[j]) / safe_prior[j]
                    ),
                }
            )
    centroid_df = pd.DataFrame(centroid_rows)

    msgs: list[tuple[Level, str]] = []
    if n_collapse > 0:
        bad = spread[ratio < collapse_threshold]["component"].tolist()
        msgs.append(
            ("ERROR",
             f"ensemble collapse: spread_retention < {collapse_threshold} for "
             f"{n_collapse} component(s): {bad}")
        )
    if n_blowup > n_z / 2:
        msgs.append(
            ("WARNING",
             f"ensemble blow-up: spread_retention > {blowup_threshold} for "
             f"{n_blowup}/{n_z} components — ES update may not have converged")
        )
    max_possible_rank = min(N - 1, n_z)
    if rank_post < max_possible_rank:
        msgs.append(
            ("WARNING",
             f"rank loss: rank(Z_post) = {rank_post} < "
             f"min(N-1, n_z) = {max_possible_rank}")
        )
    if bc > bimodality_threshold:
        msgs.append(
            ("INFO",
             f"Mahalanobis migration is bimodal (BC = {bc:.3f} > "
             f"{bimodality_threshold}) — inspect cluster-3 diagnostic")
        )

    for level, m in msgs:
        getattr(log, level.lower())(m)

    return QCReport(
        spread_retention=spread,
        rank_prior=rank_prior,
        rank_post=rank_post,
        n_collapse_components=n_collapse,
        n_blowup_components=n_blowup,
        mahalanobis_migration=maha,
        bimodality_score=bc,
        cluster_centroid_shift=centroid_df,
        messages=msgs,
    )


def write_qc_report_csvs(report: QCReport, out_dir) -> dict[str, "str"]:
    """Persist the QC tables under `out_dir` as CSV files; return a path map."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    p_spread = out / "spread_retention.csv"
    report.spread_retention.to_csv(p_spread, index=False, encoding="utf-8")
    paths["spread_retention"] = str(p_spread)

    p_maha = out / "mahalanobis_migration.csv"
    pd.DataFrame(
        {"member": np.arange(report.mahalanobis_migration.size),
         "maha": report.mahalanobis_migration}
    ).to_csv(p_maha, index=False, encoding="utf-8")
    paths["mahalanobis_migration"] = str(p_maha)

    p_cent = out / "cluster_centroid_shift.csv"
    report.cluster_centroid_shift.to_csv(p_cent, index=False, encoding="utf-8")
    paths["cluster_centroid_shift"] = str(p_cent)

    p_summary = out / "rank_check.json"
    import json

    p_summary.write_text(
        json.dumps(
            {
                "rank_prior": report.rank_prior,
                "rank_post": report.rank_post,
                "n_collapse_components": report.n_collapse_components,
                "n_blowup_components": report.n_blowup_components,
                "bimodality_score": report.bimodality_score,
                "passed": report.passed,
                "messages": [{"level": lv, "text": tx} for lv, tx in report.messages],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["rank_check"] = str(p_summary)
    return paths

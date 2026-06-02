"""Deduplicate the ensemble: collapse multiple cluster rows of the same
underlying model_id into a single row, averaging θ_post across them.

Rationale
---------
The parameter manifest selects "top-50 models near each cluster centroid".
A geological model that sits between two centroids appears in two cluster
sheets. For such duplicates, θ_prior is identical, but after ES the two
copies pick up different ε perturbations and therefore drift apart by a
small amount of pure noise.

Averaging the duplicated copies removes that noise without changing the
non-duplicated members.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class DedupResult:
    Z_post_dedup: np.ndarray         # (M, n_z), M = unique model count
    Z_prior_dedup: np.ndarray        # (M, n_z)
    model_ids_dedup: np.ndarray      # (M,)
    primary_cluster_ids: np.ndarray  # (M,) — the FIRST cluster a model appeared in
    seeds_dedup: np.ndarray          # (M,)
    sheet_names_dedup: list[str]
    n_collapsed: int                 # how many input rows were collapsed


def deduplicate_ensemble(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    model_ids: np.ndarray,
    cluster_ids: np.ndarray,
    seeds: np.ndarray,
    sheet_names: list[str],
) -> DedupResult:
    """Average duplicated rows by model_id. Non-duplicates are passed through.

    The primary_cluster_id for a duplicated model is the cluster_id of its
    first appearance (lowest input index).
    """
    seen: dict[int, list[int]] = {}
    for i, mid in enumerate(model_ids.tolist()):
        seen.setdefault(int(mid), []).append(i)

    primary_rows: list[int] = []
    for mid, idx in seen.items():
        primary_rows.append(idx[0])
    primary_rows.sort()

    M = len(primary_rows)
    Z_post_out = np.zeros((M, Z_post.shape[1]), dtype=Z_post.dtype)
    Z_prior_out = np.zeros((M, Z_prior.shape[1]), dtype=Z_prior.dtype)
    model_ids_out = np.zeros(M, dtype=model_ids.dtype)
    cluster_ids_out = np.zeros(M, dtype=cluster_ids.dtype)
    seeds_out = np.zeros(M, dtype=seeds.dtype)
    sheets_out: list[str] = []
    n_collapsed = 0
    for k, primary_i in enumerate(primary_rows):
        mid = int(model_ids[primary_i])
        rows = seen[mid]
        Z_post_out[k] = Z_post[rows].mean(axis=0)
        Z_prior_out[k] = Z_prior[primary_i]
        model_ids_out[k] = mid
        cluster_ids_out[k] = cluster_ids[primary_i]
        seeds_out[k] = seeds[primary_i]
        sheets_out.append(sheet_names[primary_i])
        if len(rows) > 1:
            n_collapsed += len(rows) - 1
    log.info(
        f"deduplicate: {model_ids.size} input rows → {M} unique model_ids "
        f"(collapsed {n_collapsed} duplicate copies)"
    )
    return DedupResult(
        Z_post_dedup=Z_post_out,
        Z_prior_dedup=Z_prior_out,
        model_ids_dedup=model_ids_out,
        primary_cluster_ids=cluster_ids_out,
        seeds_dedup=seeds_out,
        sheet_names_dedup=sheets_out,
        n_collapsed=n_collapsed,
    )

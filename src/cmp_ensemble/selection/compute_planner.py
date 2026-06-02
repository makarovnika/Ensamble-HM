"""Compute-planner for Phase 2 (ТЗ §6 Task 2.3).

Given the Mahalanobis ranking of all 149 ensemble members, partition them into:

  * `models_to_resimulate.csv` — the top-X to re-simulate in tNavigator
    (default X=80 per `configs/default.yaml` → `selection.default_top_x`).
  * `models_proxy.csv` — the remaining (N - X) models that will rely on the
    linear proxy for their forecast.
  * `validation_subset.csv` — a stratified random subset of the proxy pool
    (default 10 members per `selection.proxy_validation_n`) earmarked for
    proxy validation.

The split is deterministic given a seed and re-runnable: same input ranking +
same seed → same three CSVs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class CompletePlan:
    """Result of `plan_resimulation` — three deterministic partitions."""

    to_resimulate: pd.DataFrame    # top-X by Mahalanobis
    proxy_only: pd.DataFrame       # the rest
    validation_subset: pd.DataFrame  # K stratified members of proxy_only

    @property
    def n_total(self) -> int:
        return len(self.to_resimulate) + len(self.proxy_only)


def _stratified_choice(
    ids: pd.DataFrame,
    n_target: int,
    cluster_column: str,
    seed: int,
) -> pd.DataFrame:
    """Pick `n_target` rows from `ids`, stratified by cluster as evenly as we can."""
    rng = np.random.default_rng(seed)
    clusters = sorted(ids[cluster_column].unique())
    per_cluster = max(1, n_target // len(clusters))
    remainder = max(0, n_target - per_cluster * len(clusters))
    chosen_idx: list[int] = []
    for cl in clusters:
        pool = ids[ids[cluster_column] == cl]
        take = min(len(pool), per_cluster + (1 if remainder > 0 else 0))
        if remainder > 0:
            remainder -= 1
        if take == 0:
            continue
        sample = rng.choice(pool.index.to_numpy(), size=take, replace=False)
        chosen_idx.extend(sample.tolist())
    out = ids.loc[sorted(chosen_idx)].copy()
    if len(out) > n_target:
        out = out.iloc[:n_target]
    return out


def plan_resimulation(
    ranking: pd.DataFrame,
    *,
    top_x: int = 80,
    validation_n: int = 10,
    seed: int = 42,
    cluster_column: str = "cluster_id",
) -> CompletePlan:
    """Partition the Mahalanobis-ranked ensemble.

    Parameters
    ----------
    ranking : pd.DataFrame
        Must contain a `rank` column (1-indexed, sorted ascending = highest
        priority first), a `model_id`, a `cluster_id`, a `seed`, and a
        `maha_distance` column. Typically loaded from
        `outputs/selection/mahalanobis_ranking.csv`.
    top_x : int
        How many models to mark for re-simulation. Default 80.
    validation_n : int
        How many proxy models to earmark for proxy validation. Default 10.
    seed : int
        RNG seed for the validation-subset draw. Default 42.

    Returns
    -------
    CompletePlan with three DataFrames.
    """
    if "rank" not in ranking.columns:
        raise ValueError("ranking DataFrame must have a 'rank' column")
    sorted_ranking = ranking.sort_values("rank").reset_index(drop=True)
    n = len(sorted_ranking)
    top_x = min(int(top_x), n)
    to_resim = sorted_ranking.iloc[:top_x].copy()
    proxy_only = sorted_ranking.iloc[top_x:].copy()
    validation_n = min(int(validation_n), len(proxy_only))
    if validation_n > 0:
        val = _stratified_choice(proxy_only, validation_n, cluster_column, seed)
    else:
        val = proxy_only.iloc[:0].copy()
    log.info(
        f"plan_resimulation: N={n}, top_x={top_x}, proxy={len(proxy_only)}, "
        f"validation_subset={len(val)} (seed={seed})"
    )
    return CompletePlan(
        to_resimulate=to_resim,
        proxy_only=proxy_only,
        validation_subset=val,
    )


def write_plan_to_csv(plan: CompletePlan, out_dir) -> dict[str, str]:
    """Write the three CSVs and return a path map."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    p_to = out / "models_to_resimulate.csv"
    plan.to_resimulate.to_csv(p_to, index=False, encoding="utf-8")
    paths["models_to_resimulate"] = str(p_to)

    p_pr = out / "models_proxy.csv"
    plan.proxy_only.to_csv(p_pr, index=False, encoding="utf-8")
    paths["models_proxy"] = str(p_pr)

    p_va = out / "validation_subset.csv"
    plan.validation_subset.to_csv(p_va, index=False, encoding="utf-8")
    paths["validation_subset"] = str(p_va)

    return paths

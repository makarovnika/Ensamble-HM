"""Unit tests for compute planner (ТЗ §6 Task 2.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.selection.compute_planner import (
    plan_resimulation,
    write_plan_to_csv,
)


def _make_ranking(n: int = 30, n_clusters: int = 3, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cluster_ids = rng.integers(0, n_clusters, size=n)
    return pd.DataFrame(
        {
            "rank": np.arange(1, n + 1),
            "model_id": np.arange(100, 100 + n),
            "cluster_id": cluster_ids,
            "seed": rng.integers(1000, 9999, size=n),
            "sheet": [f"sheet-{i}" for i in range(n)],
            "maha_distance": np.sort(rng.uniform(2.0, 4.0, size=n))[::-1],
        }
    )


def test_partition_is_disjoint_and_exhaustive() -> None:
    r = _make_ranking(n=30)
    plan = plan_resimulation(r, top_x=10, validation_n=3, seed=0)
    assert plan.n_total == 30
    assert len(plan.to_resimulate) == 10
    assert len(plan.proxy_only) == 20
    overlap = set(plan.to_resimulate["model_id"]) & set(plan.proxy_only["model_id"])
    assert overlap == set()


def test_top_x_takes_highest_priority_first() -> None:
    r = _make_ranking(n=20)
    plan = plan_resimulation(r, top_x=5, validation_n=2, seed=42)
    # The top_x rows should be ranks 1..5
    assert list(plan.to_resimulate["rank"]) == [1, 2, 3, 4, 5]
    assert plan.proxy_only["rank"].min() == 6


def test_validation_subset_drawn_from_proxy_only() -> None:
    r = _make_ranking(n=25)
    plan = plan_resimulation(r, top_x=10, validation_n=5, seed=0)
    val_ids = set(plan.validation_subset["model_id"])
    proxy_ids = set(plan.proxy_only["model_id"])
    resim_ids = set(plan.to_resimulate["model_id"])
    assert val_ids <= proxy_ids
    assert val_ids & resim_ids == set()


def test_validation_subset_is_stratified() -> None:
    """With validation_n large enough, every cluster should be represented."""
    r = _make_ranking(n=60, n_clusters=3, seed=1)
    plan = plan_resimulation(r, top_x=20, validation_n=9, seed=42)
    clusters_in_val = set(plan.validation_subset["cluster_id"].unique())
    # All 3 clusters present
    assert clusters_in_val == {0, 1, 2}


def test_top_x_larger_than_n_is_truncated() -> None:
    r = _make_ranking(n=10)
    plan = plan_resimulation(r, top_x=999, validation_n=0)
    assert len(plan.to_resimulate) == 10
    assert len(plan.proxy_only) == 0


def test_validation_n_zero_returns_empty_subset() -> None:
    r = _make_ranking(n=15)
    plan = plan_resimulation(r, top_x=5, validation_n=0)
    assert len(plan.validation_subset) == 0


def test_deterministic_given_seed() -> None:
    r = _make_ranking(n=30, seed=99)
    a = plan_resimulation(r, top_x=10, validation_n=5, seed=11)
    b = plan_resimulation(r, top_x=10, validation_n=5, seed=11)
    assert list(a.validation_subset["model_id"]) == list(b.validation_subset["model_id"])
    # Different seed → different subset (usually)
    c = plan_resimulation(r, top_x=10, validation_n=5, seed=22)
    assert list(a.validation_subset["model_id"]) != list(c.validation_subset["model_id"])


def test_missing_rank_column_raises() -> None:
    bad = pd.DataFrame({"model_id": [1, 2, 3]})
    with pytest.raises(ValueError, match="rank"):
        plan_resimulation(bad)


def test_write_csvs(tmp_path) -> None:
    r = _make_ranking(n=20)
    plan = plan_resimulation(r, top_x=8, validation_n=3, seed=42)
    paths = write_plan_to_csv(plan, tmp_path)
    assert (tmp_path / "models_to_resimulate.csv").exists()
    assert (tmp_path / "models_proxy.csv").exists()
    assert (tmp_path / "validation_subset.csv").exists()
    # Round-trip the values
    df_re = pd.read_csv(tmp_path / "models_to_resimulate.csv")
    assert len(df_re) == 8
    df_pr = pd.read_csv(tmp_path / "models_proxy.csv")
    assert len(df_pr) == 12
    df_va = pd.read_csv(tmp_path / "validation_subset.csv")
    assert len(df_va) == 3

"""ТЗ §9 mandated selection tests.

Consolidates the two specific requirements from the feature spec:

  * Mahalanobis ranking returns the largest ‖Δθ‖_M first.
  * `plan_resimulation` partitions IDs into (top-X, proxy_pool, validation)
    that are disjoint and exhaust the input ranking.

Per-module unit tests (test_phase2.py, test_compute_planner.py) cover the
same code paths with finer granularity; these are the ТЗ acceptance gates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.selection.compute_planner import plan_resimulation, write_plan_to_csv
from cmp_ensemble.selection.mahalanobis import (
    mahalanobis_distance,
    rank_by_parameter_change,
)


# ──────────────────────────────────────────────────────────────────────────
# Mahalanobis ranking: largest ‖Δθ‖_M first
# ──────────────────────────────────────────────────────────────────────────


def test_ranking_first_index_is_the_largest_movement() -> None:
    rng = np.random.default_rng(0)
    N, n_z = 50, 4
    Z_prior = rng.standard_normal((N, n_z))
    Z_post = Z_prior.copy()
    target = 17
    Z_post[target] += 100.0  # huge synthetic shift
    order = rank_by_parameter_change(Z_prior, Z_post)
    assert order[0] == target


def test_ranking_is_a_permutation_of_member_indices() -> None:
    rng = np.random.default_rng(1)
    Z_prior = rng.standard_normal((30, 5))
    Z_post = Z_prior + rng.standard_normal((30, 5))
    order = rank_by_parameter_change(Z_prior, Z_post)
    assert set(order.tolist()) == set(range(30))
    assert len(set(order.tolist())) == 30  # no repeats


def test_ranking_monotone_in_distance() -> None:
    """The distances at the returned indices must be non-increasing."""
    rng = np.random.default_rng(2)
    Z_prior = rng.standard_normal((40, 6))
    Z_post = Z_prior + rng.standard_normal((40, 6))
    d = mahalanobis_distance(Z_prior, Z_post)
    order = rank_by_parameter_change(Z_prior, Z_post)
    sorted_d = d[order]
    assert (sorted_d[:-1] >= sorted_d[1:]).all()


def test_zero_shift_has_zero_distance() -> None:
    Z = np.random.default_rng(3).standard_normal((10, 4))
    d = mahalanobis_distance(Z, Z.copy())
    assert np.allclose(d, 0.0)


# ──────────────────────────────────────────────────────────────────────────
# Compute planner: disjoint exhaustive partition
# ──────────────────────────────────────────────────────────────────────────


def _ranking_df(N: int = 30, n_clusters: int = 3, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "rank": np.arange(1, N + 1),
        "model_id": np.arange(100, 100 + N),
        "cluster_id": rng.integers(0, n_clusters, size=N),
        "seed": rng.integers(1000, 9999, size=N),
        "sheet": [f"sheet-{i}" for i in range(N)],
        "maha_distance": np.sort(rng.uniform(2.0, 4.0, size=N))[::-1],
    })


def test_planner_partition_is_disjoint() -> None:
    df = _ranking_df(N=50)
    plan = plan_resimulation(df, top_x=20, validation_n=5)
    resim_ids = set(plan.to_resimulate["model_id"])
    proxy_ids = set(plan.proxy_only["model_id"])
    assert resim_ids & proxy_ids == set()


def test_planner_partition_is_exhaustive() -> None:
    df = _ranking_df(N=50)
    plan = plan_resimulation(df, top_x=20, validation_n=5)
    all_ids = set(df["model_id"])
    partitioned = set(plan.to_resimulate["model_id"]) | set(plan.proxy_only["model_id"])
    assert partitioned == all_ids


def test_planner_top_x_contains_highest_priority_ranks() -> None:
    df = _ranking_df(N=30)
    plan = plan_resimulation(df, top_x=10, validation_n=3)
    assert sorted(plan.to_resimulate["rank"]) == list(range(1, 11))
    assert plan.proxy_only["rank"].min() == 11


def test_planner_validation_subset_subset_of_proxy() -> None:
    df = _ranking_df(N=40)
    plan = plan_resimulation(df, top_x=15, validation_n=8)
    val_ids = set(plan.validation_subset["model_id"])
    proxy_ids = set(plan.proxy_only["model_id"])
    assert val_ids <= proxy_ids
    # And not in the resimulate set
    assert val_ids & set(plan.to_resimulate["model_id"]) == set()


def test_planner_writes_three_csvs(tmp_path) -> None:
    df = _ranking_df(N=30)
    plan = plan_resimulation(df, top_x=10, validation_n=4)
    paths = write_plan_to_csv(plan, tmp_path)
    for name in ("models_to_resimulate", "models_proxy", "validation_subset"):
        assert name in paths
        assert tmp_path.joinpath(f"{name}.csv").exists()
    # Round-trip lengths
    assert len(pd.read_csv(tmp_path / "models_to_resimulate.csv")) == 10
    assert len(pd.read_csv(tmp_path / "models_proxy.csv")) == 20
    assert len(pd.read_csv(tmp_path / "validation_subset.csv")) == 4


def test_planner_invalid_input_rejected() -> None:
    bad = pd.DataFrame({"model_id": [1, 2, 3]})  # missing 'rank' column
    with pytest.raises(ValueError, match="rank"):
        plan_resimulation(bad)

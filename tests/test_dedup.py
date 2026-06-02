"""Tests for ensemble deduplication."""

from __future__ import annotations

import numpy as np

from cmp_ensemble.ensemble.dedup import deduplicate_ensemble


def test_no_duplicates_passthrough() -> None:
    Z_prior = np.arange(12.0).reshape(4, 3)
    Z_post = Z_prior + 1
    model_ids = np.array([10, 20, 30, 40])
    cluster_ids = np.array([0, 1, 2, 0])
    seeds = np.array([1, 2, 3, 4])
    sheet_names = ["a", "b", "c", "d"]
    out = deduplicate_ensemble(Z_prior, Z_post, model_ids, cluster_ids, seeds, sheet_names)
    assert out.n_collapsed == 0
    assert out.Z_post_dedup.shape == Z_post.shape


def test_duplicate_post_is_averaged() -> None:
    # model 10 appears in rows 0 and 2 with same prior, different post
    Z_prior = np.array([
        [1.0, 2.0],
        [9.0, 9.0],
        [1.0, 2.0],
    ])
    Z_post = np.array([
        [3.0, 4.0],   # row 0
        [9.5, 9.5],
        [5.0, 6.0],   # row 2 (duplicate of row 0)
    ])
    out = deduplicate_ensemble(
        Z_prior=Z_prior,
        Z_post=Z_post,
        model_ids=np.array([10, 20, 10]),
        cluster_ids=np.array([0, 1, 2]),
        seeds=np.array([100, 200, 100]),
        sheet_names=["s0", "s1", "s2"],
    )
    assert out.n_collapsed == 1
    assert out.Z_post_dedup.shape == (2, 2)
    # model 10's averaged post: ((3,4)+(5,6))/2 = (4,5)
    mid_10_idx = list(out.model_ids_dedup).index(10)
    assert np.allclose(out.Z_post_dedup[mid_10_idx], [4.0, 5.0])
    # primary cluster comes from first appearance
    assert out.primary_cluster_ids[mid_10_idx] == 0


def test_preserves_ordering_by_first_appearance() -> None:
    Z_prior = np.zeros((5, 1))
    Z_post = np.arange(5.0).reshape(-1, 1)
    out = deduplicate_ensemble(
        Z_prior=Z_prior,
        Z_post=Z_post,
        model_ids=np.array([10, 20, 30, 10, 40]),  # 10 duplicated at indices 0 and 3
        cluster_ids=np.array([0, 1, 2, 1, 2]),
        seeds=np.array([1, 2, 3, 1, 4]),
        sheet_names=["s0", "s1", "s2", "s3", "s4"],
    )
    assert list(out.model_ids_dedup) == [10, 20, 30, 40]
    # averaged post for model 10: (0+3)/2 = 1.5
    assert out.Z_post_dedup[0, 0] == 1.5

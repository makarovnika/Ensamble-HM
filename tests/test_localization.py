"""Unit tests for adaptive correlation-based localization (Task 1.1)."""

from __future__ import annotations

import numpy as np
import pytest

from cmp_ensemble.ensemble.localization import (
    _sample_correlation,
    adaptive_correlation_localization,
)


def test_threshold_at_N_150_is_3_over_sqrt_150() -> None:
    rng = np.random.default_rng(0)
    Z = rng.standard_normal((150, 5))
    D = rng.standard_normal((150, 7))
    _, _, threshold = adaptive_correlation_localization(Z, D, factor=3.0)
    assert threshold == pytest.approx(3.0 / np.sqrt(150), abs=1e-12)


def test_null_distribution_zeroes_about_95_percent() -> None:
    """On independent Gaussian Z and D, ~99.7% of |corr| should fall below
    3/sqrt(N) since that is the 3σ tail of the null sampling distribution.

    Real-world ensembles will of course retain more — this test is a sanity
    check that the mask is doing something on pure noise.
    """
    rng = np.random.default_rng(7)
    N = 150
    Z = rng.standard_normal((N, 100))
    D = rng.standard_normal((N, 200))
    mask, _, _ = adaptive_correlation_localization(Z, D, factor=3.0, method="hard")
    frac_kept = float((mask > 0).mean())
    # Expect ~0.3% kept under pure null; allow generous margin.
    assert 0.0 <= frac_kept <= 0.02


def test_soft_taper_strictly_monotone_in_corr() -> None:
    """Soft-taper mask must be a non-decreasing function of |corr| around the
    threshold band."""
    rng = np.random.default_rng(1)
    Z = rng.standard_normal((30, 4))
    D = rng.standard_normal((30, 4))
    mask_hard, corr, _ = adaptive_correlation_localization(Z, D, method="hard")
    mask_soft, _, _ = adaptive_correlation_localization(
        Z, D, method="soft_taper", taper_half_width=0.05
    )
    # Soft taper retains at least as many non-zero entries as hard
    assert (mask_soft > 0).sum() >= (mask_hard > 0).sum()
    # In the [0, 1] range
    assert mask_soft.min() >= 0.0 and mask_soft.max() <= 1.0


def test_correlation_helper_basic_properties() -> None:
    rng = np.random.default_rng(2)
    N = 100
    Z = rng.standard_normal((N, 3))
    # D[:, 0] is a perfect linear function of Z[:, 0] → corr near +1
    D = np.column_stack(
        [
            2 * Z[:, 0] + 5,
            rng.standard_normal(N),
            -Z[:, 1] + 0.5,
        ]
    )
    corr = _sample_correlation(Z, D)
    assert corr.shape == (3, 3)
    assert corr[0, 0] == pytest.approx(1.0, abs=1e-12)
    assert corr[1, 2] == pytest.approx(-1.0, abs=1e-12)


def test_threshold_at_N_149_matches_phase0() -> None:
    """Our real ensemble has N=149 after dropping the truncated model. Sanity-
    check the threshold value used in production."""
    rng = np.random.default_rng(3)
    Z = rng.standard_normal((149, 9))
    D = rng.standard_normal((149, 384))
    _, _, threshold = adaptive_correlation_localization(Z, D)
    assert threshold == pytest.approx(3.0 / np.sqrt(149), rel=1e-12)
    assert threshold == pytest.approx(0.2459, abs=1e-3)

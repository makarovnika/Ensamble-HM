"""ТЗ §9 mandated forecast-metric tests.

These complement `tests/test_forecast.py` with the specific analytical
references called out in ТЗ §9:

  * CRPS(δ_y, y) = 0
  * CRPS(Uniform[0, w], y ∈ [0, w]) → analytical formula
  * coverage on a known-truth distribution
  * width_ratio sanity bounds
"""

from __future__ import annotations

import numpy as np
import pytest

from cmp_ensemble.forecast.metrics import (
    coverage_p10p90_from,
    crps_per_column,
    median_shift,
    width_ratio,
)


# ──────────────────────────────────────────────────────────────────────────
# CRPS sanity references
# ──────────────────────────────────────────────────────────────────────────


def test_crps_delta_distribution_equals_absolute_error() -> None:
    """For a degenerate distribution (all members identical at x₀):

        CRPS(δ_x₀, y) = |x₀ − y|

    This is the strongest sanity check on the Hersbach (2000) estimator —
    if it fails the implementation is wrong.
    """
    M = 1_000
    x0 = 7.0
    d = np.full((M, 4), x0)
    truth = np.array([7.0, 7.5, 6.0, 10.0])
    crps = crps_per_column(d, truth)
    assert np.allclose(crps, np.abs(truth - x0), atol=1e-12)


def test_crps_uniform_distribution_analytical() -> None:
    """Analytical reference (closed-form CRPS for U[0, w] evaluated at the
    midpoint y = w/2):

        CRPS(U[0, w], y) = E_X|X − y| − 0.5 · E_{X, X'}|X − X'|
                          = w/4            − 0.5 · (w/3)
                          = w/12

    Derivation:
      For X ~ U[0, w], y = w/2:
        E|X − y| = ∫₀^w |x − w/2|/w dx = w/4
        E|X − X'| = w/3   (mean absolute deviation between two iid U[0,w])
      ⇒  CRPS = w/4 − w/6 = 3w/12 − 2w/12 = w/12.

    The empirical estimator converges to this as M → ∞; we use a large M
    and a generous tolerance (statistical error scales as 1/√M).
    """
    M = 50_000
    rng = np.random.default_rng(42)
    for w in (1.0, 5.0, 100.0):
        x = rng.uniform(0.0, w, size=(M, 1))
        y = np.array([w / 2.0])
        crps = crps_per_column(x, y)
        expected = w / 12.0
        # 1/√50000 ≈ 0.0045, so a relative tolerance of 1% is generous
        assert abs(crps[0] - expected) / expected < 0.02, (
            f"CRPS(U[0,{w}], {w/2}) = {crps[0]:.6f}, expected {expected:.6f}"
        )


def test_crps_non_negative_for_random_inputs() -> None:
    """CRPS is by construction ≥ 0 for any distribution + truth."""
    rng = np.random.default_rng(0)
    for _ in range(20):
        d = rng.standard_normal((100, 6)) * rng.uniform(0.5, 5.0)
        truth = rng.standard_normal(6) * rng.uniform(0.5, 5.0)
        crps = crps_per_column(d, truth)
        assert (crps >= 0).all()


# ──────────────────────────────────────────────────────────────────────────
# Coverage on known-truth distributions
# ──────────────────────────────────────────────────────────────────────────


def test_coverage_truth_inside_p10p90() -> None:
    """Truth at the centre of a wide Gaussian should be inside P10-P90."""
    rng = np.random.default_rng(1)
    d = rng.standard_normal((1000, 4)) * 5.0
    truth = np.zeros(4)  # all at distribution mean
    cov = coverage_p10p90_from(d, truth)
    assert cov == 1.0


def test_coverage_truth_outside_distribution() -> None:
    """Truth far outside the P10-P90 band → coverage 0."""
    d = np.random.default_rng(2).standard_normal((500, 3))
    truth = np.array([100.0, -100.0, 50.0])
    cov = coverage_p10p90_from(d, truth)
    assert cov == 0.0


def test_coverage_partial_match() -> None:
    """A mix of in-band and out-of-band truth → coverage fraction."""
    rng = np.random.default_rng(3)
    d = rng.standard_normal((500, 4))
    # 2 inside [P10, P90], 2 outside (using ±10 sigma)
    truth = np.array([0.0, -0.1, 10.0, -10.0])
    cov = coverage_p10p90_from(d, truth)
    assert cov == 0.5


# ──────────────────────────────────────────────────────────────────────────
# width_ratio bounds
# ──────────────────────────────────────────────────────────────────────────


def test_width_ratio_identical_distributions_is_exactly_one() -> None:
    d = np.random.default_rng(4).standard_normal((100, 7))
    assert np.allclose(width_ratio(d, d), 1.0)


def test_width_ratio_doubled_spread_doubles_ratio() -> None:
    rng = np.random.default_rng(5)
    d_prior = rng.standard_normal((300, 5))
    d_post = d_prior * 2.0
    wr = width_ratio(d_post, d_prior)
    # Tolerance allows for small quantile noise in 300-sample estimates
    assert np.allclose(wr, 2.0, atol=0.05)


def test_width_ratio_handles_zero_denominator() -> None:
    """If P10_prior == P90_prior (zero spread), the formula must not crash —
    we fall back to a sane denominator of 1.0."""
    d_prior = np.ones((50, 3))   # zero spread
    d_post = np.zeros((50, 3))
    wr = width_ratio(d_post, d_prior)
    assert np.isfinite(wr).all()


# ──────────────────────────────────────────────────────────────────────────
# median_shift sanity
# ──────────────────────────────────────────────────────────────────────────


def test_median_shift_constant_offset() -> None:
    rng = np.random.default_rng(6)
    d_prior = rng.standard_normal((200, 4))
    delta = np.array([1.5, -2.0, 0.0, 3.0])
    d_post = d_prior + delta
    ms = median_shift(d_post, d_prior)
    assert np.allclose(ms, delta, atol=0.1)

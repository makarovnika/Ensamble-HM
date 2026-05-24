"""Adaptive correlation-based localization for ES (Task 1.1).

Per ТЗ §6 Task 1.1: build a mask ``L`` of shape ``(n_z, n_d)`` whose entries
zero out spurious long-range correlations in the Kalman gain. The threshold is
adaptive — based on the null distribution of sample correlations between
independent Gaussian draws of length N:

    threshold = factor / sqrt(N)         (default factor = 3.0)

`hard` mode: ``L[i, j] = 1`` if ``|corr(Z[:, i], D[:, j])| >= threshold`` else 0.
`soft_taper` mode: a smooth ramp around the threshold using a cosine taper.

The full sample-correlation matrix is returned alongside the mask so that an
audit log can inspect the post-thresholding behaviour.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

log = logging.getLogger(__name__)


def _sample_correlation(Z: np.ndarray, D: np.ndarray) -> np.ndarray:
    """Pearson correlation between every column of Z and every column of D.

    Z : (N, n_z)
    D : (N, n_d)

    Returns
    -------
    corr : (n_z, n_d) array with values in [-1, 1].
    """
    if Z.shape[0] != D.shape[0]:
        raise ValueError(
            f"Z and D must have the same first dim (N); got {Z.shape[0]} vs {D.shape[0]}"
        )
    N = Z.shape[0]
    Zc = Z - Z.mean(axis=0, keepdims=True)
    Dc = D - D.mean(axis=0, keepdims=True)
    # std with ddof=1, plus a tiny floor to avoid division by zero on constant
    # columns (which should not occur but might in degenerate fixtures).
    sz = Zc.std(axis=0, ddof=1)
    sd = Dc.std(axis=0, ddof=1)
    eps = 1.0e-300
    cov = (Zc.T @ Dc) / (N - 1)  # (n_z, n_d)
    return cov / (sz[:, None] * sd[None, :] + eps)


def adaptive_correlation_localization(
    Z: np.ndarray,
    D: np.ndarray,
    *,
    factor: float = 3.0,
    method: Literal["hard", "soft_taper"] = "hard",
    taper_half_width: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Build the localization mask from the ensemble correlation matrix.

    Parameters
    ----------
    Z, D : (N, n_z), (N, n_d) arrays.
    factor : threshold multiplier — threshold = factor / sqrt(N).
    method : ``"hard"`` returns 0/1 mask; ``"soft_taper"`` ramps between 0 and 1
        across ``threshold ± taper_half_width`` using a cosine.
    taper_half_width : only used for ``soft_taper``.

    Returns
    -------
    mask : (n_z, n_d) float array of localization weights in [0, 1].
    corr : (n_z, n_d) the underlying sample correlation matrix (for audit).
    threshold : the scalar threshold used (factor / sqrt(N)).
    """
    N = Z.shape[0]
    threshold = factor / np.sqrt(N)
    corr = _sample_correlation(Z, D)
    abs_corr = np.abs(corr)

    if method == "hard":
        mask = (abs_corr >= threshold).astype(np.float64)
    elif method == "soft_taper":
        # cosine ramp from 0 at (threshold - taper) to 1 at (threshold + taper)
        lo = threshold - taper_half_width
        hi = threshold + taper_half_width
        mask = np.empty_like(abs_corr)
        mask[abs_corr <= lo] = 0.0
        mask[abs_corr >= hi] = 1.0
        mid = (abs_corr > lo) & (abs_corr < hi)
        if taper_half_width > 0:
            x = (abs_corr[mid] - lo) / (hi - lo)  # in (0, 1)
            mask[mid] = 0.5 * (1 - np.cos(np.pi * x))
        else:
            mask[mid] = (abs_corr[mid] >= threshold).astype(np.float64)
    else:
        raise ValueError(f"Unknown localization method: {method!r}")

    n_total = mask.size
    n_nonzero = int((mask > 0).sum())
    frac_kept = n_nonzero / n_total
    log.info(
        f"localization: N={N} threshold={threshold:.4f} "
        f"method={method} kept={n_nonzero}/{n_total} ({100*frac_kept:.2f}%)"
    )
    return mask, corr, threshold

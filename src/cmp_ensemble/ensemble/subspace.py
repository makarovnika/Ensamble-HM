"""SVD truncation helper for subspace regularisation (Evensen Ch. 6)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TruncatedSVD:
    """Result of an energy-truncated SVD ``A = U Σ V^T`` with ``r`` kept components.

    Conventions
    -----------
    A : (N, n_d) input matrix
    U : (N, r), Σ : (r,) (descending), V : (n_d, r); Vt = V.T : (r, n_d).
    """

    U: np.ndarray
    s: np.ndarray
    Vt: np.ndarray
    energy_kept: float
    r: int


def truncated_svd(A: np.ndarray, energy: float = 0.99) -> TruncatedSVD:
    """SVD of A truncated at the smallest r retaining `energy` of total variance.

    `energy` is measured as the cumulative sum of squared singular values
    divided by the total. r is the smallest integer satisfying the threshold.
    The smallest non-trivial r is 1; if the input is zero, r = 0 is returned.
    """
    U, s, Vt = np.linalg.svd(A, full_matrices=False)
    total = float((s**2).sum())
    if total <= 0:
        return TruncatedSVD(U=U[:, :0], s=s[:0], Vt=Vt[:0, :], energy_kept=0.0, r=0)
    cum = (s**2).cumsum() / total
    r = int(np.searchsorted(cum, energy) + 1)
    r = min(r, len(s))
    return TruncatedSVD(
        U=U[:, :r],
        s=s[:r],
        Vt=Vt[:r, :],
        energy_kept=float(cum[r - 1]),
        r=r,
    )

"""Mahalanobis ranking — Task 2.1.

For each member i, compute ‖z_post[i] - z_prior[i]‖_M where M⁻¹ is the prior
covariance (or a supplied alternative). Models with the largest migration are
the ones whose θ has been most updated by the ES step — they are the first
candidates for re-simulation in Phase 3.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


def mahalanobis_distance(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    C_zz_prior: np.ndarray | None = None,
    *,
    jitter: float = 1.0e-12,
) -> np.ndarray:
    """Per-member ‖z_post - z_prior‖_M from the prior covariance.

    `C_zz_prior=None` → use the sample covariance of `Z_prior`.
    """
    if Z_prior.shape != Z_post.shape:
        raise ValueError(
            f"Z_prior {Z_prior.shape} and Z_post {Z_post.shape} must match"
        )
    N, n_z = Z_prior.shape
    if C_zz_prior is None:
        Zp = Z_prior - Z_prior.mean(axis=0, keepdims=True)
        C_zz_prior = Zp.T @ Zp / max(N - 1, 1)
    inv = np.linalg.pinv(C_zz_prior + jitter * np.eye(n_z))
    dz = Z_post - Z_prior
    return np.sqrt(np.einsum("ij,jk,ik->i", dz, inv, dz))


def rank_by_parameter_change(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    C_zz_prior: np.ndarray | None = None,
) -> np.ndarray:
    """Return indices in descending order of ‖Δz‖_M.

    The first index in the returned array is the model with the largest
    posterior shift.
    """
    d = mahalanobis_distance(Z_prior, Z_post, C_zz_prior)
    order = np.argsort(-d)
    log.info(
        f"Mahalanobis ranking: min={d.min():.3f} median={np.median(d):.3f} "
        f"max={d.max():.3f}"
    )
    return order

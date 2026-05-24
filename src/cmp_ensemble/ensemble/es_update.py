"""One-pass Ensemble Smoother update with subspace regularisation (Task 1.2).

Conventions
-----------
- Z_prior : (N, n_z) ensemble of prior state vectors, rows = members.
- D_sim   : (N, n_d) predicted observations, rows = members.
- d_obs   : (n_d,)   observed data.
- C_dd    : (n_d, n_d) — observation-noise covariance. Diagonal in our pipeline.

The update implements Evensen (2026) Eq. 5.13:

    z_post[i] = z_prior[i] + K · (d_obs + ε[i] − d_sim[i])
    K        = C_zd · (C_dd_ens + C_dd)⁻¹

with `(C_dd_ens + C_dd)⁻¹` evaluated in the ensemble subspace via truncated
SVD of D' / √(N-1) at `subspace_energy` (default 0.99).

If a localization mask is provided, it multiplies K element-wise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from cmp_ensemble.ensemble.subspace import TruncatedSVD, truncated_svd

log = logging.getLogger(__name__)


@dataclass
class ESUpdateResult:
    Z_post: np.ndarray              # (N, n_z)
    K: np.ndarray                   # (n_z, n_d)
    singular_values: np.ndarray     # (k,) all singular values from full SVD
    n_components_kept: int          # r ≤ min(N, n_d)
    energy_kept: float              # cumulative energy at r
    perturbations: np.ndarray       # (N, n_d) ε samples used
    localization_applied: bool


def _validate_inputs(
    Z_prior: np.ndarray,
    D_sim: np.ndarray,
    d_obs: np.ndarray,
    C_dd: np.ndarray,
    localization_mask: np.ndarray | None,
) -> None:
    if Z_prior.ndim != 2 or D_sim.ndim != 2:
        raise ValueError("Z_prior and D_sim must be 2-D (N, p)")
    if Z_prior.shape[0] != D_sim.shape[0]:
        raise ValueError("Z_prior and D_sim must have the same N")
    if d_obs.shape != (D_sim.shape[1],):
        raise ValueError(f"d_obs shape {d_obs.shape} != ({D_sim.shape[1]},)")
    if C_dd.shape != (D_sim.shape[1], D_sim.shape[1]):
        raise ValueError(
            f"C_dd shape {C_dd.shape} != ({D_sim.shape[1]},{D_sim.shape[1]})"
        )
    if localization_mask is not None and localization_mask.shape != (
        Z_prior.shape[1],
        D_sim.shape[1],
    ):
        raise ValueError(
            f"localization_mask shape {localization_mask.shape} != "
            f"({Z_prior.shape[1]},{D_sim.shape[1]})"
        )


def _sample_perturbations(
    C_dd: np.ndarray, N: int, seed: int
) -> np.ndarray:
    """N independent draws ε_i ~ N(0, C_dd). For diagonal C_dd this is cheap.

    For dense C_dd we fall back to a Cholesky factor.
    """
    n_d = C_dd.shape[0]
    rng = np.random.default_rng(seed)
    off_diag = C_dd - np.diag(np.diag(C_dd))
    if np.allclose(off_diag, 0.0):
        sigma = np.sqrt(np.maximum(np.diag(C_dd), 0.0))
        return rng.standard_normal((N, n_d)) * sigma
    # symmetric PSD → Cholesky; jitter on the diagonal if needed
    try:
        L = np.linalg.cholesky(C_dd)
    except np.linalg.LinAlgError:
        L = np.linalg.cholesky(C_dd + 1e-10 * np.eye(n_d))
    return rng.standard_normal((N, n_d)) @ L.T


def es_update(
    Z_prior: np.ndarray,
    D_sim: np.ndarray,
    d_obs: np.ndarray,
    C_dd: np.ndarray,
    *,
    localization_mask: np.ndarray | None = None,
    subspace_energy: float = 0.99,
    seed: int = 42,
) -> ESUpdateResult:
    """One ES update step. See module docstring for the formulae."""
    _validate_inputs(Z_prior, D_sim, d_obs, C_dd, localization_mask)
    N, n_z = Z_prior.shape
    n_d = D_sim.shape[1]

    # Centering
    z_bar = Z_prior.mean(axis=0)
    d_bar = D_sim.mean(axis=0)
    Zp = Z_prior - z_bar
    Dp = D_sim - d_bar

    # Sample cross-covariance C_zd
    C_zd = Zp.T @ Dp / (N - 1)         # (n_z, n_d)

    # Subspace SVD of Dp / sqrt(N-1):
    # E = Dp / sqrt(N-1)  →  E^T E = C_dd_ens
    # E = U Σ V^T, so C_dd_ens = V Σ² V^T
    E = Dp / np.sqrt(N - 1)
    tsvd: TruncatedSVD = truncated_svd(E, energy=subspace_energy)
    s_full = np.linalg.svd(E, compute_uv=False)

    # Project C_dd onto the V_r basis and invert the small r×r inner matrix.
    # (C_dd_ens + C_dd)⁻¹  ≈  V_r (Σ_r² + V_r^T C_dd V_r)⁻¹ V_r^T
    Vr = tsvd.Vt.T                     # (n_d, r)
    inner = np.diag(tsvd.s**2) + tsvd.Vt @ C_dd @ Vr   # (r, r)
    inner_inv = np.linalg.inv(inner)
    inv_total = Vr @ inner_inv @ tsvd.Vt               # (n_d, n_d)

    K = C_zd @ inv_total               # (n_z, n_d)

    loc_applied = localization_mask is not None
    if loc_applied:
        K = K * localization_mask

    # Perturbed innovations
    eps = _sample_perturbations(C_dd, N, seed=seed)    # (N, n_d)
    innov = d_obs[None, :] + eps - D_sim               # (N, n_d)
    Z_post = Z_prior + innov @ K.T                     # (N, n_z)

    log.info(
        f"ES update: N={N} n_z={n_z} n_d={n_d} subspace_r={tsvd.r}/{len(s_full)} "
        f"energy_kept={tsvd.energy_kept:.4f} loc={loc_applied}"
    )
    return ESUpdateResult(
        Z_post=Z_post,
        K=K,
        singular_values=s_full,
        n_components_kept=tsvd.r,
        energy_kept=tsvd.energy_kept,
        perturbations=eps,
        localization_applied=loc_applied,
    )

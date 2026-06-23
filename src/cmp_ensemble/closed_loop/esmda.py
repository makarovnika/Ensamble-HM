"""ES-MDA assimilation loop (Evensen, Oliver, Hanea 2026, §3.6, §6.4).

ES-MDA performs ``n_alpha`` recursive ES updates. At step ``i`` the measurement
error covariance is inflated by ``alpha_i`` and the perturbations are resampled
from ``N(d, alpha_i * C_dd)``; the weights satisfy ``sum(1/alpha_i) = 1`` so the
total assimilated information equals one ES update. Each step reuses the existing
subspace ES update in :func:`cmp_ensemble.ensemble.es_update.es_update`, so
ES-MDA with ``n_alpha = 1`` is byte-identical to a single ES update.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from cmp_ensemble.ensemble.es_update import es_update
from cmp_ensemble.ensemble.localization import adaptive_correlation_localization

log = logging.getLogger(__name__)


def uniform_alphas(n_alpha: int) -> list[float]:
    """Uniform MDA weights: every ``alpha_i = n_alpha`` so ``sum(1/alpha_i)=1``."""
    if n_alpha < 1:
        raise ValueError("n_alpha must be >= 1")
    return [float(n_alpha)] * n_alpha


def geometric_alphas(n_alpha: int, ratio: float = 0.5) -> list[float]:
    """Geometrically decreasing weights, normalised so ``sum(1/alpha_i)=1``."""
    if n_alpha < 1:
        raise ValueError("n_alpha must be >= 1")
    inv = np.array([ratio**i for i in range(n_alpha)], dtype=float)
    inv = inv / inv.sum()          # now sum(inv) == 1
    return (1.0 / inv).tolist()


def _check_alphas(alphas: list[float]) -> None:
    s = sum(1.0 / a for a in alphas)
    if not np.isclose(s, 1.0, atol=1e-8):
        raise ValueError(f"sum(1/alpha_i) must equal 1, got {s:.6f}")


def data_misfit(D: np.ndarray, d_obs: np.ndarray, C_dd: np.ndarray) -> float:
    """Mean normalised data misfit over the ensemble: mean_j (r^T C_dd^-1 r)/n_d."""
    r = d_obs[None, :] - D                      # (N, n_d)
    cdd_diag = np.diag(C_dd)
    chi2 = np.sum(r * r / cdd_diag[None, :], axis=1)   # (N,)
    return float(chi2.mean() / D.shape[1])


@dataclass
class ESMDAResult:
    Theta_post: np.ndarray                       # (N, n_z)
    alphas: list[float]
    misfit_history: list[float]                  # misfit before each step + final
    Theta_history: list[np.ndarray] = field(default_factory=list)
    D_history: list[np.ndarray] = field(default_factory=list)
    localization_applied: bool = False


def esmda(
    Theta0: np.ndarray,
    forward,
    d_obs: np.ndarray,
    C_dd: np.ndarray,
    *,
    n_alpha: int = 4,
    alphas: list[float] | None = None,
    localize: bool = False,
    localization_factor: float = 3.0,
    localization_method: str = "hard",
    subspace_energy: float = 0.99,
    seed: int = 42,
    keep_history: bool = True,
    on_step=None,
    skip_final_eval: bool = False,
) -> ESMDAResult:
    """Run ES-MDA.

    Parameters
    ----------
    Theta0 : (N, n_z) prior parameter ensemble.
    forward : callable (N, n_z) -> (N, n_d) predicted measurements.
    d_obs : (n_d,) observations.
    C_dd : (n_d, n_d) measurement error covariance (diagonal expected).
    n_alpha : number of MDA steps (used if ``alphas`` is None → uniform weights).
    alphas : explicit weight schedule; must satisfy ``sum(1/alpha_i) = 1``.
    localize : apply adaptive correlation localization at each step.
    seed : base perturbation seed; step ``i`` uses ``seed + i``.
    on_step : optional callback ``(i, Theta_i, D_i, misfit_i)`` fired after the
        forward eval of step ``i`` (the pre-update state) — used by the
        orchestrator to checkpoint each iteration for crash recovery.
    """
    Theta0 = np.asarray(Theta0, dtype=float)
    d_obs = np.asarray(d_obs, dtype=float)
    C_dd = np.asarray(C_dd, dtype=float)

    if alphas is None:
        alphas = uniform_alphas(n_alpha)
    _check_alphas(alphas)

    Theta = Theta0.copy()
    misfit_history: list[float] = []
    Theta_hist: list[np.ndarray] = []
    D_hist: list[np.ndarray] = []
    loc_applied = False

    for i, a in enumerate(alphas):
        D = forward(Theta)
        misfit_history.append(data_misfit(D, d_obs, C_dd))
        if on_step is not None:
            on_step(i, Theta, D, misfit_history[-1])

        loc_mask = None
        if localize:
            loc_mask, _, _ = adaptive_correlation_localization(
                Theta, D, factor=localization_factor, method=localization_method
            )
            loc_applied = True

        res = es_update(
            Theta, D, d_obs, a * C_dd,
            localization_mask=loc_mask,
            subspace_energy=subspace_energy,
            seed=seed + i,
        )
        if keep_history:
            Theta_hist.append(Theta.copy())
            D_hist.append(D.copy())
        Theta = res.Z_post
        log.info("ES-MDA step %d/%d alpha=%.3f misfit=%.4g",
                 i + 1, len(alphas), a, misfit_history[-1])

    # Final misfit after the last update — one extra full forward pass over the
    # posterior. skip_final_eval drops it to save N simulations: the posterior
    # Theta is still returned; only the exact posterior misfit is forgone (it can
    # be recovered later, e.g. from the forecast-window run over the posterior).
    if not skip_final_eval:
        D_final = forward(Theta)
        misfit_history.append(data_misfit(D_final, d_obs, C_dd))
        if keep_history:
            D_hist.append(D_final.copy())
        log.info("ES-MDA done: misfit %.4g -> %.4g",
                 misfit_history[0], misfit_history[-1])
    else:
        log.info("ES-MDA done (final eval skipped): misfit history = %d pre-update "
                 "steps; posterior misfit not computed", len(misfit_history))

    return ESMDAResult(
        Theta_post=Theta,
        alphas=alphas,
        misfit_history=misfit_history,
        Theta_history=Theta_hist,
        D_history=D_hist,
        localization_applied=loc_applied,
    )

"""Linear proxy for forecast — Task 2.2 (Evensen Ch. 4).

Given a training ensemble `(Z_train, D_forecast_train)`, build the linear
sensitivity matrix

    S = C_zd_forecast · C_zz⁻¹   (n_z × n_d_forecast)

Predict forecast for a new `z`:

    d̂(z) = d̄ + S^T · (z - z̄)

The proxy is trained per-cluster by default, because the ensemble θ-spread
within a cluster is narrow and per-cluster sensitivities are more meaningful
than a global one. Set `per_cluster=False` for a single global fit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class LinearProxy:
    """One linear forecast emulator, optionally trained per cluster.

    Fields
    ------
    z_bar : (n_z,) prior mean used during training.
    d_bar : (n_d_forecast,) prior mean of the forecast vector.
    S     : (n_z, n_d_forecast) — sensitivity matrix.
    cluster_id : optional cluster label for which this proxy was trained.
    n_train : number of training members.
    envelope_min, envelope_max : (n_z,) per-component min/max of the training
        Z. Used to flag extrapolation: predictions for z outside [min, max]
        are marked as out-of-envelope.
    """

    z_bar: np.ndarray
    d_bar: np.ndarray
    S: np.ndarray
    n_train: int
    envelope_min: np.ndarray
    envelope_max: np.ndarray
    cluster_id: int | None = None

    @property
    def n_z(self) -> int:
        return self.z_bar.shape[0]

    @property
    def n_d(self) -> int:
        return self.d_bar.shape[0]

    def predict(self, z: np.ndarray) -> np.ndarray:
        """Return d̂ for one or several test points.

        `z` shape (n_z,) → returns (n_d,)
        `z` shape (M, n_z) → returns (M, n_d)
        """
        if z.ndim == 1:
            return self.d_bar + (z - self.z_bar) @ self.S
        return self.d_bar[None, :] + (z - self.z_bar[None, :]) @ self.S

    def in_envelope(self, z: np.ndarray) -> np.ndarray:
        """Boolean: True if every component lies in the training min/max box."""
        if z.ndim == 1:
            return bool(((z >= self.envelope_min) & (z <= self.envelope_max)).all())
        within = (
            (z >= self.envelope_min[None, :]) & (z <= self.envelope_max[None, :])
        ).all(axis=1)
        return within


def build_linear_proxy(
    Z_train: np.ndarray,
    D_train: np.ndarray,
    *,
    cluster_id: int | None = None,
    ridge: float = 1.0e-8,
) -> LinearProxy:
    """Fit S = C_zd · C_zz⁻¹ on the training ensemble.

    A small ridge (`1e-8`) regularises `C_zz` when n_train < n_z or when the
    sample covariance is near-singular.
    """
    n_train, n_z = Z_train.shape
    z_bar = Z_train.mean(axis=0)
    d_bar = D_train.mean(axis=0)
    Zp = Z_train - z_bar
    Dp = D_train - d_bar
    C_zz = Zp.T @ Zp / max(n_train - 1, 1)
    C_zd = Zp.T @ Dp / max(n_train - 1, 1)
    inv = np.linalg.pinv(C_zz + ridge * np.eye(n_z))
    S = inv @ C_zd                                   # (n_z, n_d_forecast)
    return LinearProxy(
        z_bar=z_bar,
        d_bar=d_bar,
        S=S,
        n_train=n_train,
        envelope_min=Z_train.min(axis=0),
        envelope_max=Z_train.max(axis=0),
        cluster_id=cluster_id,
    )


def build_per_cluster_proxies(
    Z: np.ndarray,
    D: np.ndarray,
    cluster_ids: np.ndarray,
    *,
    ridge: float = 1.0e-8,
) -> dict[int, LinearProxy]:
    """Train one LinearProxy per cluster. Returns `{cluster_id: proxy}`."""
    out: dict[int, LinearProxy] = {}
    for cl in sorted({int(c) for c in cluster_ids.tolist()}):
        idx = cluster_ids == cl
        if int(idx.sum()) < 2:
            log.warning(f"  cluster {cl}: only {int(idx.sum())} member(s) — skip proxy")
            continue
        out[cl] = build_linear_proxy(Z[idx], D[idx], cluster_id=cl, ridge=ridge)
        log.info(
            f"  proxy cluster={cl} n_train={int(idx.sum())} "
            f"n_z={out[cl].n_z} n_d={out[cl].n_d}"
        )
    return out

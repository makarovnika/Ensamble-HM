"""Forward-model abstraction for the closed loop.

The ES-MDA loop only needs a callable that maps a parameter ensemble
``Theta`` (N, n_z) to a predicted-measurement ensemble ``D`` (N, n_d). In tests
we use :class:`LinearGaussianForward`; in production a tNavigator-backed forward
(``TNavForward``, added in feature CL-D) implements the same protocol.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class ForwardModel(Protocol):
    """Maps a parameter ensemble to a predicted-measurement ensemble."""

    def __call__(self, Theta: np.ndarray) -> np.ndarray:  # (N, n_z) -> (N, n_d)
        ...


class LinearGaussianForward:
    """Deterministic linear forward ``d = Theta @ H.T`` (+ optional bias).

    Used for unit/integration tests where the Bayesian posterior is analytic.
    Set ``noise_std`` > 0 only to emulate simulator noise; the default is exact.
    """

    def __init__(
        self,
        H: np.ndarray,
        *,
        bias: np.ndarray | None = None,
        noise_std: float = 0.0,
        seed: int = 0,
    ) -> None:
        self.H = np.asarray(H, dtype=float)        # (n_d, n_z)
        self.bias = None if bias is None else np.asarray(bias, dtype=float)
        self.noise_std = float(noise_std)
        self._rng = np.random.default_rng(seed)

    def __call__(self, Theta: np.ndarray) -> np.ndarray:
        D = Theta @ self.H.T
        if self.bias is not None:
            D = D + self.bias[None, :]
        if self.noise_std > 0:
            D = D + self._rng.normal(0.0, self.noise_std, size=D.shape)
        return D

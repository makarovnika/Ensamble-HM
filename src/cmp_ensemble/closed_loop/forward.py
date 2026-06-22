"""Forward-model abstraction for the closed loop.

The ES-MDA loop only needs a callable that maps a parameter ensemble
``Theta`` (N, n_z) to a predicted-measurement ensemble ``D`` (N, n_d). In tests
we use :class:`LinearGaussianForward`; in production :class:`TNavForward` runs the
ensemble through tNavigator and reads the cumulative d_sim back via
``results_reader`` — both satisfy the same :class:`ForwardModel` protocol.
"""
from __future__ import annotations

import logging
from typing import Callable, Mapping, Protocol, Sequence

import numpy as np

log = logging.getLogger(__name__)


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


class TNavForward:
    """Production forward: run a θ-ensemble through tNavigator, read d_sim back.

    The simulator and result-reading concerns are injected as callables so the
    full ES-MDA cycle is testable with a mock (no live tNavigator needed):

    * ``run_fn(thetas)`` — submit a list of θ-dicts (one per member) to the
      simulator. Typically wraps ``tnav_autorun.run_ensemble``. May return a
      status mapping; the return value is logged but not required.
    * ``read_fn(member_index, theta)`` — return the (n_d,) cumulative d-vector
      for member ``member_index`` after its run. Typically wraps
      ``results_reader.read_cumulative_dsim`` for that model's RESULTS dir.

    θ-rows are converted to dicts via ``theta_names`` (the column→key map from
    :class:`~cmp_ensemble.closed_loop.prior.PriorResult`), so the keys line up
    with ``tnav_autorun.BASE_VARIABLES`` overrides.
    """

    def __init__(
        self,
        theta_names: Sequence[str],
        run_fn: Callable[[list[dict]], object],
        read_fn: Callable[[int, Mapping[str, float]], np.ndarray],
    ) -> None:
        self.theta_names = list(theta_names)
        self.run_fn = run_fn
        self.read_fn = read_fn

    def thetas_as_dicts(self, Theta: np.ndarray) -> list[dict]:
        Theta = np.asarray(Theta, dtype=float)
        if Theta.shape[1] != len(self.theta_names):
            raise ValueError(
                f"Theta has {Theta.shape[1]} cols but {len(self.theta_names)} names"
            )
        return [dict(zip(self.theta_names, row)) for row in Theta]

    def __call__(self, Theta: np.ndarray) -> np.ndarray:
        thetas = self.thetas_as_dicts(Theta)
        log.info("TNavForward: submitting %d members", len(thetas))
        status = self.run_fn(thetas)
        if isinstance(status, Mapping):
            ok = sum(v == "ok" for v in status.values())
            log.info("TNavForward: %d/%d members ok", ok, len(thetas))
        rows = [np.asarray(self.read_fn(i, th), dtype=float) for i, th in enumerate(thetas)]
        D = np.vstack(rows)
        log.info("TNavForward: assembled D shape %s", D.shape)
        return D

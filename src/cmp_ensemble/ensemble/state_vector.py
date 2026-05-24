"""State vector assembly: z = (θ, u) or z = θ, with round-trip unpacking."""

from __future__ import annotations

import numpy as np

from cmp_ensemble.io.schemas import StateVectorSchema


def build_state_vector(
    theta: np.ndarray,
    u: np.ndarray | None = None,
    *,
    theta_names: list[str],
    control_names: list[str] | None = None,
    include_controls: bool = True,
) -> tuple[np.ndarray, StateVectorSchema]:
    """Assemble z = (θ, u) (or z = θ) as a stacked (N, n_z) array.

    Parameters
    ----------
    theta : (N, n_θ) array
    u     : (N, n_u) array or None
    theta_names : list[str], length n_θ
    control_names : list[str] or None
    include_controls : bool. If True and `u` is None, controls are simply omitted
        (no error). If False, controls are dropped even if provided.

    Returns
    -------
    z : (N, n_z) array
    schema : StateVectorSchema for round-trip unpacking
    """
    if theta.ndim != 2:
        raise ValueError(f"theta must be 2-D (N, n_θ); got {theta.shape}")
    if theta.shape[1] != len(theta_names):
        raise ValueError("theta columns != len(theta_names)")

    use_controls = include_controls and u is not None
    if use_controls:
        if u.ndim != 2 or u.shape[0] != theta.shape[0]:
            raise ValueError("u must be 2-D with the same N as theta")
        if control_names is None or len(control_names) != u.shape[1]:
            raise ValueError("control_names must match u.shape[1]")
        z = np.hstack([theta, u])
        n_t = theta.shape[1]
        n_u = u.shape[1]
        schema = StateVectorSchema(
            theta_names=list(theta_names),
            control_names=list(control_names),
            theta_slice=(0, n_t),
            control_slice=(n_t, n_t + n_u),
            n_z=n_t + n_u,
        )
    else:
        z = theta.copy()
        n_t = theta.shape[1]
        schema = StateVectorSchema(
            theta_names=list(theta_names),
            control_names=[],
            theta_slice=(0, n_t),
            control_slice=None,
            n_z=n_t,
        )
    return z, schema


def unpack_state_vector(
    z: np.ndarray, schema: StateVectorSchema
) -> tuple[np.ndarray, np.ndarray | None]:
    """Inverse of `build_state_vector`. Returns (θ, u) where u may be None."""
    if z.ndim != 2 or z.shape[1] != schema.n_z:
        raise ValueError(f"z shape {z.shape} incompatible with schema.n_z={schema.n_z}")
    t0, t1 = schema.theta_slice
    theta = z[:, t0:t1]
    if schema.control_slice is None:
        return theta, None
    c0, c1 = schema.control_slice
    return theta, z[:, c0:c1]

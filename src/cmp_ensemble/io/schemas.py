"""Pydantic v2 schemas for ensemble inputs and outputs."""

from __future__ import annotations

from datetime import datetime

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

_NP_ARRAY = ConfigDict(arbitrary_types_allowed=True)


class StateVectorSchema(BaseModel):
    """Layout of a stacked state vector `z = (θ, u)`.

    Stores the slice boundaries needed to round-trip a flat (N, n_z) array back
    into (θ, u) components.
    """

    model_config = _NP_ARRAY

    theta_names: list[str]
    control_names: list[str] = Field(default_factory=list)
    theta_slice: tuple[int, int]
    control_slice: tuple[int, int] | None = None
    n_z: int

    @model_validator(mode="after")
    def _check_slices(self) -> "StateVectorSchema":
        t0, t1 = self.theta_slice
        if t1 - t0 != len(self.theta_names):
            raise ValueError("theta_slice length does not match theta_names")
        if self.control_slice is not None:
            c0, c1 = self.control_slice
            if c1 - c0 != len(self.control_names):
                raise ValueError("control_slice length does not match control_names")
            if self.n_z != (t1 - t0) + (c1 - c0):
                raise ValueError("n_z != len(theta) + len(controls)")
        elif self.n_z != (t1 - t0):
            raise ValueError("n_z != len(theta) and no controls present")
        return self


class EnsembleData(BaseModel):
    """Per-ensemble outputs of the tNavigator loader (Task 0.1)."""

    model_config = _NP_ARRAY

    # Identifiers
    model_ids: np.ndarray            # (N,) int — MODEL column
    cluster_ids: np.ndarray          # (N,) int in {0, 1, 2}
    seeds: np.ndarray                # (N,) int — round(SEED)
    sheet_names: list[str]           # length N — names of the dynamics sheets

    # Parameters
    theta: np.ndarray                # (N, n_θ)
    theta_names: list[str]

    # Per-model simulated observables (concatenated across well × metric × time)
    d_sim_rates: np.ndarray          # (N, n_d_rates)
    d_sim_cum: np.ndarray            # (N, n_d_cum)
    rate_index: list[tuple[str, str, datetime]]   # (metric, well, time)
    cum_index: list[tuple[str, str, datetime]]    # (metric, well, time)

    # Time axis
    time_steps: np.ndarray           # (n_time,) datetime64[ns]

    # Well roster (after filtering dummy "B")
    producer_wells: list[str]
    injector_wells: list[str]

    @model_validator(mode="after")
    def _check_shapes(self) -> "EnsembleData":
        N = self.model_ids.shape[0]
        if self.cluster_ids.shape[0] != N or self.seeds.shape[0] != N:
            raise ValueError("identifier arrays have inconsistent length")
        if self.theta.shape[0] != N:
            raise ValueError(f"theta first dim ({self.theta.shape[0]}) != N ({N})")
        if self.theta.shape[1] != len(self.theta_names):
            raise ValueError("theta column count != len(theta_names)")
        if self.d_sim_rates.shape[0] != N:
            raise ValueError("d_sim_rates first dim != N")
        if self.d_sim_rates.shape[1] != len(self.rate_index):
            raise ValueError("d_sim_rates column count != len(rate_index)")
        if self.d_sim_cum.shape[0] != N:
            raise ValueError("d_sim_cum first dim != N")
        if self.d_sim_cum.shape[1] != len(self.cum_index):
            raise ValueError("d_sim_cum column count != len(cum_index)")
        if len(self.sheet_names) != N:
            raise ValueError("sheet_names length != N")
        return self

    @property
    def N(self) -> int:
        return self.model_ids.shape[0]

    @property
    def n_theta(self) -> int:
        return self.theta.shape[1]


class ObservationData(BaseModel):
    """Historical observations + noise covariance (Task 0.2)."""

    model_config = _NP_ARRAY

    d_obs_rates: np.ndarray         # (n_d_rates,)
    d_obs_cum: np.ndarray           # (n_d_cum,)
    C_dd_rates: np.ndarray          # (n_d_rates, n_d_rates) diagonal
    C_dd_cum: np.ndarray            # (n_d_cum, n_d_cum) diagonal
    rate_index: list[tuple[str, str, datetime]]
    cum_index: list[tuple[str, str, datetime]]
    time_steps: np.ndarray
    producer_wells: list[str]
    injector_wells: list[str]
    # diagnostic
    n_bhp_zero_dropped: int = 0
    n_bhp_zero_inflated: int = 0

    @model_validator(mode="after")
    def _check_shapes(self) -> "ObservationData":
        n_r = self.d_obs_rates.shape[0]
        n_c = self.d_obs_cum.shape[0]
        if self.C_dd_rates.shape != (n_r, n_r):
            raise ValueError(f"C_dd_rates shape {self.C_dd_rates.shape} != ({n_r},{n_r})")
        if self.C_dd_cum.shape != (n_c, n_c):
            raise ValueError(f"C_dd_cum shape {self.C_dd_cum.shape} != ({n_c},{n_c})")
        if len(self.rate_index) != n_r or len(self.cum_index) != n_c:
            raise ValueError("index lengths do not match d_obs vectors")
        return self

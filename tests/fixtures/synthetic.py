"""Linear-Gaussian synthetic mini-fixture for the integration test (ТЗ §9).

Configuration mirrors the ТЗ spec:

  * N = 20 ensemble members
  * 3 clusters of sizes [7, 7, 6]
  * n_θ = 5 parameters
  * n_obs = 10 historical observations
  * n_forecast = 10 forecast observations
  * Truth θ is known; observations are H @ θ_truth + iid Gaussian noise
  * Seed is fixed (default 42) so the fixture is byte-identical across runs

The fixture is intentionally a textbook linear-Gaussian problem so that the
ES posterior is mathematically guaranteed to contract toward truth — the
integration test then verifies the *pipeline* (not the math).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass
class SyntheticFixture:
    # Shape
    N: int
    n_theta: int
    n_obs: int
    n_forecast: int

    # Identity / cluster labels
    model_ids: np.ndarray            # (N,)
    cluster_ids: np.ndarray          # (N,)
    seeds: np.ndarray                # (N,)
    sheet_names: list[str]
    theta_names: list[str]
    producer_wells: list[str]

    # Truth + prior
    theta_truth: np.ndarray          # (n_theta,)
    theta_prior: np.ndarray          # (N, n_theta)

    # Forward operators and noise
    H_hist: np.ndarray               # (n_obs, n_theta)
    H_forecast: np.ndarray           # (n_forecast, n_theta)
    sigma_obs: float

    # Historical data (assimilated by ES)
    d_obs: np.ndarray                # (n_obs,)
    d_sim: np.ndarray                # (N, n_obs)
    C_dd: np.ndarray                 # (n_obs, n_obs) diagonal

    # Forecast data (used by Phase 2 proxy + Phase 3 setups)
    d_forecast_truth: np.ndarray     # (n_forecast,) — the synthetic ground truth
    d_forecast_baseline: np.ndarray  # (N, n_forecast)

    # (metric, well, time) indexes used by Phase 3 setups
    obs_index: list[tuple[str, str, datetime]] = field(default_factory=list)
    forecast_index: list[tuple[str, str, datetime]] = field(default_factory=list)


def make_synthetic_fixture(
    *,
    seed: int = 42,
    N: int = 20,
    n_theta: int = 5,
    n_obs: int = 10,
    n_forecast: int = 10,
    sigma_obs: float = 1.0,
) -> SyntheticFixture:
    """Generate the deterministic synthetic fixture."""
    rng = np.random.default_rng(seed)

    theta_names = [f"p{i}" for i in range(n_theta)]
    producer_wells = ["W1", "W2"]   # purely cosmetic — observations span this set

    cluster_sizes = [7, 7, 6]
    assert sum(cluster_sizes) == N, "cluster sizes must sum to N"
    cluster_ids = np.repeat([0, 1, 2], cluster_sizes)
    model_ids = np.arange(N, dtype=np.int64) + 100
    seeds = rng.integers(1000, 9999, size=N, dtype=np.int64)
    sheet_names = [f"syn-{cl}-{mid}" for cl, mid in zip(cluster_ids, model_ids)]

    # Truth + prior. Prior has moderate spread; sigma_obs is calibrated so ES
    # has informative data but not so much that variance collapses to 0.
    theta_truth = rng.standard_normal(n_theta) * 2.0
    theta_prior = rng.standard_normal((N, n_theta)) * 1.5

    H_hist = rng.standard_normal((n_obs, n_theta)) * 0.5
    H_forecast = rng.standard_normal((n_forecast, n_theta)) * 0.5

    d_obs = H_hist @ theta_truth + rng.standard_normal(n_obs) * sigma_obs
    d_sim = theta_prior @ H_hist.T + rng.standard_normal((N, n_obs)) * sigma_obs
    C_dd = (sigma_obs**2) * np.eye(n_obs)

    d_forecast_truth = H_forecast @ theta_truth
    d_forecast_baseline = (
        theta_prior @ H_forecast.T + rng.standard_normal((N, n_forecast)) * sigma_obs
    )

    # Build (metric, well, time) indexes — synthetic but well-formed.
    base_time = datetime(2020, 1, 1)
    obs_index = [
        ("oil_hist", producer_wells[i % len(producer_wells)],
         datetime(base_time.year + (i // 4), 1 + (i % 4) * 3, 1))
        for i in range(n_obs)
    ]
    forecast_index = [
        ("oil_forecast", producer_wells[i % len(producer_wells)],
         datetime(base_time.year + 5 + (i // 4), 1 + (i % 4) * 3, 1))
        for i in range(n_forecast)
    ]

    return SyntheticFixture(
        N=N,
        n_theta=n_theta,
        n_obs=n_obs,
        n_forecast=n_forecast,
        model_ids=model_ids,
        cluster_ids=cluster_ids,
        seeds=seeds,
        sheet_names=sheet_names,
        theta_names=theta_names,
        producer_wells=producer_wells,
        theta_truth=theta_truth,
        theta_prior=theta_prior,
        H_hist=H_hist,
        H_forecast=H_forecast,
        sigma_obs=sigma_obs,
        d_obs=d_obs,
        d_sim=d_sim,
        C_dd=C_dd,
        d_forecast_truth=d_forecast_truth,
        d_forecast_baseline=d_forecast_baseline,
        obs_index=obs_index,
        forecast_index=forecast_index,
    )

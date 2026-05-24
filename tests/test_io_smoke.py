"""Smoke tests for the Phase 0 loaders against real input data.

These are integration-style tests: they read the actual Excel files at the
repo root via the HDF5 cache that `cmp-ensemble run --phase 0` writes. Skipped
if the cache is absent (e.g. on a fresh clone or in CI).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cmp_ensemble.config import (
    load_default_config,
    load_noise_spec,
    project_root,
)
from cmp_ensemble.io.observations import load_observations
from cmp_ensemble.io.tnav_loader import load_tnav_ensemble


@pytest.fixture(scope="module")
def root() -> Path:
    return project_root()


@pytest.fixture(scope="module")
def cache_path(root: Path) -> Path:
    p = root / "outputs" / "cache" / "ensemble.h5"
    if not p.exists():
        pytest.skip(
            "outputs/cache/ensemble.h5 not present — run "
            "`cmp-ensemble run --phase 0` first."
        )
    return p


def test_load_ensemble_from_cache(root: Path, cache_path: Path) -> None:
    cfg = load_default_config(root)
    paths = cfg["io"]["paths"]
    data = load_tnav_ensemble(
        parameters_path=root / paths["parameters"],
        dynamics_path=root / paths["dynamics"],
        cache_path=cache_path,
        use_cache=True,
    )

    # We expect 149 models (one sheet 51-1_1-173 is truncated and skipped).
    assert 148 <= data.N <= 150
    assert data.n_theta == 9
    assert data.theta_names == [
        "THICK", "MAJ_R", "AZIMUTH", "NUMBER_CHANNELS", "CHANNELS_WIDTH",
        "LEN", "AMPLITUDE", "RELATIVE", "PROP",
    ]
    # No NaN anywhere
    assert not np.isnan(data.theta).any()
    assert not np.isnan(data.d_sim_rates).any()
    assert not np.isnan(data.d_sim_cum).any()
    # Cluster ids in {0, 1, 2}, with each cluster represented
    cluster_ids = set(data.cluster_ids.tolist())
    assert cluster_ids == {0, 1, 2}
    # Producers and injectors
    assert all(w.startswith("WELL") for w in data.producer_wells)
    assert all(w.startswith("INJ") for w in data.injector_wells)
    assert len(data.injector_wells) == 6
    assert 16 <= len(data.producer_wells) <= 17


def test_d_sim_d_obs_alignment(root: Path, cache_path: Path) -> None:
    cfg = load_default_config(root)
    paths = cfg["io"]["paths"]
    ensemble = load_tnav_ensemble(
        parameters_path=root / paths["parameters"],
        dynamics_path=root / paths["dynamics"],
        cache_path=cache_path,
        use_cache=True,
    )
    noise_spec = load_noise_spec(root)
    obs = load_observations(
        history_path=root / paths["history"],
        noise_spec=noise_spec,
        producer_wells=ensemble.producer_wells,
        injector_wells=ensemble.injector_wells,
        rate_index=ensemble.rate_index,
        cum_index=ensemble.cum_index,
    )
    # Shapes line up
    assert obs.d_obs_rates.shape[0] == ensemble.d_sim_rates.shape[1]
    assert obs.d_obs_cum.shape[0] == ensemble.d_sim_cum.shape[1]
    # C_dd is diagonal and positive
    diag_r = np.diag(obs.C_dd_rates)
    assert (diag_r > 0).all()
    assert np.allclose(obs.C_dd_rates - np.diag(diag_r), 0)

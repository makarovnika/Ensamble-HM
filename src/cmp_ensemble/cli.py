"""cmp-ensemble CLI entry point."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import numpy as np

from cmp_ensemble.config import (
    load_default_config,
    load_noise_spec,
    project_root,
)
from cmp_ensemble.io.observations import load_observations
from cmp_ensemble.io.tnav_loader import load_tnav_ensemble
from cmp_ensemble.logging_setup import setup_logging

log = logging.getLogger("cmp_ensemble")


@click.group()
@click.option("--log-level", default="INFO", show_default=True)
def cli(log_level: str) -> None:
    """CMP Ensemble HM pipeline."""
    setup_logging(level=log_level, log_dir=Path("logs"))


@cli.command()
@click.option(
    "--phase",
    type=click.Choice(["0", "1", "2", "3", "all"]),
    required=True,
    help="Which phase to run.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Force re-parse of Excel inputs even if a cache exists.",
)
def run(phase: str, no_cache: bool) -> None:
    """Run one or more pipeline phases."""
    root = project_root()
    cfg = load_default_config(root)

    if phase in ("0", "all"):
        _run_phase_0(root, cfg, use_cache=not no_cache)
    if phase in ("1", "2", "3", "all") and phase != "0":
        click.echo(f"Phase {phase} is not yet implemented.")


def _run_phase_0(root: Path, cfg: dict, *, use_cache: bool) -> None:
    log.info("=" * 60)
    log.info("PHASE 0 — data preparation")
    log.info("=" * 60)
    paths = cfg["io"]["paths"]
    parameters_path = root / paths["parameters"]
    dynamics_path = root / paths["dynamics"]
    history_path = root / paths["history"]
    cache_path = root / cfg["io"]["cache_dir"] / "ensemble.h5"

    ensemble = load_tnav_ensemble(
        parameters_path=parameters_path,
        dynamics_path=dynamics_path,
        cache_path=cache_path,
        use_cache=use_cache,
    )

    noise_spec = load_noise_spec(root)
    obs = load_observations(
        history_path=history_path,
        noise_spec=noise_spec,
        producer_wells=ensemble.producer_wells,
        injector_wells=ensemble.injector_wells,
        rate_index=ensemble.rate_index,
        cum_index=ensemble.cum_index,
    )

    # Write matrices
    matrices_dir = root / "outputs" / "matrices"
    matrices_dir.mkdir(parents=True, exist_ok=True)
    np.save(matrices_dir / "theta_prior.npy", ensemble.theta)
    np.save(matrices_dir / "d_sim_rates.npy", ensemble.d_sim_rates)
    np.save(matrices_dir / "d_sim_cum.npy", ensemble.d_sim_cum)
    np.save(matrices_dir / "d_obs_rates.npy", obs.d_obs_rates)
    np.save(matrices_dir / "d_obs_cum.npy", obs.d_obs_cum)
    # Save C_dd diagonals (full diag matrices are wasteful; keep both)
    np.save(matrices_dir / "C_dd_rates_diag.npy", np.diag(obs.C_dd_rates))
    np.save(matrices_dir / "C_dd_cum_diag.npy", np.diag(obs.C_dd_cum))
    np.save(matrices_dir / "model_ids.npy", ensemble.model_ids)
    np.save(matrices_dir / "cluster_ids.npy", ensemble.cluster_ids)
    log.info(f"Phase 0 outputs written to {matrices_dir}")
    log.info(f"  theta_prior.npy        shape={ensemble.theta.shape}")
    log.info(f"  d_sim_rates.npy        shape={ensemble.d_sim_rates.shape}")
    log.info(f"  d_sim_cum.npy          shape={ensemble.d_sim_cum.shape}")
    log.info(f"  d_obs_rates.npy        shape={obs.d_obs_rates.shape}")
    log.info(f"  d_obs_cum.npy          shape={obs.d_obs_cum.shape}")
    log.info(f"  C_dd_rates_diag.npy    shape={np.diag(obs.C_dd_rates).shape}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

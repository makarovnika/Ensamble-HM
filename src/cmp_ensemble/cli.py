"""cmp-ensemble CLI entry point."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import numpy as np

from cmp_ensemble.config import (
    load_default_config,
    load_noise_spec,
    load_theta_schema,
    project_root,
)
from cmp_ensemble.ensemble.es_update import es_update
from cmp_ensemble.ensemble.localization import adaptive_correlation_localization
from cmp_ensemble.ensemble.state_vector import build_state_vector
from cmp_ensemble.io.observations import load_observations
from cmp_ensemble.io.tnav_loader import load_tnav_ensemble
from cmp_ensemble.logging_setup import setup_logging
from cmp_ensemble.qc.checks import run_qc_checks, write_qc_report_csvs
from cmp_ensemble.qc.cluster_migration import (
    build_cluster_migration_table,
    render_cluster_migration_html,
)

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
    if phase in ("1", "all"):
        _run_phase_1(root, cfg)
    if phase in ("2", "3") and phase != "0":
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


def _run_phase_1(root: Path, cfg: dict) -> None:
    log.info("=" * 60)
    log.info("PHASE 1 — ES update + QC")
    log.info("=" * 60)

    # Load Phase 0 artefacts (cached or freshly parsed)
    paths = cfg["io"]["paths"]
    cache_path = root / cfg["io"]["cache_dir"] / "ensemble.h5"
    ensemble = load_tnav_ensemble(
        parameters_path=root / paths["parameters"],
        dynamics_path=root / paths["dynamics"],
        cache_path=cache_path,
        use_cache=True,
    )
    obs = load_observations(
        history_path=root / paths["history"],
        noise_spec=__import__("cmp_ensemble.config", fromlist=["load_noise_spec"]).load_noise_spec(root),
        producer_wells=ensemble.producer_wells,
        injector_wells=ensemble.injector_wells,
        rate_index=ensemble.rate_index,
        cum_index=ensemble.cum_index,
    )

    # Build state vector: θ-only (no workflow controls available in this dataset)
    z, schema = build_state_vector(
        ensemble.theta,
        u=None,
        theta_names=ensemble.theta_names,
        include_controls=False,
    )

    # Phase 1 uses cumulative-only as d (per ТЗ §6 Task 3.1 default d_obs_type)
    D_sim = ensemble.d_sim_cum
    d_obs = obs.d_obs_cum
    C_dd = obs.C_dd_cum

    # Localization
    es_cfg = cfg["es_update"]
    factor = es_cfg["localization_threshold_factor"]
    method = es_cfg["localization_method"]
    mask, corr, threshold = adaptive_correlation_localization(
        z, D_sim, factor=factor, method=method
    )

    # ES update
    result = es_update(
        z, D_sim, d_obs, C_dd,
        localization_mask=mask,
        subspace_energy=es_cfg["subspace_energy"],
        seed=es_cfg["perturbation_seed"],
    )

    # QC
    qc = run_qc_checks(
        Z_prior=z,
        Z_post=result.Z_post,
        cluster_ids=ensemble.cluster_ids,
        theta_names=ensemble.theta_names,
    )

    # Write matrices
    matrices_dir = root / "outputs" / "matrices"
    matrices_dir.mkdir(parents=True, exist_ok=True)
    np.save(matrices_dir / "theta_post.npy", result.Z_post)
    np.save(matrices_dir / "K.npy", result.K)
    np.save(matrices_dir / "locmask.npy", mask)
    np.save(matrices_dir / "perturbations.npy", result.perturbations)
    np.save(matrices_dir / "singular_values.npy", result.singular_values)
    log.info(f"Phase 1 matrices written to {matrices_dir}")
    log.info(f"  theta_post.npy           shape={result.Z_post.shape}")
    log.info(f"  K.npy                    shape={result.K.shape}")
    log.info(f"  locmask.npy              shape={mask.shape} (kept "
             f"{int((mask > 0).sum())}/{mask.size})")
    log.info(f"  subspace components kept: {result.n_components_kept} "
             f"(energy={result.energy_kept:.4f})")

    # QC artefacts
    qc_dir = root / "outputs" / "qc"
    paths_written = write_qc_report_csvs(qc, qc_dir)
    for k, v in paths_written.items():
        log.info(f"  qc/{k}: {v}")

    # Cluster migration diagnostic
    theta_schema = load_theta_schema(root)
    ref_centroids = {
        int(cl): d["values"]
        for cl, d in theta_schema.get("cluster_centroids", {}).items()
    }
    migration_table = build_cluster_migration_table(
        Z_prior=z,
        Z_post=result.Z_post,
        cluster_ids=ensemble.cluster_ids,
        theta_names=ensemble.theta_names,
        reference_centroids=ref_centroids,
    )
    migration_table.to_csv(qc_dir / "cluster_migration.csv", index=False, encoding="utf-8")
    render_cluster_migration_html(migration_table, qc_dir / "cluster3_diagnostic.html")

    # Final status banner
    status = "PASSED" if qc.passed else "FAILED"
    log.info(f"QC summary: {status}  "
             f"collapse={qc.n_collapse_components} blowup={qc.n_blowup_components} "
             f"rank_prior={qc.rank_prior} rank_post={qc.rank_post} "
             f"BC={qc.bimodality_score:.3f}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

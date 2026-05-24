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
from cmp_ensemble.forecast.d_builders import build_d
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
@click.option(
    "--localization-factor",
    type=float,
    default=None,
    help="Override es_update.localization_threshold_factor (default 3.0).",
)
@click.option(
    "--localization-method",
    type=click.Choice(["hard", "soft_taper"]),
    default=None,
    help="Override es_update.localization_method.",
)
@click.option(
    "--d-obs-type",
    type=click.Choice(["cumulative", "rates", "hybrid"]),
    default=None,
    help="Override the observation vector type (cumulative | rates | hybrid).",
)
@click.option(
    "--variant-label",
    type=str,
    default=None,
    help="If set, write outputs to outputs/phase1_variants/<label>/ instead of "
    "outputs/matrices and outputs/qc.",
)
def run(
    phase: str,
    no_cache: bool,
    localization_factor: float | None,
    localization_method: str | None,
    d_obs_type: str | None,
    variant_label: str | None,
) -> None:
    """Run one or more pipeline phases."""
    root = project_root()
    cfg = load_default_config(root)

    overrides = {
        "localization_factor": localization_factor,
        "localization_method": localization_method,
        "d_obs_type": d_obs_type,
        "variant_label": variant_label,
    }

    if phase in ("0", "all"):
        _run_phase_0(root, cfg, use_cache=not no_cache)
    if phase in ("1", "all"):
        _run_phase_1(root, cfg, overrides=overrides)
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


def _run_phase_1(root: Path, cfg: dict, *, overrides: dict | None = None) -> dict:
    """Run Phase 1 with optional overrides. Returns a dict of summary metrics
    so that callers (e.g. compare-phase1) can collect cross-variant results.
    """
    overrides = overrides or {}
    log.info("=" * 60)
    log.info("PHASE 1 — ES update + QC")
    log.info("=" * 60)

    # Resolve overrides
    es_cfg = dict(cfg["es_update"])
    if overrides.get("localization_factor") is not None:
        es_cfg["localization_threshold_factor"] = float(overrides["localization_factor"])
    if overrides.get("localization_method") is not None:
        es_cfg["localization_method"] = overrides["localization_method"]
    d_obs_type = overrides.get("d_obs_type") or "cumulative"
    variant_label = overrides.get("variant_label")

    if variant_label:
        out_root = root / "outputs" / "phase1_variants" / variant_label
    else:
        out_root = root / "outputs"
    matrices_dir = out_root / "matrices"
    qc_dir = out_root / "qc"

    log.info(f"  d_obs_type={d_obs_type}  "
             f"localization_factor={es_cfg['localization_threshold_factor']}  "
             f"localization_method={es_cfg['localization_method']}  "
             f"variant_label={variant_label or '<default>'}")

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
        noise_spec=load_noise_spec(root),
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

    # Build d arrays for the requested mode
    D_sim, d_obs, C_dd, _index = build_d(ensemble, obs, d_obs_type)
    log.info(f"  D_sim shape={D_sim.shape}, d_obs shape={d_obs.shape}")

    # Localization
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

    n_kept = int((mask > 0).sum())
    return {
        "variant_label": variant_label,
        "d_obs_type": d_obs_type,
        "localization_factor": factor,
        "localization_method": method,
        "n_d": D_sim.shape[1],
        "n_K_kept": n_kept,
        "n_K_total": mask.size,
        "frac_K_kept": n_kept / mask.size,
        "subspace_r": result.n_components_kept,
        "subspace_energy": result.energy_kept,
        "qc_passed": qc.passed,
        "n_collapse": qc.n_collapse_components,
        "n_blowup": qc.n_blowup_components,
        "rank_post": qc.rank_post,
        "bimodality_score": qc.bimodality_score,
        "spread_retention": qc.spread_retention,
        "cluster_centroid_shift": qc.cluster_centroid_shift,
        "matrices_dir": str(matrices_dir),
        "qc_dir": str(qc_dir),
    }


@cli.command(name="compare-phase1")
def compare_phase1() -> None:
    """Run three Phase 1 variants and produce a side-by-side comparison."""
    root = project_root()
    cfg = load_default_config(root)
    variants = [
        {
            "label": "a_hard_3_cum",
            "overrides": {
                "localization_factor": 3.0,
                "localization_method": "hard",
                "d_obs_type": "cumulative",
            },
            "description": "Hard 3/sqrt(N), cumulative (current default)",
        },
        {
            "label": "b_hard_2_cum",
            "overrides": {
                "localization_factor": 2.0,
                "localization_method": "hard",
                "d_obs_type": "cumulative",
            },
            "description": "Hard 2/sqrt(N), cumulative",
        },
        {
            "label": "c_hard_3_hybrid",
            "overrides": {
                "localization_factor": 3.0,
                "localization_method": "hard",
                "d_obs_type": "hybrid",
            },
            "description": "Hard 3/sqrt(N), hybrid (cum + annual rate snapshots)",
        },
    ]
    summaries = []
    for v in variants:
        v["overrides"]["variant_label"] = v["label"]
        log.info("")
        log.info("#" * 70)
        log.info(f"# Variant {v['label']}: {v['description']}")
        log.info("#" * 70)
        summary = _run_phase_1(root, cfg, overrides=v["overrides"])
        summary["description"] = v["description"]
        summaries.append(summary)

    # Build comparison table
    out_dir = root / "outputs" / "phase1_variants"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for s in summaries:
        rows.append(
            {
                "variant": s["variant_label"],
                "description": s["description"],
                "d_obs_type": s["d_obs_type"],
                "factor": s["localization_factor"],
                "method": s["localization_method"],
                "n_d": s["n_d"],
                "K_kept": s["n_K_kept"],
                "K_total": s["n_K_total"],
                "K_kept_pct": round(100 * s["frac_K_kept"], 2),
                "subspace_r": s["subspace_r"],
                "subspace_energy": round(s["subspace_energy"], 4),
                "qc_passed": s["qc_passed"],
                "collapse": s["n_collapse"],
                "blowup": s["n_blowup"],
                "BC": round(s["bimodality_score"], 3),
            }
        )
    summary_df = __import__("pandas").DataFrame(rows)
    summary_csv = out_dir / "summary.csv"
    summary_df.to_csv(summary_csv, index=False, encoding="utf-8")
    log.info("")
    log.info("=" * 70)
    log.info("COMPARISON SUMMARY")
    log.info("=" * 70)
    log.info(f"\n{summary_df.to_string(index=False)}")
    log.info(f"\nWritten to: {summary_csv}")

    # spread_retention side-by-side
    pd = __import__("pandas")
    sr_frames = []
    for s in summaries:
        df = s["spread_retention"].copy()
        df = df[["component", "spread_retention"]].rename(
            columns={"spread_retention": s["variant_label"]}
        )
        sr_frames.append(df.set_index("component"))
    sr_compare = pd.concat(sr_frames, axis=1).reset_index()
    sr_csv = out_dir / "spread_retention_compare.csv"
    sr_compare.to_csv(sr_csv, index=False, encoding="utf-8")
    log.info(f"\nspread_retention by variant:\n{sr_compare.to_string(index=False)}")
    log.info(f"Written to: {sr_csv}")

    # cluster centroid shifts compared across variants
    cc_frames = []
    for s in summaries:
        df = s["cluster_centroid_shift"][
            ["cluster", "component", "shift_in_prior_sigma"]
        ].copy()
        df = df.rename(columns={"shift_in_prior_sigma": s["variant_label"]})
        cc_frames.append(df.set_index(["cluster", "component"]))
    cc_compare = pd.concat(cc_frames, axis=1).reset_index()
    cc_csv = out_dir / "centroid_shift_compare.csv"
    cc_compare.to_csv(cc_csv, index=False, encoding="utf-8")
    log.info(f"\nCentroid shift (in σ_prior) by variant — first 12 rows:")
    log.info(f"\n{cc_compare.head(12).to_string(index=False)}")
    log.info(f"Written to: {cc_csv}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

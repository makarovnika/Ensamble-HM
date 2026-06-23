"""cmp-ensemble CLI entry point."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import numpy as np
import pandas as pd

from cmp_ensemble.config import (
    load_default_config,
    load_noise_spec,
    load_theta_schema,
    project_root,
)
from cmp_ensemble.ensemble.dedup import deduplicate_ensemble
from cmp_ensemble.ensemble.es_update import es_update
from cmp_ensemble.ensemble.localization import adaptive_correlation_localization
from cmp_ensemble.ensemble.state_vector import build_state_vector
from cmp_ensemble.forecast.d_builders import build_d
from cmp_ensemble.forecast.setups import (
    build_metrics_summary,
    run_setup1_naive,
    run_setup2_localized,
    run_setup3_full,
)
from cmp_ensemble.io.forecast_loader import load_tnav_forecast
from cmp_ensemble.io.split import split_history
from cmp_ensemble.metadata import write_sidecar
from cmp_ensemble.viz.ablation import (
    build_latex_ablation_table,
    fig03_ablation_p10p90,
    fig04_cumulative_scatter,
)
from cmp_ensemble.viz.diagnostics import (
    fig01_pipeline,
    fig02_qc_spread,
    fig06_cluster3_migration,
    mirror_to_article_assets,
)
from cmp_ensemble.viz.tier_b import render_all_tier_b
from cmp_ensemble.viz.tier_c import render_all_tier_c
from cmp_ensemble.io.observations import load_observations
from cmp_ensemble.io.tnav_loader import load_tnav_ensemble
from cmp_ensemble.logging_setup import setup_logging
from cmp_ensemble.qc.checks import run_qc_checks, write_qc_report_csvs
from cmp_ensemble.qc.cluster_migration import (
    build_cluster_migration_table,
    render_cluster_migration_html,
)
from cmp_ensemble.qc.misfit import per_well_misfit_summary, per_well_misfit_table
from cmp_ensemble.selection.compute_planner import (
    plan_resimulation,
    write_plan_to_csv,
)
from cmp_ensemble.selection.linear_proxy import build_per_cluster_proxies
from cmp_ensemble.selection.mahalanobis import (
    mahalanobis_distance,
    rank_by_parameter_change,
)
from cmp_ensemble.selection.validation import validate_proxy

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
@click.option(
    "--clip-to-prior",
    is_flag=True,
    default=False,
    help="Clip θ_post to the prior support box defined in configs/theta_schema.yaml.",
)
@click.option(
    "--dedup-ensemble",
    is_flag=True,
    default=False,
    help="In Phase 2, collapse duplicate model_ids by averaging their θ_post copies.",
)
@click.option(
    "--keep-ooe",
    is_flag=True,
    default=False,
    help="In Phase 3, keep out-of-envelope proxy predictions in setup2/3.",
)
@click.option(
    "--hindcast",
    is_flag=True,
    default=False,
    help="Use the train/val split for an honest hindcast: ES on the train slice, "
    "Phase 3 metrics on the val slice with d_truth = observed values.",
)
@click.option(
    "--train-years",
    type=int,
    default=6,
    show_default=True,
    help="Number of leading calendar years to use as training history under --hindcast.",
)
@click.option(
    "--val-years",
    type=int,
    default=2,
    show_default=True,
    help="Number of trailing calendar years to hold out as validation under --hindcast.",
)
def run(
    phase: str,
    no_cache: bool,
    localization_factor: float | None,
    localization_method: str | None,
    d_obs_type: str | None,
    variant_label: str | None,
    clip_to_prior: bool,
    dedup_ensemble: bool,
    keep_ooe: bool,
    hindcast: bool,
    train_years: int,
    val_years: int,
) -> None:
    """Run one or more pipeline phases."""
    root = project_root()
    cfg = load_default_config(root)

    overrides = {
        "localization_factor": localization_factor,
        "localization_method": localization_method,
        "d_obs_type": d_obs_type,
        "variant_label": variant_label,
        "clip_to_prior": clip_to_prior,
        "dedup_ensemble": dedup_ensemble,
        "hindcast": hindcast,
        "train_years": train_years,
        "val_years": val_years,
    }

    if phase in ("0", "all"):
        _run_phase_0(root, cfg, use_cache=not no_cache)
    if phase in ("1", "all"):
        _run_phase_1(root, cfg, overrides=overrides)
    if phase in ("2", "all"):
        _run_phase_2(root, cfg, dedup=dedup_ensemble)
    if phase in ("3", "all"):
        _run_phase_3(root, cfg, keep_ooe=keep_ooe, overrides=overrides)


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

    # Write matrices + sidecars
    matrices_dir = root / "outputs" / "matrices"
    matrices_dir.mkdir(parents=True, exist_ok=True)
    meta_extra_p0 = {"phase": 0, "N": int(ensemble.N), "n_theta": int(ensemble.n_theta)}
    for name, arr in [
        ("theta_prior", ensemble.theta),
        ("d_sim_rates", ensemble.d_sim_rates),
        ("d_sim_cum", ensemble.d_sim_cum),
        ("d_obs_rates", obs.d_obs_rates),
        ("d_obs_cum", obs.d_obs_cum),
        ("C_dd_rates_diag", np.diag(obs.C_dd_rates)),
        ("C_dd_cum_diag", np.diag(obs.C_dd_cum)),
        ("model_ids", ensemble.model_ids),
        ("cluster_ids", ensemble.cluster_ids),
    ]:
        p = matrices_dir / f"{name}.npy"
        np.save(p, arr)
        write_sidecar(p, config=cfg, extra=meta_extra_p0, repo_root=root)
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
    D_sim, d_obs, C_dd, d_index = build_d(ensemble, obs, d_obs_type)
    log.info(f"  D_sim shape={D_sim.shape}, d_obs shape={d_obs.shape}")

    # Hindcast: restrict ES to the train slice and remember the val slice
    # for Phase 3 d_truth.
    hindcast_split = None
    if overrides.get("hindcast"):
        ty = int(overrides.get("train_years", 6))
        vy = int(overrides.get("val_years", 2))
        hindcast_split = split_history(
            rate_index=ensemble.rate_index,
            cum_index=ensemble.cum_index,
            time_steps=ensemble.time_steps,
            train_years=ty, val_years=vy,
        )
        if d_obs_type == "cumulative":
            train_mask = hindcast_split.train_cum_mask
        elif d_obs_type == "rates":
            train_mask = hindcast_split.train_rate_mask
        else:  # hybrid = cum_index then rate_index — concatenate masks
            train_mask = np.concatenate(
                [hindcast_split.train_cum_mask, hindcast_split.train_rate_mask]
            )
        D_sim = D_sim[:, train_mask]
        d_obs = d_obs[train_mask]
        C_dd = C_dd[np.ix_(train_mask, train_mask)]
        d_index = [e for e, keep in zip(d_index, train_mask) if keep]
        log.info(
            f"  HINDCAST: train years {hindcast_split.train_years}, "
            f"val years {hindcast_split.val_years}; "
            f"D_sim restricted to train slice → shape={D_sim.shape}"
        )

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

    # Load parameter ranges from theta_schema.yaml for physical-bounds QC
    theta_schema = load_theta_schema(root)
    parameter_ranges: dict[str, tuple[float, float]] = {}
    for p in theta_schema.get("parameters", []):
        if "range" in p:
            lo, hi = p["range"]
            parameter_ranges[p["name"]] = (float(lo), float(hi))

    # Optional clipping of θ_post to the prior support box
    Z_post_for_qc = result.Z_post
    if overrides.get("clip_to_prior") and parameter_ranges:
        Z_post_clipped = result.Z_post.copy()
        n_clipped = 0
        for j, name in enumerate(ensemble.theta_names):
            if name not in parameter_ranges:
                continue
            lo, hi = parameter_ranges[name]
            below = Z_post_clipped[:, j] < lo
            above = Z_post_clipped[:, j] > hi
            n_clipped += int(below.sum() + above.sum())
            Z_post_clipped[below, j] = lo
            Z_post_clipped[above, j] = hi
        log.warning(f"--clip-to-prior: clamped {n_clipped} θ_post entries to prior bounds")
        result.Z_post = Z_post_clipped
        Z_post_for_qc = Z_post_clipped

    # QC
    qc = run_qc_checks(
        Z_prior=z,
        Z_post=Z_post_for_qc,
        cluster_ids=ensemble.cluster_ids,
        theta_names=ensemble.theta_names,
        parameter_ranges=parameter_ranges,
        model_ids=ensemble.model_ids,
    )

    # Write matrices + sidecar metadata
    matrices_dir.mkdir(parents=True, exist_ok=True)
    seed_phase1 = int(es_cfg["perturbation_seed"])
    meta_extra_phase1 = {
        "phase": 1,
        "d_obs_type": d_obs_type,
        "localization_factor": float(factor),
        "localization_method": method,
        "subspace_energy": float(es_cfg["subspace_energy"]),
        "N": int(z.shape[0]),
        "n_z": int(z.shape[1]),
        "n_d": int(D_sim.shape[1]),
        "clip_to_prior": bool(overrides.get("clip_to_prior", False)),
    }
    for name, arr in [
        ("theta_post", result.Z_post),
        ("K", result.K),
        ("locmask", mask),
        ("perturbations", result.perturbations),
        ("singular_values", result.singular_values),
    ]:
        p = matrices_dir / f"{name}.npy"
        np.save(p, arr)
        write_sidecar(p, config=cfg, seed=seed_phase1, extra=meta_extra_phase1, repo_root=root)
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

    # Per-well misfit diagnostic (improve-E) — use the SAME index as was fed
    # into the ES update so the shapes match (especially under --hindcast,
    # where d_index is the train-slice subset).
    misfit_index = d_index
    misfit = per_well_misfit_table(d_obs, D_sim, misfit_index)
    p_misfit = qc_dir / "per_well_misfit.csv"
    p_misfit_summary = qc_dir / "per_well_misfit_summary.csv"
    misfit.to_csv(p_misfit, index=False, encoding="utf-8")
    per_well_misfit_summary(misfit).to_csv(p_misfit_summary, index=False, encoding="utf-8")
    log.info(f"  → qc/per_well_misfit.csv ({len(misfit)} rows)")
    log.info(f"  → qc/per_well_misfit_summary.csv")

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


def _run_phase_2(root: Path, cfg: dict, *, dedup: bool = False) -> None:
    log.info("=" * 60)
    log.info("PHASE 2 — model selection + linear forecast proxy")
    log.info("=" * 60)
    if dedup:
        log.info("  --dedup-ensemble: collapsing duplicate model_ids by averaging θ_post")

    paths = cfg["io"]["paths"]
    cache_path = root / cfg["io"]["cache_dir"] / "ensemble.h5"
    forecast_cache = root / cfg["io"]["cache_dir"] / "forecast.h5"

    # Phase 0 ensemble (history)
    ensemble = load_tnav_ensemble(
        parameters_path=root / paths["parameters"],
        dynamics_path=root / paths["dynamics"],
        cache_path=cache_path,
        use_cache=True,
    )
    # Phase 1 posterior
    theta_post = np.load(root / "outputs" / "matrices" / "theta_post.npy")
    if theta_post.shape != ensemble.theta.shape:
        raise RuntimeError(
            f"theta_post shape {theta_post.shape} != theta_prior {ensemble.theta.shape}. "
            "Run Phase 1 first (or re-run if data changed)."
        )

    # Optional: collapse duplicates BEFORE ranking and proxy training.
    if dedup:
        d = deduplicate_ensemble(
            Z_prior=ensemble.theta,
            Z_post=theta_post,
            model_ids=ensemble.model_ids,
            cluster_ids=ensemble.cluster_ids,
            seeds=ensemble.seeds,
            sheet_names=ensemble.sheet_names,
        )
        theta_prior_for_rank = d.Z_prior_dedup
        theta_post_for_rank = d.Z_post_dedup
        model_ids_for_rank = d.model_ids_dedup
        cluster_ids_for_rank = d.primary_cluster_ids
        seeds_for_rank = d.seeds_dedup
        sheet_names_for_rank = d.sheet_names_dedup
    else:
        theta_prior_for_rank = ensemble.theta
        theta_post_for_rank = theta_post
        model_ids_for_rank = ensemble.model_ids
        cluster_ids_for_rank = ensemble.cluster_ids
        seeds_for_rank = ensemble.seeds
        sheet_names_for_rank = ensemble.sheet_names

    N_eff = theta_prior_for_rank.shape[0]

    # Mahalanobis ranking
    log.info("ranking models by ||Δθ||_M ...")
    maha = mahalanobis_distance(theta_prior_for_rank, theta_post_for_rank)
    order = rank_by_parameter_change(theta_prior_for_rank, theta_post_for_rank)
    out_dir = root / "outputs" / "selection"
    out_dir.mkdir(parents=True, exist_ok=True)
    ranking_df = pd.DataFrame(
        {
            "rank": np.arange(1, N_eff + 1),
            "model_id": model_ids_for_rank[order],
            "cluster_id": cluster_ids_for_rank[order],
            "seed": seeds_for_rank[order],
            "sheet": [sheet_names_for_rank[i] for i in order],
            "maha_distance": maha[order],
        }
    )
    p_rank = out_dir / "mahalanobis_ranking.csv"
    ranking_df.to_csv(p_rank, index=False, encoding="utf-8")
    write_sidecar(
        p_rank, config=cfg, repo_root=root,
        extra={"phase": 2, "step": "mahalanobis_ranking", "N": int(ensemble.N)},
    )
    log.info(f"  → outputs/selection/mahalanobis_ranking.csv  N={len(ranking_df)}")

    # ── Compute planner (Task 2.3): partition into resim / proxy / validation
    selection_cfg = cfg.get("selection", {})
    top_x = int(selection_cfg.get("default_top_x", 80))
    validation_n = int(selection_cfg.get("proxy_validation_n", 10))
    plan = plan_resimulation(
        ranking_df,
        top_x=top_x,
        validation_n=validation_n,
        seed=int(cfg["es_update"].get("perturbation_seed", 42)),
    )
    plan_paths = write_plan_to_csv(plan, out_dir)
    for k, p in plan_paths.items():
        write_sidecar(
            Path(p), config=cfg, repo_root=root,
            extra={"phase": 2, "step": "compute_planner",
                   "top_x": top_x, "validation_n": validation_n,
                   "n_resimulate": len(plan.to_resimulate),
                   "n_proxy": len(plan.proxy_only),
                   "n_validation": len(plan.validation_subset)},
        )
        log.info(f"  → outputs/selection/{Path(p).name}")
    log.info(
        f"  plan: top_x={len(plan.to_resimulate)} to re-simulate, "
        f"{len(plan.proxy_only)} via proxy, "
        f"{len(plan.validation_subset)} for validation"
    )

    # Forecast ingest (decoded_results.xlsx) — try each configured path,
    # tolerating network failures.
    decoded_path = None
    for raw in cfg["io"].get("forecast_paths", []):
        candidate = (root / raw) if not raw.startswith("//") else Path(raw)
        try:
            ok = candidate.exists()
        except OSError as exc:
            log.warning(f"  forecast path {candidate}: {exc}")
            continue
        if ok:
            decoded_path = candidate
            break
    if decoded_path is None:
        log.error(
            "decoded_results.xlsx is not reachable at any configured path. "
            "Either restore the UNC share or copy the file into "
            "data/forecast/decoded_results.xlsx (local fallback)."
        )
        log.error("Phase 2 stops at Mahalanobis ranking. "
                 "Re-run when the forecast file is available.")
        return
    log.info(f"using forecast workbook: {decoded_path}")
    # Build (cluster_id, seed) → model_id lookup. The same seed can appear in
    # multiple clusters (a model "near both centroids"), so the key is the pair.
    cluster_seed_to_model_id = {
        (int(cid), int(s)): int(mid)
        for s, mid, cid in zip(
            ensemble.seeds, ensemble.model_ids, ensemble.cluster_ids
        )
    }
    # Wipe any stale forecast cache from the previous buggy run.
    if forecast_cache.exists():
        forecast_cache.unlink()
    forecast = load_tnav_forecast(
        decoded_path=decoded_path,
        producer_wells=ensemble.producer_wells,
        cluster_seed_to_model_id=cluster_seed_to_model_id,
        cache_path=forecast_cache,
        use_cache=False,
    )

    # Pick the θ_prior rows that correspond to the forecast models.
    # Without dedup we key by (cluster_id, seed). With dedup we key by model_id
    # (which is now unique in our dedup'd arrays).
    if dedup:
        mid_to_row = {int(m): i for i, m in enumerate(model_ids_for_rank)}
        train_indices = np.array(
            [mid_to_row[int(m)] for m in forecast.model_ids if int(m) in mid_to_row],
            dtype=int,
        )
        # Some forecast models may be the SECOND copy of a deduplicated row.
        # We use the deduped row index; the forecast model_id matches uniquely.
        kept_forecast_mask = np.array(
            [int(m) in mid_to_row for m in forecast.model_ids], dtype=bool
        )
        Z_train = theta_prior_for_rank[train_indices]
        cluster_ids_train = cluster_ids_for_rank[train_indices]
        D_train = forecast.d_forecast_cum[kept_forecast_mask]
    else:
        cluster_seed_to_row = {
            (int(cid), int(s)): i
            for i, (cid, s) in enumerate(zip(ensemble.cluster_ids, ensemble.seeds))
        }
        train_indices = np.array(
            [
                cluster_seed_to_row[(int(cid), int(s))]
                for cid, s in zip(forecast.cluster_ids, forecast.seeds)
            ],
            dtype=int,
        )
        Z_train = ensemble.theta[train_indices]
        cluster_ids_train = forecast.cluster_ids
        D_train = forecast.d_forecast_cum

    log.info(
        f"proxy training input: Z {Z_train.shape}, D {D_train.shape}, "
        f"per-cluster sizes "
        + ", ".join(
            f"c{cl}={(cluster_ids_train == cl).sum()}"
            for cl in sorted(set(cluster_ids_train.tolist()))
        )
    )

    # Per-cluster linear proxy
    log.info("training per-cluster linear proxy ...")
    proxies = build_per_cluster_proxies(Z_train, D_train, cluster_ids_train)

    # Save proxies
    proxy_dir = out_dir / "proxies"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    for cl, p in proxies.items():
        np.savez(
            proxy_dir / f"proxy_cluster{cl}.npz",
            S=p.S,
            z_bar=p.z_bar,
            d_bar=p.d_bar,
            envelope_min=p.envelope_min,
            envelope_max=p.envelope_max,
            n_train=p.n_train,
        )
        log.info(f"  → outputs/selection/proxies/proxy_cluster{cl}.npz "
                 f"(n_train={p.n_train})")

    # Validation: hold out 12% within each cluster
    log.info("running proxy validation (12% held out per cluster) ...")
    val = validate_proxy(Z_train, D_train, cluster_ids_train, val_fraction=0.12, seed=42)
    val.per_cluster.to_csv(out_dir / "proxy_validation_per_cluster.csv", index=False)
    val.val_predictions.to_csv(out_dir / "proxy_validation_per_member.csv", index=False)
    pd.Series(val.aggregate).to_csv(out_dir / "proxy_validation_aggregate.csv", header=True)
    log.info(f"  proxy verdict: {val.verdict}")
    log.info(f"  per-cluster:\n{val.per_cluster.to_string(index=False)}")
    log.info(f"  aggregate: {dict(val.aggregate)}")

    # Use the trained proxies to estimate d_forecast for ALL 149 models given θ_post
    log.info("applying proxies to θ_post for all members ...")
    d_forecast_post_rows: list[np.ndarray] = []
    out_of_envelope_rows: list[bool] = []
    valid_rows: list[bool] = []
    for i in range(ensemble.N):
        cl = int(ensemble.cluster_ids[i])
        proxy = proxies.get(cl)
        if proxy is None:
            d_forecast_post_rows.append(np.full(D_train.shape[1], np.nan))
            out_of_envelope_rows.append(True)
            valid_rows.append(False)
            continue
        z = theta_post[i]
        d_forecast_post_rows.append(proxy.predict(z))
        out_of_envelope_rows.append(not proxy.in_envelope(z))
        valid_rows.append(True)
    d_forecast_post = np.vstack(d_forecast_post_rows)
    p_fp = out_dir / "d_forecast_post_via_proxy.npy"
    p_oo = out_dir / "d_forecast_post_out_of_envelope.npy"
    np.save(p_fp, d_forecast_post)
    np.save(p_oo, np.asarray(out_of_envelope_rows))
    write_sidecar(
        p_fp, config=cfg, repo_root=root,
        extra={"phase": 2, "step": "proxy_apply", "shape": list(d_forecast_post.shape),
               "n_in_envelope": int((~np.asarray(out_of_envelope_rows)).sum()),
               "proxy_verdict": val.verdict,
               "proxy_median_rel_err": float(val.aggregate["median_rel_err"])},
    )
    n_oo = int(sum(out_of_envelope_rows))
    log.info(
        f"  → outputs/selection/d_forecast_post_via_proxy.npy "
        f"shape={d_forecast_post.shape}, out-of-envelope: {n_oo}/{ensemble.N}"
    )

    # Final summary
    log.info("Phase 2 summary:")
    log.info(f"  Mahalanobis ranking: N={ensemble.N}")
    log.info(f"  Proxy clusters trained: {sorted(proxies.keys())}")
    log.info(f"  Proxy verdict: {val.verdict} (median rel err = "
             f"{val.aggregate['median_rel_err']:.3f})")
    log.info(f"  Posterior-θ predictions: {ensemble.N - n_oo}/{ensemble.N} in-envelope")


def _run_phase_3(
    root: Path,
    cfg: dict,
    *,
    keep_ooe: bool = False,
    overrides: dict | None = None,
) -> None:
    overrides = overrides or {}
    hindcast_mode = bool(overrides.get("hindcast"))
    log.info("=" * 60)
    log.info("PHASE 3 — ablation forecast (setup1 / setup2 / setup3)")
    log.info("=" * 60)
    log.info(f"  keep_ooe={keep_ooe}, hindcast={hindcast_mode}")

    paths = cfg["io"]["paths"]
    forecast_cache = root / cfg["io"]["cache_dir"] / "forecast.h5"
    if not hindcast_mode and not forecast_cache.exists():
        log.error(
            "outputs/cache/forecast.h5 not present. Run `cmp-ensemble run --phase 2` first."
        )
        return
    cache_path = root / cfg["io"]["cache_dir"] / "ensemble.h5"
    ensemble = load_tnav_ensemble(
        parameters_path=root / paths["parameters"],
        dynamics_path=root / paths["dynamics"],
        cache_path=cache_path,
        use_cache=True,
    )
    # Load observations for hindcast d_truth (regardless of mode)
    obs = load_observations(
        history_path=root / paths["history"],
        noise_spec=load_noise_spec(root),
        producer_wells=ensemble.producer_wells,
        injector_wells=ensemble.injector_wells,
        rate_index=ensemble.rate_index,
        cum_index=ensemble.cum_index,
    )

    # ── Branch: hindcast mode vs forecast mode ────────────────────────────
    if hindcast_mode:
        # Build a per-cluster proxy here in Phase 3 (we can't reuse the Phase 2
        # forecast proxy because that one was trained on 2019-2024 forecast,
        # not on the held-out val slice).
        ty = int(overrides.get("train_years", 6))
        vy = int(overrides.get("val_years", 2))
        split = split_history(
            rate_index=ensemble.rate_index,
            cum_index=ensemble.cum_index,
            time_steps=ensemble.time_steps,
            train_years=ty, val_years=vy,
        )
        log.info(f"  HINDCAST split: train {split.train_years} → val {split.val_years}")
        d_baseline_val = ensemble.d_sim_cum[:, split.val_cum_mask]  # (149, n_d_val)
        d_truth_val = obs.d_obs_cum[split.val_cum_mask]              # (n_d_val,)
        index = [e for e, keep in zip(ensemble.cum_index, split.val_cum_mask) if keep]
        cluster_ids_baseline = ensemble.cluster_ids
        cluster_ids_proxy = ensemble.cluster_ids
        log.info(
            f"  baseline (val slice): shape={d_baseline_val.shape}, "
            f"d_truth shape={d_truth_val.shape}"
        )

        # Train a per-cluster proxy on (θ_prior, d_baseline_val) so we can
        # project ES-updated θ_post onto the val slice.
        from cmp_ensemble.selection.linear_proxy import build_per_cluster_proxies
        proxies = build_per_cluster_proxies(
            ensemble.theta, d_baseline_val, ensemble.cluster_ids
        )
        theta_post = np.load(root / "outputs" / "matrices" / "theta_post.npy")
        d_proxy = np.zeros_like(d_baseline_val)
        out_of_envelope = np.zeros(ensemble.N, dtype=bool)
        for i in range(ensemble.N):
            cl = int(ensemble.cluster_ids[i])
            proxy = proxies.get(cl)
            if proxy is None:
                d_proxy[i] = np.nan
                out_of_envelope[i] = True
                continue
            d_proxy[i] = proxy.predict(theta_post[i])
            out_of_envelope[i] = not proxy.in_envelope(theta_post[i])
        d_baseline_for_setups = d_baseline_val
        evaluation_mode = f"train_val_hindcast_{ty}+{vy}"
        d_truth_for_metrics = d_truth_val
    else:
        # Reconstruct seed_to_model mapping for the forecast cache reload
        cluster_seed_to_model_id = {
            (int(cid), int(s)): int(mid)
            for s, mid, cid in zip(ensemble.seeds, ensemble.model_ids, ensemble.cluster_ids)
        }
        decoded_path = None
        for raw in cfg["io"].get("forecast_paths", []):
            candidate = (root / raw) if not raw.startswith("//") else Path(raw)
            try:
                if candidate.exists():
                    decoded_path = candidate
                    break
            except OSError:
                continue
        forecast = load_tnav_forecast(
            decoded_path=decoded_path or Path("__missing__"),
            producer_wells=ensemble.producer_wells,
            cluster_seed_to_model_id=cluster_seed_to_model_id,
            cache_path=forecast_cache,
            use_cache=True,
        )
        log.info(f"baseline forecast: M={forecast.model_ids.size}, cluster counts: "
                 + ", ".join(f"c{cl}={(forecast.cluster_ids == cl).sum()}"
                              for cl in sorted(set(forecast.cluster_ids.tolist()))))
        proxy_path = root / "outputs" / "selection" / "d_forecast_post_via_proxy.npy"
        oo_path = root / "outputs" / "selection" / "d_forecast_post_out_of_envelope.npy"
        if not proxy_path.exists() or not oo_path.exists():
            log.error("Phase 2 artefacts missing. Run `cmp-ensemble run --phase 2` first.")
            return
        d_proxy = np.load(proxy_path)
        out_of_envelope = np.load(oo_path)
        cluster_ids_baseline = forecast.cluster_ids
        cluster_ids_proxy = ensemble.cluster_ids
        index = forecast.cum_index
        d_baseline_for_setups = forecast.d_forecast_cum
        evaluation_mode = "no_truth_baseline_only"
        d_truth_for_metrics = None
    # ─────────────────────────────────────────────────────────────────────

    # Run setups
    s1 = run_setup1_naive(
        d_baseline=d_baseline_for_setups,
        index=index,
        cluster_ids=cluster_ids_baseline,
        d_truth=d_truth_for_metrics,
    )
    s2 = run_setup2_localized(
        d_baseline=d_baseline_for_setups,
        d_proxy_post=d_proxy,
        index=index,
        cluster_ids_baseline=cluster_ids_baseline,
        cluster_ids_proxy=cluster_ids_proxy,
        out_of_envelope=out_of_envelope,
        d_truth=d_truth_for_metrics,
        keep_out_of_envelope=keep_ooe,
    )
    s3 = run_setup3_full(
        d_baseline=d_baseline_for_setups,
        d_proxy_post=d_proxy,
        index=index,
        cluster_ids_baseline=cluster_ids_baseline,
        cluster_ids_proxy=cluster_ids_proxy,
        out_of_envelope=out_of_envelope,
        d_truth=d_truth_for_metrics,
        controls_available=False,
        keep_out_of_envelope=keep_ooe,
    )
    results = [s1, s2, s3]
    for r in results:
        log.info(f"  {r.label}: M={r.d_forecast.shape[0]}, notes: {'; '.join(r.notes) or 'none'}")

    out_dir = root / "outputs" / "forecast"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-setup CSV
    from cmp_ensemble.forecast.aggregation import field_total_quantiles
    for r in results:
        ft = field_total_quantiles(r.d_forecast, r.index)
        p_ft = out_dir / f"{r.label}_field_total_quantiles.csv"
        ft.to_csv(p_ft, index=False, encoding="utf-8")
        write_sidecar(
            p_ft, config=cfg, repo_root=root,
            extra={"phase": 3, "setup": r.label, "M": int(r.d_forecast.shape[0]),
                   "evaluation_mode": evaluation_mode},
        )
        log.info(f"  → outputs/forecast/{p_ft.name} ({len(ft)} rows)")

    # Summary table — stamp evaluation_mode in a leading column too.
    summary = build_metrics_summary(results)
    summary.insert(0, "evaluation_mode", evaluation_mode)
    p_sum = out_dir / "metrics_summary.csv"
    summary.to_csv(p_sum, index=False, encoding="utf-8")
    write_sidecar(
        p_sum, config=cfg, repo_root=root,
        extra={"phase": 3, "evaluation_mode": evaluation_mode},
    )
    log.info(f"  → outputs/forecast/metrics_summary.csv")
    log.info(f"\n{summary.to_string(index=False)}")

    # Figures
    figures_dir = root / "outputs" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    fig03 = fig03_ablation_p10p90(results, figures_dir / "fig03_ablation_p10p90.png")
    fig04 = fig04_cumulative_scatter(results, figures_dir / "fig04_cumulative_scatter.png")
    log.info(f"  → {fig03}")
    log.info(f"  → {fig04}")

    # Diagnostic figures (fig01 schematic, fig02 from QC, fig06 from migration)
    qc_dir = root / "outputs" / "qc"
    fig01 = fig01_pipeline(figures_dir / "fig01_pipeline.png")
    log.info(f"  → {fig01}")
    spread_csv = qc_dir / "spread_retention.csv"
    if spread_csv.exists():
        fig02 = fig02_qc_spread(spread_csv, figures_dir / "fig02_qc_spread.png")
        log.info(f"  → {fig02}")
    migration_csv = qc_dir / "cluster_migration.csv"
    if migration_csv.exists():
        fig06 = fig06_cluster3_migration(migration_csv, figures_dir / "fig06_cluster3_migration.png")
        log.info(f"  → {fig06}")

    # LaTeX table
    tex_dir = root / "outputs" / "article_assets"
    tex_dir.mkdir(parents=True, exist_ok=True)
    p_tex = build_latex_ablation_table(summary, tex_dir / "ablation_table.tex")
    log.info(f"  → {p_tex}")

    # Mirror figures to article_assets/figures_v2/
    article_dir = tex_dir / "figures_v2"
    copied = mirror_to_article_assets(figures_dir, article_dir)
    log.info(f"  mirrored {len(copied)} figure files → {article_dir.relative_to(root)}")

    log.info("Phase 3 DONE")


@cli.command(name="report")
def report_cmd() -> None:
    """Assemble outputs/report.html + outputs/qc/qc_report.html (ТЗ §8).

    Reads everything already on disk under outputs/ — does NOT re-run any
    phase. Produces a portable HTML rollup with relative links.
    """
    from cmp_ensemble.report import build_report

    root = project_root()
    log.info("=" * 60)
    log.info("REPORT — building outputs/report.html + outputs/qc/qc_report.html")
    log.info("=" * 60)
    paths = build_report(root)
    log.info(f"  → {paths['main'].relative_to(root)}")
    log.info(f"  → {paths['qc'].relative_to(root)}")
    log.info("REPORT DONE")


@cli.command(name="figures")
def figures_cmd() -> None:
    """Regenerate the manuscript figures from existing outputs.

    Reads from outputs/qc/ and outputs/forecast/ — does NOT re-run any
    phase. Run after `cmp-ensemble run --phase {0,1,2,3}` has produced the
    underlying artefacts. Writes 300 dpi PNG + vector PDF to
    outputs/figures/ and mirrors them under outputs/article_assets/figures_v2/.
    """
    root = project_root()
    cfg = load_default_config(root)
    figures_dir = root / "outputs" / "figures"
    qc_dir = root / "outputs" / "qc"
    figures_dir.mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info("FIGURES — regenerating manuscript artefacts")
    log.info("=" * 60)

    # fig01 — pipeline schematic, no data input
    p1 = fig01_pipeline(figures_dir / "fig01_pipeline.png")
    write_sidecar(p1, config=cfg, repo_root=root,
                  extra={"figure": "fig01_pipeline", "source": "static_schematic"})
    log.info(f"  → {p1.relative_to(root)}")

    # fig02 — QC spread retention (requires Phase 1 outputs)
    spread_csv = qc_dir / "spread_retention.csv"
    if spread_csv.exists():
        p2 = fig02_qc_spread(spread_csv, figures_dir / "fig02_qc_spread.png")
        write_sidecar(p2, config=cfg, repo_root=root,
                      extra={"figure": "fig02_qc_spread", "source": str(spread_csv.relative_to(root))})
        log.info(f"  → {p2.relative_to(root)}")
    else:
        log.warning(f"  skip fig02: {spread_csv} not found (run --phase 1 first)")

    # fig06 — cluster migration (requires Phase 1 outputs)
    migration_csv = qc_dir / "cluster_migration.csv"
    if migration_csv.exists():
        p6 = fig06_cluster3_migration(migration_csv, figures_dir / "fig06_cluster3_migration.png")
        write_sidecar(p6, config=cfg, repo_root=root,
                      extra={"figure": "fig06_cluster3_migration", "source": str(migration_csv.relative_to(root))})
        log.info(f"  → {p6.relative_to(root)}")
    else:
        log.warning(f"  skip fig06: {migration_csv} not found (run --phase 1 first)")

    # fig03 + fig04 are produced by `run --phase 3`. If they aren't already on
    # disk we leave them alone (no re-run from here).
    for stale in ("fig03_ablation_p10p90", "fig04_cumulative_scatter"):
        p = figures_dir / f"{stale}.png"
        if p.exists():
            log.info(f"  ✓ {p.relative_to(root)} (kept from previous Phase 3 run)")
        else:
            log.warning(f"  ✗ {p.relative_to(root)} missing — run `--phase 3` to regenerate")

    # ── Tier B diagnostic figures (viz-002)
    log.info("  rendering Tier B diagnostic figures …")
    tier_b_done = render_all_tier_b(root)
    for name, p in tier_b_done.items():
        write_sidecar(p, config=cfg, repo_root=root,
                      extra={"figure": name, "tier": "B"})
    log.info(f"  Tier B: {len(tier_b_done)} figures under outputs/qc/figures/")

    # ── Tier C interactive plotly (viz-003)
    log.info("  rendering Tier C interactive figures …")
    tier_c_done = render_all_tier_c(root)
    for name, p in tier_c_done.items():
        write_sidecar(p, config=cfg, repo_root=root,
                      extra={"figure": name, "tier": "C"})
    log.info(f"  Tier C: {len(tier_c_done)} interactive HTMLs under outputs/qc/")

    # Mirror everything into article_assets/figures_v2/
    article_dir = root / "outputs" / "article_assets" / "figures_v2"
    copied = mirror_to_article_assets(figures_dir, article_dir)
    log.info(f"  mirrored {len(copied)} files → {article_dir.relative_to(root)}")
    log.info("FIGURES DONE")


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


@cli.command(name="closed-loop")
@click.option("--cluster", type=int, default=None, help="cluster id (selects workflow)")
@click.option("--n-alpha", type=int, default=None, help="override ES-MDA steps")
@click.option("--N", "n_members", type=int, default=None, help="override ensemble size")
@click.option("--config", "config_path", default="configs/closed_loop.yaml",
              show_default=True, help="closed-loop config YAML")
@click.option("--out", "out_root", default=None, help="output root (default from config)")
@click.option("--dry-run", is_flag=True, help="sample prior + write run plan, then STOP")
@click.option("--execute", is_flag=True,
              help="auto-run tNavigator each iteration (user-approved auto-launch)")
@click.option("--skip-final-eval", is_flag=True,
              help="skip the final posterior forward pass (saves N simulations)")
def closed_loop_cmd(cluster, n_alpha, n_members, config_path, out_root, dry_run, execute, skip_final_eval):
    """Closed-loop pure-ensemble ES-MDA (TZ_closed_loop_ESMDA.md).

    Without --execute the orchestrator writes iter_0/run_plan.csv + the theta
    matrix and STOPS (CLAUDE.md no-auto-launch). --execute wires a live
    TNavForward and runs the full loop on this machine.
    """
    from cmp_ensemble.closed_loop.orchestrator import (
        ClosedLoopConfig, run_closed_loop)

    cfg = ClosedLoopConfig.from_yaml(config_path)
    if n_alpha is not None:
        cfg.n_alpha = n_alpha
    if n_members is not None:
        cfg.N = n_members
    log.info("closed-loop: cluster=%s N=%d n_alpha=%d execute=%s",
             cluster, cfg.N, cfg.n_alpha, execute)
    if dry_run and not execute:
        res = run_closed_loop(cfg, execute=False, out_root=out_root, cluster=cluster)
        log.info("DRY-RUN/plan-only: status=%s out=%s", res.status, res.out_dir)
        return
    if not execute:
        res = run_closed_loop(cfg, execute=False, out_root=out_root, cluster=cluster)
        log.info("plan-only (no --execute): status=%s out=%s. "
                 "Run tNavigator on the plan or re-invoke with --execute.",
                 res.status, res.out_dir)
        return
    # --execute: production path requires a live tNavigator + d_obs wiring.
    run_closed_loop(cfg, execute=True, out_root=out_root, cluster=cluster,
                    skip_final_eval=skip_final_eval)


@cli.command(name="closed-loop-report")
@click.option("--out", "out_root", default="outputs/closed_loop", show_default=True,
              help="closed-loop run root to summarise")
def closed_loop_report_cmd(out_root):
    """Render the closed-loop HTML rollup from a completed run's artifacts."""
    from cmp_ensemble.closed_loop.report import build_closed_loop_report

    path = build_closed_loop_report(out_root)
    log.info("closed-loop report: %s", path)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

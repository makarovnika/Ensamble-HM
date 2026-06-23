"""Closed-loop ES-MDA orchestrator (CL-E, TZ_closed_loop_ESMDA.md sections 6, 10).

run_closed_loop drives the full cycle:

    sample_prior(N) -> Theta0
    repeat i = 0 .. n_alpha-1:
        D_i      = forward(Theta_i)          # tNavigator (or test forward)
        Theta_i1 = es_update(Theta_i, D_i)   # one MDA step
        checkpoint(outputs/closed_loop/iter_i/)
    Theta_post -> forecast -> artifacts

Run policy (section 10): by default the orchestrator only *plans* -- it writes
iter_0/run_plan.csv + the theta-matrix and STOPs, leaving the simulator to the
user (CLAUDE.md no-auto-launch). execute=True (the user-approved --execute flag)
wires a real TNavForward and runs the loop. For tests a forward model is injected
directly, so the whole loop runs in-process in well under 30 s.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import yaml

from cmp_ensemble.closed_loop.esmda import esmda
from cmp_ensemble.closed_loop.prior import PriorResult, sample_prior
from cmp_ensemble.metadata import write_sidecar

log = logging.getLogger(__name__)


@dataclass
class ClosedLoopConfig:
    """Subset of configs/closed_loop.yaml the orchestrator needs."""

    N: int = 150
    seed: int = 42
    n_alpha: int = 4
    weights: str = "uniform"
    localize: bool = True
    localization_factor: float = 3.0
    localization_method: str = "hard"
    subspace_energy: float = 0.99
    theta_schema: str = "configs/closed_loop_theta_schema.yaml"
    checkpoint_dir: str = "outputs/closed_loop"
    cluster_workflows: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        ens, mda = raw.get("ensemble", {}), raw.get("esmda", {})
        return cls(
            N=int(ens.get("N", 150)),
            seed=int(raw.get("experiment", {}).get("seed", 42)),
            n_alpha=int(mda.get("n_alpha", 4)),
            weights=mda.get("weights", "uniform"),
            localize=bool(mda.get("localize", True)),
            localization_factor=float(mda.get("localization_factor", 3.0)),
            localization_method=mda.get("localization_method", "hard"),
            subspace_energy=float(mda.get("subspace_energy", 0.99)),
            theta_schema=ens.get("theta_schema", "configs/closed_loop_theta_schema.yaml"),
            checkpoint_dir=raw.get("checkpoint", {}).get("dir", "outputs/closed_loop"),
            cluster_workflows=raw.get("tnav", {}).get("cluster_workflows", {}),
            raw=raw,
        )


@dataclass
class ClosedLoopResult:
    status: str                              # "planned" | "completed"
    out_dir: Path
    theta_names: list
    Theta_post: np.ndarray | None = None
    misfit_history: list = field(default_factory=list)
    n_iter: int = 0


def write_run_plan(out_dir, iter_i, Theta, names, *, cluster=None, workflow=None, model_id_base=0):
    """Write run_plan.csv (one row per member) + the theta-matrix for one iter."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    theta_path = out_dir / "theta.npy"
    np.save(theta_path, Theta)
    np.save(out_dir / "theta_names.npy", np.array(list(names)))
    plan = out_dir / "run_plan.csv"
    lines = ["member,model_id,cluster,workflow"]
    cl = "" if cluster is None else str(cluster)
    wf = workflow or ""
    for m in range(Theta.shape[0]):
        lines.append(f"{m},{model_id_base + m},{cl},{wf}")
    plan.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_sidecar(theta_path, extra={"iter": int(iter_i), "N": int(Theta.shape[0])})
    log.info("run plan written: %s (%d members)", plan, Theta.shape[0])
    return plan


def checkpoint_iter(out_root, i, Theta, D, misfit, *, config=None):
    """Checkpoint one ES-MDA iteration for crash recovery (section 6)."""
    d = Path(out_root) / f"iter_{i}"
    d.mkdir(parents=True, exist_ok=True)
    np.save(d / "Theta.npy", Theta)
    np.save(d / "D.npy", D)
    (d / "meta.yaml").write_text(
        yaml.safe_dump(
            {"iter": int(i), "misfit": float(misfit), "N": int(Theta.shape[0]),
             "n_z": int(Theta.shape[1]), "n_d": int(D.shape[1]),
             "written_at_utc": datetime.now(timezone.utc).isoformat()},
            sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    log.info("checkpoint iter %d: misfit=%.4g -> %s", i, misfit, d)
    return d


def run_closed_loop(config, *, forward=None, d_obs=None, C_dd=None, prior=None,
                    execute=False, out_root=None, cluster=None,
                    forecast_forward=None, forecast_index=None, d_truth=None,
                    skip_final_eval=False):
    """Run (or plan) the closed-loop ES-MDA experiment."""
    out_root = Path(out_root or config.checkpoint_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    if prior is None:
        prior = sample_prior(config.theta_schema, config.N, seed=config.seed)
    Theta0, names = prior.Theta, prior.names
    workflow = config.cluster_workflows.get(cluster) if cluster is not None else None

    if forward is None and not execute:
        base = int(config.raw.get("tnav", {}).get("model_id_base", 0))
        write_run_plan(out_root / "iter_0", 0, Theta0, names,
                       cluster=cluster, workflow=workflow, model_id_base=base)
        log.warning("Plan-only: wrote %s/iter_0/run_plan.csv and STOPPED. "
                    "Run tNavigator on the plan, or re-invoke with --execute.", out_root)
        return ClosedLoopResult(status="planned", out_dir=out_root,
                                theta_names=list(names))

    if forward is None and execute:
        # Wire the live tNavigator forward (production path, user-approved).
        from cmp_ensemble.closed_loop import production as prod

        if cluster is None:
            raise ValueError("--execute requires --cluster (selects the workflow)")
        wf = (config.cluster_workflows.get(cluster)
              or config.cluster_workflows.get(str(cluster)))
        if not wf:
            raise ValueError(f"no workflow mapped for cluster {cluster}")
        producers, injectors = prod.load_well_layout()
        cum_index = prod.build_cum_index(producers, prod.build_anchors(config))
        if d_obs is None or C_dd is None:
            d_obs, C_dd = prod.load_closed_loop_observations(
                config, cum_index, producers, injectors)
        base = int(config.raw.get("tnav", {}).get("model_id_base", 1000))
        model_ids = prod.assign_model_ids(config.N, base)
        conn, project = prod.open_production_session(config)
        snf_root = Path(config.raw.get("tnav", {}).get("project", "")).with_suffix(".snf")
        tnav_cfg = config.raw.get("tnav", {})
        if tnav_cfg.get("overwrite_slot", False):
            # WF overwrites a single model slot each run -> serial run/read/archive.
            forward = prod.build_overwrite_forward(
                project, wf, names, snf_root, cum_index,
                slot_rel=tnav_cfg.get("model_slot_dir", "Models/51/134"),
                archive_root=out_root,
                archive=tnav_cfg.get("archive_members", True),
                resume=config.raw.get("run_policy", {}).get("resume", True),
                max_retries=config.raw.get("run_policy", {}).get("max_retries", 1))
            log.info("production OVERWRITE forward wired: cluster=%s workflow=%s slot=%s",
                     cluster, wf, tnav_cfg.get("model_slot_dir"))
        else:
            resolver = prod.ResultsResolver(snf_root)
            forward = prod.build_tnav_forward(
                project, wf, model_ids, names, resolver, cum_index)
            log.info("production forward wired: cluster=%s workflow=%s model_ids=%s..%s",
                     cluster, wf, model_ids[0], model_ids[-1])

    if d_obs is None or C_dd is None:
        raise ValueError("d_obs and C_dd are required to run the loop")

    def _on_step(i, Theta_i, D_i, misfit_i):
        checkpoint_iter(out_root, i, Theta_i, D_i, misfit_i, config=config.raw)

    res = esmda(
        Theta0, forward, np.asarray(d_obs, float), np.asarray(C_dd, float),
        n_alpha=config.n_alpha, localize=config.localize,
        localization_factor=config.localization_factor,
        localization_method=config.localization_method,
        subspace_energy=config.subspace_energy, seed=config.seed, on_step=_on_step,
        skip_final_eval=skip_final_eval)

    post_path = out_root / "Theta_post.npy"
    np.save(post_path, res.Theta_post)
    np.save(out_root / "theta_names.npy", np.array(list(names)))
    np.save(out_root / "misfit_history.npy", np.array(res.misfit_history))
    write_sidecar(post_path, config=config.raw, seed=config.seed,
                  extra={"n_alpha": config.n_alpha,
                         "misfit_first": float(res.misfit_history[0]),
                         "misfit_last": float(res.misfit_history[-1]),
                         "localization_applied": bool(res.localization_applied)})
    log.info("closed loop done: misfit %.4g -> %.4g, posterior %s",
             res.misfit_history[0], res.misfit_history[-1], post_path)

    # CL-F: diagnostic figures (always) + forecast corridors (if a forecast
    # forward is supplied). Failures here must not lose the posterior, so guard.
    try:
        from cmp_ensemble.closed_loop import figures as figs

        figdir = out_root / "figures"
        figs.fig_misfit_evolution(res.misfit_history, figdir / "misfit_evolution.png")
        figs.fig_theta_migration(Theta0, res.Theta_post, names,
                                 figdir / "theta_migration.png")
        if forecast_forward is not None and forecast_index is not None:
            from cmp_ensemble.closed_loop import forecast as fc_mod

            d_prior_fc = fc_mod.run_forecast(Theta0, forecast_forward)
            d_post_fc = fc_mod.run_forecast(res.Theta_post, forecast_forward)
            fc = fc_mod.summarize_forecast(d_prior_fc, d_post_fc, forecast_index,
                                           d_truth=d_truth)
            fc_mod.write_forecast_artifacts(fc, out_root)
            figs.fig_forecast_corridors(fc.prior_quantiles, fc.post_quantiles,
                                        figdir / "forecast_corridors.png")
            log.info("forecast written: width_ratio over %d rows",
                     len(fc.metrics.width_ratio_table))
    except Exception as exc:  # noqa: BLE001 -- figures/forecast are non-critical
        log.warning("CL-F figures/forecast step failed (posterior is safe): %s", exc)

    return ClosedLoopResult(status="completed", out_dir=out_root,
                            theta_names=list(names), Theta_post=res.Theta_post,
                            misfit_history=res.misfit_history, n_iter=config.n_alpha)

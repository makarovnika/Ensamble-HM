"""Production wiring for the closed-loop --execute path (CL-E.x).

Bridges the simulator-agnostic orchestrator to a live tNavigator run:

* assigns each ensemble member a model id (``base + i``, configurable),
* builds the canonical cumulative ``cum_index`` (3 metrics x producers x
  year-end anchors) and loads d_obs / C_dd via ``io.observations`` so d_obs is
  pinned to the same (metric, well, time) order the reader fills,
* resolves each model's ``result.SMSPEC`` by globbing
  ``Models/**/<model_id>/RESULTS/**`` (works with any tNavigator run name),
* assembles a :class:`TNavForward` whose run/read callables wrap
  ``tnav_autorun.run_ensemble`` and ``results_reader.read_cumulative_dsim``.

Everything except :func:`open_production_session` is testable without tNavigator
(mock the session / use a fake SMSPEC tree).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from cmp_ensemble.closed_loop.forward import TNavForward
from cmp_ensemble.closed_loop.results_reader import read_cumulative_dsim

log = logging.getLogger(__name__)

CUM_METRICS = ["Накопл. нефть", "Накопл. вода", "Накопл. газ"]


def assign_model_ids(N: int, base: int = 1000) -> list[int]:
    """Member i -> model id base + i (fresh slots, no overwrite of 110..133)."""
    return [base + i for i in range(N)]


def load_well_layout(path: str | Path = "configs/well_layout.yaml") -> tuple[list, list]:
    d = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    producers = [w["name"] for w in d.get("producers", [])]
    injectors = [w["name"] for w in d.get("injectors", [])]
    return producers, injectors


def build_anchors(config) -> list[datetime]:
    """Year-end anchors from config, else 2011-12-31 .. 2018-12-31."""
    raw = config.raw.get("observations", {}).get("anchors") if hasattr(config, "raw") else None
    if raw:
        return [datetime.fromisoformat(str(a)) for a in raw]
    return [datetime(y, 12, 31) for y in range(2011, 2019)]


def build_cum_index(producers, anchors, metrics=None):
    """Canonical (metric, well, time) order — fed to BOTH d_obs and the reader."""
    metrics = metrics or CUM_METRICS
    return [(m, w, t) for m in metrics for w in producers for t in anchors]


def load_closed_loop_observations(config, cum_index, producers, injectors,
                                  history_path="Исторические значения.xlsx"):
    """d_obs / C_dd for the cumulative closed loop, pinned to ``cum_index``."""
    from cmp_ensemble.io.observations import load_observations

    noise_spec_path = (config.raw.get("observations", {})
                       .get("noise_spec", "configs/noise_spec.yaml"))
    noise_spec = yaml.safe_load(Path(noise_spec_path).read_text(encoding="utf-8"))
    obs = load_observations(
        Path(history_path),
        noise_spec=noise_spec,
        producer_wells=list(producers),
        injector_wells=list(injectors),
        rate_index=[],                      # cumulative-only closed loop
        cum_index=list(cum_index),
    )
    return obs.d_obs_cum, obs.C_dd_cum


class ResultsResolver:
    """Resolve a model's result.SMSPEC under a tNavigator .snf Models tree."""

    def __init__(self, snf_root: str | Path):
        self.snf_root = Path(snf_root)

    def smspec(self, model_id: int) -> Path:
        # glob across any group dir and any RESULTS run-name
        hits = sorted(self.snf_root.glob(f"Models/**/{model_id}/RESULTS/**/result.SMSPEC"))
        if not hits:
            raise FileNotFoundError(
                f"no result.SMSPEC for model {model_id} under {self.snf_root}")
        if len(hits) > 1:
            log.warning("model %s: %d SMSPEC matches, using first %s",
                        model_id, len(hits), hits[0])
        return hits[0]


def make_run_fn(project, workflow: str, model_ids, *, max_retries: int = 1):
    """run_fn(thetas) -> status, wrapping tnav_autorun.run_ensemble."""
    from tnav_autorun import run_ensemble

    def run_fn(thetas):
        return run_ensemble(project, workflow, list(model_ids), thetas,
                            max_retries=max_retries)
    return run_fn


def make_read_fn(resolver: ResultsResolver, model_ids, cum_index, *, missing="raise"):
    """read_fn(i, theta) -> d-vector for member i, via results_reader."""
    def read_fn(i, theta):
        smspec = resolver.smspec(model_ids[i])
        return read_cumulative_dsim(smspec, cum_index, missing=missing)
    return read_fn


def build_tnav_forward(project, workflow, model_ids, theta_names, resolver,
                       cum_index, *, max_retries=1, missing="raise") -> TNavForward:
    """Assemble the production TNavForward (no live session needed to build)."""
    run_fn = make_run_fn(project, workflow, model_ids, max_retries=max_retries)
    read_fn = make_read_fn(resolver, model_ids, cum_index, missing=missing)
    return TNavForward(theta_names, run_fn, read_fn)


def open_production_session(config):
    """Open a live tNavigator session from config.tnav.{exe,project}.

    Raises a clear error if the exe path is unset — the only thing the user must
    supply for a real --execute run.
    """
    tnav = config.raw.get("tnav", {})
    exe, project_path = tnav.get("exe"), tnav.get("project")
    if not exe:
        raise ValueError(
            "tnav.exe is unset in closed_loop.yaml — set the path to "
            "tNavigator-con.exe before running --execute.")
    from tnav_autorun import open_session

    conn, project = open_session(exe, project_path)
    return conn, project

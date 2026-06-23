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


# ─── Overwrite-slot path (session 027 user setup) ────────────────────────────
# The WF now builds AND simulates, but overwrites a single model slot every run.
# So members must run SERIALLY: run -> read the slot -> archive (theta + result)
# -> next member. Batch-running would leave only the last member's results.
import json
import shutil
from datetime import datetime, timezone


def slot_smspec(slot_dir: str | Path) -> Path:
    """Newest result.SMSPEC under the overwrite model slot's RESULTS tree."""
    slot_dir = Path(slot_dir)
    hits = sorted(slot_dir.glob("RESULTS/**/result.SMSPEC"),
                  key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no result.SMSPEC under {slot_dir}/RESULTS")
    return hits[-1]


def archive_member(archive_dir: str | Path, member: int, theta: dict,
                   full_vars: dict, smspec: Path, d_vector, *, iteration: int) -> Path:
    """Snapshot one member's (theta, WF params, simulation result) for reproducibility."""
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    # theta (sampled overrides) + full WF variables
    (archive_dir / "theta.json").write_text(
        json.dumps({k: float(v) for k, v in theta.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (archive_dir / "wf_variables.json").write_text(
        json.dumps({k: float(v) for k, v in full_vars.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    # copy the Eclipse summary (+ siblings needed to re-open it)
    stem = smspec.stem
    for suffix in (".SMSPEC", ".UNSMRY", ".sum"):
        src = smspec.with_suffix(suffix)
        if src.exists():
            shutil.copy2(src, archive_dir / f"{stem}{suffix}")
    # model_file_list.txt (the WF include-file manifest) if present alongside
    mfl = smspec.parent / "model_file_list.txt"
    if mfl.exists():
        shutil.copy2(mfl, archive_dir / "model_file_list.txt")
    import numpy as np

    np.save(archive_dir / "d_sim.npy", np.asarray(d_vector, dtype=float))
    (archive_dir / "meta.yaml").write_text(
        "\n".join([
            f"member: {member}", f"iteration: {iteration}",
            f"smspec_source: {smspec.as_posix()}",
            f"n_d: {len(d_vector)}",
            f"archived_at_utc: {datetime.now(timezone.utc).isoformat()}",
        ]) + "\n", encoding="utf-8")
    return archive_dir


class TNavOverwriteForward:
    """Serial forward for a single overwrite slot: run -> read -> archive per member.

    Each ES-MDA step (one __call__) runs every member through the WF, which
    overwrites the same model slot and simulates synchronously; we read the slot
    and archive (theta + WF vars + result.SMSPEC) before the next member runs.
    """

    def __init__(self, project, workflow, theta_names, slot_dir, cum_index,
                 *, archive_root=None, archive=True, slot_model_id=134, missing="raise",
                 resume=True, max_retries=1):
        self.project = project
        self.workflow = workflow
        self.theta_names = list(theta_names)
        self.slot_dir = Path(slot_dir)
        self.cum_index = cum_index
        self.archive_root = Path(archive_root) if archive_root else None
        self.archive = archive and self.archive_root is not None
        self.slot_model_id = slot_model_id
        self.missing = missing
        # resume needs the archive to read cached d_sim back; tie them together.
        self.resume = resume and self.archive
        self.max_retries = int(max_retries)
        self._call = 0

    def _run_one(self, theta: dict) -> None:
        from tnav_autorun import run_member

        run_member(self.project, self.workflow, self.slot_model_id, theta, save=True)

    def _cached_dsim(self, adir: Path, theta: dict):
        """Return the archived d_sim if this member's theta already ran, else None.

        The theta sequence is deterministic given config+seed, so a re-launch
        reproduces each (iter, member) theta exactly -> a matching cache is valid.
        """
        import json

        import numpy as np

        dpath, tpath = adir / "d_sim.npy", adir / "theta.json"
        if not (dpath.exists() and tpath.exists()):
            return None
        cached = json.loads(tpath.read_text(encoding="utf-8"))
        cur = {k: float(v) for k, v in theta.items()}
        if set(cached) != set(cur):
            return None
        a = np.array([cached[k] for k in sorted(cached)])
        b = np.array([cur[k] for k in sorted(cur)])
        if not np.allclose(a, b, rtol=1e-9, atol=1e-12):
            return None
        return np.load(dpath)

    def _run_read_member(self, theta: dict):
        """Run one member with retries; return the d_sim vector."""
        last = None
        for attempt in range(self.max_retries + 1):
            try:
                self._run_one(theta)
                smspec = slot_smspec(self.slot_dir)
                return read_cumulative_dsim(smspec, self.cum_index, missing=self.missing)
            except Exception as exc:  # noqa: BLE001 -- retry transient sim/read failures
                last = exc
                log.warning("member run/read attempt %d/%d failed: %s",
                            attempt + 1, self.max_retries + 1, exc)
        raise RuntimeError(f"member failed after {self.max_retries + 1} attempts: {last}")

    def __call__(self, Theta):
        import numpy as np
        from tnav_autorun import build_variables

        Theta = np.asarray(Theta, dtype=float)
        if Theta.shape[1] != len(self.theta_names):
            raise ValueError(
                f"Theta has {Theta.shape[1]} cols but {len(self.theta_names)} names")
        thetas = [dict(zip(self.theta_names, row)) for row in Theta]
        rows = []
        for m, theta in enumerate(thetas):
            adir = (self.archive_root / f"iter_{self._call}" / f"member_{m}"
                    if self.archive else None)
            if self.resume:
                cached = self._cached_dsim(adir, theta)
                if cached is not None:
                    log.info("[iter %d] member %d/%d: RESUMED from archive",
                             self._call, m + 1, len(thetas))
                    rows.append(cached)
                    continue
            log.info("[iter %d] member %d/%d: run -> sim (overwrite slot)",
                     self._call, m + 1, len(thetas))
            d = self._run_read_member(theta)
            if self.archive:
                smspec = slot_smspec(self.slot_dir)
                archive_member(adir, m, theta, build_variables(theta), smspec, d,
                               iteration=self._call)
            rows.append(d)
        self._call += 1
        return np.vstack(rows)


def build_overwrite_forward(project, workflow, theta_names, snf_root, cum_index,
                            *, slot_rel="Models/51/134", archive_root=None,
                            archive=True, missing="raise", resume=True,
                            max_retries=1) -> TNavOverwriteForward:
    """Assemble the overwrite-slot forward from config-derived paths."""
    slot_dir = Path(snf_root) / slot_rel
    slot_model_id = int(Path(slot_rel).name) if Path(slot_rel).name.isdigit() else 134
    return TNavOverwriteForward(
        project, workflow, theta_names, slot_dir, cum_index,
        archive_root=archive_root, archive=archive,
        slot_model_id=slot_model_id, missing=missing,
        resume=resume, max_retries=max_retries)

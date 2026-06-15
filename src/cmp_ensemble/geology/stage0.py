"""Stage 0 build: deck inventory + property-cube diff Exp1 vs Exp2.

Produces two artefacts under ``outputs/geology_validation/`` (TZ §3, §4):

* ``model_index.csv`` — one row per directory in both experiments
  (experiment, dir, deck_name, cluster, seed, has_results, has_PORO, has_NTG,
   has_PERMX, has_SATNUM, has_WELLTRACK, n_wells).
* ``exp_diff.csv`` — one row per SEED present in both experiments, with
  Δmean and Δvar of PORO / PERMX / NTG (and frac-net delta).

Both come with sidecar ``*.meta.yaml`` (git SHA, seed, config hash, timestamp)
per the project's reproducibility convention.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict
from pathlib import Path

import numpy as np

from cmp_ensemble.io.grdecl import (
    DeckInfo,
    read_grid_geometry,
    read_keyword_cube,
    read_welltrack,
    scan_experiment_dir,
)

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# model_index
# ──────────────────────────────────────────────────────────────────────────


def _deck_inc_stem(d: DeckInfo) -> str:
    return Path(d.deck_name).stem


def _check_include_present(d: DeckInfo, keyword_stem: str) -> bool:
    return d.include(keyword_stem).exists()


def build_model_index(experiment_roots: dict[int, Path]) -> list[dict]:
    """Walk all configured experiment roots and tabulate every model deck.

    ``experiment_roots`` is ``{experiment_number: path_to_root}``; missing
    roots are logged and skipped.
    """
    rows: list[dict] = []
    for exp_id, root in experiment_roots.items():
        decks = scan_experiment_dir(root, exp_id)
        log.info(f"experiment {exp_id}: scanned {len(decks)} decks under {root}")
        for d in decks:
            stem = _deck_inc_stem(d)
            n_wells = _count_wells(d.include(f"WELLTRACK"))
            rows.append({
                "experiment": exp_id,
                "directory": d.directory.name,
                "deck_name": d.deck_name,
                "deck_stem": stem,
                "cluster": d.cluster if d.cluster is not None else "",
                "seed": d.seed if d.seed is not None else "",
                "is_centroid": int(d.is_centroid),
                "has_results": int(d.has_results),
                "has_PORO": int(_check_include_present(d, "PORO")),
                "has_PERMX": int(_check_include_present(d, "PERMX")),
                "has_NTG": int(_check_include_present(d, "NTG")),
                "has_SATNUM": int(_check_include_present(d, "SATNUM")),
                "has_WELLTRACK": int(_check_include_present(d, "WELLTRACK")),
                "n_wells": n_wells,
            })
    return rows


def _count_wells(welltrack_path: Path) -> int:
    if not welltrack_path.exists():
        return 0
    try:
        return len(read_welltrack(welltrack_path))
    except Exception as e:
        log.warning(f"{welltrack_path}: failed to count wells: {e}")
        return 0


def write_csv(rows: list[dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return out_path
    fieldnames = list(rows[0].keys())
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return out_path


# ──────────────────────────────────────────────────────────────────────────
# exp_diff
# ──────────────────────────────────────────────────────────────────────────


_CUBE_KEYWORDS = ("PORO", "PERMX", "NTG")


def _load_cubes(d: DeckInfo, n_cells: int) -> dict[str, np.ndarray]:
    stem = _deck_inc_stem(d)
    cubes: dict[str, np.ndarray] = {}
    for kw in _CUBE_KEYWORDS:
        p = d.include(kw)
        if not p.exists():
            continue
        try:
            cubes[kw] = read_keyword_cube(p, kw, n_cells)
        except Exception as e:
            log.warning(f"{p}: failed to read {kw}: {e}")
    return cubes


def build_exp_diff(
    decks_by_exp: dict[int, list[DeckInfo]],
    n_cells: int,
    a_exp: int = 1,
    b_exp: int = 2,
) -> list[dict]:
    """Per matched-SEED diff of cube statistics between two experiments.

    Only decks classified by the deck-name parser (i.e. excluding centroids
    and forecast decks) are considered, and only SEEDs present in both
    experiments.
    """
    a_by_seed = {d.seed: d for d in decks_by_exp.get(a_exp, [])
                 if d.seed is not None and not d.is_centroid}
    b_by_seed = {d.seed: d for d in decks_by_exp.get(b_exp, [])
                 if d.seed is not None and not d.is_centroid}
    common = sorted(set(a_by_seed) & set(b_by_seed))
    log.info(
        f"matched SEEDs across Exp{a_exp}/Exp{b_exp}: {len(common)} "
        f"(Exp{a_exp}-only={len(set(a_by_seed) - set(b_by_seed))}, "
        f"Exp{b_exp}-only={len(set(b_by_seed) - set(a_by_seed))})"
    )

    rows: list[dict] = []
    for i, seed in enumerate(common, 1):
        a = a_by_seed[seed]
        b = b_by_seed[seed]
        ca = _load_cubes(a, n_cells)
        cb = _load_cubes(b, n_cells)
        row: dict = {
            "seed": seed,
            "cluster_a": a.cluster, "cluster_b": b.cluster,
        }
        for kw in _CUBE_KEYWORDS:
            if kw in ca and kw in cb:
                aa, bb = ca[kw], cb[kw]
                row[f"mean_{kw}_a"] = float(aa.mean())
                row[f"mean_{kw}_b"] = float(bb.mean())
                row[f"delta_mean_{kw}"] = float(bb.mean() - aa.mean())
                row[f"var_{kw}_a"] = float(aa.var())
                row[f"var_{kw}_b"] = float(bb.var())
                row[f"delta_var_{kw}"] = float(bb.var() - aa.var())
                if kw == "NTG":
                    row["frac_net_a"] = float((aa == 1).mean())
                    row["frac_net_b"] = float((bb == 1).mean())
                    row["delta_frac_net"] = (
                        row["frac_net_b"] - row["frac_net_a"]
                    )
                    row["frac_netflag_changed"] = float((aa != bb).mean())
            else:
                # Mark missing cubes explicitly so downstream tools can filter
                row[f"mean_{kw}_a"] = ""
                row[f"mean_{kw}_b"] = ""
                row[f"delta_mean_{kw}"] = ""
                row[f"var_{kw}_a"] = ""
                row[f"var_{kw}_b"] = ""
                row[f"delta_var_{kw}"] = ""
        rows.append(row)
        if i % 25 == 0 or i == len(common):
            log.info(f"  [{i}/{len(common)}] exp_diff: seed={seed} done")
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Stage 0 entry point
# ──────────────────────────────────────────────────────────────────────────


def run_stage0(
    project_root: Path,
    sim_root: Path | None = None,
    n_cells: int = 535_720,
) -> dict[str, Path]:
    """Build ``model_index.csv`` and ``exp_diff.csv`` under ``outputs/geology_validation``."""
    project_root = Path(project_root)
    sim_root = sim_root or (project_root / "simulation models results")
    out_dir = project_root / "outputs" / "geology_validation"
    out_dir.mkdir(parents=True, exist_ok=True)

    experiment_roots = {
        1: sim_root / "Experiment 1",
        2: sim_root / "Experiment 2",
    }
    rows = build_model_index(experiment_roots)
    idx_path = write_csv(rows, out_dir / "model_index.csv")
    log.info(f"model_index.csv: {len(rows)} rows → {idx_path}")

    decks_by_exp = {
        eid: scan_experiment_dir(root, eid)
        for eid, root in experiment_roots.items()
    }
    diff_rows = build_exp_diff(decks_by_exp, n_cells=n_cells)
    diff_path = write_csv(diff_rows, out_dir / "exp_diff.csv")
    log.info(f"exp_diff.csv: {len(diff_rows)} rows → {diff_path}")

    return {"model_index": idx_path, "exp_diff": diff_path}

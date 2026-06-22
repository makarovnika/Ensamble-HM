"""Per-well-block geological descriptors (TZ_geology_validation.md §5.1).

For every cell pierced by a well trajectory we read ``PORO``, ``PERMX``,
``NTG`` from the deck's INCLUDE files; the sand indicator is

    is_sand[c] = (NTG[c] == 1) AND (PERMX[c] > perm_cutoff)

with ``perm_cutoff`` calibrated per-model from the bi-modality of
``log10(PERMX)`` (the trough between the non-reservoir spike at PERMX≈0 and
the channel mode at ≥10² mD). The derived per-well aggregates are

    net_sand_penetrated   = Σ dz_eff  over sand-classified cells
    kh_penetrated         = Σ PERMX·dz_eff  over all cells
    frac_channel_cells    = n_sand_cells / n_cells_traversed
    mean_ntg_along_well   = Σ NTG·dz_eff / Σ dz_eff

If a ``COMPDATMD`` interval list is supplied, only **perforated** cells
contribute to ``net_sand_penetrated``; the un-perforated counterparts are
still counted under the other aggregates so downstream code can recover the
gross-vs-net distinction.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cmp_ensemble.io.grdecl import (
    DeckInfo,
    read_compdatmd,
    read_grid_geometry,
    read_keyword_cube,
    read_welltrack,
)
from cmp_ensemble.geology.welltrack import (
    CellTraversal, GridIndex, build_grid_index, walk_all_wells,
)

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Cutoff calibration
# ──────────────────────────────────────────────────────────────────────────


def calibrate_perm_cutoff(
    permx: np.ndarray,
    fallback_mD: float = 0.0,
    min_grid_size: int = 100,
    sanity_cap_percentile: float = 99.0,
) -> float:
    """Find the bi-modality trough in ``log10(PERMX[PERMX > 0])``.

    If the histogram of log-PERMX shows two distinct modes (low-perm haze
    vs channel mode), the trough between them is the natural sand cutoff.

    On Watt Field decks the non-reservoir fraction is already encoded as
    ``PERMX == 0`` (≈51 % of cells in the audited Exp2/300 deck), so the
    positive-PERMX histogram is **single-peaked** and bi-modal calibration
    fails by design — we then fall back to ``fallback_mD = 0`` (every
    positive-PERMX cell with NTG=1 classified as sand).
    """
    pos = permx[permx > 0]
    if pos.size < min_grid_size:
        return float(fallback_mD)
    log_p = np.log10(pos)
    counts, edges = np.histogram(log_p, bins=80, range=(log_p.min(), log_p.max()))
    kernel = np.array([1, 3, 5, 3, 1], dtype=float)
    kernel /= kernel.sum()
    smooth = np.convolve(counts, kernel, mode="same")
    maxima = [k for k in range(1, len(smooth) - 1)
              if smooth[k] >= smooth[k - 1] and smooth[k] >= smooth[k + 1]]
    if len(maxima) < 2:
        log.info(f"calibrate_perm_cutoff: log10(PERMX) is single-peaked — "
                 f"falling back to {fallback_mD} mD (PERMX==0 already encodes "
                 f"non-reservoir).")
        return float(fallback_mD)
    top_two = sorted(maxima, key=lambda k: -smooth[k])[:2]
    a, b = sorted(top_two)
    trough = a + int(np.argmin(smooth[a:b + 1]))
    cutoff_log = float(edges[trough + 1])
    cutoff = float(10 ** cutoff_log)
    # AUDIT sanity cap (docs/geology_audit.md Issue 1):
    # On 2 seeds the bi-modal detector latched on noisy upper tail and
    # returned cutoff = 10760 mD, which rejected 99.9% of reservoir cells.
    cap = float(np.percentile(pos, sanity_cap_percentile))
    if cutoff > cap:
        log.warning(
            f"calibrate_perm_cutoff: bi-modal trough at {cutoff:.1f} mD > "
            f"{sanity_cap_percentile:.0f}th percentile of PERMX>0 ({cap:.1f} mD) "
            f"— rejecting as algorithmic artefact, falling back to {fallback_mD}.")
        return float(fallback_mD)
    log.info(f"calibrate_perm_cutoff: bi-modal trough at log10={cutoff_log:.3f} "
             f"→ {cutoff:.3f} mD")
    return cutoff


# ──────────────────────────────────────────────────────────────────────────
# Per-well aggregation
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class WellDescriptors:
    well: str
    n_cells_traversed: int
    n_cells_perforated: int
    n_sand_cells: int
    net_sand_penetrated: float
    kh_penetrated: float
    frac_channel_cells: float
    mean_ntg_along_well: float


def _cell_to_flat(i: int, j: int, k: int, nx: int, ny: int) -> int:
    """Eclipse i-fastest flat index: idx = (k*ny + j)*nx + i."""
    return (k * ny + j) * nx + i


def compute_descriptors(
    traversals: list[CellTraversal],
    poro: np.ndarray,
    permx: np.ndarray,
    ntg: np.ndarray,
    nx: int, ny: int,
    perm_cutoff: float,
) -> dict[str, WellDescriptors]:
    """Aggregate the per-cell traversals into one row per well."""
    by_well: dict[str, list[CellTraversal]] = {}
    for t in traversals:
        by_well.setdefault(t.well, []).append(t)
    out: dict[str, WellDescriptors] = {}
    for well, rows in by_well.items():
        if not rows:
            continue
        n_cells = len(rows)
        n_perf = sum(1 for r in rows if r.perforated)
        net_sand = 0.0
        kh = 0.0
        ntg_weighted = 0.0
        dz_total = 0.0
        n_sand = 0
        for r in rows:
            flat = _cell_to_flat(r.i, r.j, r.k, nx, ny)
            ntg_c = float(ntg[flat])
            permx_c = float(permx[flat])
            poro_c = float(poro[flat])  # noqa: F841 (reserved for future use)
            is_sand = (ntg_c == 1) and (permx_c > perm_cutoff)
            if is_sand:
                n_sand += 1
                if r.perforated:
                    net_sand += r.dz_eff
            kh += permx_c * r.dz_eff
            ntg_weighted += ntg_c * r.dz_eff
            dz_total += r.dz_eff
        out[well] = WellDescriptors(
            well=well,
            n_cells_traversed=n_cells,
            n_cells_perforated=n_perf,
            n_sand_cells=n_sand,
            net_sand_penetrated=net_sand,
            kh_penetrated=kh,
            frac_channel_cells=(n_sand / n_cells) if n_cells else 0.0,
            mean_ntg_along_well=(ntg_weighted / dz_total) if dz_total else 0.0,
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# Model-level entry point
# ──────────────────────────────────────────────────────────────────────────


def descriptors_for_deck(
    deck: DeckInfo,
    grid_index: GridIndex | None = None,
    n_cells: int | None = None,
    perm_cutoff: float | None = None,
    ds: float = 1.0,
) -> tuple[dict[str, WellDescriptors], float]:
    """Build descriptors for every well in one model deck.

    Returns ``(descriptors_by_well, perm_cutoff_used)``. Pass a precomputed
    ``grid_index`` when iterating over a whole experiment — the per-grid kd-tree
    construction is the most expensive step.
    """
    deck_stem = Path(deck.deck_name).stem
    inc = deck.include_dir
    if grid_index is None:
        geo = read_grid_geometry(inc / f"{deck_stem}_GRID.inc",
                                  inc / f"{deck_stem}.grdecl")
        grid_index = build_grid_index(geo)
        n_cells = geo.n_cells
    if n_cells is None:
        n_cells = grid_index.nx * grid_index.ny * grid_index.nz
    poro = read_keyword_cube(inc / f"{deck_stem}_PORO.inc", "PORO", n_cells)
    permx = read_keyword_cube(inc / f"{deck_stem}_PERMX.inc", "PERMX", n_cells)
    ntg = read_keyword_cube(inc / f"{deck_stem}_NTG.inc", "NTG", n_cells)
    if perm_cutoff is None:
        perm_cutoff = calibrate_perm_cutoff(permx)
    tracks = read_welltrack(inc / f"{deck_stem}_WELLTRACK.inc")
    compdat_path = inc / f"{deck_stem}_SCHEDULE.inc"
    perf = read_compdatmd(compdat_path) if compdat_path.exists() else {}
    traversals = walk_all_wells(tracks, grid_index, perforation_md_by_well=perf, ds=ds)
    descriptors = compute_descriptors(
        traversals, poro=poro, permx=permx, ntg=ntg,
        nx=grid_index.nx, ny=grid_index.ny,
        perm_cutoff=perm_cutoff,
    )
    return descriptors, perm_cutoff


def descriptors_for_experiment(
    decks: list[DeckInfo],
    n_cells: int = 535_720,
    ds: float = 1.0,
    progress_every: int = 10,
) -> list[dict]:
    """Run ``descriptors_for_deck`` for every deck; one row per (model, well).

    All decks in an experiment share the same grid geometry; we therefore build
    the ``GridIndex`` once from the first viable deck and reuse it everywhere.
    """
    if not decks:
        return []
    first = decks[0]
    deck_stem = Path(first.deck_name).stem
    geo = read_grid_geometry(
        first.include_dir / f"{deck_stem}_GRID.inc",
        first.include_dir / f"{deck_stem}.grdecl",
    )
    idx = build_grid_index(geo)
    log.info(f"built shared GridIndex (NX={geo.nx} NY={geo.ny} NZ={geo.nz}) "
             f"from {first.directory.name}")

    rows: list[dict] = []
    for n, deck in enumerate(decks, 1):
        try:
            desc, cutoff = descriptors_for_deck(deck, grid_index=idx,
                                                n_cells=n_cells, ds=ds)
        except FileNotFoundError as e:
            log.warning(f"skip {deck.directory.name}: missing input {e}")
            continue
        except Exception as e:
            log.warning(f"skip {deck.directory.name}: {type(e).__name__}: {e}")
            continue
        for well, d in desc.items():
            rows.append({
                "experiment": deck.experiment,
                "directory": deck.directory.name,
                "deck_name": deck.deck_name,
                "cluster": deck.cluster if deck.cluster is not None else "",
                "seed": deck.seed if deck.seed is not None else "",
                "well": well,
                "perm_cutoff_mD": cutoff,
                "n_cells_traversed": d.n_cells_traversed,
                "n_cells_perforated": d.n_cells_perforated,
                "n_sand_cells": d.n_sand_cells,
                "net_sand_penetrated": d.net_sand_penetrated,
                "kh_penetrated": d.kh_penetrated,
                "frac_channel_cells": d.frac_channel_cells,
                "mean_ntg_along_well": d.mean_ntg_along_well,
            })
        if n % progress_every == 0 or n == len(decks):
            log.info(f"  [{n}/{len(decks)}] descriptors built "
                     f"({len(desc)} wells, cutoff={cutoff:.2f} mD)")
    return rows

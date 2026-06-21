"""Connected sand geobodies + well-well connectivity (TZ §5.2).

Builds the property-cube level analyses that feed axes 1, 2 and 3 of the
geology validation:

* ``build_sand_mask`` — boolean 3D array under the canonical sand rule
  ``NTG == 1 AND PERMX > perm_cutoff``.
* ``label_geobodies`` — ``scipy.ndimage.label`` over the sand mask;
  defaults to 26-connectivity (TZ §5.2 default), 6-connectivity available
  for the sensitivity sweep.
* ``geobody_stats`` — per-body volume, principal-axis lengths,
  anisotropy (≜ longest / shortest principal extent), orientation in plan
  (azimuth in degrees, 0° = east, CCW positive).
* ``well_connectivity_matrix`` — boolean 23×23 well-well matrix: two wells
  are connected iff at least one sand geobody is pierced by both.
* ``connectivity_for_deck`` — end-to-end driver for one model.

The hypothesis from TZ §5.2 (and Notion §7.4) is that connectivity to
INJ wells explains the water-cut spread asymmetry — the well-to-INJ
counts produced here go straight into the geolval-005 diversity table
and geolval-007 summary comparison.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage

from cmp_ensemble.io.grdecl import (
    DeckInfo,
    read_compdatmd,
    read_grid_geometry,
    read_keyword_cube,
    read_welltrack,
)
from cmp_ensemble.geology.welltrack import (
    GridIndex, build_grid_index, walk_all_wells,
)
from cmp_ensemble.geology.descriptors import calibrate_perm_cutoff

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Sand mask + labelling
# ──────────────────────────────────────────────────────────────────────────


def build_sand_mask(
    permx: np.ndarray,
    ntg: np.ndarray,
    nx: int, ny: int, nz: int,
    perm_cutoff: float = 0.0,
) -> np.ndarray:
    """Return a ``(nz, ny, nx)`` bool array under the canonical sand rule."""
    mask_flat = (ntg == 1) & (permx > perm_cutoff)
    # Eclipse i-fastest flat order: idx = (k*ny + j)*nx + i
    return mask_flat.reshape(nz, ny, nx)


_CONN_STRUCTURE = {
    6: ndimage.generate_binary_structure(3, 1),   # face-only
    26: ndimage.generate_binary_structure(3, 3),  # face + edge + vertex
}


def label_geobodies(
    mask: np.ndarray,
    connectivity: int = 26,
) -> tuple[np.ndarray, int]:
    """Return ``(labels, n_bodies)``; ``labels[c] == 0`` ↔ non-sand."""
    if connectivity not in _CONN_STRUCTURE:
        raise ValueError(f"connectivity must be 6 or 26, got {connectivity}")
    return ndimage.label(mask, structure=_CONN_STRUCTURE[connectivity])


# ──────────────────────────────────────────────────────────────────────────
# Per-body statistics
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class GeobodyStat:
    body_id: int
    n_cells: int
    bbox_extent: tuple[int, int, int]  # (di, dj, dk)
    anisotropy: float                  # longest / shortest principal extent
    orientation_deg: float             # in plan, CCW from east


def _principal_axes_2d(coords: np.ndarray) -> tuple[float, float, float]:
    """PCA on 2D coordinates → (major_len, minor_len, angle_deg)."""
    if coords.shape[0] < 2:
        return 0.0, 0.0, 0.0
    centred = coords - coords.mean(axis=0)
    cov = np.cov(centred.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # Eigenvalues are ascending — flip for major-first
    eigvals = eigvals[::-1]
    eigvecs = eigvecs[:, ::-1]
    major_len = 2.0 * float(np.sqrt(max(eigvals[0], 0.0)))
    minor_len = 2.0 * float(np.sqrt(max(eigvals[1], 0.0)))
    angle = float(np.degrees(np.arctan2(eigvecs[1, 0], eigvecs[0, 0])))
    # Normalise to [-90, 90]: an axis is direction-agnostic
    if angle > 90:
        angle -= 180
    elif angle < -90:
        angle += 180
    return major_len, minor_len, angle


def geobody_stats(labels: np.ndarray, max_bodies: int | None = None
                  ) -> list[GeobodyStat]:
    """One entry per labelled body; sorted descending by ``n_cells``."""
    if labels.max() == 0:
        return []
    flat_idx = np.argwhere(labels > 0)  # (n_sand_cells, 3) — order (k, j, i)
    body_ids = labels[flat_idx[:, 0], flat_idx[:, 1], flat_idx[:, 2]]
    sort_perm = np.argsort(body_ids, kind="stable")
    body_ids_sorted = body_ids[sort_perm]
    flat_sorted = flat_idx[sort_perm]
    splits = np.searchsorted(body_ids_sorted,
                              np.arange(1, int(body_ids_sorted.max()) + 2))
    out: list[GeobodyStat] = []
    for bid in range(1, int(body_ids_sorted.max()) + 1):
        a, b = splits[bid - 1], splits[bid]
        cells = flat_sorted[a:b]  # (n, 3) → (k, j, i)
        if cells.shape[0] == 0:
            continue
        di = int(cells[:, 2].max() - cells[:, 2].min() + 1)
        dj = int(cells[:, 1].max() - cells[:, 1].min() + 1)
        dk = int(cells[:, 0].max() - cells[:, 0].min() + 1)
        # Principal axes in plan (i, j) for orientation
        plan_xy = cells[:, [2, 1]].astype(float)  # (i, j)
        major, minor, angle = _principal_axes_2d(plan_xy)
        extents = sorted((max(di, 1), max(dj, 1), max(dk, 1)), reverse=True)
        anisotropy = extents[0] / max(extents[-1], 1)
        out.append(GeobodyStat(
            body_id=int(bid), n_cells=int(cells.shape[0]),
            bbox_extent=(di, dj, dk),
            anisotropy=float(anisotropy),
            orientation_deg=float(angle),
        ))
    out.sort(key=lambda g: -g.n_cells)
    if max_bodies is not None:
        out = out[:max_bodies]
    return out


# ──────────────────────────────────────────────────────────────────────────
# Well-well connectivity
# ──────────────────────────────────────────────────────────────────────────


def _wells_to_body_sets(
    well_cell_ijk: dict[str, list[tuple[int, int, int]]],
    labels: np.ndarray,
) -> dict[str, set[int]]:
    """For each well, the set of sand-body IDs its cells touch (drop 0)."""
    out: dict[str, set[int]] = {}
    for well, cells in well_cell_ijk.items():
        bodies = set()
        for i, j, k in cells:
            if not (0 <= i < labels.shape[2]
                    and 0 <= j < labels.shape[1]
                    and 0 <= k < labels.shape[0]):
                continue
            bid = int(labels[k, j, i])
            if bid > 0:
                bodies.add(bid)
        out[well] = bodies
    return out


def well_connectivity_matrix(
    well_cell_ijk: dict[str, list[tuple[int, int, int]]],
    labels: np.ndarray,
    well_order: list[str] | None = None,
) -> tuple[np.ndarray, list[str], dict[str, set[int]]]:
    """``(n, n)`` bool matrix: wells share at least one sand body.

    Returns ``(matrix, ordered_well_names, body_sets_by_well)``.
    Diagonal is True for wells that pierce any sand body (else False).
    """
    body_sets = _wells_to_body_sets(well_cell_ijk, labels)
    names = sorted(well_cell_ijk) if well_order is None else list(well_order)
    n = len(names)
    M = np.zeros((n, n), dtype=bool)
    for a in range(n):
        sa = body_sets[names[a]]
        if not sa:
            continue
        M[a, a] = True
        for b in range(a + 1, n):
            sb = body_sets[names[b]]
            if sa & sb:
                M[a, b] = True
                M[b, a] = True
    return M, names, body_sets


# ──────────────────────────────────────────────────────────────────────────
# Whole-deck driver
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class DeckConnectivity:
    seed: int
    cluster: int
    experiment: int
    directory: str
    n_bodies_26: int
    n_bodies_6: int
    frac_sand_in_largest_26: float
    frac_sand_in_largest_6: float
    frac_sand_in_top10_26: float
    geobody_stats_26: list[GeobodyStat]
    geobody_stats_6: list[GeobodyStat]
    well_matrix_26: np.ndarray
    well_names: list[str]
    body_sets_26: dict[str, set[int]]


def _well_cell_ijk(deck: DeckInfo, idx: GridIndex,
                   perforation_md_by_well, ds: float = 1.0
                   ) -> dict[str, list[tuple[int, int, int]]]:
    deck_stem = Path(deck.deck_name).stem
    tracks = read_welltrack(deck.include(f"WELLTRACK"))
    traversals = walk_all_wells(tracks, idx, perforation_md_by_well, ds=ds)
    out: dict[str, list[tuple[int, int, int]]] = {}
    for t in traversals:
        out.setdefault(t.well, []).append((t.i, t.j, t.k))
    return out


def connectivity_for_deck(
    deck: DeckInfo,
    grid_index: GridIndex | None = None,
    n_cells: int | None = None,
    perm_cutoff: float | None = None,
    ds: float = 1.0,
    top_bodies_for_stats: int = 50,
) -> DeckConnectivity:
    """End-to-end connectivity build for one model."""
    deck_stem = Path(deck.deck_name).stem
    inc = deck.include_dir
    if grid_index is None:
        geo = read_grid_geometry(inc / f"{deck_stem}_GRID.inc",
                                  inc / f"{deck_stem}.grdecl")
        grid_index = build_grid_index(geo)
        n_cells = geo.n_cells
    if n_cells is None:
        n_cells = grid_index.nx * grid_index.ny * grid_index.nz
    permx = read_keyword_cube(inc / f"{deck_stem}_PERMX.inc", "PERMX", n_cells)
    ntg = read_keyword_cube(inc / f"{deck_stem}_NTG.inc", "NTG", n_cells)
    if perm_cutoff is None:
        perm_cutoff = calibrate_perm_cutoff(permx)
    mask = build_sand_mask(permx, ntg,
                           nx=grid_index.nx, ny=grid_index.ny,
                           nz=grid_index.nz, perm_cutoff=perm_cutoff)
    labels_26, n26 = label_geobodies(mask, connectivity=26)
    labels_6, n6 = label_geobodies(mask, connectivity=6)
    stats_26 = geobody_stats(labels_26, max_bodies=top_bodies_for_stats)
    stats_6 = geobody_stats(labels_6, max_bodies=top_bodies_for_stats)
    total_sand = int(mask.sum())
    frac26 = (stats_26[0].n_cells / total_sand) if (total_sand and stats_26) else 0.0
    frac6 = (stats_6[0].n_cells / total_sand) if (total_sand and stats_6) else 0.0
    frac_top10 = (sum(s.n_cells for s in stats_26[:10]) / total_sand) \
        if total_sand else 0.0
    sched = inc / f"{deck_stem}_SCHEDULE.inc"
    perf = read_compdatmd(sched) if sched.exists() else {}
    well_cells = _well_cell_ijk(deck, grid_index, perf, ds=ds)
    M, names, body_sets = well_connectivity_matrix(well_cells, labels_26)
    return DeckConnectivity(
        seed=deck.seed or -1,
        cluster=deck.cluster if deck.cluster is not None else -1,
        experiment=deck.experiment,
        directory=deck.directory.name,
        n_bodies_26=int(n26), n_bodies_6=int(n6),
        frac_sand_in_largest_26=float(frac26),
        frac_sand_in_largest_6=float(frac6),
        frac_sand_in_top10_26=float(frac_top10),
        geobody_stats_26=stats_26, geobody_stats_6=stats_6,
        well_matrix_26=M, well_names=names, body_sets_26=body_sets,
    )


def connectivity_summary_row(c: DeckConnectivity) -> dict:
    """Compact one-line summary suited for the per-experiment CSV."""
    top1 = c.geobody_stats_26[0] if c.geobody_stats_26 else None
    inj_idx = [i for i, n in enumerate(c.well_names) if n.upper().startswith("INJ")]
    prod_idx = [i for i, n in enumerate(c.well_names) if not n.upper().startswith("INJ")]
    n_inj_conn_per_prod = []
    for p in prod_idx:
        n_inj_conn_per_prod.append(int(c.well_matrix_26[p, inj_idx].sum()))
    return {
        "experiment": c.experiment,
        "directory": c.directory,
        "cluster": c.cluster,
        "seed": c.seed,
        "n_bodies_26": c.n_bodies_26,
        "n_bodies_6": c.n_bodies_6,
        "frac_sand_in_largest_26": c.frac_sand_in_largest_26,
        "frac_sand_in_largest_6": c.frac_sand_in_largest_6,
        "frac_sand_in_top10_26": c.frac_sand_in_top10_26,
        "top1_n_cells": top1.n_cells if top1 else 0,
        "top1_anisotropy": top1.anisotropy if top1 else 0.0,
        "top1_orientation_deg": top1.orientation_deg if top1 else 0.0,
        "n_producers": len(prod_idx),
        "n_injectors": len(inj_idx),
        "mean_inj_connections_per_producer":
            float(np.mean(n_inj_conn_per_prod)) if n_inj_conn_per_prod else 0.0,
        "max_inj_connections_per_producer":
            int(max(n_inj_conn_per_prod)) if n_inj_conn_per_prod else 0,
        "n_producers_connected_to_any_inj":
            int(sum(1 for x in n_inj_conn_per_prod if x > 0)),
    }

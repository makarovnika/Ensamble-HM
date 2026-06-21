"""Map well trajectories onto ECLIPSE corner-point grid cells.

The traversal is reduced to two 1-D problems by exploiting the fact that
tNavigator emits **near-vertical pillars** for this dataset (max XY drift of
top vs bottom < 0.6 m on cells of ≈100 m — see session-025 audit):

  * **XY → (i, j)**: a pillar polygon test on the top face of the grid
    accelerated by a kd-tree over cell-top centroids.
  * **Z → k**: for each (i, j) column, bracket the sample's depth in the
    mean top/bottom Z of every layer's ZCORN samples.

The exported ``welltrack_to_cells(...)`` returns one row per cell pierced
by the polyline, with the cell's effective thickness ``dz_eff`` and an
``MD``-based perforation flag (from optional ``COMPDATMD`` intervals).

These approximations are documented in the sidecar of every artefact that
uses this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.spatial import cKDTree

from cmp_ensemble.io.grdecl import GridGeometry

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# GridIndex — precomputed per-grid lookup structure
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class GridIndex:
    """Precomputed (i,j,k) lookup structure for a single grid geometry.

    Build once per model; reuse across all 23 wells.
    """
    nx: int
    ny: int
    nz: int
    # Top-face pillar XY arranged by (j, i): shape (ny+1, nx+1, 2)
    pillar_xy_top: np.ndarray
    # ZCORN reshaped to (nz, 2, ny, 2, nx, 2)
    zcorn_4d: np.ndarray
    # Top-face cell centroids in plan: shape (ny*nx, 2)
    cell_top_centroid: np.ndarray
    # kd-tree on cell_top_centroid for fast XY → candidate (i, j)
    tree: cKDTree


def build_grid_index(geometry: GridGeometry) -> GridIndex:
    """Reshape COORD/ZCORN into the lookup form."""
    if geometry.coord is None or geometry.zcorn is None:
        raise ValueError(
            "geometry has no COORD/ZCORN — supply the companion .grdecl when "
            "loading the deck (see read_grid_geometry)"
        )
    nx, ny, nz = geometry.nx, geometry.ny, geometry.nz
    coord = geometry.coord.reshape(ny + 1, nx + 1, 6)
    # Vertical-pillar approximation: take top XY as the pillar's plan position
    pillar_xy_top = coord[..., :2].astype(np.float64)  # (ny+1, nx+1, 2)
    # Cell-top centroid = average of 4 surrounding pillars
    cell_top = 0.25 * (
        pillar_xy_top[:-1, :-1] + pillar_xy_top[1:, :-1] +
        pillar_xy_top[:-1, 1:] + pillar_xy_top[1:, 1:]
    )  # (ny, nx, 2)
    tree = cKDTree(cell_top.reshape(-1, 2))
    # ZCORN raw layout (Eclipse convention): for each (k, j, i), the eight
    # corners come in the order top-j0-i0, top-j0-i1, top-j1-i0, top-j1-i1,
    # bot-j0-i0, … . The flat layout is
    #   index = ((((k*2 + zside)*ny + j)*2 + jside)*nx + i)*2 + iside
    # so the natural reshape is (nz, 2, ny, 2, nx, 2).
    zcorn_4d = geometry.zcorn.reshape(nz, 2, ny, 2, nx, 2).astype(np.float64)
    return GridIndex(
        nx=nx, ny=ny, nz=nz,
        pillar_xy_top=pillar_xy_top,
        zcorn_4d=zcorn_4d,
        cell_top_centroid=cell_top.reshape(-1, 2),
        tree=tree,
    )


# ──────────────────────────────────────────────────────────────────────────
# Geometric primitives
# ──────────────────────────────────────────────────────────────────────────


def _point_in_quad(px: float, py: float, quad: np.ndarray) -> bool:
    """Cross-product winding test for a 4-vertex polygon (order: SW,SE,NE,NW).

    ``quad`` is shape (4, 2); convex or weakly non-convex grid cells pass.
    """
    sign = None
    for k in range(4):
        ax, ay = quad[k]
        bx, by = quad[(k + 1) % 4]
        cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
        if cross == 0:
            continue
        cur = cross > 0
        if sign is None:
            sign = cur
        elif sign != cur:
            return False
    return True


def _xy_to_ij(idx: GridIndex, x: float, y: float, k_neighbors: int = 6
              ) -> tuple[int, int] | None:
    """Find the (i, j) cell whose top-face polygon contains XY, or ``None``.

    Uses the kd-tree on cell-top centroids to pull ``k_neighbors`` candidates
    and tests each with the cross-product polygon test.
    """
    _, idxs = idx.tree.query([x, y], k=min(k_neighbors, idx.nx * idx.ny))
    for flat in np.atleast_1d(idxs):
        j, i = divmod(int(flat), idx.nx)
        quad = np.array([
            idx.pillar_xy_top[j,     i],     # SW
            idx.pillar_xy_top[j,     i + 1], # SE
            idx.pillar_xy_top[j + 1, i + 1], # NE
            idx.pillar_xy_top[j + 1, i],     # NW
        ])
        if _point_in_quad(x, y, quad):
            return i, j
    return None


def _z_to_k(idx: GridIndex, i: int, j: int, z: float) -> int | None:
    """Find the k-layer in column (i, j) whose mean Z range brackets ``z``."""
    # Mean top of cell k at (i,j) = mean of 4 top-corners; same for bot.
    # Vectorised over k.
    z_top = idx.zcorn_4d[:, 0, j, :, i, :].mean(axis=(1, 2))  # (nz,)
    z_bot = idx.zcorn_4d[:, 1, j, :, i, :].mean(axis=(1, 2))
    in_layer = (z >= z_top) & (z <= z_bot)
    where = np.where(in_layer)[0]
    if where.size == 0:
        return None
    return int(where[0])


# ──────────────────────────────────────────────────────────────────────────
# Welltrack sampling and cell aggregation
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class CellTraversal:
    well: str
    i: int
    j: int
    k: int
    dz_eff: float
    md_in: float
    md_out: float
    perforated: bool


def _segment_overlaps_intervals(
    md_in: float, md_out: float,
    intervals: list[tuple[float, float]],
    eps: float = 1e-6,
) -> bool:
    """Return True iff the run [md_in, md_out] overlaps any (mdl, mdu) strictly.

    Open-overlap convention (``eps`` margin) keeps adjacent cells whose runs
    touch the perforation boundary by a single point classified as
    un-perforated — matching how Eclipse / tNavigator treats COMPDATMD limits.
    """
    a, b = (min(md_in, md_out), max(md_in, md_out))
    for mdl, mdu in intervals:
        if max(a, mdl) + eps < min(b, mdu):
            return True
    return False


def welltrack_to_cells(
    track: np.ndarray,
    idx: GridIndex,
    well: str = "",
    perforation_md: list[tuple[float, float]] | None = None,
    ds: float = 0.5,
) -> list[CellTraversal]:
    """Walk a polyline track, sample every ``ds`` metres of MD, collapse to cells.

    Parameters
    ----------
    track : np.ndarray
        Shape ``(n_points, 4)`` columns ``X Y Z MD`` (output of
        ``read_welltrack``).
    idx : GridIndex
        Precomputed lookup structure for the grid.
    well : str
        Well name copied into every output row.
    perforation_md : list of (md_low, md_high), optional
        From ``read_compdatmd``. If ``None``, every traversed cell is marked
        perforated (CLAUDE.md-documented default per TZ §4 Task 0.2).
    ds : float
        Sampling step in MD metres; 0.5 m gives sub-cell resolution.

    Returns
    -------
    list[CellTraversal]
        One row per contiguous run in the same (i,j,k) cell along the well.
    """
    if track.shape[1] < 4 or track.shape[0] < 2:
        return []
    md_total = float(track[-1, 3] - track[0, 3])
    if md_total <= 0:
        return []
    n = max(2, int(np.ceil(md_total / ds)) + 1)
    md_grid = np.linspace(track[0, 3], track[-1, 3], n)
    # piecewise-linear sampling in MD
    x = np.interp(md_grid, track[:, 3], track[:, 0])
    y = np.interp(md_grid, track[:, 3], track[:, 1])
    z = np.interp(md_grid, track[:, 3], track[:, 2])

    runs: list[CellTraversal] = []
    cur: tuple[int, int, int] | None = None
    md_in = float(md_grid[0])
    z_in = float(z[0])

    for s in range(n):
        ij = _xy_to_ij(idx, float(x[s]), float(y[s]))
        if ij is None:
            cell = None
        else:
            i, j = ij
            k = _z_to_k(idx, i, j, float(z[s]))
            cell = (i, j, k) if k is not None else None

        if cell != cur:
            if cur is not None:
                md_out = float(md_grid[s - 1])
                z_out = float(z[s - 1])
                runs.append(CellTraversal(
                    well=well,
                    i=cur[0], j=cur[1], k=cur[2],
                    dz_eff=abs(z_out - z_in),
                    md_in=md_in, md_out=md_out,
                    perforated=(perforation_md is None) or
                    _segment_overlaps_intervals(md_in, md_out, perforation_md),
                ))
            cur = cell
            md_in = float(md_grid[s])
            z_in = float(z[s])

    # close last run
    if cur is not None:
        md_out = float(md_grid[-1])
        z_out = float(z[-1])
        runs.append(CellTraversal(
            well=well,
            i=cur[0], j=cur[1], k=cur[2],
            dz_eff=abs(z_out - z_in),
            md_in=md_in, md_out=md_out,
            perforated=(perforation_md is None) or
            _segment_overlaps_intervals(md_in, md_out, perforation_md),
        ))
    return runs


def walk_all_wells(
    welltracks: dict[str, np.ndarray],
    idx: GridIndex,
    perforation_md_by_well: dict[str, list[tuple[float, float]]] | None = None,
    ds: float = 0.5,
) -> list[CellTraversal]:
    """Apply ``welltrack_to_cells`` over every well in the model."""
    perf_lookup = perforation_md_by_well or {}
    out: list[CellTraversal] = []
    for name, track in welltracks.items():
        rows = welltrack_to_cells(
            track, idx, well=name,
            perforation_md=perf_lookup.get(name),
            ds=ds,
        )
        out.extend(rows)
    return out

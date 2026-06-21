"""Tests for geolval-001 — welltrack→cells geometry + per-well descriptors.

Covered:
* ``read_compdatmd`` round-trip on a synthetic SCHEDULE.inc;
* ``_point_in_quad`` cross-product winding test;
* ``welltrack_to_cells`` on a synthetic 2×2×3 grid with a vertical and a
  slanted well — known analytic dz_eff, (i,j,k);
* ``calibrate_perm_cutoff`` on a synthetic bi-modal log-PERMX histogram
  (must find the trough) and on a single-peaked one (must return 0);
* ``compute_descriptors`` end-to-end against hand-computed Σ dz_eff and
  Σ permx·dz_eff.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import numpy as np
import pytest

from cmp_ensemble.io.grdecl import GridGeometry, read_compdatmd
from cmp_ensemble.geology.descriptors import (
    calibrate_perm_cutoff,
    compute_descriptors,
)
from cmp_ensemble.geology.welltrack import (
    GridIndex,
    _point_in_quad,
    build_grid_index,
    welltrack_to_cells,
)


# ──────────────────────────────────────────────────────────────────────────
# COMPDATMD
# ──────────────────────────────────────────────────────────────────────────


def test_read_compdatmd_two_wells(tmp_path):
    p = tmp_path / "sched.inc"
    p.write_text(dedent("""\
        -- header
        RPTSCHED
        'WELLS=2' /

        COMPDATMD
        -- comment
           'INJ1'      1*    100.0 200.0 MD OPEN 2* 0.15 1* -6 0 1 1* 1 /
           'INJ1'      1*    200.0 300.0 MD OPEN 2* 0.15 1* -6 0 1 1* 2 /
           'WELL5'     1*    500.0 650.0 MD OPEN 2* 0.15 1* -6 0 1 1* 1 /
           'WELL5'     1*    650.0 700.0 MD SHUT 2* 0.15 1* -6 0 1 1* 2 /
        /

        DATES
         1 'JAN' 2011 /
        """), encoding="utf-8")
    out = read_compdatmd(p)
    assert set(out) == {"INJ1", "WELL5"}
    assert out["INJ1"] == [(100.0, 200.0), (200.0, 300.0)]
    # WELL5's second interval is SHUT → must be dropped
    assert out["WELL5"] == [(500.0, 650.0)]


def test_read_compdatmd_missing_block(tmp_path):
    p = tmp_path / "sched.inc"
    p.write_text("WELSPECS\n /\n", encoding="utf-8")
    assert read_compdatmd(p) == {}


# ──────────────────────────────────────────────────────────────────────────
# _point_in_quad
# ──────────────────────────────────────────────────────────────────────────


def test_point_in_quad_basic():
    unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
    assert _point_in_quad(0.5, 0.5, unit)
    assert _point_in_quad(0.0, 0.0, unit)  # on a vertex
    assert not _point_in_quad(-0.1, 0.5, unit)
    assert not _point_in_quad(1.5, 0.5, unit)


def test_point_in_quad_skewed():
    # parallelogram shifted right by 0.5 at the top
    skew = np.array([[0, 0], [1, 0], [1.5, 1], [0.5, 1]], dtype=float)
    assert _point_in_quad(0.6, 0.5, skew)
    assert not _point_in_quad(0.0, 0.5, skew)  # outside left side


# ──────────────────────────────────────────────────────────────────────────
# welltrack_to_cells on a synthetic 2×2×3 grid
# ──────────────────────────────────────────────────────────────────────────


def _make_uniform_grid(nx: int, ny: int, nz: int,
                       dx: float = 100.0, dy: float = 100.0,
                       dz_layer: float = 10.0,
                       z0: float = 1000.0) -> GridGeometry:
    """Build a perfectly orthogonal corner-point grid for tests.

    COORD: (ny+1)*(nx+1) pillars, each (x_top, y_top, z_top, x_bot, y_bot, z_bot)
    ZCORN: shape (nz, 2, ny, 2, nx, 2) → flat (nx*ny*nz*8).
    """
    coord = np.zeros(((ny + 1) * (nx + 1), 6), dtype=float)
    for j in range(ny + 1):
        for i in range(nx + 1):
            x = i * dx
            y = j * dy
            coord[j * (nx + 1) + i] = [x, y, z0, x, y, z0 + nz * dz_layer]
    zcorn = np.empty((nz, 2, ny, 2, nx, 2), dtype=float)
    for k in range(nz):
        z_top = z0 + k * dz_layer
        z_bot = z_top + dz_layer
        zcorn[k, 0] = z_top  # all top corners of layer k
        zcorn[k, 1] = z_bot
    return GridGeometry(nx=nx, ny=ny, nz=nz,
                        coord=coord.flatten(), zcorn=zcorn.flatten())


def test_welltrack_to_cells_vertical_well():
    geo = _make_uniform_grid(nx=2, ny=2, nz=3, dx=100, dy=100,
                             dz_layer=10, z0=1000)
    idx = build_grid_index(geo)
    # vertical well at (50, 50) — i.e. centre of cell (i=0, j=0)
    track = np.array([
        [50.0, 50.0, 1000.0, 0.0],
        [50.0, 50.0, 1030.0, 30.0],
    ])
    runs = welltrack_to_cells(track, idx, well="V1", ds=0.5)
    cells = [(r.i, r.j, r.k) for r in runs]
    # Should pass through (0,0,0), (0,0,1), (0,0,2)
    assert cells == [(0, 0, 0), (0, 0, 1), (0, 0, 2)]
    # Each cell's dz_eff ≈ 10 m (layer thickness), to within sampling step.
    for r in runs:
        assert abs(r.dz_eff - 10.0) < 1.0


def test_welltrack_to_cells_perforation_filter():
    geo = _make_uniform_grid(nx=1, ny=1, nz=4, dz_layer=10, z0=1000)
    idx = build_grid_index(geo)
    track = np.array([
        [50.0, 50.0, 1000.0, 0.0],
        [50.0, 50.0, 1040.0, 40.0],
    ])
    # Perforate only MD 10..30 — that's cells k=1 and k=2 in this grid.
    runs = welltrack_to_cells(track, idx, well="W1",
                              perforation_md=[(10.0, 30.0)], ds=0.5)
    by_k = {(r.k): r.perforated for r in runs}
    assert by_k[0] is False
    assert by_k[1] is True
    assert by_k[2] is True
    assert by_k[3] is False


# ──────────────────────────────────────────────────────────────────────────
# calibrate_perm_cutoff
# ──────────────────────────────────────────────────────────────────────────


def test_calibrate_perm_cutoff_bi_modal():
    rng = np.random.default_rng(42)
    low_mode = 10 ** rng.normal(loc=0.5, scale=0.2, size=4000)   # ≈ 3 mD
    high_mode = 10 ** rng.normal(loc=3.0, scale=0.2, size=4000)  # ≈ 1000 mD
    permx = np.concatenate([low_mode, high_mode])
    cutoff = calibrate_perm_cutoff(permx)
    # Trough should fall between the two means (10**1.0 = 10 and 10**2.0 = 100).
    assert 1.0 < cutoff < 1000.0, f"cutoff={cutoff} out of bi-modal trough range"


def test_calibrate_perm_cutoff_single_peak_falls_back():
    rng = np.random.default_rng(42)
    permx = 10 ** rng.normal(loc=2.5, scale=0.3, size=10_000)
    cutoff = calibrate_perm_cutoff(permx, fallback_mD=0.0)
    assert cutoff == 0.0


def test_calibrate_perm_cutoff_tiny_array():
    assert calibrate_perm_cutoff(np.array([1.0, 2.0, 3.0]),
                                  fallback_mD=42.0) == 42.0


# ──────────────────────────────────────────────────────────────────────────
# compute_descriptors — analytical check
# ──────────────────────────────────────────────────────────────────────────


def test_compute_descriptors_analytical(tmp_path):
    from cmp_ensemble.geology.welltrack import CellTraversal
    # Grid 2×1×3 — 6 cells. Hand-built traversals for 1 well, 4 cells (k=0..3),
    # each dz_eff = 5 m.
    nx, ny = 2, 1
    poro = np.zeros(6); poro[:] = 0.2
    permx = np.array([100.0, 0.0, 500.0, 1.0, 200.0, 50.0])
    ntg = np.array([1.0, 0.0, 1.0, 1.0, 1.0, 0.0])
    traversals = [
        # cells along the well: (i=0, j=0, k=0..2) — flat indices 0, 2, 4
        CellTraversal(well="W", i=0, j=0, k=0, dz_eff=5.0,
                      md_in=0, md_out=5, perforated=True),
        CellTraversal(well="W", i=0, j=0, k=1, dz_eff=5.0,
                      md_in=5, md_out=10, perforated=True),
        CellTraversal(well="W", i=0, j=0, k=2, dz_eff=5.0,
                      md_in=10, md_out=15, perforated=False),
    ]
    out = compute_descriptors(traversals, poro=poro, permx=permx, ntg=ntg,
                              nx=nx, ny=ny, perm_cutoff=0.5)
    d = out["W"]
    assert d.n_cells_traversed == 3
    assert d.n_cells_perforated == 2
    # flat = (k*ny + j)*nx + i, with (i=0, j=0): k=0→0, k=1→2, k=2→4
    # PERMX = [100, 500, 200]; NTG = [1, 1, 1] → all three are sand,
    # but only k=0,1 are perforated → net_sand = 5+5 = 10 m.
    assert d.n_sand_cells == 3
    assert d.net_sand_penetrated == 10.0
    # kh = 100*5 + 500*5 + 200*5 = 4000
    assert d.kh_penetrated == 4000.0
    assert d.mean_ntg_along_well == 1.0
    assert d.frac_channel_cells == 1.0


def test_compute_descriptors_skips_empty_wells():
    out = compute_descriptors([], poro=np.zeros(1), permx=np.zeros(1),
                              ntg=np.zeros(1), nx=1, ny=1, perm_cutoff=0.0)
    assert out == {}

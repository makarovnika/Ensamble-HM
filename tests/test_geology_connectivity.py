"""Tests for geolval-002 — sand-mask labelling + well-well connectivity."""

from __future__ import annotations

import numpy as np
import pytest

from cmp_ensemble.geology.connectivity import (
    _principal_axes_2d,
    build_sand_mask,
    geobody_stats,
    label_geobodies,
    well_connectivity_matrix,
)


# ──────────────────────────────────────────────────────────────────────────
# build_sand_mask
# ──────────────────────────────────────────────────────────────────────────


def test_sand_mask_reshape_and_rule():
    # Flat layout (k*ny + j)*nx + i with nx=2 ny=2 nz=2 → 8 cells.
    permx = np.array([100, 50, 0, 200, 0.5, 0.0, 300, 10], dtype=float)
    ntg = np.array([1, 1, 0, 1, 1, 1, 0, 1], dtype=float)
    mask = build_sand_mask(permx, ntg, nx=2, ny=2, nz=2, perm_cutoff=1.0)
    assert mask.shape == (2, 2, 2)
    # Sand iff NTG==1 AND PERMX>1: indices 0(100), 1(50), 3(200), 7(10)
    expected = np.zeros(8, dtype=bool)
    expected[[0, 1, 3, 7]] = True
    np.testing.assert_array_equal(mask.flatten(), expected)


# ──────────────────────────────────────────────────────────────────────────
# label_geobodies
# ──────────────────────────────────────────────────────────────────────────


def test_label_geobodies_two_disjoint_blobs_6conn():
    mask = np.zeros((3, 3, 3), dtype=bool)
    mask[0, 0, 0] = True
    mask[2, 2, 2] = True
    labels, n = label_geobodies(mask, connectivity=6)
    assert n == 2
    assert labels[0, 0, 0] != labels[2, 2, 2]


def test_label_geobodies_diagonal_touch_differs_by_conn():
    # Two cells touching only at a corner — connected under 26 but not 6.
    mask = np.zeros((2, 2, 2), dtype=bool)
    mask[0, 0, 0] = True
    mask[1, 1, 1] = True
    _, n6 = label_geobodies(mask, connectivity=6)
    _, n26 = label_geobodies(mask, connectivity=26)
    assert n6 == 2
    assert n26 == 1


def test_label_geobodies_invalid_connectivity_raises():
    with pytest.raises(ValueError):
        label_geobodies(np.zeros((2, 2, 2), dtype=bool), connectivity=18)


# ──────────────────────────────────────────────────────────────────────────
# geobody_stats — bbox, anisotropy, orientation
# ──────────────────────────────────────────────────────────────────────────


def test_geobody_stats_elongated_along_i():
    # A 1×10×1 body — should be axis-aligned, anisotropy ~10, orient ≈ 0°.
    mask = np.zeros((3, 3, 10), dtype=bool)
    mask[1, 1, :] = True
    labels, _ = label_geobodies(mask, connectivity=26)
    stats = geobody_stats(labels)
    assert len(stats) == 1
    g = stats[0]
    assert g.n_cells == 10
    assert g.bbox_extent == (10, 1, 1)
    assert g.anisotropy >= 9
    assert abs(g.orientation_deg) < 5  # along east


def test_geobody_stats_elongated_along_j():
    # 1×1 body of length 8 along j — orientation should be ±90°.
    mask = np.zeros((3, 8, 3), dtype=bool)
    mask[1, :, 1] = True
    labels, _ = label_geobodies(mask, connectivity=26)
    stats = geobody_stats(labels)
    g = stats[0]
    assert g.bbox_extent == (1, 8, 1)
    assert abs(abs(g.orientation_deg) - 90) < 5


def test_geobody_stats_sorted_descending_by_cells():
    mask = np.zeros((3, 3, 6), dtype=bool)
    mask[0, 0, 0:1] = True  # 1 cell
    mask[1, 1, 2:5] = True  # 3 cells, disjoint
    labels, _ = label_geobodies(mask, connectivity=6)
    stats = geobody_stats(labels)
    assert [s.n_cells for s in stats] == sorted([s.n_cells for s in stats],
                                                  reverse=True)


def test_geobody_stats_empty_mask():
    labels = np.zeros((2, 2, 2), dtype=int)
    assert geobody_stats(labels) == []


# ──────────────────────────────────────────────────────────────────────────
# _principal_axes_2d
# ──────────────────────────────────────────────────────────────────────────


def test_principal_axes_horizontal_line():
    coords = np.array([[i, 0] for i in range(10)], dtype=float)
    major, minor, angle = _principal_axes_2d(coords)
    assert major > 0
    assert minor == 0
    assert abs(angle) < 1e-6


def test_principal_axes_diagonal_45deg():
    coords = np.array([[i, i] for i in range(10)], dtype=float)
    _, _, angle = _principal_axes_2d(coords)
    assert abs(angle - 45) < 1


def test_principal_axes_too_few_points():
    coords = np.array([[1.0, 2.0]])
    assert _principal_axes_2d(coords) == (0.0, 0.0, 0.0)


# ──────────────────────────────────────────────────────────────────────────
# well_connectivity_matrix
# ──────────────────────────────────────────────────────────────────────────


def test_well_connectivity_matrix_two_wells_shared_body():
    labels = np.zeros((2, 3, 3), dtype=int)
    labels[0, 0, 0] = 1
    labels[0, 0, 1] = 1
    labels[0, 0, 2] = 2  # separate body
    # WELL_A touches body 1; WELL_B touches body 1 → connected.
    cells = {
        "WELL_A": [(0, 0, 0)],
        "WELL_B": [(1, 0, 0)],
        "WELL_C": [(2, 0, 0)],
    }
    M, names, sets = well_connectivity_matrix(cells, labels,
                                              well_order=["WELL_A", "WELL_B", "WELL_C"])
    assert M.shape == (3, 3)
    assert M[0, 1] is np.True_ or M[0, 1] == True
    assert M[1, 0] == True
    # WELL_C touches body 2 → not connected to A or B
    assert not M[0, 2]
    assert not M[2, 1]
    assert M[2, 2] == True  # diagonal: touches sand
    assert sets["WELL_A"] == {1}
    assert sets["WELL_C"] == {2}


def test_well_connectivity_matrix_out_of_bounds_safely_dropped():
    labels = np.ones((2, 2, 2), dtype=int)
    M, _, _ = well_connectivity_matrix(
        {"W": [(99, 99, 99)]}, labels, well_order=["W"],
    )
    assert M.shape == (1, 1)
    assert M[0, 0] == False  # the (99,99,99) cell was dropped

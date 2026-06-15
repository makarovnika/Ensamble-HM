"""Tests for the GRDECL/keyword parser — geolval-000.

Covered:
- RLE-aware ``read_keyword_cube`` on synthetic fixtures: pure RLE, bare,
  mixed, with leading NOECHO directive and inline ``-- comments``;
- error paths: keyword missing, RLE overrun, RLE underrun, malformed token;
- ``read_grid_geometry`` on a synthetic SPECGRID + FAULTS block;
- ``read_welltrack`` on a synthetic two-well block;
- deck-name classification (``c_s-<seed>.data`` vs centroid);
- a slow smoke test against the real Exp2/300 deck — skipped when the dataset
  is not on disk so CI on a slim checkout still passes.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import numpy as np
import pytest

from cmp_ensemble.io.grdecl import (
    DeckInfo,
    GridGeometry,
    _classify_deck_name,
    read_grid_geometry,
    read_keyword_cube,
    read_welltrack,
    scan_experiment_dir,
)


# ──────────────────────────────────────────────────────────────────────────
# read_keyword_cube — RLE + edge cases
# ──────────────────────────────────────────────────────────────────────────


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(dedent(body), encoding="utf-8")
    return p


def test_keyword_cube_pure_rle(tmp_path):
    p = _write(tmp_path, "ntg.inc", """\
        NOECHO

        NTG
          3*1 2*0 1 /
        """)
    arr = read_keyword_cube(p, "NTG", 6)
    np.testing.assert_array_equal(arr, [1, 1, 1, 0, 0, 1])


def test_keyword_cube_bare_floats(tmp_path):
    p = _write(tmp_path, "poro.inc", """\
        PORO
          0.10 0.20 0.30
          0.40 0.50 /
        """)
    arr = read_keyword_cube(p, "PORO", 5)
    np.testing.assert_allclose(arr, [0.1, 0.2, 0.3, 0.4, 0.5])


def test_keyword_cube_mixed_and_comments(tmp_path):
    p = _write(tmp_path, "permx.inc", """\
        -- file header
        NOECHO

        PERMX
        -- comment in the middle
          2*100.0 50.0 -- inline comment
          3*0 1000.0 /
        """)
    arr = read_keyword_cube(p, "PERMX", 7)
    np.testing.assert_allclose(arr, [100, 100, 50, 0, 0, 0, 1000])


def test_keyword_cube_int_dtype_satnum(tmp_path):
    p = _write(tmp_path, "satnum.inc", """\
        SATNUM
          4*3 2*5 1 /
        """)
    arr = read_keyword_cube(p, "SATNUM", 7, dtype=np.int32)
    assert arr.dtype == np.int32
    np.testing.assert_array_equal(arr, [3, 3, 3, 3, 5, 5, 1])


def test_keyword_cube_missing_keyword_raises(tmp_path):
    p = _write(tmp_path, "foo.inc", """\
        PORO
          0.1 0.2 /
        """)
    with pytest.raises(ValueError, match="keyword 'NTG' not found"):
        read_keyword_cube(p, "NTG", 2)


def test_keyword_cube_overrun_raises(tmp_path):
    p = _write(tmp_path, "ntg.inc", """\
        NTG
          5*1 /
        """)
    with pytest.raises(ValueError, match="overruns"):
        read_keyword_cube(p, "NTG", 3)


def test_keyword_cube_underrun_raises(tmp_path):
    p = _write(tmp_path, "ntg.inc", """\
        NTG
          2*1 /
        """)
    with pytest.raises(ValueError, match=r"produced 2 values, expected 5"):
        read_keyword_cube(p, "NTG", 5)


def test_keyword_cube_malformed_token_raises(tmp_path):
    p = _write(tmp_path, "ntg.inc", """\
        NTG
          1 abc 1 /
        """)
    with pytest.raises(ValueError, match="cannot parse token 'abc'"):
        read_keyword_cube(p, "NTG", 3)


# ──────────────────────────────────────────────────────────────────────────
# read_grid_geometry
# ──────────────────────────────────────────────────────────────────────────


def test_grid_geometry_specgrid_and_faults(tmp_path):
    p = _write(tmp_path, "g.inc", """\
        -- header
        SPECGRID
         10 20 5 /

        FAULTS
        -- name        i1 i2 j1 j2 k1 k2 dir
          'FA' 1 1 5 5 1 5 I   /
          'FB' 2 3 7 7 2 4 J-  /
        /
        """)
    geo = read_grid_geometry(p)
    assert (geo.nx, geo.ny, geo.nz) == (10, 20, 5)
    assert geo.n_cells == 1000
    assert len(geo.faults) == 2
    assert geo.faults[0] == dict(name="FA", i1=1, i2=1, j1=5, j2=5,
                                  k1=1, k2=5, dir="I")
    assert geo.faults[1]["dir"] == "J-"


def test_grid_geometry_with_grdecl_coord_zcorn(tmp_path):
    g = _write(tmp_path, "g.inc", "SPECGRID\n 2 1 1 /\n")
    grdecl = _write(tmp_path, "x.grdecl", """\
        COORD
          0 0 0 0 0 0
          1 0 0 1 0 0
          0 1 0 0 1 0
          1 1 0 1 1 0 /
        ZCORN
          16*0 16*1 /
        """)
    geo = read_grid_geometry(g, grdecl)
    assert geo.coord is not None and geo.coord.size == 24
    assert geo.zcorn is not None and geo.zcorn.size == 32  # 16 + 16


def test_grid_geometry_specgrid_missing(tmp_path):
    p = _write(tmp_path, "g.inc", "FAULTS\n /\n")
    with pytest.raises(ValueError, match="SPECGRID"):
        read_grid_geometry(p)


# ──────────────────────────────────────────────────────────────────────────
# read_welltrack
# ──────────────────────────────────────────────────────────────────────────


def test_welltrack_two_wells(tmp_path):
    p = _write(tmp_path, "wt.inc", """\
        -- generated by tNavigator
        WELLTRACK 'INJ1'
        -- X             Y            Z        MD
           100.0  200.0   0.0     0.0
           100.0  200.0 100.0   100.0
           101.0  200.0 110.0   111.0 /

        WELLTRACK 'PROD7'
           500.0  400.0   0.0     0.0
           500.0  450.0  10.0    50.0 /
        """)
    tracks = read_welltrack(p)
    assert set(tracks) == {"INJ1", "PROD7"}
    assert tracks["INJ1"].shape == (3, 4)
    assert tracks["PROD7"].shape == (2, 4)
    np.testing.assert_allclose(tracks["INJ1"][-1], [101.0, 200.0, 110.0, 111.0])


def test_welltrack_empty_when_no_blocks(tmp_path):
    p = _write(tmp_path, "wt.inc", "-- nothing here\n")
    assert read_welltrack(p) == {}


# ──────────────────────────────────────────────────────────────────────────
# Deck-name classification + scan_experiment_dir
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name, expected", [
    ("0_4-32434.data", (0, 32434, False)),
    ("1_1-95424.data", (1, 95424, False)),
    ("2_1-742.data",   (2, 742,   False)),
    ("0_1-centroid.data", (0, None, True)),
    ("2-centroid_1.data", (2, None, True)),
    ("random_name.data",  (None, None, False)),
])
def test_classify_deck_name(name, expected):
    assert _classify_deck_name(name) == expected


def test_scan_experiment_dir_synthetic(tmp_path):
    # Build a fake experiment root with 2 model dirs + one empty dir
    (tmp_path / "100").mkdir()
    (tmp_path / "100" / "0_4-12345.data").write_text("RUN /\n", encoding="utf-8")
    (tmp_path / "100" / "RESULTS").mkdir()
    (tmp_path / "200").mkdir()
    (tmp_path / "200" / "1_1-67890.data").write_text("RUN /\n", encoding="utf-8")
    (tmp_path / "300_empty").mkdir()  # skipped — no deck

    decks = scan_experiment_dir(tmp_path, 99)
    assert len(decks) == 2
    by_seed = {d.seed: d for d in decks}
    assert set(by_seed) == {12345, 67890}
    assert by_seed[12345].has_results is True
    assert by_seed[67890].has_results is False
    assert by_seed[12345].cluster == 0
    assert by_seed[12345].include_dir == tmp_path / "100" / "INCLUDE"


# ──────────────────────────────────────────────────────────────────────────
# Smoke test against the real Exp2 deck (slow — skipped if dataset absent)
# ──────────────────────────────────────────────────────────────────────────


REAL_DECK = Path("simulation models results/Experiment 2/300")


@pytest.mark.skipif(not REAL_DECK.exists(),
                    reason="real Watt Field dataset not on disk")
def test_real_exp2_300_full_grid():
    stem = "0_4-32434"
    inc = REAL_DECK / "INCLUDE"
    geo = read_grid_geometry(inc / f"{stem}_GRID.inc")
    assert (geo.nx, geo.ny, geo.nz) == (227, 59, 40)
    assert geo.n_cells == 535_720
    assert len(geo.faults) > 100
    poro = read_keyword_cube(inc / f"{stem}_PORO.inc", "PORO", geo.n_cells)
    assert poro.shape == (geo.n_cells,)
    assert np.isnan(poro).sum() == 0
    assert (poro >= 0).all()
    ntg = read_keyword_cube(inc / f"{stem}_NTG.inc", "NTG", geo.n_cells)
    assert set(np.unique(ntg).tolist()).issubset({0.0, 1.0})
    wt = read_welltrack(inc / f"{stem}_WELLTRACK.inc")
    assert len(wt) == 23

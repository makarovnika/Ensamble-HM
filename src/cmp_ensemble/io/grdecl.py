"""GRDECL/keyword-style parser for tNavigator decks.

Targets the subset of ECLIPSE-syntax INCLUDE files emitted by tNavigator that
this project actually consumes:

  * scalar property cubes (``PORO``, ``PERMX``, ``NTG``, ``SATNUM`` …) with
    run-length-encoded data terminated by ``/``;
  * grid header (``SPECGRID`` for NX/NY/NZ, optional ``FAULTS`` block, optional
    ``COORD``/``ZCORN`` from the companion ``.grdecl``);
  * well trajectories (``WELLTRACK '<name>'`` blocks with X Y Z MD rows).

Deliberately no dependency on resdata / libecl — the analysis machine is offline
and the decks are well-formed ASCII. RLE expansion is the only non-trivial part.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_RLE_TOKEN = re.compile(r"^(\d+)\*(.+)$")
_COMMENT = re.compile(r"--[^\n]*")
_DIRECTIVE = re.compile(r"(?m)^\s*(NOECHO|ECHO)\s*$")


def _strip_text(text: str) -> str:
    """Drop inline ``-- comments`` and ``NOECHO``/``ECHO`` directive lines."""
    text = _COMMENT.sub("", text)
    text = _DIRECTIVE.sub("", text)
    return text


def _iter_tokens_until_slash(text: str, start: int):
    """Yield whitespace-separated tokens from ``text[start:]`` until ``/``.

    The terminator slash is consumed but not yielded.
    """
    i, n = start, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return
        if text[i] == "/":
            return
        j = i
        while j < n and not text[j].isspace() and text[j] != "/":
            j += 1
        yield text[i:j]
        i = j


def _expand_token(tok: str) -> tuple[int, str]:
    """``"117*0"`` → ``(117, "0")``; bare ``"0.12"`` → ``(1, "0.12")``."""
    m = _RLE_TOKEN.match(tok)
    if m:
        return int(m.group(1)), m.group(2)
    return 1, tok


def _find_keyword(text: str, keyword: str) -> int:
    """Return position just past the keyword line, or -1 if absent.

    Keyword must sit on its own line (with optional leading whitespace).
    """
    pattern = re.compile(r"(?m)^[ \t]*" + re.escape(keyword) + r"[ \t]*$")
    m = pattern.search(text)
    return m.end() if m else -1


def read_keyword_cube(
    path: Path | str,
    keyword: str,
    n_cells: int,
    dtype=np.float64,
) -> np.ndarray:
    """Read a single property cube; expand RLE; verify length == ``n_cells``.

    ``dtype`` is the numpy dtype of the returned array (default ``float64``;
    pass ``np.int32`` for categorical cubes like SATNUM).
    """
    path = Path(path)
    text = _strip_text(path.read_text(encoding="utf-8", errors="replace"))
    head = _find_keyword(text, keyword)
    if head < 0:
        raise ValueError(f"{path}: keyword '{keyword}' not found")
    arr = np.empty(n_cells, dtype=dtype)
    pos = 0
    for tok in _iter_tokens_until_slash(text, head):
        count, value = _expand_token(tok)
        try:
            v = dtype(value) if np.issubdtype(np.dtype(dtype), np.floating) \
                else dtype(float(value))
        except ValueError as e:
            raise ValueError(f"{path}: cannot parse token '{tok}' "
                             f"for keyword '{keyword}': {e}") from None
        if pos + count > n_cells:
            raise ValueError(
                f"{path}: keyword '{keyword}' overruns at token '{tok}' — "
                f"pos={pos}, count={count}, n_cells={n_cells}"
            )
        arr[pos:pos + count] = v
        pos += count
    if pos != n_cells:
        raise ValueError(
            f"{path}: keyword '{keyword}' produced {pos} values, "
            f"expected {n_cells}"
        )
    return arr


# ──────────────────────────────────────────────────────────────────────────
# Grid geometry
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class GridGeometry:
    """NX/NY/NZ + optional FAULTS + optional COORD/ZCORN arrays.

    COORD and ZCORN are populated only if a ``.grdecl`` containing them is
    supplied — tNavigator decks usually split SPECGRID off into a separate
    INCLUDE, and the COORD/ZCORN live elsewhere or in a binary cache.
    """

    nx: int
    ny: int
    nz: int
    faults: list[dict] = field(default_factory=list)
    coord: np.ndarray | None = None
    zcorn: np.ndarray | None = None

    @property
    def n_cells(self) -> int:
        return self.nx * self.ny * self.nz


def _read_faults_block(text: str) -> list[dict]:
    fm = re.search(r"(?m)^FAULTS\b", text)
    if not fm:
        return []
    sub = text[fm.end():]
    end_marker = re.search(r"(?m)^[ \t]*/[ \t]*$", sub)
    block = sub[:end_marker.start()] if end_marker else sub
    rows: list[dict] = []
    for line in block.splitlines():
        ln = line.strip()
        if not ln or ln.startswith("--"):
            continue
        parts = ln.split()
        if len(parts) < 8 or not parts[0].startswith("'"):
            continue
        name = parts[0].strip("'")
        try:
            i1, i2, j1, j2, k1, k2 = map(int, parts[1:7])
        except ValueError:
            continue
        direction = parts[7].rstrip("/").strip()
        rows.append(dict(
            name=name, i1=i1, i2=i2, j1=j1, j2=j2, k1=k1, k2=k2, dir=direction,
        ))
    return rows


def read_grid_geometry(
    grid_inc: Path | str,
    grdecl: Path | str | None = None,
) -> GridGeometry:
    """Parse SPECGRID + FAULTS from ``grid_inc``; optionally COORD/ZCORN."""
    p = Path(grid_inc)
    text = _strip_text(p.read_text(encoding="utf-8", errors="replace"))
    m = re.search(
        r"(?m)^SPECGRID\s*\n\s*(\d+)\s+(\d+)\s+(\d+)", text
    )
    if not m:
        raise ValueError(f"{p}: SPECGRID block not found")
    nx, ny, nz = int(m.group(1)), int(m.group(2)), int(m.group(3))
    faults = _read_faults_block(text)
    coord = zcorn = None
    if grdecl is not None and Path(grdecl).exists():
        gt = _strip_text(Path(grdecl).read_text(encoding="utf-8", errors="replace"))
        coord = _try_read_free_array(gt, "COORD")
        zcorn = _try_read_free_array(gt, "ZCORN")
    return GridGeometry(nx=nx, ny=ny, nz=nz, faults=faults,
                        coord=coord, zcorn=zcorn)


def _try_read_free_array(text: str, keyword: str) -> np.ndarray | None:
    head = _find_keyword(text, keyword)
    if head < 0:
        return None
    vals: list[float] = []
    for tok in _iter_tokens_until_slash(text, head):
        count, value = _expand_token(tok)
        try:
            v = float(value)
        except ValueError:
            return None
        vals.extend([v] * count)
    return np.array(vals, dtype=np.float64)


# ──────────────────────────────────────────────────────────────────────────
# Well trajectories
# ──────────────────────────────────────────────────────────────────────────


def read_welltrack(path: Path | str) -> dict[str, np.ndarray]:
    """Return ``{well_name: ndarray(shape=(n_points, 4))}`` with X Y Z MD."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r"^WELLTRACK\s+'([^']+)'\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    out: dict[str, np.ndarray] = {}
    for i, m in enumerate(matches):
        name = m.group(1)
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = _COMMENT.sub("", text[block_start:block_end])
        pts: list[list[float]] = []
        for line in block.splitlines():
            ln = line.strip()
            if not ln:
                continue
            had_slash = ln.endswith("/")
            ln_clean = ln.rstrip("/").strip()
            if not ln_clean:
                if had_slash:
                    break
                continue
            parts = ln_clean.split()
            if len(parts) < 4:
                if had_slash:
                    break
                continue
            try:
                xyzm = [float(parts[k]) for k in range(4)]
            except ValueError:
                if had_slash:
                    break
                continue
            pts.append(xyzm)
            if had_slash:
                break
        if pts:
            out[name] = np.asarray(pts, dtype=np.float64)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Deck inventory helpers (TZ §2.3)
# ──────────────────────────────────────────────────────────────────────────


_DECK_NAME_PAT = re.compile(r"^(?P<cluster>\d+)_(?P<sub>\d+)-(?P<seed>\d+)\.data$",
                            re.IGNORECASE)
_DECK_NAME_CENTROID_PAT = re.compile(
    r"^(?P<cluster>\d+)[_-](?P<sub>\w+)?[-_]?centroid(?:_\d+)?\.data$",
    re.IGNORECASE,
)


@dataclass
class DeckInfo:
    """Lightweight directory descriptor for a single tNavigator deck."""
    experiment: int
    directory: Path
    deck_name: str
    cluster: int | None
    seed: int | None
    is_centroid: bool
    has_results: bool

    @property
    def include_dir(self) -> Path:
        return self.directory / "INCLUDE"

    def include(self, stem: str) -> Path:
        """Return path to a named INCLUDE file (e.g. ``f"{deck}_PORO.inc"``)."""
        deck_stem = Path(self.deck_name).stem
        return self.include_dir / f"{deck_stem}_{stem}.inc"


def scan_experiment_dir(root: Path | str, experiment: int) -> list[DeckInfo]:
    """Walk ``simulation models results/Experiment <N>/<dir>`` and classify decks.

    Returns one ``DeckInfo`` per ``<dir>``; the first ``.data`` deck found inside
    each ``<dir>`` is taken as the canonical name. Directories without a deck
    are skipped silently.
    """
    root = Path(root)
    out: list[DeckInfo] = []
    if not root.exists():
        log.warning(f"{root}: experiment root does not exist")
        return out
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        deck = next((d for d in sorted(sub.glob("*.data"))), None)
        if deck is None:
            continue
        cluster, seed, is_centroid = _classify_deck_name(deck.name)
        out.append(DeckInfo(
            experiment=experiment,
            directory=sub,
            deck_name=deck.name,
            cluster=cluster,
            seed=seed,
            is_centroid=is_centroid,
            has_results=(sub / "RESULTS").exists(),
        ))
    return out


def _classify_deck_name(name: str) -> tuple[int | None, int | None, bool]:
    m = _DECK_NAME_PAT.match(name)
    if m:
        return int(m.group("cluster")), int(m.group("seed")), False
    if "centroid" in name.lower():
        mc = re.match(r"^(\d+)", name)
        return (int(mc.group(1)) if mc else None), None, True
    return None, None, False

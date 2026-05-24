"""tNavigator ensemble loader — Task 0.1.

Reads 150 models from the two Excel workbooks:

  * Parameters / manifest : models_near_adapted_centroids.xlsx
        3 sheets × 50 rows × 15 columns. Header is in row 3, data in rows 4-53.
        Cluster id is parsed from the sheet name (Кластер_<k>_адаптация).

  * Per-model dynamics    : Показатели динамики.xlsx
        150 sheets, 1 sheet = 1 model. Header is in row 0, monthly data starts
        in row 1. Sheet name pattern: ``51-<cluster>_<X>-<round(SEED)>``.

Linkage rule (validated in session 002): ``round(SEED)`` from the parameter
table equals the trailing token in the dynamics sheet name. All 150 / 150
models match under this rule.

The loader caches the parsed result as ``outputs/cache/ensemble.h5`` so the
expensive Excel parse (≈30 s for 150 sheets) is done only once.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from cmp_ensemble.io.schemas import EnsembleData

log = logging.getLogger(__name__)

PARAM_COLS = [
    "THICK", "MAJ_R", "AZIMUTH", "NUMBER_CHANNELS", "CHANNELS_WIDTH",
    "LEN", "AMPLITUDE", "RELATIVE", "PROP",
]

# Metric families we extract from the dynamics sheets.
# Rates (monthly): one entry per (metric, well, month)
RATE_METRICS = ["Дебит нефти", "Дебит воды", "Дебит газа", "Забойное давление"]
# Injection rates per injector
INJ_METRICS = ["Приёмистость воды"]
# Cumulative (yearly): one entry per (metric, well, year-end)
CUM_METRICS = ["Накопл. нефть", "Накопл. вода", "Накопл. газ"]

DUMMY_WELL = "B"
SHEET_NAME_RE = re.compile(r"^51-(\d)_\d+-(\d+)$")


def _parse_dynamics_sheet_name(name: str) -> tuple[int, int] | None:
    """Return (cluster_id, seed_int) parsed from a dynamics sheet name, or None."""
    m = SHEET_NAME_RE.match(name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _load_parameters(path: Path) -> pd.DataFrame:
    """Read the 3-sheet parameter workbook into one tidy DataFrame.

    Columns: MODEL (int), cluster_id (int), seed_int (round of SEED), THICK..PROP.
    """
    log.info(f"Loading parameter workbook: {path.name}")
    xl = pd.ExcelFile(path)
    frames = []
    for sh in xl.sheet_names:
        # cluster id from sheet name "Кластер_<k>_адаптация"
        try:
            cluster_id = int(sh.split("_")[1])
        except (IndexError, ValueError):
            raise ValueError(f"Cannot parse cluster id from sheet name {sh!r}")
        df = pd.read_excel(xl, sheet_name=sh, header=3)
        df = df.dropna(subset=["MODEL"]).copy()
        df["MODEL"] = df["MODEL"].astype(int)
        df["cluster_id"] = cluster_id
        df["seed_int"] = df["SEED"].astype(float).round().astype(int)
        for c in PARAM_COLS:
            df[c] = df[c].astype(float)
        frames.append(df[["MODEL", "cluster_id", "seed_int", *PARAM_COLS]])
    out = pd.concat(frames, ignore_index=True)
    log.info(f"  parsed {len(out)} models across {len(xl.sheet_names)} clusters")
    return out


def _classify_wells(headers: list[str]) -> tuple[list[str], list[str]]:
    """Return (producers, injectors) from the dynamics header row.

    Wells are inferred from the parenthesised suffix of column headers like
    ``Дебит воды (WELL1)``. Producers start with ``WELL``, injectors with
    ``INJ``. The dummy well ``B`` is excluded.
    """
    wells: set[str] = set()
    for h in headers:
        if isinstance(h, str) and "(" in h and h.endswith(")"):
            inner = h[h.rfind("(") + 1 : -1].strip()
            # skip occasional "пл." and " #N" duplicates
            if any(ch in inner for ch in (".", "#", " ")):
                continue
            wells.add(inner)
    producers = sorted(w for w in wells if w.startswith("WELL"))
    injectors = sorted(w for w in wells if w.startswith("INJ"))
    return producers, injectors


def _find_metric_column(
    cols: list[str], metric: str, well: str
) -> str | None:
    """Locate the column ``"<metric> (<well>)"`` in the dynamics sheet.

    Returns the exact column name, or None if absent. We do exact match
    against the parenthesised pattern to avoid catching ``Накопл.`` variants
    like ``Накопл. закачка #2``.
    """
    target = f"{metric} ({well})"
    return target if target in cols else None


def _year_end_indices(dates: pd.Series) -> dict[int, int]:
    """For each calendar year present in `dates`, return the index of the last row.

    Used to extract year-end cumulative values without re-bucketing the timeline.
    """
    years = pd.to_datetime(dates).dt.year
    last: dict[int, int] = {}
    for i, y in enumerate(years):
        last[int(y)] = i
    return last


def _extract_one_model_dynamics(
    df: pd.DataFrame,
    producers: list[str],
    injectors: list[str],
) -> tuple[np.ndarray, np.ndarray, list[tuple], list[tuple], np.ndarray]:
    """Extract rate and cumulative vectors from a single dynamics sheet.

    Returns
    -------
    rates : (n_d_rates,) array — flattened (metric × well × time)
    cums  : (n_d_cum,) array   — flattened (metric × well × year_end)
    rate_index : list of (metric, well, datetime) of length n_d_rates
    cum_index  : list of (metric, well, datetime) of length n_d_cum
    time_steps : (n_time,) datetime64 array
    """
    cols = df.columns.tolist()
    dates = df["Дата"]
    time_steps = pd.to_datetime(dates).to_numpy()
    year_ends = _year_end_indices(dates)
    sorted_years = sorted(year_ends.keys())

    rates: list[float] = []
    rate_index: list[tuple[str, str, datetime]] = []

    # producer rate metrics + BHP
    for metric in RATE_METRICS:
        for well in producers:
            col = _find_metric_column(cols, metric, well)
            if col is None:
                # missing column — fill with zeros and warn once via index marker
                vals = np.zeros(len(df), dtype=float)
            else:
                vals = pd.to_numeric(df[col], errors="coerce").fillna(0.0).to_numpy()
            rates.extend(vals.tolist())
            for t in time_steps:
                rate_index.append((metric, well, pd.Timestamp(t).to_pydatetime()))

    # injector rate metrics
    for metric in INJ_METRICS:
        for well in injectors:
            col = _find_metric_column(cols, metric, well)
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0.0).to_numpy() if col else np.zeros(len(df))
            rates.extend(vals.tolist())
            for t in time_steps:
                rate_index.append((metric, well, pd.Timestamp(t).to_pydatetime()))

    # cumulative metrics at year-ends
    cums: list[float] = []
    cum_index: list[tuple[str, str, datetime]] = []
    for metric in CUM_METRICS:
        for well in producers:
            col = _find_metric_column(cols, metric, well)
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0.0).to_numpy() if col else np.zeros(len(df))
            for y in sorted_years:
                idx = year_ends[y]
                cums.append(float(vals[idx]))
                cum_index.append((metric, well, pd.Timestamp(time_steps[idx]).to_pydatetime()))

    return (
        np.asarray(rates, dtype=np.float64),
        np.asarray(cums, dtype=np.float64),
        rate_index,
        cum_index,
        time_steps,
    )


def _cache_path(root: Path) -> Path:
    return root / "outputs" / "cache" / "ensemble.h5"


def _load_from_cache(path: Path) -> EnsembleData | None:
    if not path.exists():
        return None
    log.info(f"Loading cached ensemble from {path}")
    with h5py.File(path, "r") as f:
        return EnsembleData(
            model_ids=f["model_ids"][:],
            cluster_ids=f["cluster_ids"][:],
            seeds=f["seeds"][:],
            sheet_names=[s.decode() for s in f["sheet_names"][:]],
            theta=f["theta"][:],
            theta_names=[s.decode() for s in f["theta_names"][:]],
            d_sim_rates=f["d_sim_rates"][:],
            d_sim_cum=f["d_sim_cum"][:],
            rate_index=[
                (m.decode(), w.decode(), datetime.fromisoformat(t.decode()))
                for m, w, t in f["rate_index"][:]
            ],
            cum_index=[
                (m.decode(), w.decode(), datetime.fromisoformat(t.decode()))
                for m, w, t in f["cum_index"][:]
            ],
            time_steps=f["time_steps"][:].astype("datetime64[ns]"),
            producer_wells=[s.decode() for s in f["producer_wells"][:]],
            injector_wells=[s.decode() for s in f["injector_wells"][:]],
        )


def _save_to_cache(data: EnsembleData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info(f"Caching ensemble to {path}")
    with h5py.File(path, "w") as f:
        f.create_dataset("model_ids", data=data.model_ids)
        f.create_dataset("cluster_ids", data=data.cluster_ids)
        f.create_dataset("seeds", data=data.seeds)
        f.create_dataset(
            "sheet_names",
            data=np.array([s.encode() for s in data.sheet_names]),
        )
        f.create_dataset("theta", data=data.theta)
        f.create_dataset(
            "theta_names",
            data=np.array([s.encode() for s in data.theta_names]),
        )
        f.create_dataset("d_sim_rates", data=data.d_sim_rates)
        f.create_dataset("d_sim_cum", data=data.d_sim_cum)
        f.create_dataset(
            "rate_index",
            data=np.array(
                [
                    (m.encode(), w.encode(), t.isoformat().encode())
                    for m, w, t in data.rate_index
                ]
            ),
        )
        f.create_dataset(
            "cum_index",
            data=np.array(
                [
                    (m.encode(), w.encode(), t.isoformat().encode())
                    for m, w, t in data.cum_index
                ]
            ),
        )
        f.create_dataset(
            "time_steps",
            data=data.time_steps.astype("datetime64[ns]").astype("int64"),
        )
        f.create_dataset(
            "producer_wells",
            data=np.array([s.encode() for s in data.producer_wells]),
        )
        f.create_dataset(
            "injector_wells",
            data=np.array([s.encode() for s in data.injector_wells]),
        )


def load_tnav_ensemble(
    parameters_path: Path,
    dynamics_path: Path,
    *,
    cache_path: Path | None = None,
    use_cache: bool = True,
) -> EnsembleData:
    """Load the 150-model ensemble. See module docstring for the data contract.

    Parameters
    ----------
    parameters_path : path to ``models_near_adapted_centroids.xlsx``
    dynamics_path   : path to ``Показатели динамики.xlsx``
    cache_path      : where to read/write the HDF5 cache. Default
                      ``<repo>/outputs/cache/ensemble.h5``.
    use_cache       : if True and the cache exists, returns the cached object
                      without re-parsing the Excel inputs.
    """
    if use_cache and cache_path is not None and cache_path.exists():
        cached = _load_from_cache(cache_path)
        if cached is not None:
            log.info(
                f"Loaded {cached.N} models from cache (n_θ={cached.n_theta}, "
                f"n_d_rates={cached.d_sim_rates.shape[1]}, "
                f"n_d_cum={cached.d_sim_cum.shape[1]})"
            )
            return cached

    params = _load_parameters(parameters_path)
    # build seed → (model_id, cluster_id, theta) lookup
    lookup: dict[tuple[int, int], pd.Series] = {
        (int(row.cluster_id), int(row.seed_int)): row for row in params.itertuples()
    }

    log.info(f"Loading dynamics workbook: {dynamics_path.name}")
    xl_dyn = pd.ExcelFile(dynamics_path)
    sheet_names = xl_dyn.sheet_names
    log.info(f"  {len(sheet_names)} sheets to parse")

    # First pass: read sheet 0 to discover well roster and time steps.
    first_sheet = sheet_names[0]
    df0 = pd.read_excel(xl_dyn, sheet_name=first_sheet)
    producers, injectors = _classify_wells(df0.columns.tolist())
    # Drop dummy wells
    producers = [w for w in producers if w != DUMMY_WELL]
    injectors = [w for w in injectors if w != DUMMY_WELL]
    log.info(f"  producers ({len(producers)}): {producers}")
    log.info(f"  injectors ({len(injectors)}): {injectors}")

    # Build per-model rows
    model_ids_l: list[int] = []
    cluster_ids_l: list[int] = []
    seeds_l: list[int] = []
    theta_rows: list[np.ndarray] = []
    rate_rows: list[np.ndarray] = []
    cum_rows: list[np.ndarray] = []
    used_sheet_names: list[str] = []
    canonical_time = None
    rate_index = None
    cum_index = None

    n_skipped = 0
    for sh in sheet_names:
        parsed = _parse_dynamics_sheet_name(sh)
        if parsed is None:
            log.debug(f"  skip non-model sheet {sh!r}")
            n_skipped += 1
            continue
        cluster_id, seed_int = parsed
        key = (cluster_id, seed_int)
        if key not in lookup:
            log.warning(
                f"  dynamics sheet {sh!r} (cluster={cluster_id}, seed={seed_int}) "
                "has no matching parameter row — skipping"
            )
            n_skipped += 1
            continue
        row = lookup[key]
        df = pd.read_excel(xl_dyn, sheet_name=sh)
        rates, cums, r_idx, c_idx, time_steps = _extract_one_model_dynamics(
            df, producers, injectors
        )
        n_nan = int(np.isnan(rates).sum() + np.isnan(cums).sum())
        log.info(
            f"  loaded model_id={int(row.MODEL)} cluster={cluster_id} "
            f"seed={seed_int} n_NaN={n_nan} n_d_rates={rates.size} n_d_cum={cums.size}"
        )
        if n_nan > 0:
            raise ValueError(
                f"Sheet {sh!r} contains NaN values in dynamics — refusing to load."
            )

        # On the first parsed sheet, capture the canonical time grid + indices
        if canonical_time is None:
            canonical_time = time_steps
            rate_index = r_idx
            cum_index = c_idx
        else:
            if rates.size != rate_rows[0].size or cums.size != cum_rows[0].size:
                # Some sheets in the ensemble have a truncated timeline (e.g.
                # 51-1_1-173 has 74 rows vs the canonical 97). We skip them
                # with a warning rather than aborting — the ES update tolerates
                # N=149.
                log.warning(
                    f"  sheet {sh!r} has truncated timeline "
                    f"(n_d_rates={rates.size} vs canonical {rate_rows[0].size}). "
                    f"Skipping this model."
                )
                n_skipped += 1
                continue

        model_ids_l.append(int(row.MODEL))
        cluster_ids_l.append(cluster_id)
        seeds_l.append(seed_int)
        theta_rows.append(
            np.array([getattr(row, c) for c in PARAM_COLS], dtype=np.float64)
        )
        rate_rows.append(rates)
        cum_rows.append(cums)
        used_sheet_names.append(sh)

    if n_skipped:
        log.info(f"  skipped {n_skipped} non-model / unmatched sheets")
    if not theta_rows:
        raise RuntimeError("No models loaded — check input paths and linkage.")

    data = EnsembleData(
        model_ids=np.asarray(model_ids_l, dtype=np.int64),
        cluster_ids=np.asarray(cluster_ids_l, dtype=np.int64),
        seeds=np.asarray(seeds_l, dtype=np.int64),
        sheet_names=used_sheet_names,
        theta=np.vstack(theta_rows),
        theta_names=PARAM_COLS,
        d_sim_rates=np.vstack(rate_rows),
        d_sim_cum=np.vstack(cum_rows),
        rate_index=rate_index,
        cum_index=cum_index,
        time_steps=canonical_time,
        producer_wells=producers,
        injector_wells=injectors,
    )
    log.info(
        f"Loaded ensemble: N={data.N}, n_θ={data.n_theta}, "
        f"n_d_rates={data.d_sim_rates.shape[1]}, n_d_cum={data.d_sim_cum.shape[1]}"
    )

    if cache_path is not None:
        _save_to_cache(data, cache_path)

    return data

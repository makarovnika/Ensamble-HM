"""Forecast ensemble loader — extends Phase 0 with `decoded_results.xlsx`.

123 of the 150 models were re-simulated through 2024-10. The remaining 27
(26 in cluster 0 + the truncated-timeline 51-1_1-173) are absent from the
forecast workbook for physical reasons documented in
`claude-progress.md` ("pressure depletion failure").

The loader returns a `ForecastData` object indexed by model_id, with
year-end cumulative production per producer over the forecast window
(2019-01 → 2024-10) plus the timestamp grid for finer-grained diagnostics.

Note on historical-portion mismatch
-----------------------------------
Cross-checked in session 005: the first 97 rows of `decoded_results.xlsx`
differ numerically from `Показатели динамики.xlsx` for the same model
(median water-rate diff ≈ 390 sm³/d). The forecast workbook is therefore
treated as a **fresh simulation**, not a continuation. For Phase 1 we keep
using the original `Показатели динамики.xlsx` (since adaptation was made
against that). For Phase 3 we use `decoded_results.xlsx` directly.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

CUM_FORECAST_METRICS = ("Накопл. нефть", "Накопл. вода", "Накопл. газ")
RATE_FORECAST_METRICS = ("Дебит нефти", "Дебит воды", "Дебит газа")
DUMMY_WELL = "B"

# decoded_results.xlsx sheet name pattern: "<cluster>_<X>-<seed>"
SHEET_NAME_RE = re.compile(r"^(\d)_\d+-(\d+)$")


@dataclass
class ForecastData:
    model_ids: np.ndarray            # (M,)
    cluster_ids: np.ndarray          # (M,)
    seeds: np.ndarray                # (M,)
    sheet_names: list[str]
    # Forecast cumulative at the end of each forecast calendar year
    # (n_metrics × n_producers × n_years), flattened.
    d_forecast_cum: np.ndarray       # (M, n_d_cum_forecast)
    cum_index: list[tuple[str, str, datetime]]
    # Forecast monthly rates (n_metrics × n_producers × n_months), flattened.
    d_forecast_rates: np.ndarray     # (M, n_d_rates_forecast)
    rate_index: list[tuple[str, str, datetime]]
    forecast_time_steps: np.ndarray  # (n_forecast_months,)
    producer_wells: list[str]
    history_cutoff: datetime         # last historical date (start of forecast)
    cumulative_anomaly: bool = False  # whether d_forecast_cum has at-cutoff subtracted


def _parse_sheet_name(name: str) -> tuple[int, int] | None:
    m = SHEET_NAME_RE.match(name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _find_metric_column(cols: list[str], metric: str, well: str) -> str | None:
    target = f"{metric} ({well})"
    return target if target in cols else None


def _year_end_indices(times: pd.Series) -> dict[int, int]:
    out: dict[int, int] = {}
    for i, t in enumerate(times):
        out[int(pd.Timestamp(t).year)] = i
    return out


def _save_to_cache(data: ForecastData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as f:
        f.create_dataset("model_ids", data=data.model_ids)
        f.create_dataset("cluster_ids", data=data.cluster_ids)
        f.create_dataset("seeds", data=data.seeds)
        f.create_dataset(
            "sheet_names", data=np.array([s.encode() for s in data.sheet_names])
        )
        f.create_dataset("d_forecast_cum", data=data.d_forecast_cum)
        f.create_dataset("d_forecast_rates", data=data.d_forecast_rates)
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
            "rate_index",
            data=np.array(
                [
                    (m.encode(), w.encode(), t.isoformat().encode())
                    for m, w, t in data.rate_index
                ]
            ),
        )
        f.create_dataset(
            "forecast_time_steps",
            data=data.forecast_time_steps.astype("datetime64[ns]").astype("int64"),
        )
        f.create_dataset(
            "producer_wells",
            data=np.array([s.encode() for s in data.producer_wells]),
        )
        f.attrs["history_cutoff"] = data.history_cutoff.isoformat()
        f.attrs["cumulative_anomaly"] = bool(data.cumulative_anomaly)


def _load_from_cache(path: Path) -> ForecastData | None:
    if not path.exists():
        return None
    log.info(f"Loading cached forecast from {path}")
    with h5py.File(path, "r") as f:
        return ForecastData(
            model_ids=f["model_ids"][:],
            cluster_ids=f["cluster_ids"][:],
            seeds=f["seeds"][:],
            sheet_names=[s.decode() for s in f["sheet_names"][:]],
            d_forecast_cum=f["d_forecast_cum"][:],
            d_forecast_rates=f["d_forecast_rates"][:],
            cum_index=[
                (m.decode(), w.decode(), datetime.fromisoformat(t.decode()))
                for m, w, t in f["cum_index"][:]
            ],
            rate_index=[
                (m.decode(), w.decode(), datetime.fromisoformat(t.decode()))
                for m, w, t in f["rate_index"][:]
            ],
            forecast_time_steps=f["forecast_time_steps"][:].astype("datetime64[ns]"),
            producer_wells=[s.decode() for s in f["producer_wells"][:]],
            history_cutoff=datetime.fromisoformat(f.attrs["history_cutoff"]),
            cumulative_anomaly=bool(f.attrs.get("cumulative_anomaly", False)),
        )


def load_tnav_forecast(
    decoded_path: Path,
    *,
    producer_wells: list[str],
    cluster_seed_to_model_id: dict[tuple[int, int], int],
    history_cutoff: datetime = datetime(2019, 1, 1),
    cumulative_anomaly: bool = True,
    cache_path: Path | None = None,
    use_cache: bool = True,
) -> ForecastData:
    """Load `decoded_results.xlsx` and slice out the forecast period.

    Parameters
    ----------
    decoded_path             : path to `decoded_results.xlsx`.
    producer_wells           : the well roster from the Phase 0 ensemble (we
                               keep the same well order for downstream alignment).
    cluster_seed_to_model_id : mapping ``{(cluster_id, seed_int): model_id}``
                               built from the parameter manifest. Same seed
                               can appear under multiple clusters because the
                               manifest selects "models near each cluster
                               centroid" independently — the same physical
                               model can be in cluster 0's top-50 and cluster
                               1's top-50 with different θ_adapt for each.
    history_cutoff           : first day **inside** the forecast window. Any
                               row with Дата >= cutoff is treated as forecast.
    cache_path               : optional HDF5 cache path. Default
                               ``<repo>/outputs/cache/forecast.h5``.
    use_cache                : reuse cache if present.
    """
    if use_cache and cache_path is not None and cache_path.exists():
        cached = _load_from_cache(cache_path)
        if cached is not None:
            log.info(
                f"Loaded forecast cache: M={cached.model_ids.size}, "
                f"n_d_cum={cached.d_forecast_cum.shape[1]}, "
                f"n_d_rates={cached.d_forecast_rates.shape[1]}"
            )
            return cached

    log.info(f"Loading forecast workbook: {decoded_path.name}")
    xl = pd.ExcelFile(decoded_path)
    sheets = xl.sheet_names
    log.info(f"  {len(sheets)} sheets to parse")

    rows = []
    canonical_time = None
    cum_index_canon = None
    rate_index_canon = None

    for sh in sheets:
        parsed = _parse_sheet_name(sh)
        if parsed is None:
            log.warning(f"  skip non-model sheet {sh!r}")
            continue
        cluster_id, seed_int = parsed
        key = (cluster_id, seed_int)
        if key not in cluster_seed_to_model_id:
            log.warning(
                f"  sheet {sh!r} (cluster={cluster_id}, seed={seed_int}) "
                "has no matching (cluster, seed) entry in manifest — skipping"
            )
            continue
        model_id = cluster_seed_to_model_id[key]

        df = pd.read_excel(xl, sheet_name=sh)
        times = pd.to_datetime(df["Дата"])
        forecast_mask = times >= pd.Timestamp(history_cutoff)
        if not forecast_mask.any():
            log.warning(f"  sheet {sh!r}: no rows past {history_cutoff.date()} — skipping")
            continue
        # Capture the at-cutoff row (last history row before forecast) for the
        # cumulative-anomaly subtraction. If no history rows are present,
        # at_cutoff_row is None and we keep totals as-is.
        history_mask = times < pd.Timestamp(history_cutoff)
        at_cutoff_row: pd.Series | None = None
        if history_mask.any():
            at_cutoff_row = df[history_mask].iloc[-1]
        fdf = df[forecast_mask].reset_index(drop=True)
        ftimes = pd.to_datetime(fdf["Дата"])

        # Extract rates: per metric × producer × forecast month
        rates_vals: list[float] = []
        rate_index_local: list[tuple[str, str, datetime]] = []
        for metric in RATE_FORECAST_METRICS:
            for well in producer_wells:
                col = _find_metric_column(fdf.columns.tolist(), metric, well)
                vals = (
                    pd.to_numeric(fdf[col], errors="coerce").fillna(0.0).to_numpy()
                    if col
                    else np.zeros(len(fdf))
                )
                rates_vals.extend(vals.tolist())
                for t in ftimes:
                    rate_index_local.append(
                        (metric, well, pd.Timestamp(t).to_pydatetime())
                    )

        # Extract cumulative: year-end anchors within forecast window.
        # When cumulative_anomaly=True, subtract the at-cutoff value so the
        # entry represents production added in the forecast period only.
        year_ends = _year_end_indices(ftimes)
        sorted_years = sorted(year_ends.keys())
        cum_vals: list[float] = []
        cum_index_local: list[tuple[str, str, datetime]] = []
        for metric in CUM_FORECAST_METRICS:
            for well in producer_wells:
                col = _find_metric_column(fdf.columns.tolist(), metric, well)
                vals = (
                    pd.to_numeric(fdf[col], errors="coerce").fillna(0.0).to_numpy()
                    if col
                    else np.zeros(len(fdf))
                )
                # Determine the baseline to subtract
                if cumulative_anomaly and at_cutoff_row is not None and col is not None:
                    raw = at_cutoff_row[col]
                    baseline = float(pd.to_numeric(raw, errors="coerce")) if pd.notna(raw) else 0.0
                else:
                    baseline = 0.0
                for y in sorted_years:
                    idx = year_ends[y]
                    cum_vals.append(float(vals[idx]) - baseline)
                    cum_index_local.append(
                        (
                            metric,
                            well,
                            pd.Timestamp(ftimes.iloc[idx]).to_pydatetime(),
                        )
                    )

        # Capture canonical time grid + indexes from first parsed sheet
        if canonical_time is None:
            canonical_time = ftimes.to_numpy()
            cum_index_canon = cum_index_local
            rate_index_canon = rate_index_local
        else:
            if len(rates_vals) != rows[0]["rates"].size or len(cum_vals) != rows[0]["cums"].size:
                log.warning(
                    f"  sheet {sh!r}: forecast dimensions inconsistent "
                    f"(rates={len(rates_vals)} vs canonical "
                    f"{rows[0]['rates'].size}) — skipping"
                )
                continue

        n_nan = int(np.isnan(rates_vals).sum() + np.isnan(cum_vals).sum())
        log.info(
            f"  loaded forecast model_id={model_id} cluster={cluster_id} "
            f"seed={seed_int} n_NaN={n_nan} n_d_rates={len(rates_vals)} "
            f"n_d_cum={len(cum_vals)}"
        )
        rows.append(
            {
                "model_id": model_id,
                "cluster_id": cluster_id,
                "seed": seed_int,
                "sheet": sh,
                "rates": np.asarray(rates_vals, dtype=np.float64),
                "cums": np.asarray(cum_vals, dtype=np.float64),
            }
        )

    if not rows:
        raise RuntimeError("No forecast models loaded.")

    data = ForecastData(
        model_ids=np.asarray([r["model_id"] for r in rows], dtype=np.int64),
        cluster_ids=np.asarray([r["cluster_id"] for r in rows], dtype=np.int64),
        seeds=np.asarray([r["seed"] for r in rows], dtype=np.int64),
        sheet_names=[r["sheet"] for r in rows],
        d_forecast_cum=np.vstack([r["cums"] for r in rows]),
        d_forecast_rates=np.vstack([r["rates"] for r in rows]),
        cum_index=cum_index_canon,
        rate_index=rate_index_canon,
        forecast_time_steps=canonical_time,
        producer_wells=list(producer_wells),
        history_cutoff=history_cutoff,
        cumulative_anomaly=cumulative_anomaly,
    )
    log.info(
        f"Loaded forecast ensemble: M={data.model_ids.size}, "
        f"n_d_cum={data.d_forecast_cum.shape[1]}, "
        f"n_d_rates={data.d_forecast_rates.shape[1]}, "
        f"forecast window: {pd.Timestamp(data.forecast_time_steps[0]).date()} → "
        f"{pd.Timestamp(data.forecast_time_steps[-1]).date()}"
    )
    log.info(
        f"  cluster coverage: "
        + ", ".join(
            f"c{cl}={(data.cluster_ids == cl).sum()}"
            for cl in sorted(set(data.cluster_ids.tolist()))
        )
    )

    if cache_path is not None:
        _save_to_cache(data, cache_path)
    return data

"""Inter-model spread and geological width_ratio (TZ §5.3).

Reuses descriptors and connectivity tables produced by the earlier geolval
features instead of re-streaming cubes, keeping this step in seconds rather
than tens of minutes.

Outputs:

* ``diversity_descriptor_spread.csv`` — per-metric × per-experiment ×
  per-cluster spread quantiles (p10, p50, p90, IQR, std).
* ``diversity_width_ratio.csv`` — for every metric, ``spread(Exp2) /
  spread(Exp1)`` next to the ES width_ratio (1.47 oil / 2.22 water /
  1.47 gas — Notion §7.4) for direct comparison. A value > 1 means the
  new ensemble *broadens* the variability on that geological axis; < 1
  means it tightens.

The aggregate descriptor distribution is sampled at well level (it is
the basis of TZ §5.3's "spread descriptor"), then again at model level
by averaging per-well descriptors within each model — both are kept so
downstream code can pick the granularity that matches its claim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Reference ES width_ratio from Notion §7.4 (setup2 vs setup1; setup3 ≡ setup2
# after the TZ-v3 surgery, so we keep the originally-reported triple as-is).
ES_WIDTH_RATIO = {
    "WOPT_cumulative_oil": 1.47,
    "WWPT_cumulative_water": 2.22,
    "WGPT_cumulative_gas": 1.47,
}


# ──────────────────────────────────────────────────────────────────────────
# Spread quantiles
# ──────────────────────────────────────────────────────────────────────────


def _spread_block(values: np.ndarray) -> dict[str, float]:
    """Return five-number summary + std + IQR for one ensemble slice."""
    if values.size == 0:
        return {k: float("nan") for k in
                ("n", "mean", "std", "p10", "p50", "p90", "iqr", "range")}
    return {
        "n": int(values.size),
        "mean": float(np.nanmean(values)),
        "std": float(np.nanstd(values, ddof=1)) if values.size > 1 else 0.0,
        "p10": float(np.nanpercentile(values, 10)),
        "p50": float(np.nanpercentile(values, 50)),
        "p90": float(np.nanpercentile(values, 90)),
        "iqr": float(np.nanpercentile(values, 75) - np.nanpercentile(values, 25)),
        "range": float(np.nanmax(values) - np.nanmin(values)),
    }


_WELL_METRICS = [
    "net_sand_penetrated",
    "kh_penetrated",
    "frac_channel_cells",
    "mean_ntg_along_well",
]


def descriptor_spread(
    descriptors_df: pd.DataFrame,
    by_cluster: bool = True,
) -> pd.DataFrame:
    """Per-metric spread aggregated within (experiment, cluster) groups.

    Two scopes per group:
      * ``scope = "all_wells"`` — distribution across (model × well) pairs.
      * ``scope = "model_mean"`` — first average across wells per model,
        then aggregate over models. This is the more honest "inter-model"
        spread (TZ §5.3 wording).
    """
    if descriptors_df.empty:
        return pd.DataFrame()
    df = descriptors_df.copy()
    df["cluster"] = df["cluster"].fillna(-1).astype(int)

    rows: list[dict] = []
    grouping = ["experiment", "cluster"] if by_cluster else ["experiment"]
    for keys, sub in df.groupby(grouping):
        if not isinstance(keys, tuple):
            keys = (keys,)
        for metric in _WELL_METRICS:
            if metric not in sub.columns:
                continue
            # scope 1 — all well rows
            row = dict(zip(grouping, [int(k) for k in keys]))
            row["scope"] = "all_wells"
            row["metric"] = metric
            row.update(_spread_block(sub[metric].to_numpy(dtype=float)))
            rows.append(row)
            # scope 2 — model-mean
            row2 = dict(zip(grouping, [int(k) for k in keys]))
            row2["scope"] = "model_mean"
            row2["metric"] = metric
            model_avgs = sub.groupby("seed")[metric].mean().to_numpy(dtype=float)
            row2.update(_spread_block(model_avgs))
            rows.append(row2)
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# Connectivity spread (per-model metrics already aggregated)
# ──────────────────────────────────────────────────────────────────────────


_CONN_METRICS = [
    "n_bodies_26",
    "frac_sand_in_largest_26",
    "frac_sand_in_top10_26",
    "top1_anisotropy",
    "top1_orientation_deg",
    "mean_inj_connections_per_producer",
    "max_inj_connections_per_producer",
    "n_producers_connected_to_any_inj",
]


def connectivity_spread(
    connectivity_df: pd.DataFrame,
    by_cluster: bool = True,
) -> pd.DataFrame:
    """Per-experiment (and optionally per-cluster) spread of connectivity metrics."""
    if connectivity_df.empty:
        return pd.DataFrame()
    df = connectivity_df.copy()
    df["cluster"] = df["cluster"].fillna(-1).astype(int)
    rows: list[dict] = []
    grouping = ["experiment", "cluster"] if by_cluster else ["experiment"]
    for keys, sub in df.groupby(grouping):
        if not isinstance(keys, tuple):
            keys = (keys,)
        for metric in _CONN_METRICS:
            if metric not in sub.columns:
                continue
            row = dict(zip(grouping, [int(k) for k in keys]))
            row["metric"] = metric
            row.update(_spread_block(sub[metric].to_numpy(dtype=float)))
            rows.append(row)
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# Width-ratio table (geological ↔ ES)
# ──────────────────────────────────────────────────────────────────────────


def geological_width_ratio(
    spread_df: pd.DataFrame,
    a_exp: int = 1,
    b_exp: int = 2,
    spread_column: str = "std",
    scope: str | None = "model_mean",
) -> pd.DataFrame:
    """Compute ``spread(b) / spread(a)`` for each metric, aggregated over clusters.

    By default uses the model-mean scope (TZ §5.3 "inter-model" definition)
    and ``std`` as the spread measure.
    """
    if spread_df.empty:
        return pd.DataFrame()
    df = spread_df.copy()
    if "scope" in df.columns and scope is not None:
        df = df[df["scope"] == scope]
    # Aggregate clusters away — sum the variances and re-sqrt-root for std,
    # or just take the cluster -1 ("all") rows if present. The simplest honest
    # path: re-aggregate across clusters by mean (each cluster is roughly equal
    # weight in the design — 50 models per cluster). The result is the
    # "average within-cluster spread".
    grouped = (
        df.groupby(["experiment", "metric"])[spread_column]
        .mean()
        .unstack(level=0)
    )
    if a_exp not in grouped.columns or b_exp not in grouped.columns:
        return pd.DataFrame()
    out = pd.DataFrame(index=grouped.index)
    out[f"spread_a_exp{a_exp}"] = grouped[a_exp]
    out[f"spread_b_exp{b_exp}"] = grouped[b_exp]
    out["width_ratio_geo"] = grouped[b_exp] / grouped[a_exp].replace(0, np.nan)
    out["es_width_ratio_ref"] = [ES_WIDTH_RATIO.get(m, np.nan) for m in out.index]
    out["interpretation"] = np.where(
        out["width_ratio_geo"].isna(), "—",
        np.where(out["width_ratio_geo"] > 1.0,
                  "Exp2 broadens variability",
                  "Exp2 tightens variability"),
    )
    return out.reset_index()


# ──────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class DiversityArtefacts:
    descriptor_spread: pd.DataFrame
    connectivity_spread: pd.DataFrame
    width_ratio: pd.DataFrame


def build_diversity(
    descriptors_paths: dict[int, Path] | None = None,
    connectivity_path: Path | None = None,
    root: Path | None = None,
) -> DiversityArtefacts:
    """Top-level builder.

    Defaults match the canonical output layout:
      ``outputs/geology_validation/descriptors_exp{1,2}.csv``
      ``outputs/geology_validation/connectivity_summary.csv``
    """
    root = root or Path(".")
    if descriptors_paths is None:
        descriptors_paths = {
            1: root / "outputs/geology_validation/descriptors_exp1.csv",
            2: root / "outputs/geology_validation/descriptors_exp2.csv",
        }
    if connectivity_path is None:
        connectivity_path = root / "outputs/geology_validation/connectivity_summary.csv"
    desc_frames = []
    for exp_id, p in descriptors_paths.items():
        if not p.exists():
            log.warning(f"{p}: missing descriptor CSV — skipping Exp{exp_id}")
            continue
        d = pd.read_csv(p)
        if "experiment" not in d.columns:
            d["experiment"] = exp_id
        desc_frames.append(d)
    desc = pd.concat(desc_frames, ignore_index=True) if desc_frames else pd.DataFrame()
    conn = pd.read_csv(connectivity_path) if connectivity_path.exists() else pd.DataFrame()
    dspread = descriptor_spread(desc, by_cluster=True)
    cspread = connectivity_spread(conn, by_cluster=True)
    full_spread = pd.concat(
        [dspread.assign(source="descriptor"),
         cspread.assign(source="connectivity", scope="model_summary")],
        ignore_index=True,
    )
    wr = geological_width_ratio(full_spread, scope=None)
    return DiversityArtefacts(
        descriptor_spread=dspread,
        connectivity_spread=cspread,
        width_ratio=wr,
    )

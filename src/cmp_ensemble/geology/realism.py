"""Axis 2 — geological realism (TZ §5.2, geolval-004).

Three artefacts:

  ``concept_conformance.csv``  per (cluster, parameter): fraction of models
                              whose realised channel parameter falls in the
                              Notion §5 cluster box. Computed from the θ
                              values used to drive the geomodelling, which —
                              under the contract that the geomodeller honours
                              its inputs — equal the realised channel-geometry
                              targets. A genuinely independent geometry-side
                              proxy lives in ``connectivity_summary.csv``
                              (``top1_anisotropy``, ``top1_orientation_deg``)
                              and is summarised in ``realism_metrics.csv``.

  ``facies_proportions.csv``  per (experiment, model): fraction of cells
                              piercing channels along well trajectories
                              (mean across wells) — the simplest per-model
                              facies summary the descriptors already carry.

  ``realism_metrics.csv``     per (experiment, cluster): overall
                              concept-conformance pass rate (all three
                              parameters in their boxes), top1 anisotropy
                              and orientation distributions.

Both experiments share the same θ ensemble (TZ §0), so concept-conformance
on the θ side is identical between experiments by construction. The
*geometry* side (top1_anisotropy, top1_orientation_deg) is where Exp1/Exp2
can differ — that's the realism_metrics.csv comparison.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Notion §5 cluster boxes (verbatim from TZ §5.2)
CLUSTER_BOXES = {
    "THICK":   {0: (5.6, 10.1),   1: (10.9, 17.0), 2: (13.9, 18.2)},
    "MAJ_R":   {0: (3400, 4584),  1: (2849, 4086), 2: (2198, 2724)},
    "AZIMUTH": {0: (65.0, 105.0), 1: (65.0, 105.0), 2: (65.0, 105.0)},
}


# ──────────────────────────────────────────────────────────────────────────
# θ-side concept conformance
# ──────────────────────────────────────────────────────────────────────────


def _load_theta_per_cluster(centroid_excel: Path) -> pd.DataFrame:
    """Return one row per model: ``[cluster, MODEL, SEED_rounded, THICK, MAJ_R, AZIMUTH]``."""
    frames: list[pd.DataFrame] = []
    xl = pd.ExcelFile(centroid_excel)
    for i, sh in enumerate(xl.sheet_names):
        df = pd.read_excel(centroid_excel, sheet_name=sh, header=3)
        df.columns = [c if isinstance(c, str) else f"col{i}"
                      for i, c in enumerate(df.columns)]
        if not {"MODEL", "SEED", "THICK", "MAJ_R", "AZIMUTH"}.issubset(df.columns):
            continue
        sub = df[["MODEL", "SEED", "THICK", "MAJ_R", "AZIMUTH"]].dropna().copy()
        sub["MODEL"] = sub["MODEL"].astype(int)
        sub["SEED_rounded"] = sub["SEED"].round().astype(int)
        sub["cluster"] = i
        frames.append(sub)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def compute_concept_conformance(
    theta_df: pd.DataFrame,
    cluster_boxes: dict[str, dict[int, tuple[float, float]]] | None = None,
) -> pd.DataFrame:
    """For each (cluster, parameter), report the fraction of models in box.

    Each model is checked against the box for **its own** cluster. The
    output also includes ``all_three_in_box`` per cluster — the share of
    models that fall in every one of THICK/MAJ_R/AZIMUTH boxes simultaneously.
    """
    if theta_df.empty:
        return pd.DataFrame()
    boxes = cluster_boxes or CLUSTER_BOXES
    rows: list[dict] = []
    for cl in sorted(theta_df["cluster"].unique()):
        sub = theta_df[theta_df["cluster"] == cl]
        n = len(sub)
        in_box_flags = {}
        for param, per_cl in boxes.items():
            if cl not in per_cl or param not in sub.columns:
                continue
            lo, hi = per_cl[cl]
            in_box = (sub[param] >= lo) & (sub[param] <= hi)
            in_box_flags[param] = in_box
            rows.append({
                "cluster": int(cl), "parameter": param,
                "box_low": float(lo), "box_high": float(hi),
                "n_models": int(n),
                "n_in_box": int(in_box.sum()),
                "frac_in_box": float(in_box.mean()),
                "median_observed": float(sub[param].median()),
                "min_observed": float(sub[param].min()),
                "max_observed": float(sub[param].max()),
            })
        if in_box_flags:
            all_three = np.logical_and.reduce(list(in_box_flags.values()))
            rows.append({
                "cluster": int(cl), "parameter": "all_three",
                "box_low": np.nan, "box_high": np.nan,
                "n_models": int(n),
                "n_in_box": int(all_three.sum()),
                "frac_in_box": float(all_three.mean()),
                "median_observed": np.nan,
                "min_observed": np.nan,
                "max_observed": np.nan,
            })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# Facies proportions (per-model)
# ──────────────────────────────────────────────────────────────────────────


def compute_facies_proportions(
    descriptors_df: pd.DataFrame,
) -> pd.DataFrame:
    """Mean per-well frac_channel + frac_non_channel per model, per experiment."""
    if descriptors_df.empty:
        return pd.DataFrame()
    g = (descriptors_df
         .groupby(["experiment", "seed", "cluster"])
         .agg(mean_frac_channel=("frac_channel_cells", "mean"),
              mean_ntg=("mean_ntg_along_well", "mean"),
              n_wells=("well", "count"))
         .reset_index())
    g["mean_frac_non_channel"] = 1.0 - g["mean_frac_channel"]
    return g


# ──────────────────────────────────────────────────────────────────────────
# Geometry-side realism metrics (axes that differ between Exp1 and Exp2)
# ──────────────────────────────────────────────────────────────────────────


def compute_realism_metrics(
    connectivity_df: pd.DataFrame,
) -> pd.DataFrame:
    """Per (experiment, cluster): median / IQR of geometry-side realism proxies."""
    if connectivity_df.empty:
        return pd.DataFrame()
    df = connectivity_df.copy()
    df["cluster"] = df["cluster"].fillna(-1).astype(int)
    rows: list[dict] = []
    for (exp, cl), sub in df.groupby(["experiment", "cluster"]):
        row = {
            "experiment": int(exp), "cluster": int(cl),
            "n_models": len(sub),
        }
        for col in ("top1_anisotropy", "top1_orientation_deg",
                    "frac_sand_in_largest_26",
                    "mean_inj_connections_per_producer"):
            if col in sub.columns:
                vals = sub[col].dropna()
                row[f"{col}_median"] = float(vals.median()) if len(vals) else np.nan
                row[f"{col}_iqr"] = float(
                    vals.quantile(0.75) - vals.quantile(0.25)
                ) if len(vals) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class RealismArtefacts:
    concept_conformance: pd.DataFrame
    facies_proportions: pd.DataFrame
    realism_metrics: pd.DataFrame


def build_realism(root: Path) -> RealismArtefacts:
    centroid_excel = root / "models_near_adapted_centroids.xlsx"
    desc_paths = [
        root / "outputs/geology_validation/descriptors_exp1.csv",
        root / "outputs/geology_validation/descriptors_exp2.csv",
    ]
    conn_path = root / "outputs/geology_validation/connectivity_summary.csv"

    theta_df = _load_theta_per_cluster(centroid_excel)
    conformance = compute_concept_conformance(theta_df)

    desc_frames = []
    for p in desc_paths:
        if p.exists():
            d = pd.read_csv(p)
            desc_frames.append(d)
    desc = pd.concat(desc_frames, ignore_index=True) if desc_frames else pd.DataFrame()
    fp = compute_facies_proportions(desc)

    conn = pd.read_csv(conn_path) if conn_path.exists() else pd.DataFrame()
    rm = compute_realism_metrics(conn)

    return RealismArtefacts(
        concept_conformance=conformance,
        facies_proportions=fp,
        realism_metrics=rm,
    )

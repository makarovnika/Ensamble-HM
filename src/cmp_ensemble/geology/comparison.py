"""Final summary_comparison.csv for the article (TZ §3 deliverable 6).

Reads every artefact produced by geolval-{000..006} and produces one
row per (axis, metric) with:

  axis            (0..4)
  metric          e.g. "compliance_8_6_4_pass_rate_cluster2"
  scope           "all" or "cluster_<n>"
  value_old       the Exp1/setup1 value
  value_new       the Exp2/setup2 value
  direction       ">"   (higher is better)
                  "<"   (lower is better)
                  "~"   (no a-priori direction; report only)
  status          "BETTER" / "WORSE" / "NEUTRAL" / "PENDING_USER_INPUT"
  delta           value_new - value_old
  ratio           value_new / value_old (or NaN if old == 0)
  evidence        path of the artefact the row was sourced from
  notes           one-line interpretation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _classify_status(value_old: float, value_new: float, direction: str) -> str:
    if direction == "~":
        return "NEUTRAL"
    if pd.isna(value_old) or pd.isna(value_new):
        return "NEUTRAL"
    delta = value_new - value_old
    eps = max(1e-9, 1e-3 * max(abs(value_old), abs(value_new)))
    if abs(delta) < eps:
        return "NEUTRAL"
    if direction == ">":
        return "BETTER" if delta > 0 else "WORSE"
    return "BETTER" if delta < 0 else "WORSE"


def _row(axis: int, metric: str, scope: str,
         value_old: float, value_new: float,
         direction: str, evidence: str, notes: str = "") -> dict:
    return {
        "axis": axis, "metric": metric, "scope": scope,
        "value_old": float(value_old) if value_old is not None else np.nan,
        "value_new": float(value_new) if value_new is not None else np.nan,
        "direction": direction,
        "status": _classify_status(
            float(value_old) if value_old is not None else np.nan,
            float(value_new) if value_new is not None else np.nan,
            direction,
        ),
        "delta": (float(value_new) - float(value_old))
            if (value_old is not None and value_new is not None) else np.nan,
        "ratio": (float(value_new) / float(value_old))
            if (value_old not in (None, 0.0) and value_new is not None) else np.nan,
        "evidence": evidence,
        "notes": notes,
    }


# ──────────────────────────────────────────────────────────────────────────
# Per-axis builders
# ──────────────────────────────────────────────────────────────────────────


def build_axis0(exp_diff_path: Path) -> list[dict]:
    """Axis 0 = topological rebuild between experiments (TZ §11 Q5)."""
    if not exp_diff_path.exists():
        return []
    df = pd.read_csv(exp_diff_path)
    rows = []
    if "frac_netflag_changed" in df.columns:
        rows.append(_row(
            0, "frac_netflag_changed", "all_matched_seeds",
            value_old=0.0,
            value_new=float(df["frac_netflag_changed"].mean()),
            direction="~",
            evidence=str(exp_diff_path),
            notes="Topological churn between experiments (mean over matched SEEDs)."
        ))
    for kw in ("PORO", "PERMX", "NTG"):
        col = f"delta_mean_{kw}"
        if col in df.columns:
            rows.append(_row(
                0, f"abs_mean_delta_{kw}", "all_matched_seeds",
                value_old=0.0,
                value_new=float(df[col].abs().mean()),
                direction="~",
                evidence=str(exp_diff_path),
                notes=f"Mean |Δ mean({kw})| over matched seeds."
            ))
    return rows


def build_axis2(connectivity_path: Path) -> list[dict]:
    """Axis 2 = geological realism via connectivity (per-experiment medians)."""
    if not connectivity_path.exists():
        return []
    df = pd.read_csv(connectivity_path)
    e1 = df[df["experiment"] == 1].drop_duplicates("seed")
    e2 = df[df["experiment"] == 2].drop_duplicates("seed")
    rows = []
    # Median frac_largest_26 (higher = more connected reservoir = more realistic)
    rows.append(_row(
        2, "median_frac_sand_in_largest_26", "all",
        value_old=float(e1["frac_sand_in_largest_26"].median()),
        value_new=float(e2["frac_sand_in_largest_26"].median()),
        direction=">",
        evidence=str(connectivity_path),
        notes="Median fraction of sand cells in the dominant geobody."
    ))
    # Worst-case frac_largest_26 (higher = even worst realisation is connected)
    rows.append(_row(
        2, "min_frac_sand_in_largest_26", "all",
        value_old=float(e1["frac_sand_in_largest_26"].min()),
        value_new=float(e2["frac_sand_in_largest_26"].min()),
        direction=">",
        evidence=str(connectivity_path),
        notes="Worst-case fraction of sand in dominant geobody — flags pathological realisations."
    ))
    # Disconnected-from-INJ model count (lower = better)
    rows.append(_row(
        2, "n_models_with_mean_inj_conn_lt_1", "all",
        value_old=float((e1["mean_inj_connections_per_producer"] < 1).sum()),
        value_new=float((e2["mean_inj_connections_per_producer"] < 1).sum()),
        direction="<",
        evidence=str(connectivity_path),
        notes="Number of pathological models where producers are essentially disconnected from injectors."
    ))
    # Median n_bodies_26 (lower = more coherent, but should be ~ flat)
    rows.append(_row(
        2, "median_n_bodies_26", "all",
        value_old=float(e1["n_bodies_26"].median()),
        value_new=float(e2["n_bodies_26"].median()),
        direction="<",
        evidence=str(connectivity_path),
        notes="Median count of sand geobodies; small = single coherent reservoir."
    ))
    return rows


def build_axis3(width_ratio_path: Path) -> list[dict]:
    """Axis 3 = inter-model diversity (geological width_ratio)."""
    if not width_ratio_path.exists():
        return []
    df = pd.read_csv(width_ratio_path)
    rows = []
    for _, r in df.iterrows():
        rows.append(_row(
            3, f"width_ratio_{r['metric']}", "all",
            value_old=float(r["spread_a_exp1"]),
            value_new=float(r["spread_b_exp2"]),
            direction="~",
            evidence=str(width_ratio_path),
            notes=f"Exp2/Exp1 spread ratio = {r['width_ratio_geo']:.3f} ({r['interpretation']})."
        ))
    return rows


def build_axis4(compliance_path: Path) -> list[dict]:
    """Axis 4 = history-mismatch + regulation 8.6.4 compliance."""
    if not compliance_path.exists():
        return []
    df = pd.read_csv(compliance_path)
    rows = []
    s1_all = df[(df["setup"] == "setup1_naive") & (df["cluster"] == -1)]
    s2_all = df[(df["setup"] == "setup2_localized") & (df["cluster"] == -1)]
    if not s1_all.empty and not s2_all.empty:
        rows.append(_row(
            4, "regulation_8_6_4_pass_rate", "all",
            value_old=float(s1_all["pass_all_three_rate"].iloc[0]),
            value_new=float(s2_all["pass_all_three_rate"].iloc[0]),
            direction=">",
            evidence=str(compliance_path),
            notes="Fraction of models passing all three 8.6.4 criteria."
        ))
    for cl in (0, 1, 2):
        s1c = df[(df["setup"] == "setup1_naive") & (df["cluster"] == cl)]
        s2c = df[(df["setup"] == "setup2_localized") & (df["cluster"] == cl)]
        if not s1c.empty and not s2c.empty:
            rows.append(_row(
                4, "regulation_8_6_4_pass_rate", f"cluster_{cl}",
                value_old=float(s1c["pass_all_three_rate"].iloc[0]),
                value_new=float(s2c["pass_all_three_rate"].iloc[0]),
                direction=">",
                evidence=str(compliance_path),
                notes=f"Cluster {cl} 8.6.4 pass-rate; TZ §5.4 expected ~30->92% for cluster 2."
            ))
    return rows


def build_axis4_misfit(misfit_path: Path) -> list[dict]:
    """Axis 4 secondary — per-cluster mean total mismatch."""
    if not misfit_path.exists():
        return []
    df = pd.read_csv(misfit_path)
    rows = []
    for cl in (0, 1, 2):
        s1 = df[(df["setup"] == "setup1_naive") & (df["cluster"] == cl)]
        s2 = df[(df["setup"] == "setup2_localized") & (df["cluster"] == cl)]
        if not s1.empty and not s2.empty:
            rows.append(_row(
                4, "mean_total_mismatch_pct", f"cluster_{cl}",
                value_old=float(s1["total_mismatch_pct"].mean()),
                value_new=float(s2["total_mismatch_pct"].mean()),
                direction="<",
                evidence=str(misfit_path),
                notes=f"Mean total mismatch % per cluster {cl} (lower=better)."
            ))
    return rows


def build_axis4_crossaxis(corr_path: Path) -> list[dict]:
    """Axis 4 cross-axis = mismatch ↔ realism correlation."""
    import json
    if not corr_path.exists():
        return []
    corr = json.loads(corr_path.read_text(encoding="utf-8"))
    if not corr:
        return []
    s1 = corr.get("setup1_naive")
    s2 = corr.get("setup2_localized")
    if s1 is None or s2 is None:
        return []
    return [_row(
        4, "abs_pearson_r_mismatch_vs_realism", "all",
        value_old=abs(float(s1)), value_new=abs(float(s2)),
        direction="~",
        evidence=str(corr_path),
        notes=(
            "|Pearson r| close to zero in both setups → mismatch reduction is "
            "NOT bought by degrading topology realism."
        ),
    )]


# ──────────────────────────────────────────────────────────────────────────
# Pending-input rows (axes 1, 2 realism via facies, etc.)
# ──────────────────────────────────────────────────────────────────────────


def build_pending() -> list[dict]:
    """Rows for analyses blocked on TZ §11 open questions (after Q1 default)."""
    # geolval-003 (R²-uplift) closed using the default cutoff rule from
    # configs/geology.yaml — its axis-1 rows are emitted by build_axis1().
    # geolval-004 concept-conformance still benefits from an explicit facies
    # dictionary; if absent, build_axis2_realism uses the synthetic-θ-based
    # proxy boxes.
    return []


def build_axis1(r2_uplift_path: Path) -> list[dict]:
    """Axis 1 — geology→production link via R²-uplift on per-well responses."""
    if not r2_uplift_path.exists():
        return []
    df = pd.read_csv(r2_uplift_path)
    if df.empty:
        return []
    rows: list[dict] = []
    # Keep only the all-scope, cum_oil_* responses (drop the watercut-locked twin)
    sub = df[df["scope"] == "all"]
    sub = sub[sub["response"].str.startswith("cum_oil_")]
    for _, r in sub.iterrows():
        well = r["response"].replace("cum_oil_", "")
        rows.append(_row(
            1, f"r2_uplift_{well}", "all",
            value_old=float(r["R2_theta"]),
            value_new=float(r["R2_theta_geo"]),
            direction=">",
            evidence=str(r2_uplift_path),
            notes=(f"+{(r['R2_theta_geo']-r['R2_theta'])*100:.1f} pp uplift, "
                   f"CI [{r['ci_low']:.3f}, {r['ci_high']:.3f}], n={int(r['n'])}.")
        ))
    return rows


def build_axis1_correlations(corr_path: Path) -> list[dict]:
    """Axis 1 secondary — flag descriptor↔production correlations that clear 3/√N."""
    if not corr_path.exists():
        return []
    df = pd.read_csv(corr_path)
    sig = df[df["passes_3_over_sqrt_N"] == True]
    rows: list[dict] = []
    for _, r in sig.iterrows():
        rows.append({
            "axis": 1, "metric": f"corr_{r['descriptor']}_{r['response']}",
            "scope": "all",
            "value_old": 0.0,
            "value_new": float(r["pearson_r"]),
            "direction": "~",
            "status": "SIGNIFICANT",
            "delta": float(r["pearson_r"]),
            "ratio": np.nan,
            "evidence": str(corr_path),
            "notes": f"Pearson r = {r['pearson_r']:+.3f}, n = {int(r['n'])} (clears 3/√N).",
        })
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────


def build_summary_comparison(root: Path) -> pd.DataFrame:
    out_root = root / "outputs/geology_validation"
    rows: list[dict] = []
    rows.extend(build_axis0(out_root / "exp_diff.csv"))
    rows.extend(build_axis1(out_root / "r2_uplift.csv"))
    rows.extend(build_axis1_correlations(out_root / "corr_descriptor_production.csv"))
    rows.extend(build_axis2(out_root / "connectivity_summary.csv"))
    rows.extend(build_axis3(out_root / "diversity_width_ratio.csv"))
    rows.extend(build_axis4(out_root / "history_compliance_summary.csv"))
    rows.extend(build_axis4_misfit(out_root / "history_model_misfit.csv"))
    rows.extend(build_axis4_crossaxis(out_root / "history_cross_axis_correlations.json"))
    rows.extend(build_pending())
    return pd.DataFrame(rows)

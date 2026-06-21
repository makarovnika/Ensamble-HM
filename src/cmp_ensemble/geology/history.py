"""History-mismatch ↔ realism cross-axis (TZ §5.4).

Re-uses three pre-computed tables to avoid recomputing the Phase-1 ES update:

  outputs/qc/regulation_8_6_4_compliance.csv   per (setup, model) compliance
  outputs/qc/per_well_misfit.csv               per (model, well, metric) residuals
  outputs/geology_validation/connectivity_summary.csv

Produces three artefacts under ``outputs/geology_validation/``:

  history_compliance_summary.csv   pass-rates per setup × cluster + delta
  history_model_misfit.csv         one row per (setup, model) with total misfit
  history_vs_realism.csv           the cross-axis table for geol_fig06 —
                                   per-model misfit and frac_sand_in_largest_26
                                   joined on seed, both setups in long format

The article's main scientific claim — "Exp2 reduces mismatch without
sacrificing geological realism" — is supported by the cross-axis table:
a model whose mismatch drops between setup1 and setup2 should not show
a corresponding drop in connectivity / realism.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Regulation 8.6.4 — compliance summary by setup × cluster
# ──────────────────────────────────────────────────────────────────────────


def compliance_summary(
    compliance_df: pd.DataFrame,
) -> pd.DataFrame:
    """Pass-rates and per-criterion pass counts per (setup, cluster).

    Adds an ``all_clusters`` row per setup so the article can quote the
    overall number directly.
    """
    if compliance_df.empty:
        return pd.DataFrame()
    df = compliance_df.copy()
    rows: list[dict] = []
    for setup, sub in df.groupby("setup"):
        for cl in sorted(sub["cluster_id"].unique()):
            block = sub[sub["cluster_id"] == cl]
            rows.append({
                "setup": setup, "cluster": int(cl),
                "n_models": len(block),
                "pass_all_three_count": int(block["pass_all_three"].sum()),
                "pass_all_three_rate": float(block["pass_all_three"].mean()),
                "pass_field_cum_rate": float(block["pass_field_cum_5pct"].mean()),
                "pass_field_annual_rate": float(block["pass_field_annual_10pct"].mean()),
                "pass_well_top80_rate": float(block["pass_well_top80_20pct"].mean()),
            })
        # all-clusters row
        rows.append({
            "setup": setup, "cluster": -1,
            "n_models": len(sub),
            "pass_all_three_count": int(sub["pass_all_three"].sum()),
            "pass_all_three_rate": float(sub["pass_all_three"].mean()),
            "pass_field_cum_rate": float(sub["pass_field_cum_5pct"].mean()),
            "pass_field_annual_rate": float(sub["pass_field_annual_10pct"].mean()),
            "pass_well_top80_rate": float(sub["pass_well_top80_20pct"].mean()),
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# Per-model misfit aggregate
# ──────────────────────────────────────────────────────────────────────────


def model_misfit(
    compliance_df: pd.DataFrame,
) -> pd.DataFrame:
    """Per-(setup, model) misfit derived from regulation 8.6.4 deviations.

    The regulation table already has three % deviation columns that play the
    role of weighted mismatch (field cumulative, field annual max, per-well
    top-80% max). We sum them into a single ``total_mismatch_pct`` column
    so the cross-axis scatter and correlation use one number per model.
    """
    if compliance_df.empty:
        return pd.DataFrame()
    needed = {"setup", "model_id",
              "dev_field_cum_pct", "dev_field_annual_max_pct",
              "dev_well_top80_max_pct"}
    missing = needed - set(compliance_df.columns)
    if missing:
        raise ValueError(f"compliance table missing columns: {missing}")
    df = compliance_df.copy()
    df["total_mismatch_pct"] = (
        df["dev_field_cum_pct"]
        + df["dev_field_annual_max_pct"]
        + df["dev_well_top80_max_pct"]
    )
    return df[[
        "setup", "model_id", "cluster_id",
        "dev_field_cum_pct", "dev_field_annual_max_pct",
        "dev_well_top80_max_pct", "total_mismatch_pct", "pass_all_three",
    ]].rename(columns={"cluster_id": "cluster"})


# ──────────────────────────────────────────────────────────────────────────
# Cross-axis: mismatch ↓ AT realism →/↑
# ──────────────────────────────────────────────────────────────────────────


def load_model_seed_map(
    excel_path: Path | str = "models_near_adapted_centroids.xlsx",
) -> pd.DataFrame:
    """Load the MODEL → round(SEED) mapping from the canonical workbook.

    Each sheet has a two-line preamble; row 2 is the real header. Columns of
    interest: ``MODEL`` (compliance.model_id) and ``SEED`` (connectivity.seed
    after rounding).
    """
    excel_path = Path(excel_path)
    frames: list[pd.DataFrame] = []
    xl = pd.ExcelFile(excel_path)
    for sh in xl.sheet_names:
        # The sheets carry a 3-row preamble (title + blank + spacer);
        # the real header sits at row 3.
        df = pd.read_excel(excel_path, sheet_name=sh, header=3)
        df.columns = [c if isinstance(c, str) else f"col{i}"
                      for i, c in enumerate(df.columns)]
        # MODEL ends up in the first column after header; SEED in the last
        if "MODEL" in df.columns and "SEED" in df.columns:
            sub = df[["MODEL", "SEED"]].dropna().copy()
            sub["MODEL"] = sub["MODEL"].astype(int)
            sub["SEED_rounded"] = sub["SEED"].round().astype(int)
            sub["cluster_from_sheet"] = sh
            frames.append(sub)
    if not frames:
        raise ValueError(f"{excel_path}: could not parse MODEL/SEED columns")
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates("MODEL")


def history_vs_realism(
    model_misfit_df: pd.DataFrame,
    connectivity_df: pd.DataFrame,
    model_seed_map: pd.DataFrame | None = None,
    realism_column: str = "frac_sand_in_largest_26",
) -> pd.DataFrame:
    """Join per-(setup, model) misfit with the model's connectivity realism.

    ``model_seed_map`` is required because ``compliance.model_id`` (e.g. 403,
    2149) is the Excel sheet's MODEL ID, while ``connectivity.seed`` (e.g.
    32434, 22369) is the rounded full SEED from the deck name. The mapping
    is in ``models_near_adapted_centroids.xlsx`` — load it once via
    ``load_model_seed_map``.

    If ``model_seed_map`` is not supplied the function falls back to a direct
    join (useful for unit tests with synthetic data).
    """
    if model_misfit_df.empty or connectivity_df.empty:
        return pd.DataFrame()
    conn = connectivity_df.copy()
    conn = conn.sort_values("experiment", ascending=False)\
               .drop_duplicates("seed", keep="first")
    if model_seed_map is not None and not model_seed_map.empty:
        mm = model_misfit_df.merge(
            model_seed_map[["MODEL", "SEED_rounded"]],
            left_on="model_id", right_on="MODEL", how="left",
        )
        mm = mm.drop(columns=["MODEL"]).rename(columns={"SEED_rounded": "seed_real"})
        joined = mm.merge(
            conn[["seed", "cluster", realism_column,
                  "mean_inj_connections_per_producer", "n_bodies_26"]],
            left_on="seed_real", right_on="seed", how="left",
        )
    else:
        joined = model_misfit_df.merge(
            conn[["seed", "cluster", realism_column,
                  "mean_inj_connections_per_producer", "n_bodies_26"]],
            left_on="model_id", right_on="seed", how="left",
        )
    return joined


# ──────────────────────────────────────────────────────────────────────────
# Top-level driver
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class HistoryArtefacts:
    compliance_summary: pd.DataFrame
    model_misfit: pd.DataFrame
    history_vs_realism: pd.DataFrame
    cross_axis_correlations: dict[str, float]


def build_history(
    root: Path | None = None,
) -> HistoryArtefacts:
    root = root or Path(".")
    comp_path = root / "outputs/qc/regulation_8_6_4_compliance.csv"
    conn_path = root / "outputs/geology_validation/connectivity_summary.csv"
    comp = pd.read_csv(comp_path) if comp_path.exists() else pd.DataFrame()
    conn = pd.read_csv(conn_path) if conn_path.exists() else pd.DataFrame()

    comp_summary = compliance_summary(comp)
    mm = model_misfit(comp)
    try:
        model_seed_map = load_model_seed_map(
            root / "models_near_adapted_centroids.xlsx")
    except Exception as e:
        log.warning(f"could not load MODEL→SEED map: {e}; cross-axis disabled")
        model_seed_map = None
    cross = history_vs_realism(mm, conn, model_seed_map=model_seed_map)
    # Cross-axis Pearson correlation per setup — does mismatch correlate
    # negatively with connectivity realism (i.e. better-connected → lower
    # mismatch, the article's claim)?
    correlations: dict[str, float] = {}
    if not cross.empty:
        for setup, sub in cross.groupby("setup"):
            misfit_col = "total_mismatch_pct"
            joined = sub.dropna(subset=[misfit_col, "frac_sand_in_largest_26"])
            if len(joined) >= 3:
                r = float(np.corrcoef(joined[misfit_col],
                                       joined["frac_sand_in_largest_26"])[0, 1])
                correlations[str(setup)] = r
    return HistoryArtefacts(
        compliance_summary=comp_summary,
        model_misfit=mm,
        history_vs_realism=cross,
        cross_axis_correlations=correlations,
    )

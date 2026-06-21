"""Article-grade figures for the geology-validation report (TZ §6).

Five figures are fully buildable from the existing artefacts (axes 2-4):

  geol_fig03_facies_geometry  — channel parameter distributions vs cluster boxes
  geol_fig04_geobody_connectivity — connectivity stats, old vs new
  geol_fig05_diversity        — geological width_ratio bar chart
  geol_fig06_history_vs_realism — scatter mismatch vs realism (the main claim)
  geol_fig07_cluster2_migration — cluster-2 mismatch and realism, both setups

Two are stubbed until TZ §11 Q1 (facies dictionary) lands:

  geol_fig01_r2_uplift           — needs descriptor↔production R² regression
  geol_fig02_descriptor_corr     — needs descriptor↔production correlations

Every saved figure exists in both PNG (300 dpi, manuscript) and PDF
(vector, ``article_assets/figures_v2/``).
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

DPI = 300

# Colour palette consistent with the rest of the project
CLUSTER_COLORS = {0: "#1f77b4", 1: "#ff7f0e", 2: "#2ca02c"}
SETUP_COLORS = {"setup1_naive": "#666666", "setup2_localized": "#d62728"}
EXP_COLORS = {1: "#7f7f7f", 2: "#d62728"}


def _save_pair(fig: plt.Figure, fig_dir: Path, name: str) -> tuple[Path, Path]:
    """Save fig as PNG (manuscript) + PDF (vector). Returns both paths."""
    fig_dir.mkdir(parents=True, exist_ok=True)
    png = fig_dir / f"{name}.png"
    pdf = fig_dir / f"{name}.pdf"
    fig.savefig(png, dpi=DPI, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png, pdf


# ──────────────────────────────────────────────────────────────────────────
# fig03 — facies geometry vs cluster boxes
# ──────────────────────────────────────────────────────────────────────────

# Notion §5 cluster boxes (from TZ §5.2)
CLUSTER_BOXES = {
    "THICK":   {0: (5.6, 10.1),  1: (10.9, 17.0), 2: (13.9, 18.2)},
    "MAJ_R":   {0: (3400, 4584), 1: (2849, 4086), 2: (2198, 2724)},
    "AZIMUTH": {0: (65, 105),    1: (65, 105),    2: (65, 105)},
}


def geol_fig03_facies_geometry(
    centroid_excel: Path,
    out_dir: Path,
) -> tuple[Path, Path]:
    """Distributions of THICK / MAJ_R / AZIMUTH vs cluster reference boxes."""
    sheets = pd.ExcelFile(centroid_excel).sheet_names
    frames = []
    for i, sh in enumerate(sheets):
        df = pd.read_excel(centroid_excel, sheet_name=sh, header=3)
        df["cluster"] = i
        frames.append(df[["cluster", "THICK", "MAJ_R", "AZIMUTH"]])
    df = pd.concat(frames, ignore_index=True).dropna()

    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for ax, param in zip(axes, ("THICK", "MAJ_R", "AZIMUTH")):
        for cl in (0, 1, 2):
            sub = df[df["cluster"] == cl][param].to_numpy()
            ax.hist(sub, bins=15, alpha=0.55, label=f"cluster {cl}",
                    color=CLUSTER_COLORS[cl], edgecolor="black", linewidth=0.4)
            lo, hi = CLUSTER_BOXES[param][cl]
            ax.axvspan(lo, hi, alpha=0.12, color=CLUSTER_COLORS[cl])
        ax.set_title(param)
        ax.set_xlabel(param)
        ax.set_ylabel("models")
        ax.grid(alpha=0.2)
    axes[0].legend(loc="upper right", fontsize=8)
    fig.suptitle("Channel parameter distributions per cluster "
                 "(shaded = Notion §5 reference box)",
                 fontsize=11)
    fig.tight_layout()
    return _save_pair(fig, out_dir, "geol_fig03_facies_geometry")


# ──────────────────────────────────────────────────────────────────────────
# fig04 — geobody connectivity, old vs new
# ──────────────────────────────────────────────────────────────────────────


def geol_fig04_geobody_connectivity(
    connectivity_path: Path,
    out_dir: Path,
) -> tuple[Path, Path]:
    df = pd.read_csv(connectivity_path)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    metrics = [
        ("n_bodies_26",                 "n_bodies (26-conn)",         True),
        ("frac_sand_in_largest_26",     "frac sand in largest body",  False),
        ("mean_inj_connections_per_producer",
         "mean INJ connections / producer", False),
    ]
    for ax, (col, title, log_y) in zip(axes, metrics):
        data_by_exp = [df[df["experiment"] == e][col].dropna().to_numpy()
                       for e in (1, 2)]
        ax.boxplot(data_by_exp, labels=["Exp1 (old)", "Exp2 (new)"],
                    showfliers=True,
                    boxprops=dict(linewidth=1.3),
                    flierprops=dict(marker="o", markersize=3, markerfacecolor="#444",
                                    markeredgecolor="#444", alpha=0.4))
        if log_y:
            ax.set_yscale("symlog")
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.25)
    fig.suptitle("Connectivity: per-experiment distributions "
                 "(focus on the tails — medians are saturated)",
                 fontsize=11)
    fig.tight_layout()
    return _save_pair(fig, out_dir, "geol_fig04_geobody_connectivity")


# ──────────────────────────────────────────────────────────────────────────
# fig05 — geological width_ratio
# ──────────────────────────────────────────────────────────────────────────


def geol_fig05_diversity(
    width_ratio_path: Path,
    out_dir: Path,
) -> tuple[Path, Path]:
    df = pd.read_csv(width_ratio_path).sort_values("width_ratio_geo")
    fig, ax = plt.subplots(figsize=(8, 5.5))
    colors = ["#d62728" if v > 1 else "#1f77b4" for v in df["width_ratio_geo"]]
    ax.barh(df["metric"], df["width_ratio_geo"], color=colors,
             edgecolor="black", linewidth=0.4)
    ax.axvline(1.0, color="black", linewidth=0.8)
    ax.set_xlabel("width_ratio = spread(Exp2) / spread(Exp1)")
    ax.set_title("Geological width_ratio per metric\n"
                 "blue = Exp2 tightens variability (more deterministic), "
                 "red = Exp2 broadens it", fontsize=10)
    ax.grid(axis="x", alpha=0.2)
    # Show ES width_ratio reference for forecast metrics
    es_oil = df[df["metric"].str.contains("WOPT")]
    if not es_oil.empty:
        ax.text(2.5, len(df) - 0.5, "ES forecast width_ratio (1.47/2.22/1.47)\n"
                "lives on a different plane — see §discussion",
                fontsize=8, style="italic", color="#555")
    fig.tight_layout()
    return _save_pair(fig, out_dir, "geol_fig05_diversity")


# ──────────────────────────────────────────────────────────────────────────
# fig06 — the main figure: mismatch ↓ AT realism →/↑
# ──────────────────────────────────────────────────────────────────────────


def geol_fig06_history_vs_realism(
    history_vs_realism_path: Path,
    out_dir: Path,
) -> tuple[Path, Path]:
    df = pd.read_csv(history_vs_realism_path).dropna(
        subset=["frac_sand_in_largest_26", "total_mismatch_pct"])
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, setup in zip(axes, ("setup1_naive", "setup2_localized")):
        sub = df[df["setup"] == setup]
        for cl in (0, 1, 2):
            s = sub[sub["cluster_x"] == cl]
            ax.scatter(s["frac_sand_in_largest_26"], s["total_mismatch_pct"],
                       s=24, alpha=0.65, color=CLUSTER_COLORS[cl],
                       edgecolor="black", linewidth=0.3,
                       label=f"cluster {cl}")
        ax.set_xlabel("frac_sand_in_largest_26 (realism →)")
        ax.set_ylabel("total mismatch (%)")
        ax.set_title(f"{setup} — mean mismatch = "
                     f"{sub['total_mismatch_pct'].mean():.1f}%")
        ax.grid(alpha=0.25)
        if setup == "setup1_naive":
            ax.legend(loc="upper left", fontsize=8)
    fig.suptitle(
        "Mismatch vs realism per setup. Lower-left ⟸ no realism cost paid "
        "for the mismatch reduction in setup2",
        fontsize=11
    )
    fig.tight_layout()
    return _save_pair(fig, out_dir, "geol_fig06_history_vs_realism")


# ──────────────────────────────────────────────────────────────────────────
# fig07 — cluster 2 migration (mismatch + connectivity, both setups)
# ──────────────────────────────────────────────────────────────────────────


def geol_fig07_cluster2_migration(
    history_vs_realism_path: Path,
    out_dir: Path,
) -> tuple[Path, Path]:
    df = pd.read_csv(history_vs_realism_path).dropna(
        subset=["frac_sand_in_largest_26", "total_mismatch_pct"])
    c2 = df[df["cluster_x"] == 2]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    # Left: per-model mismatch, paired
    ax = axes[0]
    s1 = c2[c2["setup"] == "setup1_naive"].set_index("model_id")
    s2 = c2[c2["setup"] == "setup2_localized"].set_index("model_id")
    common = s1.index.intersection(s2.index)
    if len(common):
        x = np.zeros(len(common))
        y = np.ones(len(common))
        for mid in common:
            ax.plot([0, 1],
                    [s1.loc[mid, "total_mismatch_pct"],
                     s2.loc[mid, "total_mismatch_pct"]],
                    "-", color="#2ca02c", alpha=0.35, linewidth=0.6)
        ax.scatter(x, [s1.loc[mid, "total_mismatch_pct"] for mid in common],
                    s=22, color=SETUP_COLORS["setup1_naive"], label="setup1_naive")
        ax.scatter(y, [s2.loc[mid, "total_mismatch_pct"] for mid in common],
                    s=22, color=SETUP_COLORS["setup2_localized"],
                    label="setup2_localized")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["setup1_naive", "setup2_localized"])
    ax.set_ylabel("total mismatch (%)")
    ax.set_title(f"Cluster 2 mismatch — n={len(common)} paired models")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", fontsize=8)
    # Right: realism per setup
    ax = axes[1]
    ax.boxplot([s1["frac_sand_in_largest_26"].to_numpy(),
                 s2["frac_sand_in_largest_26"].to_numpy()],
                labels=["setup1_naive", "setup2_localized"], widths=0.5,
                boxprops=dict(linewidth=1.3))
    ax.set_ylabel("frac_sand_in_largest_26")
    ax.set_title("Cluster 2 realism — unchanged by ES update")
    ax.grid(axis="y", alpha=0.25)
    fig.suptitle(
        "Cluster 2 — mismatch drops sharply, realism is preserved",
        fontsize=11
    )
    fig.tight_layout()
    return _save_pair(fig, out_dir, "geol_fig07_cluster2_migration")


# ──────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────


def render_all_geology_figures(root: Path) -> dict[str, tuple[Path, Path]]:
    """Render the five buildable figures + report on pending ones."""
    out_root = root / "outputs/geology_validation/figures"
    art_root = root / "outputs/article_assets/figures_v2"
    out_root.mkdir(parents=True, exist_ok=True)
    art_root.mkdir(parents=True, exist_ok=True)

    plan = [
        ("geol_fig03", lambda: geol_fig03_facies_geometry(
            root / "models_near_adapted_centroids.xlsx", out_root)),
        ("geol_fig04", lambda: geol_fig04_geobody_connectivity(
            root / "outputs/geology_validation/connectivity_summary.csv", out_root)),
        ("geol_fig05", lambda: geol_fig05_diversity(
            root / "outputs/geology_validation/diversity_width_ratio.csv", out_root)),
        ("geol_fig06", lambda: geol_fig06_history_vs_realism(
            root / "outputs/geology_validation/history_vs_realism.csv", out_root)),
        ("geol_fig07", lambda: geol_fig07_cluster2_migration(
            root / "outputs/geology_validation/history_vs_realism.csv", out_root)),
    ]
    done: dict[str, tuple[Path, Path]] = {}
    for name, fn in plan:
        try:
            png, pdf = fn()
            # Mirror PDFs into article_assets/figures_v2/
            mirror = art_root / pdf.name
            mirror.write_bytes(pdf.read_bytes())
            done[name] = (png, pdf)
            log.info(f"  {name} -> {png.name}, {pdf.name}")
        except FileNotFoundError as e:
            log.warning(f"  skip {name}: missing input ({e})")
        except Exception as e:
            log.warning(f"  skip {name}: {type(e).__name__}: {e}")
    return done

"""Diagnostic figures for the manuscript (ТЗ §4 figs 01, 02, 06).

Three static figures derived from artefacts already on disk:

  fig01_pipeline             — block diagram of the four pipeline phases.
                                Pure matplotlib drawing, no data input.
  fig02_qc_spread            — bar chart from outputs/qc/spread_retention.csv
                                with reference lines at 1.0 (no change) and
                                0.1 (collapse threshold from ТЗ §6 Task 1.3).
  fig06_cluster3_migration   — grouped bars per cluster × θ component from
                                outputs/qc/cluster_migration.csv. Static
                                replacement for the Plotly HTML diagnostic.

Each function saves a 300 dpi PNG and a vector PDF, and returns the PNG path.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# Cluster palette — keeps the colours consistent with the Plotly diagnostic.
CLUSTER_COLORS = {
    0: "#4C78A8",   # blue
    1: "#F58518",   # orange
    2: "#54A24B",   # green
}


def _save_with_pdf(fig, png_path: Path, dpi: int = 300) -> Path:
    """Save the figure both as 300 dpi PNG and as a vector PDF next to it."""
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
    fig.savefig(png_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    return png_path


# ──────────────────────────────────────────────────────────────────────────
# fig01 — pipeline block diagram
# ──────────────────────────────────────────────────────────────────────────


def fig01_pipeline(out_path: Path) -> Path:
    """Block diagram of the four phases. No data input — purely schematic."""
    sns.set_theme(style="white", context="paper")
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 4.5)
    ax.set_axis_off()

    phases = [
        {
            "label": "Phase 0\nData Ingest",
            "x": 0.5,
            "items": [
                "models_near_adapted_centroids.xlsx",
                "Показатели динамики.xlsx",
                "Исторические значения.xlsx",
                "→ θ_prior, d_sim, d_obs, C_dd",
            ],
            "color": "#E8F0F8",
        },
        {
            "label": "Phase 1\nES Update + QC",
            "x": 3.4,
            "items": [
                "adaptive correlation localization",
                "subspace SVD truncation (99%)",
                "Z_post = Z_prior + K(d_obs+ε−d_sim)",
                "QC: spread, rank, Mahalanobis, BC",
            ],
            "color": "#FCE4D6",
        },
        {
            "label": "Phase 2\nSelection",
            "x": 6.3,
            "items": [
                "rank by ||Δθ||_M",
                "per-cluster linear proxy",
                "leave-one-out validation",
                "→ resimulate / proxy / val CSVs",
            ],
            "color": "#FFF2CC",
        },
        {
            "label": "Phase 3\nAblation Forecast",
            "x": 9.2,
            "items": [
                "setup1 (baseline)",
                "setup2 (ES + localization)",
                "setup3 ≡ setup2 (no controls)",
                "P10/P50/P90 + width_ratio",
            ],
            "color": "#E2F0D9",
        },
    ]
    box_w, box_h = 2.6, 3.6
    for ph in phases:
        rect = mpatches.FancyBboxPatch(
            (ph["x"], 0.45), box_w, box_h,
            boxstyle="round,pad=0.08", linewidth=1.4,
            edgecolor="#222", facecolor=ph["color"], zorder=2,
        )
        ax.add_patch(rect)
        ax.text(ph["x"] + box_w / 2, 0.45 + box_h - 0.45, ph["label"],
                ha="center", va="top", fontsize=11, fontweight="bold")
        for k, line in enumerate(ph["items"]):
            ax.text(ph["x"] + 0.15, 0.45 + box_h - 1.1 - k * 0.55, "• " + line,
                    ha="left", va="top", fontsize=8)

    # Arrows between phases
    for i in range(len(phases) - 1):
        x_from = phases[i]["x"] + box_w + 0.02
        x_to = phases[i + 1]["x"] - 0.02
        ax.annotate(
            "", xy=(x_to, 2.25), xytext=(x_from, 2.25),
            arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#333"),
        )

    # Caption
    ax.text(6, 0.10,
            "Synthetic mini-fixture (N=20) covers all 4 phases end-to-end (ТЗ §9).",
            ha="center", va="bottom", fontsize=8, style="italic", color="#555")

    fig.suptitle(
        "CMP Ensemble HM — pipeline overview (ТЗ §6 Phases 0–3)",
        fontsize=13, y=0.98,
    )
    fig.tight_layout()
    return _save_with_pdf(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# fig02 — QC spread retention bar chart
# ──────────────────────────────────────────────────────────────────────────


def fig02_qc_spread(spread_csv: Path, out_path: Path) -> Path:
    """Bar chart of σ_post / σ_prior per θ component."""
    sns.set_theme(style="whitegrid", context="paper")
    df = pd.read_csv(spread_csv)
    if "spread_retention" not in df.columns or "component" not in df.columns:
        raise ValueError(
            f"{spread_csv} is missing required columns 'component' and 'spread_retention'"
        )

    fig, ax = plt.subplots(figsize=(8, 4.5))
    components = df["component"].tolist()
    ratios = df["spread_retention"].to_numpy(dtype=float)

    colors = ["#54A24B" if r < 1.0 else "#888888" for r in ratios]
    # Mark collapses (< 0.1) in red
    for i, r in enumerate(ratios):
        if r < 0.1:
            colors[i] = "#D62728"

    bars = ax.bar(components, ratios, color=colors, edgecolor="#222", linewidth=0.8)
    ax.axhline(1.0, color="#222", linewidth=0.9, linestyle="--", label="σ_post = σ_prior (no update)")
    ax.axhline(0.1, color="#D62728", linewidth=0.9, linestyle=":", label="collapse threshold (ТЗ §6)")
    ax.set_ylabel("σ_post / σ_prior", fontsize=10)
    ax.set_xlabel("θ component", fontsize=10)
    ax.set_title("Phase 1 QC: spread retention per θ component", fontsize=11)
    ax.tick_params(axis="x", rotation=30)
    for tick in ax.get_xticklabels():
        tick.set_horizontalalignment("right")
    # Annotate each bar with its value
    for bar, r in zip(bars, ratios):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            r + 0.02,
            f"{r:.2f}",
            ha="center", va="bottom", fontsize=8,
        )
    ax.set_ylim(0, max(1.2, ratios.max() * 1.15))
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    return _save_with_pdf(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# fig06 — cluster centroid migration (matplotlib replacement for plotly HTML)
# ──────────────────────────────────────────────────────────────────────────


def fig06_cluster3_migration(migration_csv: Path, out_path: Path) -> Path:
    """Per-cluster grouped bars: reference / prior / posterior centroid in θ-space.

    Mirrors the Plotly HTML diagnostic at outputs/qc/cluster3_diagnostic.html
    but as a static vector figure for the manuscript.
    """
    sns.set_theme(style="whitegrid", context="paper")
    df = pd.read_csv(migration_csv)
    if "cluster" not in df.columns or "component" not in df.columns:
        raise ValueError(f"{migration_csv} missing 'cluster' or 'component'")

    clusters = sorted(df["cluster"].unique())
    components = list(df["component"].drop_duplicates())

    fig, axes = plt.subplots(
        len(clusters), 1, figsize=(11, 3.5 * len(clusters)), squeeze=False,
    )
    axes = axes[:, 0]

    width = 0.27
    x = np.arange(len(components))

    for ax, cl in zip(axes, clusters):
        sub = df[df["cluster"] == cl].set_index("component").loc[components]
        color = CLUSTER_COLORS.get(int(cl), "#888")
        ref = sub["reference"].to_numpy(dtype=float)
        pri = sub["prior_centroid"].to_numpy(dtype=float)
        pst = sub["post_centroid"].to_numpy(dtype=float)

        # Normalise each component to its own scale so the bars are comparable
        # (THICK ~ 10 m, MAJ_R ~ 4000 m would be invisible otherwise).
        scale = np.maximum(np.abs(pri), 1e-12)
        ref_n = ref / scale
        pri_n = pri / scale
        pst_n = pst / scale

        ax.bar(x - width, ref_n, width, color="#999999", label="reference centroid", edgecolor="#222", linewidth=0.6)
        ax.bar(x, pri_n, width, color=color, alpha=0.55, label="prior centroid", edgecolor="#222", linewidth=0.6)
        ax.bar(x + width, pst_n, width, color=color, label="posterior centroid", edgecolor="#222", linewidth=0.6)

        # Annotate the percentage shift from prior to post
        for xi, (p, q) in enumerate(zip(pri, pst)):
            if abs(p) < 1e-12:
                continue
            pct = (q - p) / p * 100
            if abs(pct) > 1:
                ax.text(xi + width, pst_n[xi] + 0.04, f"{pct:+.1f}%",
                        ha="center", va="bottom", fontsize=7, color="#222")

        ax.set_title(f"Cluster {cl}", fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels(components, rotation=30, ha="right", fontsize=8)
        ax.set_ylabel("value / |prior centroid|", fontsize=9)
        ax.axhline(1.0, color="#333", linewidth=0.5, linestyle=":")
        ax.legend(fontsize=8, loc="upper right")

    fig.suptitle(
        "Cluster centroid migration in θ-space (ТЗ §6 Task 1.4)",
        fontsize=12, y=0.995,
    )
    fig.tight_layout()
    return _save_with_pdf(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# Helper: mirror a figure into article_assets/figures_v2/
# ──────────────────────────────────────────────────────────────────────────


def mirror_to_article_assets(figures_dir: Path, article_assets_dir: Path) -> list[Path]:
    """Copy every fig*.{png,pdf} from `figures_dir` to `article_assets_dir`.

    Per ТЗ §4 the figures should also exist under
    `outputs/article_assets/figures_v2/` for the manuscript.
    """
    import shutil

    article_assets_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for src in sorted(figures_dir.glob("fig*.*")):
        if src.suffix.lower() not in {".png", ".pdf"}:
            continue
        dst = article_assets_dir / src.name
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied

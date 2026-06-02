"""Phase 3 ablation figures (ТЗ §6 Task 3.5 + figures fig03, fig04).

Two main figures:

  fig03_ablation_p10p90 — Field-total cumulative production over the forecast
                          window. One row per metric (oil / water / gas),
                          one column per setup. P10-P50-P90 bands.

  fig04_cumulative_scatter — Per-model scatter of end-of-forecast cumulative
                             (one panel per metric). Setups overlaid.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

from cmp_ensemble.forecast.aggregation import field_total_quantiles
from cmp_ensemble.forecast.setups import SetupResult


CUM_METRICS = ("Накопл. нефть", "Накопл. вода", "Накопл. газ")
SETUP_COLORS = {
    "setup1_naive": "#4C78A8",      # blue
    "setup2_localized": "#F58518",  # orange
    "setup3_full": "#54A24B",       # green
}


def fig03_ablation_p10p90(results: list[SetupResult], out_path: Path) -> Path:
    """Field-total cumulative oil/water/gas P10/P50/P90 vs time, per setup."""
    sns.set_theme(style="whitegrid", context="paper")
    metrics = [m for m in CUM_METRICS]
    n_rows, n_cols = len(metrics), len(results)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(4 * n_cols, 3 * n_rows), squeeze=False)
    for j, r in enumerate(results):
        ft = field_total_quantiles(r.d_forecast, r.index)
        for i, metric in enumerate(metrics):
            ax = axes[i, j]
            sub = ft[ft["metric"] == metric].sort_values("time")
            if sub.empty:
                ax.set_visible(False)
                continue
            t = list(range(len(sub)))
            tlabels = [str(d) for d in sub["time"]]
            color = SETUP_COLORS.get(r.label, "#888")
            ax.fill_between(t, sub["p10"], sub["p90"], color=color, alpha=0.30, label="P10–P90")
            ax.plot(t, sub["p50"], color=color, linewidth=1.8, label="P50")
            ax.set_xticks(t)
            ax.set_xticklabels(tlabels, rotation=45, ha="right", fontsize=7)
            if i == 0:
                ax.set_title(r.label, fontsize=10)
            if j == 0:
                ax.set_ylabel(f"{metric}\n(field total, sm³)", fontsize=9)
            ax.tick_params(axis="y", labelsize=8)
            if i == n_rows - 1 and j == n_cols - 1:
                ax.legend(loc="lower right", fontsize=8)
    fig.suptitle(
        "Field-total forecast quantiles by setup (Phase 3 ablation)",
        fontsize=12, y=1.02,
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def fig04_cumulative_scatter(
    results: list[SetupResult],
    out_path: Path,
) -> Path:
    """One panel per metric. Scatter of per-model end-of-forecast field-total
    cumulative production. Setups colour-coded.
    """
    sns.set_theme(style="whitegrid", context="paper")
    metrics = list(CUM_METRICS)
    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4), squeeze=False)
    axes = axes[0]
    for ax, metric in zip(axes, metrics):
        for r in results:
            # End-of-forecast = last time anchor per (metric, well, time)
            last_time = max(t for (m, w, t) in r.index if m == metric)
            mask = np.array(
                [
                    (mm == metric and tt == last_time)
                    for (mm, ww, tt) in r.index
                ],
                dtype=bool,
            )
            # Field total per model at last time
            per_model_total = r.d_forecast[:, mask].sum(axis=1)
            ax.scatter(
                np.arange(per_model_total.size),
                per_model_total,
                s=10,
                alpha=0.65,
                label=r.label,
                color=SETUP_COLORS.get(r.label, "#888"),
            )
        ax.set_title(metric, fontsize=10)
        ax.set_xlabel("Member index", fontsize=9)
        ax.set_ylabel("End-of-forecast field cumulative (sm³)", fontsize=9)
        ax.legend(fontsize=8)
    fig.suptitle(
        "End-of-forecast field cumulative per model (Phase 3)",
        fontsize=12, y=1.02,
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def build_latex_ablation_table(summary_df, out_path: Path) -> Path:
    """LaTeX-formatted summary table per ТЗ §10 article_assets/ablation_table.tex."""
    rows = []
    rows.append(r"\begin{table}[h]")
    rows.append(r"\centering")
    rows.append(r"\caption{Ablation summary: width ratio and median shift across setups.}")
    rows.append(r"\label{tab:ablation}")
    rows.append(r"\begin{tabular}{lllrrr}")
    rows.append(r"\toprule")
    rows.append(r"Setup & Metric & $M$ & mean width ratio & mean median shift & coverage P10--P90 \\")
    rows.append(r"\midrule")
    for _, r in summary_df.iterrows():
        cov = r["coverage_p10p90"]
        cov_s = f"{cov:.3f}" if not (cov != cov) else "--"   # NaN check
        # Escape underscores for LaTeX outside the f-string — backslashes
        # inside f-string expressions are illegal until Python 3.12 (PEP 701).
        setup_tex = str(r["setup"]).replace("_", r"\_")
        rows.append(
            f"{setup_tex} & {r['phase']} & {int(r['M_members'])} & "
            f"{r['mean_width_ratio']:.3f} & {r['mean_median_shift']:.3e} & {cov_s} \\\\"
        )
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabular}")
    rows.append(r"\end{table}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(rows), encoding="utf-8")
    return out_path

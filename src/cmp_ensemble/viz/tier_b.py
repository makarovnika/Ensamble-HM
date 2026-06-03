"""Tier B diagnostic figures for the HTML QC report.

Eight figures, all rendered as PNG at 120 dpi (lower than Tier A's 300 dpi —
these are embedded in `outputs/qc/qc_report.html` where file size matters).

  B1 qc_singular_spectrum         — log-y spectrum + 99 %-energy marker
  B2 qc_locmask_heatmap           — 9×384 binary mask with block separators
  B3 qc_mahalanobis_distribution  — histogram per cluster with KDE
  B4 qc_per_well_misfit_heatmap   — diverging residual_z by (metric × well) × time
  B5 qc_theta_pairgrid            — 9-D pairgrid, prior (grey) vs posterior (red)
  B6 qc_proxy_validation_scatter  — median_rel_err per validation member, cluster-coloured
  B7 qc_forecast_per_well         — 4×4 small multiples, oil rate per producer
  B8 qc_history_match_quality     — 3-panel field-total cum oil/water/gas

All functions accept input paths + an output PNG path; return the written path.
None do any data ingest (read CSV / npy / h5); they fail loudly if the input is
missing rather than fabricating data.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

log = logging.getLogger(__name__)

# Cluster palette — must match docs/visualization_plan.md.
CLUSTER_COLORS = {0: "#1f77b4", 1: "#ff7f0e", 2: "#2ca02c"}
PRIOR_COLOR = "#7f7f7f"
POSTERIOR_COLOR = "#d62728"
DPI = 120


def _save(fig, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ──────────────────────────────────────────────────────────────────────────
# B1 — singular spectrum
# ──────────────────────────────────────────────────────────────────────────


def qc_singular_spectrum(sv_npy: Path, out_path: Path) -> Path:
    sv = np.load(sv_npy)
    energy = (sv ** 2).cumsum() / max((sv ** 2).sum(), 1e-30)
    r = int(np.searchsorted(energy, 0.99) + 1)

    sns.set_theme(style="whitegrid", context="paper")
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.semilogy(np.arange(1, sv.size + 1), sv, marker="o", markersize=3,
                color="#1f77b4", linewidth=1)
    ax.axvline(r, color=POSTERIOR_COLOR, linestyle="--", linewidth=1.2,
               label=f"99 % energy → r = {r}")
    ax.set_xlabel("Component index k", fontsize=10)
    ax.set_ylabel(r"Singular value $\sigma_k$ (log scale)", fontsize=10)
    ax.set_title("Phase 1 subspace SVD spectrum", fontsize=11)
    ax.legend(fontsize=9, loc="upper right")
    return _save(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# B2 — locmask heatmap
# ──────────────────────────────────────────────────────────────────────────


def qc_locmask_heatmap(locmask_npy: Path, out_path: Path) -> Path:
    mask = np.load(locmask_npy)
    sns.set_theme(style="white", context="paper")
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.imshow(mask, aspect="auto", interpolation="nearest",
              cmap="Greens", vmin=0, vmax=1)
    n_z, n_d = mask.shape
    # Block separators for the typical n_d_cum layout: 3 metrics × n_wells × n_years.
    # Assume the columns repeat by metric — split into 3 equal blocks.
    if n_d % 3 == 0:
        for k in (n_d // 3, 2 * n_d // 3):
            ax.axvline(k - 0.5, color="#222", linewidth=0.8)
        labels = ["Накопл. нефть", "Накопл. вода", "Накопл. газ"]
        for j, lbl in enumerate(labels):
            ax.text((j + 0.5) * n_d / 3, -1.0, lbl, ha="center", va="top",
                    fontsize=8, color="#444")
    ax.set_xlabel("Observation column j", fontsize=10)
    ax.set_ylabel("θ component k", fontsize=10)
    ax.set_yticks(range(n_z))
    ax.set_title(f"Localization mask — {int((mask > 0).sum())}/{mask.size} kept "
                 f"({100 * (mask > 0).mean():.2f} %)", fontsize=11)
    return _save(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# B3 — Mahalanobis migration distribution per cluster
# ──────────────────────────────────────────────────────────────────────────


def qc_mahalanobis_distribution(
    maha_csv: Path, cluster_ids_npy: Path, out_path: Path,
) -> Path:
    df = pd.read_csv(maha_csv)
    cluster_ids = np.load(cluster_ids_npy)
    if "cluster" not in df.columns:
        # Re-attach cluster ids by member order
        if len(df) != cluster_ids.size:
            raise ValueError(
                f"mahalanobis CSV has {len(df)} rows but cluster_ids has "
                f"{cluster_ids.size} — cannot merge."
            )
        df["cluster"] = cluster_ids

    sns.set_theme(style="whitegrid", context="paper")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for cl in sorted(df["cluster"].unique()):
        sub = df[df["cluster"] == cl]["maha"]
        sns.kdeplot(sub, ax=ax, label=f"cluster {int(cl)} (n={len(sub)})",
                    color=CLUSTER_COLORS.get(int(cl), "#888"), linewidth=2)
        ax.hist(sub, bins=15, alpha=0.18,
                color=CLUSTER_COLORS.get(int(cl), "#888"), density=True)
    ax.set_xlabel(r"$\|\Delta\theta\|_M$", fontsize=10)
    ax.set_ylabel("density", fontsize=10)
    ax.set_title("Mahalanobis migration per cluster", fontsize=11)
    ax.legend(fontsize=9)
    return _save(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# B4 — per-well misfit heatmap (diverging residual_z)
# ──────────────────────────────────────────────────────────────────────────


def qc_per_well_misfit_heatmap(misfit_csv: Path, out_path: Path) -> Path:
    df = pd.read_csv(misfit_csv)
    # Build a (metric, well) × time matrix of residual_z
    if "residual_z" not in df.columns:
        raise ValueError(f"{misfit_csv} missing residual_z column")
    df["mw"] = df["metric"].astype(str) + " · " + df["well"].astype(str)
    pivot = df.pivot_table(index="mw", columns="time", values="residual_z",
                            aggfunc="mean")
    # Clip extreme values for visual readability (rare outliers)
    pivot = pivot.clip(lower=-10, upper=10)

    sns.set_theme(style="white", context="paper")
    fig, ax = plt.subplots(figsize=(12, max(4, 0.18 * len(pivot))))
    sns.heatmap(pivot, cmap="RdBu_r", center=0, vmin=-5, vmax=5,
                cbar_kws={"label": "(d_sim_mean − d_obs) / σ_sim, clipped at ±10"},
                ax=ax)
    ax.set_xlabel("year-end timestamp", fontsize=10)
    ax.set_ylabel("metric · well", fontsize=9)
    ax.set_title("Per-well history-match residual z-score", fontsize=11)
    ax.tick_params(axis="x", rotation=45, labelsize=7)
    ax.tick_params(axis="y", labelsize=7)
    return _save(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# B5 — θ pairgrid: prior (grey) vs posterior (red) overlay
# ──────────────────────────────────────────────────────────────────────────


def qc_theta_pairgrid(
    theta_prior_npy: Path,
    theta_post_npy: Path,
    out_path: Path,
    theta_names: list[str] | None = None,
) -> Path:
    Z_prior = np.load(theta_prior_npy)
    Z_post = np.load(theta_post_npy)
    n_z = Z_prior.shape[1]
    names = theta_names or [f"θ{i}" for i in range(n_z)]
    df = pd.concat([
        pd.DataFrame(Z_prior, columns=names).assign(stage="prior"),
        pd.DataFrame(Z_post, columns=names).assign(stage="posterior"),
    ], ignore_index=True)

    sns.set_theme(style="whitegrid", context="paper", font_scale=0.7)
    g = sns.pairplot(
        df, hue="stage", vars=names, corner=True,
        palette={"prior": PRIOR_COLOR, "posterior": POSTERIOR_COLOR},
        plot_kws=dict(s=8, alpha=0.55, edgecolor="none"),
        diag_kws=dict(common_norm=False, alpha=0.5, fill=True),
        diag_kind="kde",
    )
    g.figure.suptitle("θ_prior (grey) vs θ_posterior (red) — pair grid",
                      y=1.02, fontsize=11)
    g.figure.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    g.figure.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(g.figure)
    return out_path


# ──────────────────────────────────────────────────────────────────────────
# B6 — proxy validation scatter (median rel err per held-out member)
# ──────────────────────────────────────────────────────────────────────────


def qc_proxy_validation_scatter(val_csv: Path, out_path: Path) -> Path:
    df = pd.read_csv(val_csv)
    if not {"cluster", "median_rel_err"}.issubset(df.columns):
        raise ValueError(f"{val_csv} missing required columns")

    sns.set_theme(style="whitegrid", context="paper")
    fig, ax = plt.subplots(figsize=(7, 4))
    for cl in sorted(df["cluster"].unique()):
        sub = df[df["cluster"] == cl]
        ax.scatter(
            np.full(len(sub), int(cl)) + np.random.default_rng(int(cl)).uniform(
                -0.12, 0.12, size=len(sub)
            ),
            sub["median_rel_err"],
            color=CLUSTER_COLORS.get(int(cl), "#888"),
            s=60, alpha=0.85, edgecolor="#222", linewidth=0.6,
            label=f"cluster {int(cl)} (n={len(sub)})",
        )
    ax.axhline(1.0, color="#222", linestyle="--", linewidth=0.8,
               label="PASS threshold (median rel err < 1)")
    ax.axhline(2.0, color="#aa3333", linestyle=":", linewidth=0.8,
               label="FAIL threshold")
    ax.set_xticks(sorted(df["cluster"].unique()))
    ax.set_xlabel("cluster", fontsize=10)
    ax.set_ylabel("median relative error per validation member", fontsize=10)
    ax.set_title("Proxy validation — held-out median relative error", fontsize=11)
    ax.legend(fontsize=8, loc="upper left")
    return _save(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# B7 — per-well forecast small multiples
# ──────────────────────────────────────────────────────────────────────────


def qc_forecast_per_well(
    forecast_h5: Path,
    out_path: Path,
    metric: str = "Накопл. нефть",
) -> Path:
    import h5py

    with h5py.File(forecast_h5, "r") as f:
        d_cum = f["d_forecast_cum"][:]
        cum_index_raw = f["cum_index"][:]
        cluster_ids = f["cluster_ids"][:]
    index = [
        (m.decode(), w.decode(), pd.Timestamp(t.decode()))
        for m, w, t in cum_index_raw
    ]
    df_idx = pd.DataFrame(index, columns=["metric", "well", "time"])
    df_idx["pos"] = np.arange(len(df_idx))

    metric_rows = df_idx[df_idx["metric"] == metric]
    if metric_rows.empty:
        raise ValueError(f"metric {metric!r} absent from cum_index")
    wells = sorted(metric_rows["well"].unique())
    n_wells = len(wells)

    sns.set_theme(style="whitegrid", context="paper")
    n_cols = 4
    n_rows = (n_wells + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(11, 2.6 * n_rows),
                             sharex=True, squeeze=False)
    for k, well in enumerate(wells):
        ax = axes[k // n_cols, k % n_cols]
        for cl in sorted(set(cluster_ids.tolist())):
            cl_mask = cluster_ids == cl
            for i in np.where(cl_mask)[0]:
                cols = metric_rows[metric_rows["well"] == well]["pos"].to_numpy()
                times = metric_rows[metric_rows["well"] == well]["time"].tolist()
                ax.plot(times, d_cum[i, cols],
                        color=CLUSTER_COLORS.get(int(cl), "#888"),
                        linewidth=0.4, alpha=0.4)
        ax.set_title(well, fontsize=9)
        ax.tick_params(axis="x", labelsize=6, rotation=45)
        ax.tick_params(axis="y", labelsize=6)
    # blank unused panels
    for k in range(n_wells, n_rows * n_cols):
        axes[k // n_cols, k % n_cols].axis("off")
    fig.suptitle(f"Per-producer forecast cumulative — {metric}",
                 fontsize=11, y=1.01)
    fig.tight_layout()
    return _save(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# B8 — history match quality (field-total ensemble cloud + d_obs)
# ──────────────────────────────────────────────────────────────────────────


def qc_history_match_quality(
    d_sim_cum_npy: Path,
    d_obs_cum_npy: Path,
    ensemble_h5: Path,
    out_path: Path,
) -> Path:
    import h5py

    d_sim = np.load(d_sim_cum_npy)
    d_obs = np.load(d_obs_cum_npy)
    with h5py.File(ensemble_h5, "r") as f:
        cum_index_raw = f["cum_index"][:]
    index = [
        (m.decode(), w.decode(), pd.Timestamp(t.decode()))
        for m, w, t in cum_index_raw
    ]
    df_idx = pd.DataFrame(index, columns=["metric", "well", "time"])
    df_idx["pos"] = np.arange(len(df_idx))

    metrics = ["Накопл. нефть", "Накопл. вода", "Накопл. газ"]
    sns.set_theme(style="whitegrid", context="paper")
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), squeeze=False)
    for ax, metric in zip(axes[0], metrics):
        rows = df_idx[df_idx["metric"] == metric].sort_values("time")
        if rows.empty:
            ax.set_visible(False)
            continue
        # Field total = sum across wells for each (model, year-end)
        years = sorted(rows["time"].unique())
        field_sim = np.zeros((d_sim.shape[0], len(years)))
        field_obs = np.zeros(len(years))
        for j, y in enumerate(years):
            cols = rows[rows["time"] == y]["pos"].to_numpy()
            field_sim[:, j] = d_sim[:, cols].sum(axis=1)
            field_obs[j] = d_obs[cols].sum()
        # Ensemble cloud (thin lines) + observation
        for i in range(field_sim.shape[0]):
            ax.plot(years, field_sim[i], color="#1f77b4", linewidth=0.3, alpha=0.25)
        ax.plot(years, field_obs, color=POSTERIOR_COLOR, linewidth=2.0,
                marker="o", markersize=4, label="d_obs (historical)")
        ax.plot(years, np.median(field_sim, axis=0), color="#0a2c5a",
                linewidth=1.6, linestyle="--", label="d_sim median")
        ax.set_title(metric, fontsize=10)
        ax.tick_params(axis="x", labelsize=7, rotation=30)
        ax.tick_params(axis="y", labelsize=8)
        ax.set_ylabel("field total, ст.м³", fontsize=9)
        ax.legend(fontsize=7, loc="upper left")
    fig.suptitle("History match quality — field-total cumulative production",
                 fontsize=11, y=1.02)
    fig.tight_layout()
    return _save(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────


def render_all_tier_b(root: Path) -> dict[str, Path]:
    """Render all 8 Tier B figures from the artefacts under `root/outputs/`.

    Returns a {figure_id: path} map for whatever managed to render. Missing
    inputs are logged and skipped.
    """
    out_root = root / "outputs"
    out_dir = out_root / "qc" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    matrices = out_root / "matrices"
    qc = out_root / "qc"
    selection = out_root / "selection"
    cache = out_root / "cache"

    plan: list[tuple[str, callable]] = [
        ("qc_singular_spectrum", lambda: qc_singular_spectrum(
            matrices / "singular_values.npy", out_dir / "qc_singular_spectrum.png")),
        ("qc_locmask_heatmap", lambda: qc_locmask_heatmap(
            matrices / "locmask.npy", out_dir / "qc_locmask_heatmap.png")),
        ("qc_mahalanobis_distribution", lambda: qc_mahalanobis_distribution(
            qc / "mahalanobis_migration.csv",
            matrices / "cluster_ids.npy",
            out_dir / "qc_mahalanobis_distribution.png")),
        ("qc_per_well_misfit_heatmap", lambda: qc_per_well_misfit_heatmap(
            qc / "per_well_misfit.csv",
            out_dir / "qc_per_well_misfit_heatmap.png")),
        ("qc_theta_pairgrid", lambda: qc_theta_pairgrid(
            matrices / "theta_prior.npy", matrices / "theta_post.npy",
            out_dir / "qc_theta_pairgrid.png",
            ["THICK", "MAJ_R", "AZIMUTH", "NUMBER_CHANNELS", "CHANNELS_WIDTH",
             "LEN", "AMPLITUDE", "RELATIVE", "PROP"])),
        ("qc_proxy_validation_scatter", lambda: qc_proxy_validation_scatter(
            selection / "proxy_validation_per_member.csv",
            out_dir / "qc_proxy_validation_scatter.png")),
        ("qc_forecast_per_well", lambda: qc_forecast_per_well(
            cache / "forecast.h5",
            out_dir / "qc_forecast_per_well.png")),
        ("qc_history_match_quality", lambda: qc_history_match_quality(
            matrices / "d_sim_cum.npy", matrices / "d_obs_cum.npy",
            cache / "ensemble.h5",
            out_dir / "qc_history_match_quality.png")),
    ]
    done: dict[str, Path] = {}
    for name, fn in plan:
        try:
            done[name] = fn()
            log.info(f"  ✓ {name} → {done[name].relative_to(root)}")
        except FileNotFoundError as exc:
            log.warning(f"  ✗ skip {name}: input missing ({exc})")
        except Exception as exc:
            log.warning(f"  ✗ skip {name}: {type(exc).__name__}: {exc}")
    return done

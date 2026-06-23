"""Closed-loop figures (CL-F): misfit evolution, theta migration, forecast corridors.

Matplotlib-only (Agg-safe), each builder writes a 300-dpi PNG + vector PDF for
the manuscript. Mirrors the diagnostics style of viz/diagnostics.py.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def _save(fig, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
    return out_path


def fig_misfit_evolution(misfit_history, out_path):
    """Mean normalised data misfit before each ES-MDA step + final."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    m = np.asarray(misfit_history, dtype=float)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(range(len(m)), m, "o-", color="#1f77b4", lw=2, ms=7)
    ax.set_xlabel("ES-MDA step")
    ax.set_ylabel("mean normalised data misfit")
    ax.set_title("ES-MDA misfit evolution")
    ax.set_xticks(range(len(m)))
    labels = [f"{i}" for i in range(len(m) - 1)] + ["post"]
    ax.set_xticklabels(labels)
    ax.grid(True, alpha=0.3)
    if m[0] > 0:
        ax.annotate(f"{(1 - m[-1] / m[0]) * 100:.0f}% reduction",
                    xy=(len(m) - 1, m[-1]), xytext=(0.5, 0.85),
                    textcoords="axes fraction", fontsize=10)
    return _save(fig, out_path)


def fig_theta_migration(Theta_prior, Theta_post, names, out_path, *, subset=None):
    """Prior vs posterior ensemble mean per parameter, normalised by prior std."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    Theta_prior = np.asarray(Theta_prior, float)
    Theta_post = np.asarray(Theta_post, float)
    names = list(names)
    if subset is not None:
        idx = [names.index(n) for n in subset if n in names]
    else:
        idx = list(range(min(len(names), 9)))   # default: first 9 (geology block)
    sel = [names[i] for i in idx]
    mu0 = Theta_prior[:, idx].mean(axis=0)
    mu1 = Theta_post[:, idx].mean(axis=0)
    sd0 = Theta_prior[:, idx].std(axis=0)
    sd0 = np.where(sd0 > 0, sd0, 1.0)
    shift_sigma = (mu1 - mu0) / sd0

    fig, ax = plt.subplots(figsize=(7, 4))
    x = np.arange(len(sel))
    colors = ["#2ca02c" if abs(s) > 0.05 else "#999999" for s in shift_sigma]
    ax.bar(x, shift_sigma, color=colors)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(sel, rotation=45, ha="right")
    ax.set_ylabel("posterior shift (in prior sigma)")
    ax.set_title("Theta migration: prior -> posterior")
    ax.grid(True, axis="y", alpha=0.3)
    return _save(fig, out_path)


def fig_forecast_corridors(prior_quantiles, post_quantiles, out_path, *, metric=None):
    """P10/P50/P90 field-total corridors: prior (grey) vs posterior (blue)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    pq, sq = prior_quantiles.copy(), post_quantiles.copy()
    metrics = sorted(sq["metric"].unique()) if metric is None else [metric]
    fig, axes = plt.subplots(len(metrics), 1, figsize=(7, 3 * len(metrics)),
                             squeeze=False)
    for ax, m in zip(axes[:, 0], metrics):
        p = pq[pq["metric"] == m].sort_values("time")
        s = sq[sq["metric"] == m].sort_values("time")
        t_p = pd.to_datetime(p["time"]); t_s = pd.to_datetime(s["time"])
        ax.fill_between(t_p, p["p10"], p["p90"], color="#999999", alpha=0.3,
                        label="prior P10-P90")
        ax.fill_between(t_s, s["p10"], s["p90"], color="#1f77b4", alpha=0.35,
                        label="posterior P10-P90")
        ax.plot(t_s, s["p50"], color="#1f77b4", lw=2, label="posterior P50")
        ax.plot(t_p, p["p50"], color="#555555", lw=1.2, ls="--", label="prior P50")
        ax.set_title(str(m))
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("Forecast corridors (field total): prior vs posterior")
    fig.tight_layout()
    return _save(fig, out_path)

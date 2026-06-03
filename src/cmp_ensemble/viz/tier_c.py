"""Tier C interactive Plotly figures for the HTML reports.

Two figures + one polish:

  C1 cluster3_diagnostic.html        — already exists (qc/cluster_migration.py);
                                        this module adds σ-shift on hover via a
                                        polish helper, not a new file.
  C2 interactive_ablation.html       — dropdown metric (oil/water/gas) ×
                                        3 setups overlaid, P10/P50/P90 envelope.
  C3 interactive_theta_explorer.html — parallel-coordinates of 9 θ parameters,
                                        cluster colour, prior vs posterior view.

Every HTML carries the same light-theme markers as Tier-A reports
(`<meta name="color-scheme" content="light only">` plus dark-mode override CSS)
so they render identically regardless of the user's OS theme.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

log = logging.getLogger(__name__)


CLUSTER_COLORS = {0: "#1f77b4", 1: "#ff7f0e", 2: "#2ca02c"}
SETUP_COLORS = {
    "setup1_naive": "#4C78A8",
    "setup2_localized": "#F58518",
    "setup3_full": "#54A24B",
}

# Same light-mode injection as in qc/cluster_migration.py — keeps the three
# Tier-C HTMLs visually consistent and ignores browser/OS dark mode.
LIGHT_HEAD = (
    '<meta name="color-scheme" content="light only">\n'
    '<style>\n'
    '  :root { color-scheme: light; }\n'
    '  html, body { background: #ffffff !important; color: #1a1a1a !important; }\n'
    '  @media (prefers-color-scheme: dark) {\n'
    '    html, body { background: #ffffff !important; color: #1a1a1a !important; }\n'
    '  }\n'
    '</style>\n'
)


def _write_with_light_theme(fig: go.Figure, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = fig.to_html(include_plotlyjs="cdn", full_html=True)
    html = html.replace("<head>", "<head>\n" + LIGHT_HEAD, 1)
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ──────────────────────────────────────────────────────────────────────────
# C2 — interactive ablation: dropdown metric × 3 setups overlaid
# ──────────────────────────────────────────────────────────────────────────


def interactive_ablation(
    setup_csvs: dict[str, Path],
    out_path: Path,
) -> Path:
    """Build an interactive ablation plot with a metric-selector dropdown.

    `setup_csvs` is `{setup_label: path/to/setup*_field_total_quantiles.csv}`.
    Every CSV must have columns ``metric, time, p10, p50, p90`` (the standard
    `field_total_quantiles` schema). The figure overlays the three setups for
    one metric at a time; a dropdown switches metric.
    """
    frames: list[tuple[str, str, pd.DataFrame]] = []
    for label, csv_path in setup_csvs.items():
        df = pd.read_csv(csv_path)
        needed = {"metric", "time", "p10", "p50", "p90"}
        missing = needed - set(df.columns)
        if missing:
            raise ValueError(f"{csv_path}: missing columns {missing}")
        frames.append((label, csv_path.name, df))

    if not frames:
        raise ValueError("setup_csvs is empty — nothing to plot")

    metrics = sorted({m for _, _, df in frames for m in df["metric"].unique()})
    if not metrics:
        raise ValueError("no metrics found across the supplied CSVs")

    fig = go.Figure()
    traces_per_metric: list[int] = []
    for metric in metrics:
        n_added = 0
        for label, _src, df in frames:
            sub = df[df["metric"] == metric].sort_values("time")
            if sub.empty:
                continue
            colour = SETUP_COLORS.get(label, "#666")
            # P10-P90 envelope (filled area as a single closed loop)
            x_band = list(sub["time"]) + list(sub["time"][::-1])
            y_band = list(sub["p90"]) + list(sub["p10"][::-1])
            fig.add_trace(go.Scatter(
                x=x_band, y=y_band, fill="toself",
                fillcolor=colour, opacity=0.18,
                line=dict(color="rgba(0,0,0,0)"),
                hoverinfo="skip", showlegend=False,
                name=f"{label}_band", visible=(metric == metrics[0]),
            ))
            n_added += 1
            # P50 line
            fig.add_trace(go.Scatter(
                x=sub["time"], y=sub["p50"],
                mode="lines+markers",
                marker=dict(size=5),
                line=dict(color=colour, width=2),
                name=label,
                hovertemplate=(
                    f"<b>{label}</b><br>time: %{{x}}<br>"
                    "P50: %{y:.3g}<extra></extra>"
                ),
                visible=(metric == metrics[0]),
            ))
            n_added += 1
        traces_per_metric.append(n_added)

    # Build dropdown buttons that toggle which contiguous block of traces
    # is visible.
    total_traces = sum(traces_per_metric)
    buttons: list[dict] = []
    offsets = np.cumsum([0] + traces_per_metric).tolist()
    for i, metric in enumerate(metrics):
        visibility = [False] * total_traces
        for k in range(offsets[i], offsets[i + 1]):
            visibility[k] = True
        buttons.append(dict(
            label=str(metric),
            method="update",
            args=[
                {"visible": visibility},
                {"title": f"Interactive ablation — {metric}"},
            ],
        ))
    fig.update_layout(
        updatemenus=[dict(
            active=0, buttons=buttons, direction="down",
            x=0.0, xanchor="left", y=1.15, yanchor="top",
            bgcolor="#f4f4f4", bordercolor="#888",
        )],
        title=f"Interactive ablation — {metrics[0]}",
        xaxis_title="time (year-end)",
        yaxis_title="field-total quantile",
        template="plotly_white",
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#1a1a1a"),
        legend=dict(bgcolor="rgba(255,255,255,0.85)"),
        margin=dict(t=110),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="#e0e0e0")
    fig.update_yaxes(gridcolor="#e0e0e0")
    return _write_with_light_theme(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# C3 — interactive parallel-coordinates θ-explorer
# ──────────────────────────────────────────────────────────────────────────


def interactive_theta_explorer(
    theta_prior_npy: Path,
    theta_post_npy: Path,
    cluster_ids_npy: Path,
    out_path: Path,
    theta_names: list[str] | None = None,
) -> Path:
    """Parallel-coordinates plot of θ with cluster colours; toggle prior vs post."""
    Z_prior = np.load(theta_prior_npy)
    Z_post = np.load(theta_post_npy)
    cluster_ids = np.load(cluster_ids_npy)
    n_z = Z_prior.shape[1]
    names = theta_names or [f"θ{i}" for i in range(n_z)]

    def _make_parcoord(Z: np.ndarray, label: str) -> go.Parcoords:
        dims = []
        for j, nm in enumerate(names):
            dims.append(dict(
                range=[float(Z[:, j].min()), float(Z[:, j].max())],
                label=nm,
                values=Z[:, j].tolist(),
            ))
        colorscale = [
            [0.0, CLUSTER_COLORS[0]],
            [0.5, CLUSTER_COLORS[1]],
            [1.0, CLUSTER_COLORS[2]],
        ]
        return go.Parcoords(
            line=dict(color=cluster_ids.astype(float).tolist(),
                      colorscale=colorscale, showscale=True,
                      colorbar=dict(title="cluster")),
            dimensions=dims,
            name=label,
        )

    fig = go.Figure()
    fig.add_trace(_make_parcoord(Z_prior, "prior"))
    fig.add_trace(_make_parcoord(Z_post, "posterior"))
    # Plotly Parcoords can't be hidden via simple visibility on the same Figure
    # the way Scatter can — they each take the full figure area. We therefore
    # write two separate divs using subplots-like layout (top half / bottom half)
    # with shared annotations.
    fig.data[0].domain = dict(x=[0.0, 1.0], y=[0.58, 1.0])
    fig.data[1].domain = dict(x=[0.0, 1.0], y=[0.0, 0.42])
    fig.update_layout(
        title="θ explorer — prior (top) vs posterior (bottom)",
        annotations=[
            dict(text="<b>θ_prior</b>", x=0.5, y=1.06, xref="paper", yref="paper",
                 showarrow=False, font=dict(size=12)),
            dict(text="<b>θ_posterior</b>", x=0.5, y=0.48, xref="paper", yref="paper",
                 showarrow=False, font=dict(size=12)),
        ],
        template="plotly_white",
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#1a1a1a"),
        height=720,
        margin=dict(t=90),
    )
    return _write_with_light_theme(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# C1 polish — σ-shift hover on existing cluster3_diagnostic.html
# ──────────────────────────────────────────────────────────────────────────


def polish_cluster3_hover(
    migration_csv: Path,
    out_path: Path,
) -> Path:
    """Rebuild cluster3_diagnostic.html with richer hover (σ-shift).

    Mirrors `cmp_ensemble.qc.cluster_migration.render_cluster_migration_html`
    but adds a hover line that quantifies the prior→posterior shift in units of
    |prior centroid|. Kept in this module so callers can choose between the
    plain and the σ-aware renderer.
    """
    df = pd.read_csv(migration_csv)
    clusters = sorted(df["cluster"].unique())
    components = list(df["component"].drop_duplicates())

    from plotly.subplots import make_subplots
    fig = make_subplots(
        rows=len(clusters), cols=1,
        subplot_titles=[f"Cluster {c}" for c in clusters],
        shared_xaxes=False,
    )
    seen_labels: set[str] = set()
    for row, cl in enumerate(clusters, start=1):
        sub = df[df["cluster"] == cl].set_index("component").loc[components]

        def _hover(values: np.ndarray, kind: str) -> list[str]:
            """Hover lines including the σ-shift relative to |prior centroid|."""
            out = []
            for comp, v in zip(components, values):
                p = float(sub.loc[comp, "prior_centroid"])
                q = float(sub.loc[comp, "post_centroid"])
                r = float(sub.loc[comp, "reference"]) if not np.isnan(
                    sub.loc[comp, "reference"]) else None
                pct = ((q - p) / p * 100) if abs(p) > 1e-12 else 0.0
                ref_str = "" if r is None else f"<br>reference: {r:.4g}"
                out.append(
                    f"<b>{comp}</b><br>{kind}: {v:.4g}{ref_str}"
                    f"<br>prior→post shift: {pct:+.2f}% of |prior|"
                )
            return out

        if not sub["reference"].isna().all():
            ref_vals = sub["reference"].to_numpy(dtype=float)
            fig.add_trace(go.Bar(
                name="reference centroid", x=components, y=ref_vals,
                marker_color="#888888",
                hovertext=_hover(ref_vals, "reference"),
                hoverinfo="text",
                showlegend=("reference centroid" not in seen_labels),
            ), row=row, col=1)
            seen_labels.add("reference centroid")
        pri_vals = sub["prior_centroid"].to_numpy(dtype=float)
        pst_vals = sub["post_centroid"].to_numpy(dtype=float)
        fig.add_trace(go.Bar(
            name="prior centroid", x=components, y=pri_vals,
            marker_color="#1f77b4",
            hovertext=_hover(pri_vals, "prior"),
            hoverinfo="text",
            showlegend=("prior centroid" not in seen_labels),
        ), row=row, col=1)
        seen_labels.add("prior centroid")
        fig.add_trace(go.Bar(
            name="posterior centroid", x=components, y=pst_vals,
            marker_color="#d62728",
            hovertext=_hover(pst_vals, "posterior"),
            hoverinfo="text",
            showlegend=("posterior centroid" not in seen_labels),
        ), row=row, col=1)
        seen_labels.add("posterior centroid")

    fig.update_layout(
        title="Cluster centroid migration — interactive (σ-shift in hover)",
        barmode="group", height=300 * len(clusters),
        template="plotly_white",
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#1a1a1a"),
    )
    fig.update_xaxes(gridcolor="#e0e0e0", tickfont=dict(color="#1a1a1a"))
    fig.update_yaxes(gridcolor="#e0e0e0", tickfont=dict(color="#1a1a1a"))
    return _write_with_light_theme(fig, out_path)


# ──────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────


def render_all_tier_c(root: Path) -> dict[str, Path]:
    """Render the 2 Tier C interactive figures from existing outputs/.

    The C1 polish writes to a separate file `cluster3_diagnostic_hover.html`
    so the plain plotly diagnostic (rendered by Phase 1 via
    qc/cluster_migration.py) is preserved.
    """
    out_root = root / "outputs"
    out_dir = out_root / "qc"
    out_dir.mkdir(parents=True, exist_ok=True)
    forecast_dir = out_root / "forecast"
    matrices = out_root / "matrices"

    plan: list[tuple[str, callable]] = [
        ("interactive_ablation", lambda: interactive_ablation(
            {
                "setup1_naive":
                    forecast_dir / "setup1_naive_field_total_quantiles.csv",
                "setup2_localized":
                    forecast_dir / "setup2_localized_field_total_quantiles.csv",
                "setup3_full":
                    forecast_dir / "setup3_full_field_total_quantiles.csv",
            },
            out_dir / "interactive_ablation.html",
        )),
        ("interactive_theta_explorer", lambda: interactive_theta_explorer(
            matrices / "theta_prior.npy",
            matrices / "theta_post.npy",
            matrices / "cluster_ids.npy",
            out_dir / "interactive_theta_explorer.html",
            ["THICK", "MAJ_R", "AZIMUTH", "NUMBER_CHANNELS", "CHANNELS_WIDTH",
             "LEN", "AMPLITUDE", "RELATIVE", "PROP"],
        )),
        ("cluster3_diagnostic_hover", lambda: polish_cluster3_hover(
            out_dir / "cluster_migration.csv",
            out_dir / "cluster3_diagnostic_hover.html",
        )),
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

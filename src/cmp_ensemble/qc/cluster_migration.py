"""Cluster centroid migration diagnostic (Task 1.4).

Generates an interactive plotly HTML showing, for each cluster:
  - The reference centroid (`Адаптированный центроид →` row from
    `models_near_adapted_centroids.xlsx` — stored in `configs/theta_schema.yaml`)
  - The ensemble prior centroid (mean of the 50 cluster members in θ-space)
  - The ensemble posterior centroid (after ES update)

The reference centroid is the starting point all 50 members inherit during
adaptation. If the ES update moves the cluster centroid away from the
reference, that quantifies how much the ensemble re-conditions on the data.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

log = logging.getLogger(__name__)


def build_cluster_migration_table(
    Z_prior: np.ndarray,
    Z_post: np.ndarray,
    cluster_ids: np.ndarray,
    theta_names: list[str],
    reference_centroids: dict[int, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Long-format table: one row per (cluster × component) with prior/post means.

    `reference_centroids` is the dictionary from `configs/theta_schema.yaml`
    ``cluster_centroids``. Missing entries are filled with NaN.
    """
    rows = []
    for cl in sorted({int(c) for c in cluster_ids.tolist()}):
        idx = cluster_ids == cl
        prior_mean = Z_prior[idx].mean(axis=0)
        post_mean = Z_post[idx].mean(axis=0)
        ref = (reference_centroids or {}).get(cl, {})
        for j, name in enumerate(theta_names):
            rows.append(
                {
                    "cluster": cl,
                    "component": name,
                    "reference": float(ref.get(name, np.nan)),
                    "prior_centroid": float(prior_mean[j]),
                    "post_centroid": float(post_mean[j]),
                    "delta_prior_to_post": float(post_mean[j] - prior_mean[j]),
                    "delta_ref_to_prior": float(
                        prior_mean[j] - ref.get(name, np.nan)
                    )
                    if name in ref
                    else np.nan,
                    "delta_ref_to_post": float(
                        post_mean[j] - ref.get(name, np.nan)
                    )
                    if name in ref
                    else np.nan,
                }
            )
    return pd.DataFrame(rows)


def render_cluster_migration_html(
    table: pd.DataFrame,
    out_path: Path,
    title: str = "Cluster centroid migration (ТЗ Task 1.4)",
) -> None:
    """Render a per-cluster bar comparison of reference / prior / posterior."""
    clusters = sorted(table["cluster"].unique())
    components = list(table["component"].drop_duplicates())
    fig = make_subplots(
        rows=len(clusters), cols=1,
        subplot_titles=[f"Cluster {c}" for c in clusters],
        shared_xaxes=False,
    )
    for row, cl in enumerate(clusters, start=1):
        sub = table[table["cluster"] == cl].set_index("component").loc[components]
        if not sub["reference"].isna().all():
            fig.add_trace(
                go.Bar(name="reference centroid", x=components,
                       y=sub["reference"], marker_color="#888"),
                row=row, col=1,
            )
        fig.add_trace(
            go.Bar(name="prior centroid", x=components,
                   y=sub["prior_centroid"], marker_color="#1f77b4"),
            row=row, col=1,
        )
        fig.add_trace(
            go.Bar(name="posterior centroid", x=components,
                   y=sub["post_centroid"], marker_color="#d62728"),
            row=row, col=1,
        )

    # avoid duplicated legend entries across subplots
    seen = set()
    for tr in fig.data:
        if tr.name in seen:
            tr.showlegend = False
        else:
            seen.add(tr.name)
    fig.update_layout(
        title=title,
        height=300 * len(clusters),
        barmode="group",
        template="plotly_white",
        # Force a fully white canvas so the figure never picks up a dark theme
        # from the browser / OS even if plotly_white CDN gets a default override.
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#1a1a1a"),
    )
    fig.update_xaxes(gridcolor="#e0e0e0", zerolinecolor="#bbbbbb",
                     tickfont=dict(color="#1a1a1a"))
    fig.update_yaxes(gridcolor="#e0e0e0", zerolinecolor="#bbbbbb",
                     tickfont=dict(color="#1a1a1a"))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Wrap the plotly output so we can force light-mode at the HTML level too.
    html = fig.to_html(include_plotlyjs="cdn", full_html=True)
    light_head = (
        '<meta name="color-scheme" content="light only">\n'
        '<style>\n'
        '  :root { color-scheme: light; }\n'
        '  html, body { background: #ffffff !important; color: #1a1a1a !important; }\n'
        '  @media (prefers-color-scheme: dark) {\n'
        '    html, body { background: #ffffff !important; color: #1a1a1a !important; }\n'
        '  }\n'
        '</style>\n'
    )
    html = html.replace("<head>", "<head>\n" + light_head, 1)
    out_path.write_text(html, encoding="utf-8")
    log.info(f"cluster migration diagnostic written to {out_path}")

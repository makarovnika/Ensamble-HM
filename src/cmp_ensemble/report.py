"""Assemble the project-level HTML report (ТЗ §8 + §11).

Two HTML files are written:

  * ``outputs/report.html``        — top-level project rollup. Sections for
                                     each phase + figures + summary metrics.
  * ``outputs/qc/qc_report.html``  — Phase 1 QC summary: spread retention,
                                     rank, Mahalanobis migration histogram,
                                     bimodality coefficient, cluster centroid
                                     shift, physical-bounds violations,
                                     duplicate-model summary.

Both files are self-contained relative to ``outputs/`` — every link is
relative, so the directory can be copied or zipped and the report still
works. Bulky tables are not embedded; we link to them.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from jinja2 import Environment

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _read_csv_if_exists(path: Path) -> pd.DataFrame | None:
    if not _exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception as exc:
        log.warning(f"could not read {path}: {exc}")
        return None


def _read_json_if_exists(path: Path) -> dict | None:
    if not _exists(path):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(f"could not read {path}: {exc}")
        return None


def _relpath(target: Path, anchor: Path) -> str:
    """POSIX-style relative path from `anchor` to `target` (browser-friendly)."""
    try:
        return Path(target).resolve().relative_to(anchor.resolve()).as_posix()
    except ValueError:
        import os

        return os.path.relpath(target, start=anchor).replace("\\", "/")


def _df_to_html(df: pd.DataFrame | None, max_rows: int | None = 50) -> str:
    if df is None or df.empty:
        return "<p class='muted'><em>not available</em></p>"
    view = df if max_rows is None or len(df) <= max_rows else df.head(max_rows)
    html = view.to_html(index=False, classes="rep-table", border=0,
                       float_format=lambda x: f"{x:.4g}")
    if max_rows is not None and len(df) > max_rows:
        html += f"<p class='muted'><em>showing first {max_rows} of {len(df)} rows</em></p>"
    return html


# ──────────────────────────────────────────────────────────────────────────
# Template strings
# ──────────────────────────────────────────────────────────────────────────


_BASE_CSS = """
<meta name="color-scheme" content="light only">
<style>
  /* Force light theme regardless of OS / browser dark-mode preference. */
  :root { color-scheme: light; }
  html, body { background: #ffffff; }
  body { font-family: -apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
         color: #1a1a1a; max-width: 1100px; margin: 2em auto; padding: 0 1em;
         line-height: 1.5; }
  h1, h2, h3 { color: #111; }
  h1 { border-bottom: 2px solid #2b2b2b; padding-bottom: 0.3em; }
  h2 { margin-top: 1.6em; border-bottom: 1px solid #d4d4d4; padding-bottom: 0.2em; }
  h3 { margin-top: 1.2em; color: #333; }
  .meta { color: #5a5a5a; font-size: 0.88em; margin-bottom: 1.6em; }
  .muted { color: #777; font-style: italic; }
  .kv { display: grid; grid-template-columns: 14em 1fr; gap: 0.2em 0.8em;
        font-size: 0.92em; margin: 0.6em 0 1em 0; }
  .kv dt { font-weight: 600; color: #444; }
  .kv dd { margin: 0; color: #1a1a1a; }
  .rep-table { background: #ffffff; color: #1a1a1a;
               border-collapse: collapse; margin: 0.8em 0; font-size: 0.86em; }
  .rep-table th, .rep-table td { padding: 4px 9px; text-align: right;
                                   border-bottom: 1px solid #e0e0e0; }
  .rep-table th { background: #f4f4f4; color: #222; border-bottom: 2px solid #aaa;
                   text-align: left; }
  .rep-table tr:nth-child(even) td { background: #fafafa; }
  .rep-table td:first-child, .rep-table th:first-child { text-align: left; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
           font-size: 0.78em; font-weight: 600; }
  .badge.pass { background: #d4edda; color: #155724; }
  .badge.warn { background: #fff3cd; color: #856404; }
  .badge.fail { background: #f8d7da; color: #721c24; }
  .badge.info { background: #d1ecf1; color: #0c5460; }
  .fig { margin: 1em 0; text-align: center; }
  .fig img { max-width: 100%; height: auto; border: 1px solid #ddd;
              border-radius: 4px; background: #ffffff; }
  .fig figcaption { color: #555; font-size: 0.86em; margin-top: 0.3em; }
  ul.compact { margin: 0.3em 0; padding-left: 1.4em; }
  ul.compact li { margin: 0.15em 0; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2em; }
  a { color: #1a5fb4; }
  a:visited { color: #6f42c1; }
  pre, code { color: #1a1a1a; }
  pre { background: #f5f5f5; padding: 0.8em; border-radius: 4px;
        overflow-x: auto; font-size: 0.85em; }
  code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px;
         font-size: 0.9em; }
  /* Hard-override any user-agent dark-mode adjustments. */
  @media (prefers-color-scheme: dark) {
    html, body { background: #ffffff !important; color: #1a1a1a !important; }
    .rep-table tr:nth-child(even) td { background: #fafafa !important; }
    .rep-table th { background: #f4f4f4 !important; color: #222 !important; }
  }
</style>
"""


_MAIN_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CMP Ensemble HM — Project Report</title>
""" + _BASE_CSS + """
</head>
<body>
<h1>CMP Ensemble HM — Project Report</h1>
<p class="meta">
  Generated {{ generated_at }}
  &nbsp;·&nbsp; git&nbsp;<code>{{ git_sha[:10] }}</code>{% if git_dirty %} <span class="badge warn">dirty</span>{% endif %}
  &nbsp;·&nbsp; <a href="{{ qc_report_rel }}">QC report</a>
  {% if tz_link %}&nbsp;·&nbsp; <a href="{{ tz_link }}">ТЗ</a>{% endif %}
</p>

<h2>Overview</h2>
<dl class="kv">
  <dt>Ensemble size N</dt><dd>{{ N }}</dd>
  <dt>n_θ</dt><dd>{{ n_theta }} ({{ theta_names | join(", ") }})</dd>
  <dt>Wells</dt><dd>{{ n_producers }} producers + {{ n_injectors }} injectors</dd>
  <dt>Time grid</dt><dd>{{ time_min }} → {{ time_max }} ({{ n_time_steps }} monthly steps)</dd>
  <dt>Forecast horizon</dt><dd>{{ forecast_period or "no forecast loaded" }}</dd>
  <dt>Evaluation mode</dt><dd><span class="badge info">{{ evaluation_mode }}</span></dd>
</dl>

<h2>Phase 0 — Data ingest</h2>
<dl class="kv">
  <dt>θ_prior</dt><dd>shape {{ theta_prior_shape }} · <a href="{{ paths.theta_prior }}">theta_prior.npy</a></dd>
  <dt>d_sim_cum</dt><dd>shape {{ d_sim_cum_shape }} · <a href="{{ paths.d_sim_cum }}">d_sim_cum.npy</a></dd>
  <dt>d_obs_cum</dt><dd>shape {{ d_obs_cum_shape }} · <a href="{{ paths.d_obs_cum }}">d_obs_cum.npy</a></dd>
  <dt>C_dd_cum diag</dt><dd>shape {{ c_dd_cum_shape }} · <a href="{{ paths.C_dd_cum }}">C_dd_cum_diag.npy</a></dd>
</dl>

<h2>Phase 1 — ES update + QC</h2>
<p>
  Subspace truncation kept <strong>{{ subspace_r }}/{{ subspace_total }}</strong> components
  (energy = {{ subspace_energy }}). Localization with factor =
  {{ localization_factor }}, method = <code>{{ localization_method }}</code>,
  kept <strong>{{ loc_kept }}/{{ loc_total }}</strong> K-entries ({{ loc_kept_pct }}%).
</p>
<dl class="kv">
  <dt>QC verdict</dt><dd>{% if qc_passed %}<span class="badge pass">PASSED</span>{% else %}<span class="badge fail">FAILED</span>{% endif %}</dd>
  <dt>rank_prior / rank_post</dt><dd>{{ rank_prior }} / {{ rank_post }}</dd>
  <dt>bimodality coefficient</dt><dd>{{ bimodality_score }} ({% if bc_warning %}<span class="badge warn">bimodal</span>{% else %}<span class="badge pass">unimodal</span>{% endif %})</dd>
  <dt>collapse / blow-up components</dt><dd>{{ n_collapse }} / {{ n_blowup }}</dd>
  <dt>out-of-prior θ_post entries</dt><dd>{{ n_oob }}</dd>
  <dt>duplicate model_ids</dt><dd>{{ n_duplicates }}</dd>
</dl>

<h3>Spread retention per θ component</h3>
{{ spread_retention_html | safe }}

<div class="fig">
  <a href="{{ paths.fig02 }}"><img src="{{ paths.fig02 }}" alt="QC spread retention"></a>
  <figcaption>fig02 — σ_post / σ_prior per θ component (Phase 1 QC).</figcaption>
</div>

<h2>Phase 2 — Selection + linear proxy</h2>
<dl class="kv">
  <dt>Mahalanobis ranking</dt><dd>{{ ranking_n }} models · <a href="{{ paths.ranking }}">mahalanobis_ranking.csv</a></dd>
  <dt>Top-X to re-simulate</dt><dd>{{ resim_n }} · <a href="{{ paths.resim }}">models_to_resimulate.csv</a></dd>
  <dt>Proxy pool</dt><dd>{{ proxy_n }} · <a href="{{ paths.proxy_pool }}">models_proxy.csv</a></dd>
  <dt>Validation subset</dt><dd>{{ val_n }} · <a href="{{ paths.val_subset }}">validation_subset.csv</a></dd>
  <dt>Proxy verdict</dt><dd>{% if proxy_verdict %}<span class="badge {{ proxy_verdict_class }}">{{ proxy_verdict }}</span> median rel err = {{ proxy_median_err }}{% else %}<em>not run</em>{% endif %}</dd>
</dl>

<h3>Proxy validation — per cluster</h3>
{{ proxy_val_html | safe }}

<h2>Phase 3 — Ablation forecast</h2>
<p>Evaluation mode: <span class="badge info">{{ evaluation_mode }}</span></p>

<h3>Metrics summary</h3>
{{ metrics_summary_html | safe }}

<div class="grid2">
  <div class="fig">
    <a href="{{ paths.fig03 }}"><img src="{{ paths.fig03 }}" alt="Ablation P10-P90"></a>
    <figcaption>fig03 — Field-total cumulative P10/P50/P90 per setup.</figcaption>
  </div>
  <div class="fig">
    <a href="{{ paths.fig04 }}"><img src="{{ paths.fig04 }}" alt="Cumulative scatter"></a>
    <figcaption>fig04 — End-of-forecast field cumulative per model.</figcaption>
  </div>
</div>

<h2>All figures</h2>
<ul class="compact">
  {% for f in figures %}<li><a href="{{ f.rel }}">{{ f.name }}</a></li>{% endfor %}
</ul>

<h2>Pipeline diagram</h2>
<div class="fig">
  <a href="{{ paths.fig01 }}"><img src="{{ paths.fig01 }}" alt="Pipeline diagram"></a>
  <figcaption>fig01 — Block diagram of Phases 0–3.</figcaption>
</div>

<h2>Cluster centroid migration</h2>
<div class="fig">
  <a href="{{ paths.fig06 }}"><img src="{{ paths.fig06 }}" alt="Cluster migration"></a>
  <figcaption>fig06 — Reference / prior / posterior centroid per cluster × θ component.</figcaption>
</div>

<h2>Article assets</h2>
<ul class="compact">
  <li><a href="{{ paths.tex }}">ablation_table.tex</a></li>
  <li><a href="{{ paths.figures_v2 }}">figures_v2/</a> — manuscript-ready copies</li>
</ul>
</body>
</html>
"""


_QC_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Phase 1 QC report</title>
""" + _BASE_CSS + """
</head>
<body>
<h1>Phase 1 QC report</h1>
<p class="meta">
  Generated {{ generated_at }}
  &nbsp;·&nbsp; <a href="{{ main_report_rel }}">← project report</a>
</p>

<dl class="kv">
  <dt>Verdict</dt><dd>{% if qc_passed %}<span class="badge pass">PASSED</span>{% else %}<span class="badge fail">FAILED</span>{% endif %}</dd>
  <dt>N</dt><dd>{{ N }} ensemble members</dd>
  <dt>rank_prior / rank_post</dt><dd>{{ rank_prior }} / {{ rank_post }}</dd>
  <dt>bimodality coefficient</dt><dd>{{ bimodality_score }}</dd>
  <dt>collapse / blow-up components</dt><dd>{{ n_collapse }} / {{ n_blowup }}</dd>
</dl>

<h2>Spread retention</h2>
{{ spread_retention_html | safe }}

<h2>Cluster centroid shift</h2>
{{ cluster_centroid_html | safe }}

<h2>Mahalanobis migration histogram</h2>
<p>min = {{ maha_min }}, median = {{ maha_median }}, max = {{ maha_max }}</p>
{{ maha_summary_html | safe }}

<h2>Physical-bounds violations</h2>
{{ physical_bounds_html | safe }}

<h2>Duplicate-model summary</h2>
<p>{{ n_duplicates }} model_ids appear in multiple cluster rows
   (same θ_prior, different θ_post copies from ε perturbations).</p>
{{ duplicates_html | safe }}

<h2>Messages</h2>
{% if messages %}
<ul class="compact">
  {% for lvl, msg in messages %}
    <li><span class="badge {{ lvl|lower }}">{{ lvl }}</span> {{ msg }}</li>
  {% endfor %}
</ul>
{% else %}
<p class="muted">no messages</p>
{% endif %}
</body>
</html>
"""


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────


def build_report(root: Path) -> dict[str, Path]:
    """Render outputs/report.html and outputs/qc/qc_report.html.

    Returns a dict {"main": path, "qc": path} of the two HTML files.
    """
    root = Path(root).resolve()
    out_root = root / "outputs"
    qc_dir = out_root / "qc"
    matrices_dir = out_root / "matrices"
    selection_dir = out_root / "selection"
    forecast_dir = out_root / "forecast"
    figures_dir = out_root / "figures"
    article_assets_dir = out_root / "article_assets"
    main_html = out_root / "report.html"
    qc_html = qc_dir / "qc_report.html"

    # ── Gather Phase 0 + Phase 1 data ───────────────────────────────────────
    import numpy as np

    theta_prior = np.load(matrices_dir / "theta_prior.npy") if _exists(matrices_dir / "theta_prior.npy") else None
    d_sim_cum = np.load(matrices_dir / "d_sim_cum.npy") if _exists(matrices_dir / "d_sim_cum.npy") else None
    d_obs_cum = np.load(matrices_dir / "d_obs_cum.npy") if _exists(matrices_dir / "d_obs_cum.npy") else None
    c_dd_cum_diag = (
        np.load(matrices_dir / "C_dd_cum_diag.npy")
        if _exists(matrices_dir / "C_dd_cum_diag.npy") else None
    )

    spread_df = _read_csv_if_exists(qc_dir / "spread_retention.csv")
    centroid_df = _read_csv_if_exists(qc_dir / "cluster_centroid_shift.csv")
    maha_df = _read_csv_if_exists(qc_dir / "mahalanobis_migration.csv")
    rank_json = _read_json_if_exists(qc_dir / "rank_check.json")
    bounds_df = _read_csv_if_exists(qc_dir / "physical_bounds_violations.csv")
    duplicates_df = _read_csv_if_exists(qc_dir / "duplicate_models.csv")

    ranking_df = _read_csv_if_exists(selection_dir / "mahalanobis_ranking.csv")
    resim_df = _read_csv_if_exists(selection_dir / "models_to_resimulate.csv")
    proxy_pool_df = _read_csv_if_exists(selection_dir / "models_proxy.csv")
    val_subset_df = _read_csv_if_exists(selection_dir / "validation_subset.csv")
    proxy_val_df = _read_csv_if_exists(selection_dir / "proxy_validation_per_cluster.csv")
    proxy_val_agg = _read_csv_if_exists(selection_dir / "proxy_validation_aggregate.csv")

    summary_df = _read_csv_if_exists(forecast_dir / "metrics_summary.csv")

    # ── Pull side-car for evaluation_mode / git sha ─────────────────────────
    from cmp_ensemble.metadata import _git_sha, _git_dirty
    git_sha = _git_sha(root)
    git_dirty = _git_dirty(root)
    evaluation_mode = "unknown"
    if summary_df is not None and "evaluation_mode" in summary_df.columns:
        modes = summary_df["evaluation_mode"].dropna().unique().tolist()
        if modes:
            evaluation_mode = str(modes[0])

    # ── Compute high-level numbers ──────────────────────────────────────────
    N = int(theta_prior.shape[0]) if theta_prior is not None else 0
    n_theta = int(theta_prior.shape[1]) if theta_prior is not None else 0
    # θ names: try a config
    theta_names: list[str] = []
    try:
        from cmp_ensemble.config import load_theta_schema
        ts = load_theta_schema(root)
        theta_names = [p["name"] for p in ts.get("parameters", [])]
    except Exception:
        theta_names = []

    # Producer / injector counts from well_layout config
    n_producers = n_injectors = 0
    try:
        from cmp_ensemble.config import load_well_layout
        wl = load_well_layout(root)
        n_producers = len(wl.get("producers", []))
        n_injectors = len(wl.get("injectors", []))
    except Exception:
        pass

    # Time grid
    time_min = time_max = "-"
    n_time_steps = 0
    try:
        import h5py
        cache = root / "outputs" / "cache" / "ensemble.h5"
        if cache.exists():
            with h5py.File(cache, "r") as f:
                ts_raw = f["time_steps"][:].astype("datetime64[ns]")
                time_min = pd.Timestamp(ts_raw[0]).date().isoformat()
                time_max = pd.Timestamp(ts_raw[-1]).date().isoformat()
                n_time_steps = int(ts_raw.size)
    except Exception:
        pass

    # Forecast horizon (from forecast cache)
    forecast_period = None
    try:
        import h5py
        fcache = root / "outputs" / "cache" / "forecast.h5"
        if fcache.exists():
            with h5py.File(fcache, "r") as f:
                fts = f["forecast_time_steps"][:].astype("datetime64[ns]")
                m_count = int(f["model_ids"].shape[0])
                forecast_period = (
                    f"{pd.Timestamp(fts[0]).date()} → {pd.Timestamp(fts[-1]).date()} "
                    f"({fts.size} steps, {m_count} models)"
                )
    except Exception:
        pass

    # Phase 1 numerics
    subspace_r = subspace_total = "-"
    subspace_energy = "-"
    if _exists(matrices_dir / "singular_values.npy"):
        sv = np.load(matrices_dir / "singular_values.npy")
        subspace_total = int(sv.size)
        cum_energy = np.cumsum(sv**2) / max(np.sum(sv**2), 1e-30)
        r = int(np.searchsorted(cum_energy, 0.99)) + 1
        subspace_r = min(r, subspace_total)
        subspace_energy = f"{float(cum_energy[subspace_r - 1]):.4f}"

    loc_kept = loc_total = 0
    loc_kept_pct = "-"
    if _exists(matrices_dir / "locmask.npy"):
        m = np.load(matrices_dir / "locmask.npy")
        loc_kept = int((m > 0).sum())
        loc_total = int(m.size)
        loc_kept_pct = f"{100 * loc_kept / max(loc_total, 1):.2f}"

    # QC summary
    qc_passed = True
    rank_prior = rank_post = "-"
    bc = "-"
    bc_warning = False
    n_collapse = n_blowup = 0
    messages: list[tuple[str, str]] = []
    if rank_json is not None:
        qc_passed = bool(rank_json.get("passed", True))
        rank_prior = rank_json.get("rank_prior", "-")
        rank_post = rank_json.get("rank_post", "-")
        bc_v = rank_json.get("bimodality_score")
        bc = f"{bc_v:.3f}" if isinstance(bc_v, (float, int)) else "-"
        bc_warning = isinstance(bc_v, (float, int)) and bc_v > 0.3
        n_collapse = int(rank_json.get("n_collapse_components", 0))
        n_blowup = int(rank_json.get("n_blowup_components", 0))
        for m in rank_json.get("messages", []):
            messages.append((str(m.get("level", "INFO")), str(m.get("text", ""))))

    # Bounds / duplicates counts
    n_oob = int(bounds_df["n_out_of_bounds"].sum()) if bounds_df is not None and "n_out_of_bounds" in bounds_df else 0
    n_duplicates = int(len(duplicates_df)) if duplicates_df is not None else 0

    # Proxy verdict
    proxy_verdict = None
    proxy_verdict_class = "info"
    proxy_median_err = "-"
    if proxy_val_agg is not None:
        try:
            median_err = float(
                proxy_val_agg.set_index(proxy_val_agg.columns[0]).loc["median_rel_err"].iloc[0]
            )
            proxy_median_err = f"{median_err:.3f}"
            proxy_verdict = "PASS" if median_err < 1.0 else ("WARN" if median_err < 2.0 else "FAIL")
            proxy_verdict_class = {"PASS": "pass", "WARN": "warn", "FAIL": "fail"}[proxy_verdict]
        except Exception:
            pass

    # Figures list
    figures = []
    if figures_dir.exists():
        for f in sorted(figures_dir.glob("fig*.png")):
            figures.append({"name": f.name, "rel": _relpath(f, out_root)})

    # ── Render main report ─────────────────────────────────────────────────
    env = Environment(autoescape=True)
    paths = {
        "theta_prior": _relpath(matrices_dir / "theta_prior.npy", out_root),
        "d_sim_cum": _relpath(matrices_dir / "d_sim_cum.npy", out_root),
        "d_obs_cum": _relpath(matrices_dir / "d_obs_cum.npy", out_root),
        "C_dd_cum": _relpath(matrices_dir / "C_dd_cum_diag.npy", out_root),
        "ranking": _relpath(selection_dir / "mahalanobis_ranking.csv", out_root),
        "resim": _relpath(selection_dir / "models_to_resimulate.csv", out_root),
        "proxy_pool": _relpath(selection_dir / "models_proxy.csv", out_root),
        "val_subset": _relpath(selection_dir / "validation_subset.csv", out_root),
        "fig01": _relpath(figures_dir / "fig01_pipeline.png", out_root),
        "fig02": _relpath(figures_dir / "fig02_qc_spread.png", out_root),
        "fig03": _relpath(figures_dir / "fig03_ablation_p10p90.png", out_root),
        "fig04": _relpath(figures_dir / "fig04_cumulative_scatter.png", out_root),
        "fig06": _relpath(figures_dir / "fig06_cluster3_migration.png", out_root),
        "tex": _relpath(article_assets_dir / "ablation_table.tex", out_root),
        "figures_v2": _relpath(article_assets_dir / "figures_v2", out_root),
    }
    main_tpl = env.from_string(_MAIN_TEMPLATE)
    main_rendered = main_tpl.render(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        git_sha=git_sha,
        git_dirty=git_dirty,
        qc_report_rel="qc/qc_report.html",
        tz_link="../TZ_ensemble_forecast.md" if (root / "TZ_ensemble_forecast.md").exists() else None,
        N=N,
        n_theta=n_theta,
        theta_names=theta_names,
        n_producers=n_producers,
        n_injectors=n_injectors,
        time_min=time_min,
        time_max=time_max,
        n_time_steps=n_time_steps,
        forecast_period=forecast_period,
        evaluation_mode=evaluation_mode,
        theta_prior_shape=str(theta_prior.shape) if theta_prior is not None else "-",
        d_sim_cum_shape=str(d_sim_cum.shape) if d_sim_cum is not None else "-",
        d_obs_cum_shape=str(d_obs_cum.shape) if d_obs_cum is not None else "-",
        c_dd_cum_shape=str(c_dd_cum_diag.shape) if c_dd_cum_diag is not None else "-",
        subspace_r=subspace_r,
        subspace_total=subspace_total,
        subspace_energy=subspace_energy,
        localization_factor=3.0,
        localization_method="hard",
        loc_kept=loc_kept,
        loc_total=loc_total,
        loc_kept_pct=loc_kept_pct,
        qc_passed=qc_passed,
        rank_prior=rank_prior,
        rank_post=rank_post,
        bimodality_score=bc,
        bc_warning=bc_warning,
        n_collapse=n_collapse,
        n_blowup=n_blowup,
        n_oob=n_oob,
        n_duplicates=n_duplicates,
        spread_retention_html=_df_to_html(spread_df, max_rows=None),
        ranking_n=len(ranking_df) if ranking_df is not None else 0,
        resim_n=len(resim_df) if resim_df is not None else 0,
        proxy_n=len(proxy_pool_df) if proxy_pool_df is not None else 0,
        val_n=len(val_subset_df) if val_subset_df is not None else 0,
        proxy_verdict=proxy_verdict,
        proxy_verdict_class=proxy_verdict_class,
        proxy_median_err=proxy_median_err,
        proxy_val_html=_df_to_html(proxy_val_df, max_rows=None),
        metrics_summary_html=_df_to_html(summary_df, max_rows=None),
        figures=figures,
        paths=paths,
    )
    main_html.parent.mkdir(parents=True, exist_ok=True)
    main_html.write_text(main_rendered, encoding="utf-8")

    # ── Render QC report ───────────────────────────────────────────────────
    maha_min = maha_max = maha_median = "-"
    if maha_df is not None and "maha" in maha_df.columns:
        maha_min = f"{maha_df['maha'].min():.3f}"
        maha_max = f"{maha_df['maha'].max():.3f}"
        maha_median = f"{maha_df['maha'].median():.3f}"
    maha_summary_html = _df_to_html(maha_df, max_rows=20) if maha_df is not None else "<p class='muted'><em>not available</em></p>"

    qc_tpl = env.from_string(_QC_TEMPLATE)
    qc_rendered = qc_tpl.render(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        main_report_rel="../report.html",
        qc_passed=qc_passed,
        N=N,
        rank_prior=rank_prior,
        rank_post=rank_post,
        bimodality_score=bc,
        n_collapse=n_collapse,
        n_blowup=n_blowup,
        spread_retention_html=_df_to_html(spread_df, max_rows=None),
        cluster_centroid_html=_df_to_html(centroid_df, max_rows=None),
        maha_min=maha_min, maha_median=maha_median, maha_max=maha_max,
        maha_summary_html=maha_summary_html,
        physical_bounds_html=_df_to_html(bounds_df, max_rows=None),
        n_duplicates=n_duplicates,
        duplicates_html=_df_to_html(duplicates_df, max_rows=None),
        messages=messages,
    )
    qc_html.parent.mkdir(parents=True, exist_ok=True)
    qc_html.write_text(qc_rendered, encoding="utf-8")

    log.info(f"report → {main_html}")
    log.info(f"qc report → {qc_html}")
    return {"main": main_html, "qc": qc_html}

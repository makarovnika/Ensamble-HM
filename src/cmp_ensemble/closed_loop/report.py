"""Closed-loop HTML rollup (CL-G, TZ_closed_loop_ESMDA.md section 11).

Self-contained HTML (inline CSS, no jinja2) summarising one closed-loop run:
ES-MDA config, misfit reduction, the three figures (misfit / theta migration /
forecast corridors), and the forecast metric tables. Asset links are POSIX-
relative so the out_root directory is portable as a zip.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CSS = """
:root { color-scheme: light only; }
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem;
       color: #1a1a1a; background: #fff; max-width: 1000px; }
h1 { border-bottom: 2px solid #1f77b4; padding-bottom: .3rem; }
h2 { color: #1f77b4; margin-top: 2rem; }
table { border-collapse: collapse; margin: 1rem 0; font-size: .9rem; }
th, td { border: 1px solid #ccc; padding: .3rem .6rem; text-align: right; }
th { background: #f0f4f8; }
td:first-child, th:first-child { text-align: left; }
img { max-width: 100%; border: 1px solid #eee; margin: .5rem 0; }
.kv { background: #f7f9fb; padding: .8rem 1rem; border-radius: 6px; }
.muted { color: #888; font-style: italic; }
"""


def _csv_to_html_table(path: Path, max_rows: int = 40) -> str:
    if not path.exists():
        return '<p class="muted">not available</p>'
    import pandas as pd

    df = pd.read_csv(path)
    truncated = len(df) > max_rows
    html = df.head(max_rows).to_html(index=False, border=0, float_format=lambda x: f"{x:.4g}")
    if truncated:
        html += f'<p class="muted">… {len(df) - max_rows} more rows in {path.name}</p>'
    return html


def _img(rel: str, root: Path) -> str:
    p = root / rel
    if not p.exists():
        return f'<p class="muted">missing figure: {rel}</p>'
    return f'<img src="{rel}" alt="{rel}"/>'


def build_closed_loop_report(out_root: str | Path) -> Path:
    """Render outputs/closed_loop/report.html from a completed run's artifacts."""
    root = Path(out_root)
    import numpy as np

    misfit_path = root / "misfit_history.npy"
    misfit_line = '<p class="muted">misfit history not available</p>'
    if misfit_path.exists():
        m = np.load(misfit_path)
        red = (1 - m[-1] / m[0]) * 100 if m[0] else 0.0
        misfit_line = (f'<div class="kv">misfit: <b>{m[0]:.4g}</b> → '
                       f'<b>{m[-1]:.4g}</b> ({red:.0f}% reduction over '
                       f'{len(m) - 1} ES-MDA steps)</div>')

    sidecar = root / "Theta_post.npy.meta.yaml"
    meta_html = '<p class="muted">no sidecar</p>'
    if sidecar.exists():
        meta_html = f"<pre>{sidecar.read_text(encoding='utf-8')}</pre>"

    fc = root / "forecast"
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Closed-loop ES-MDA report</title><style>{_CSS}</style></head><body>
<h1>Closed-loop pure-ensemble ES-MDA — run report</h1>
<p>Pure-ensemble history matching via ES-MDA (TZ_closed_loop_ESMDA.md). Posterior
parameter ensemble assimilated against annual cumulative oil/water/gas.</p>

<h2>Assimilation</h2>
{misfit_line}
<h3>ES-MDA misfit evolution</h3>
{_img('figures/misfit_evolution.png', root)}

<h2>Parameter update</h2>
<h3>Theta migration (prior → posterior, in prior sigma)</h3>
{_img('figures/theta_migration.png', root)}

<h2>Forecast (post-2018)</h2>
<h3>Corridors: prior vs posterior</h3>
{_img('figures/forecast_corridors.png', root)}
<h3>Metrics summary (width_ratio / median_shift)</h3>
{_csv_to_html_table(fc / 'metrics_summary.csv')}

<h2>Reproducibility</h2>
{meta_html}
</body></html>"""
    out = root / "report.html"
    out.write_text(html, encoding="utf-8")
    log.info("closed-loop report written: %s", out)
    return out

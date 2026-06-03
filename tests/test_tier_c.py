"""Tier C interactive Plotly figures — viz-003 tests.

Covered:

* per-figure non-empty HTML floor
* plotly JS hook present (so the file is renderable, not a static stub)
* light-theme markers (`color-scheme: light only` + dark-mode override)
* schema rejection on malformed inputs
* dispatcher resilience when outputs/ is incomplete
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.viz.tier_c import (
    interactive_ablation,
    interactive_theta_explorer,
    polish_cluster3_hover,
    render_all_tier_c,
)


MIN_HTML_BYTES = 10_000  # cdn plotly boilerplate + a non-trivial figure body


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


def _make_quantile_csv(path: Path, metrics: list[str]) -> Path:
    rows = []
    times = pd.date_range("2011-12-31", periods=8, freq="YE")
    for m in metrics:
        for t in times:
            rows.append({
                "metric": m, "time": t.strftime("%Y-%m-%d"),
                "p10": 1.0, "p50": 2.0, "p90": 3.0,
            })
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def quantile_csvs(tmp_path: Path) -> dict[str, Path]:
    metrics = ["WOPT", "WWPT", "WGPT"]
    return {
        "setup1_naive": _make_quantile_csv(tmp_path / "s1.csv", metrics),
        "setup2_localized": _make_quantile_csv(tmp_path / "s2.csv", metrics),
        "setup3_full": _make_quantile_csv(tmp_path / "s3.csv", metrics),
    }


@pytest.fixture
def theta_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    rng = np.random.default_rng(42)
    Z_prior = rng.normal(size=(30, 9))
    Z_post = Z_prior + rng.normal(scale=0.1, size=(30, 9))
    cluster_ids = rng.integers(0, 3, size=30)
    p = tmp_path / "theta_prior.npy"
    q = tmp_path / "theta_post.npy"
    c = tmp_path / "cluster_ids.npy"
    np.save(p, Z_prior)
    np.save(q, Z_post)
    np.save(c, cluster_ids)
    return p, q, c


@pytest.fixture
def migration_csv(tmp_path: Path) -> Path:
    rows = []
    for cl in [0, 1, 2]:
        for comp in ["A", "B", "C"]:
            rows.append({
                "cluster": cl, "component": comp,
                "prior_centroid": 1.0, "post_centroid": 1.1,
                "reference": 0.95,
            })
    p = tmp_path / "migration.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


# ──────────────────────────────────────────────────────────────────────────
# Per-figure tests
# ──────────────────────────────────────────────────────────────────────────


def test_interactive_ablation_writes_plotly_html(tmp_path, quantile_csvs):
    out = tmp_path / "ablation.html"
    p = interactive_ablation(quantile_csvs, out)
    assert p.exists()
    size = p.stat().st_size
    assert size > MIN_HTML_BYTES, f"too small ({size} B)"
    html = p.read_text(encoding="utf-8")
    # plotly JS hook + dropdown
    assert "plotly" in html.lower()
    assert "updatemenus" in html.lower() or "WOPT" in html
    # light theme markers
    assert 'content="light only"' in html
    assert "prefers-color-scheme" in html


def test_interactive_ablation_rejects_missing_columns(tmp_path):
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"metric": ["X"], "time": ["2011-12-31"]}).to_csv(bad, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        interactive_ablation({"setup1_naive": bad}, tmp_path / "out.html")


def test_interactive_ablation_rejects_empty(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        interactive_ablation({}, tmp_path / "out.html")


def test_interactive_theta_explorer_writes_parcoords(tmp_path, theta_inputs):
    p, q, c = theta_inputs
    out = tmp_path / "theta.html"
    res = interactive_theta_explorer(p, q, c, out)
    assert res.exists()
    size = res.stat().st_size
    assert size > MIN_HTML_BYTES, f"too small ({size} B)"
    html = res.read_text(encoding="utf-8")
    assert "parcoords" in html.lower()
    assert 'content="light only"' in html
    # both panels labelled
    assert "prior" in html.lower() and "posterior" in html.lower()


def test_interactive_theta_explorer_custom_labels(tmp_path, theta_inputs):
    p, q, c = theta_inputs
    out = tmp_path / "theta_labels.html"
    interactive_theta_explorer(p, q, c, out, theta_names=[
        "THICK", "MAJ_R", "AZIMUTH", "NUMBER_CHANNELS", "CHANNELS_WIDTH",
        "LEN", "AMPLITUDE", "RELATIVE", "PROP",
    ])
    html = out.read_text(encoding="utf-8")
    assert "THICK" in html and "MAJ_R" in html


def test_polish_cluster3_hover_includes_shift(tmp_path, migration_csv):
    out = tmp_path / "c3.html"
    polish_cluster3_hover(migration_csv, out)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    # σ-shift hover text was injected
    assert "prior→post shift" in html or "prior\\u2192post shift" in html \
        or "% of |prior|" in html
    assert 'content="light only"' in html


# ──────────────────────────────────────────────────────────────────────────
# Dispatcher resilience
# ──────────────────────────────────────────────────────────────────────────


def test_render_all_tier_c_empty_outputs(tmp_path):
    (tmp_path / "outputs").mkdir()
    done = render_all_tier_c(tmp_path)
    # No crash; missing-input failures are swallowed and logged.
    assert isinstance(done, dict)
    assert all(p.exists() for p in done.values())


def test_render_all_tier_c_with_minimal_outputs(tmp_path, quantile_csvs,
                                                  theta_inputs, migration_csv):
    """End-to-end: lay down the artifacts in the canonical paths and dispatch."""
    out = tmp_path / "outputs"
    (out / "forecast").mkdir(parents=True)
    (out / "matrices").mkdir(parents=True)
    (out / "qc").mkdir(parents=True)

    # forecast quantile CSVs
    for label, src in quantile_csvs.items():
        (out / "forecast" / f"{label}_field_total_quantiles.csv").write_bytes(
            src.read_bytes())

    # matrices
    p, q, c = theta_inputs
    (out / "matrices" / "theta_prior.npy").write_bytes(p.read_bytes())
    (out / "matrices" / "theta_post.npy").write_bytes(q.read_bytes())
    (out / "matrices" / "cluster_ids.npy").write_bytes(c.read_bytes())

    # migration csv
    (out / "qc" / "cluster_migration.csv").write_bytes(migration_csv.read_bytes())

    done = render_all_tier_c(tmp_path)
    assert "interactive_ablation" in done
    assert "interactive_theta_explorer" in done
    assert "cluster3_diagnostic_hover" in done
    for name, p in done.items():
        assert p.exists(), f"{name} → {p} not written"
        assert p.stat().st_size > MIN_HTML_BYTES, f"{name} too small"

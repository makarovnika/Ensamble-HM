"""CL-G: closed-loop HTML rollup."""
import numpy as np

from cmp_ensemble.closed_loop.report import build_closed_loop_report


def _make_run(root):
    """Minimal completed-run artifacts the report reads."""
    (root / "figures").mkdir(parents=True, exist_ok=True)
    (root / "forecast").mkdir(parents=True, exist_ok=True)
    np.save(root / "misfit_history.npy", np.array([5.0, 3.0, 2.0, 1.4, 1.1]))
    (root / "Theta_post.npy.meta.yaml").write_text(
        "git_sha: abc123\nseed: 42\n", encoding="utf-8")
    for f in ("misfit_evolution.png", "theta_migration.png", "forecast_corridors.png"):
        (root / "figures" / f).write_bytes(b"\x89PNG\r\n")   # stub
    (root / "forecast" / "metrics_summary.csv").write_text(
        "metric,width_ratio,median_shift\noil,0.62,1200\nwater,0.81,300\n",
        encoding="utf-8")


def test_report_renders_and_embeds_sections(tmp_path):
    _make_run(tmp_path)
    out = build_closed_loop_report(tmp_path)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "Closed-loop pure-ensemble ES-MDA" in html
    assert "55% reduction" in html or "% reduction" in html      # misfit 5->1.1
    assert "figures/misfit_evolution.png" in html
    assert "width_ratio" in html                                 # metrics table embedded
    assert "abc123" in html                                      # sidecar embedded
    # asset links are relative (portable zip), no absolute Windows path leaks
    assert ":\\" not in html and str(tmp_path) not in html


def test_report_graceful_when_artifacts_missing(tmp_path):
    out = build_closed_loop_report(tmp_path)                     # empty dir
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "not available" in html or "missing figure" in html

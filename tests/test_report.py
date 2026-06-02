"""Tests for the HTML report builder (ТЗ §8)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cmp_ensemble.report import build_report


def _scaffold_minimal_outputs(root: Path) -> None:
    """Build a tiny outputs/ tree so build_report has something to render.

    Only the artefacts that the report touches are materialised; everything
    else is left missing so the resilience paths are exercised.
    """
    out = root / "outputs"
    (out / "matrices").mkdir(parents=True, exist_ok=True)
    (out / "qc").mkdir(parents=True, exist_ok=True)
    (out / "selection").mkdir(parents=True, exist_ok=True)
    (out / "forecast").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "article_assets" / "figures_v2").mkdir(parents=True, exist_ok=True)

    np.save(out / "matrices" / "theta_prior.npy", np.zeros((20, 5)))
    np.save(out / "matrices" / "d_sim_cum.npy", np.zeros((20, 10)))
    np.save(out / "matrices" / "d_obs_cum.npy", np.zeros(10))
    np.save(out / "matrices" / "C_dd_cum_diag.npy", np.ones(10))
    np.save(out / "matrices" / "singular_values.npy", np.array([5.0, 4.0, 3.0, 2.0, 1.0]))
    np.save(out / "matrices" / "locmask.npy", np.array([[1, 0, 1], [0, 1, 0]], dtype=int))

    pd.DataFrame({
        "component": ["a", "b"],
        "sigma_prior": [1.0, 2.0],
        "sigma_post": [0.8, 2.0],
        "spread_retention": [0.8, 1.0],
    }).to_csv(out / "qc" / "spread_retention.csv", index=False)

    pd.DataFrame({
        "cluster": [0, 0], "component": ["a", "b"],
        "prior_centroid": [1.0, 2.0], "post_centroid": [1.1, 1.9],
        "abs_shift": [0.1, -0.1], "shift_in_prior_sigma": [0.1, -0.1],
    }).to_csv(out / "qc" / "cluster_centroid_shift.csv", index=False)

    pd.DataFrame({"member": range(20), "maha": np.linspace(0.5, 3.0, 20)}).to_csv(
        out / "qc" / "mahalanobis_migration.csv", index=False
    )

    (out / "qc" / "rank_check.json").write_text(
        json.dumps({
            "rank_prior": 5, "rank_post": 5,
            "n_collapse_components": 0, "n_blowup_components": 0,
            "bimodality_score": 0.12, "passed": True,
            "messages": [{"level": "INFO", "text": "all good"}],
        }),
        encoding="utf-8",
    )

    pd.DataFrame({
        "component": ["a"], "prior_min": [0], "prior_max": [10],
        "post_min": [0.1], "post_max": [9.9],
        "n_below_prior_min": [0], "n_above_prior_max": [0], "n_out_of_bounds": [0],
    }).to_csv(out / "qc" / "physical_bounds_violations.csv", index=False)

    pd.DataFrame(columns=["model_id", "n_cluster_copies", "clusters",
                          "avg_shift_norm", "post_divergence_norm", "noise_to_signal"]).to_csv(
        out / "qc" / "duplicate_models.csv", index=False
    )

    pd.DataFrame({
        "rank": [1, 2, 3], "model_id": [100, 101, 102],
        "cluster_id": [0, 1, 2], "seed": [1, 2, 3],
        "sheet": ["s1", "s2", "s3"], "maha_distance": [3.0, 2.5, 2.0],
    }).to_csv(out / "selection" / "mahalanobis_ranking.csv", index=False)

    pd.DataFrame({
        "rank": [1, 2], "model_id": [100, 101], "cluster_id": [0, 1],
        "seed": [1, 2], "sheet": ["s1", "s2"], "maha_distance": [3.0, 2.5],
    }).to_csv(out / "selection" / "models_to_resimulate.csv", index=False)

    pd.DataFrame({
        "rank": [3], "model_id": [102], "cluster_id": [2],
        "seed": [3], "sheet": ["s3"], "maha_distance": [2.0],
    }).to_csv(out / "selection" / "models_proxy.csv", index=False)

    pd.DataFrame({
        "rank": [3], "model_id": [102], "cluster_id": [2],
        "seed": [3], "sheet": ["s3"], "maha_distance": [2.0],
    }).to_csv(out / "selection" / "validation_subset.csv", index=False)

    pd.Series({"median_rel_err": 0.6, "mean_rel_err": 0.7, "max_rel_err": 1.1}).to_csv(
        out / "selection" / "proxy_validation_aggregate.csv", header=True
    )

    pd.DataFrame({
        "cluster": [0, 1], "n_train": [10, 10], "n_val": [2, 2],
        "median_rel_err": [0.5, 0.7],
        "mean_rel_err": [0.6, 0.8], "max_rel_err": [0.9, 1.1],
    }).to_csv(out / "selection" / "proxy_validation_per_cluster.csv", index=False)

    pd.DataFrame({
        "evaluation_mode": ["no_truth_baseline_only"] * 3,
        "setup": ["setup1_naive", "setup2_localized", "setup3_full"],
        "phase": ["oil"] * 3,
        "M_members": [20, 20, 20],
        "mean_width_ratio": [1.0, 1.5, 1.5],
        "median_width_ratio": [1.0, 1.5, 1.5],
        "mean_median_shift": [0.0, 100.0, 100.0],
        "coverage_p10p90": [None, None, None],
    }).to_csv(out / "forecast" / "metrics_summary.csv", index=False)

    for fname in ("fig01_pipeline.png", "fig02_qc_spread.png",
                  "fig03_ablation_p10p90.png", "fig04_cumulative_scatter.png",
                  "fig06_cluster3_migration.png"):
        (out / "figures" / fname).write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00")


def test_build_report_creates_two_html_files(tmp_path: Path) -> None:
    _scaffold_minimal_outputs(tmp_path)
    # We need configs/ for theta_schema / well_layout — point project_root
    # away from tmp by injecting a config dir.
    (tmp_path / "configs").mkdir(exist_ok=True)
    (tmp_path / "configs" / "theta_schema.yaml").write_text(
        "parameters:\n  - name: a\n    range: [0, 1]\n  - name: b\n    range: [0, 1]\n",
        encoding="utf-8",
    )
    (tmp_path / "configs" / "well_layout.yaml").write_text(
        "producers: [{name: W1}, {name: W2}]\ninjectors: [{name: I1}]\n",
        encoding="utf-8",
    )

    paths = build_report(tmp_path)
    assert paths["main"].exists()
    assert paths["qc"].exists()
    assert paths["main"].stat().st_size > 2000
    assert paths["qc"].stat().st_size > 1000


def test_report_html_contains_key_sections(tmp_path: Path) -> None:
    _scaffold_minimal_outputs(tmp_path)
    (tmp_path / "configs").mkdir(exist_ok=True)
    (tmp_path / "configs" / "theta_schema.yaml").write_text(
        "parameters: []\n", encoding="utf-8"
    )
    (tmp_path / "configs" / "well_layout.yaml").write_text(
        "producers: []\ninjectors: []\n", encoding="utf-8"
    )

    paths = build_report(tmp_path)
    main = paths["main"].read_text(encoding="utf-8")
    qc = paths["qc"].read_text(encoding="utf-8")

    for marker in ("CMP Ensemble HM", "Phase 0", "Phase 1", "Phase 2", "Phase 3",
                   "Spread retention", "Mahalanobis", "Ablation"):
        assert marker in main, f"main report missing section: {marker}"
    for marker in ("Phase 1 QC report", "Spread retention", "Mahalanobis",
                   "Physical-bounds violations", "Duplicate-model"):
        assert marker in qc, f"qc report missing section: {marker}"

    # No absolute paths leaked (relative links only)
    assert "F:\\" not in main and "F:/" not in main
    assert "C:\\" not in main and "C:/" not in main


def test_report_handles_missing_artefacts(tmp_path: Path) -> None:
    """build_report must not crash when most artefacts are missing."""
    (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "theta_schema.yaml").write_text("parameters: []\n", encoding="utf-8")
    (tmp_path / "configs" / "well_layout.yaml").write_text(
        "producers: []\ninjectors: []\n", encoding="utf-8"
    )
    paths = build_report(tmp_path)
    assert paths["main"].exists()
    assert paths["qc"].exists()
    main = paths["main"].read_text(encoding="utf-8")
    # Falls back gracefully to "-" / "not available"
    assert "not available" in main or "<em>" in main

"""ТЗ §9 mandated setup tests.

Two requirements from the feature spec:
  * the three setups parse correctly from `configs/experiment_setups.yaml`
  * `setup3_full` degrades to setup2 when workflow controls are absent
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import yaml

from cmp_ensemble.config import project_root
from cmp_ensemble.forecast.setups import (
    run_setup1_naive,
    run_setup2_localized,
    run_setup3_full,
)


def _load_setups_yaml() -> dict:
    cfg_path = project_root() / "configs" / "experiment_setups.yaml"
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────────────────
# YAML parse
# ──────────────────────────────────────────────────────────────────────────


def test_yaml_defines_exactly_three_named_setups() -> None:
    cfg = _load_setups_yaml()
    setups = cfg.get("setups", {})
    assert set(setups.keys()) == {"setup1_naive", "setup2_localized", "setup3_full"}


def test_setup1_naive_disables_es_and_localization_and_controls() -> None:
    setups = _load_setups_yaml()["setups"]
    s1 = setups["setup1_naive"]
    assert s1["use_es_update"] is False
    assert s1["use_localization"] is False
    assert s1["use_control_uncertainty"] is False
    assert s1["d_obs_type"] == "cumulative"


def test_setup2_localized_enables_es_and_localization_but_not_controls() -> None:
    s2 = _load_setups_yaml()["setups"]["setup2_localized"]
    assert s2["use_es_update"] is True
    assert s2["use_localization"] is True
    assert s2["use_control_uncertainty"] is False
    assert s2["d_obs_type"] == "cumulative"


def test_setup3_full_requests_controls_and_hybrid() -> None:
    s3 = _load_setups_yaml()["setups"]["setup3_full"]
    assert s3["use_es_update"] is True
    assert s3["use_localization"] is True
    assert s3["use_control_uncertainty"] is True
    # ТЗ §6 spec: d_obs_type = "hybrid"
    assert s3["d_obs_type"] == "hybrid"


def test_every_setup_has_a_description() -> None:
    setups = _load_setups_yaml()["setups"]
    for name, cfg in setups.items():
        assert "description" in cfg and isinstance(cfg["description"], str)
        assert len(cfg["description"]) >= 10, f"{name} description too short"


# ──────────────────────────────────────────────────────────────────────────
# setup3 degenerates to setup2 when controls absent
# ──────────────────────────────────────────────────────────────────────────


def _toy_inputs(N: int = 12, n_d: int = 6):
    rng = np.random.default_rng(42)
    d_baseline = rng.standard_normal((N, n_d))
    d_proxy = rng.standard_normal((N, n_d))
    index = [
        ("oil_forecast", f"W{i % 2}", datetime(2020, 1 + (i % 4) * 3, 1))
        for i in range(n_d)
    ]
    cluster_ids = np.array([0, 0, 1, 1, 2, 2] * (N // 6))[:N]
    out_of_envelope = np.zeros(N, dtype=bool)
    return d_baseline, d_proxy, index, cluster_ids, out_of_envelope


def test_setup3_with_controls_false_matches_setup2() -> None:
    """When controls_available=False, setup3 must produce the same d_forecast
    matrix as setup2 (it just inherits + notes the degradation)."""
    d_base, d_post, idx, cl, oo = _toy_inputs()
    s2 = run_setup2_localized(
        d_baseline=d_base, d_proxy_post=d_post, index=idx,
        cluster_ids_baseline=cl, cluster_ids_proxy=cl,
        out_of_envelope=oo, keep_out_of_envelope=True,
    )
    s3 = run_setup3_full(
        d_baseline=d_base, d_proxy_post=d_post, index=idx,
        cluster_ids_baseline=cl, cluster_ids_proxy=cl,
        out_of_envelope=oo, controls_available=False,
        keep_out_of_envelope=True,
    )
    assert np.array_equal(s2.d_forecast, s3.d_forecast)


def test_setup3_with_controls_false_records_degradation_note() -> None:
    d_base, d_post, idx, cl, oo = _toy_inputs()
    s3 = run_setup3_full(
        d_baseline=d_base, d_proxy_post=d_post, index=idx,
        cluster_ids_baseline=cl, cluster_ids_proxy=cl,
        out_of_envelope=oo, controls_available=False,
    )
    assert any("degenerates to setup2" in n for n in s3.notes)


def test_setup3_with_controls_true_records_different_note() -> None:
    """When the user (hypothetically) provides controls, the degradation
    note must NOT be present."""
    d_base, d_post, idx, cl, oo = _toy_inputs()
    s3 = run_setup3_full(
        d_baseline=d_base, d_proxy_post=d_post, index=idx,
        cluster_ids_baseline=cl, cluster_ids_proxy=cl,
        out_of_envelope=oo, controls_available=True,
    )
    assert not any("degenerates to setup2" in n for n in s3.notes)


# ──────────────────────────────────────────────────────────────────────────
# setup1 identity sanity
# ──────────────────────────────────────────────────────────────────────────


def test_setup1_naive_uses_baseline_as_is() -> None:
    d_base, _, idx, cl, _ = _toy_inputs()
    s1 = run_setup1_naive(d_baseline=d_base, index=idx, cluster_ids=cl)
    assert np.array_equal(s1.d_forecast, d_base)
    # width_ratio is identity = 1 for setup1
    assert (s1.metrics.summary_per_metric["mean_width_ratio"] - 1.0).abs().max() < 1e-9

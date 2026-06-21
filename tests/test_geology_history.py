"""Tests for geolval-006 — compliance summary, model misfit, cross-axis."""

from __future__ import annotations

import pandas as pd

from cmp_ensemble.geology.history import (
    compliance_summary,
    history_vs_realism,
    model_misfit,
)


def _fake_compliance(setup: str, base_dev: float) -> pd.DataFrame:
    rows = []
    for cl in (0, 1, 2):
        for mid in range(cl * 5, cl * 5 + 5):
            rows.append({
                "setup": setup, "model_id": mid, "cluster_id": cl,
                "dev_field_cum_pct": base_dev + mid * 0.1,
                "dev_field_annual_max_pct": base_dev + mid * 0.05,
                "dev_well_top80_max_pct": base_dev * 2,
                "pass_field_cum_5pct": True,
                "pass_field_annual_10pct": True,
                "pass_well_top80_20pct": (base_dev < 3),
                "pass_all_three": (base_dev < 3),
            })
    return pd.DataFrame(rows)


def test_compliance_summary_per_cluster_plus_all():
    df = pd.concat([_fake_compliance("setup1", 5.0),
                     _fake_compliance("setup2", 2.0)],
                    ignore_index=True)
    out = compliance_summary(df)
    # 2 setups × (3 clusters + 1 all-clusters row) = 8 rows
    assert len(out) == 8
    # All-clusters rows have cluster = -1
    all_rows = out[out["cluster"] == -1]
    assert set(all_rows["setup"]) == {"setup1", "setup2"}
    # setup2's pass-rate is higher (base_dev=2 < 3 threshold above)
    s2_all = all_rows[all_rows["setup"] == "setup2"].iloc[0]
    s1_all = all_rows[all_rows["setup"] == "setup1"].iloc[0]
    assert s2_all["pass_all_three_rate"] > s1_all["pass_all_three_rate"]


def test_model_misfit_sums_three_components():
    df = pd.DataFrame({
        "setup": ["A", "A"], "model_id": [1, 2], "cluster_id": [0, 0],
        "dev_field_cum_pct": [1.0, 2.0],
        "dev_field_annual_max_pct": [3.0, 4.0],
        "dev_well_top80_max_pct": [5.0, 6.0],
        "pass_all_three": [True, False],
    })
    out = model_misfit(df)
    # total = sum of three dev_* columns
    assert out.loc[0, "total_mismatch_pct"] == 9.0
    assert out.loc[1, "total_mismatch_pct"] == 12.0


def test_history_vs_realism_with_seed_mapping():
    misfit = pd.DataFrame({
        "setup": ["A", "A", "B", "B"],
        "model_id": [10, 20, 10, 20],
        "cluster": [0, 0, 0, 0],
        "total_mismatch_pct": [50.0, 10.0, 30.0, 8.0],
        "dev_field_cum_pct": [5, 1, 3, 1],
        "dev_field_annual_max_pct": [5, 1, 3, 1],
        "dev_well_top80_max_pct": [40, 8, 24, 6],
        "pass_all_three": [False, True, False, True],
    })
    conn = pd.DataFrame({
        "experiment": [2, 2],
        "seed": [1234, 5678],
        "cluster": [0, 0],
        "frac_sand_in_largest_26": [0.99, 0.30],
        "mean_inj_connections_per_producer": [6.0, 2.0],
        "n_bodies_26": [1, 50],
    })
    seed_map = pd.DataFrame({
        "MODEL": [10, 20], "SEED_rounded": [1234, 5678],
    })
    joined = history_vs_realism(misfit, conn, model_seed_map=seed_map)
    # All 4 rows should now have realism columns populated
    assert len(joined) == 4
    assert joined["frac_sand_in_largest_26"].notna().sum() == 4
    # Model 10 → seed 1234 → frac_largest=0.99 in both setups
    m10 = joined[joined["model_id"] == 10]
    assert (m10["frac_sand_in_largest_26"] == 0.99).all()
    m20 = joined[joined["model_id"] == 20]
    assert (m20["frac_sand_in_largest_26"] == 0.30).all()


def test_history_vs_realism_without_map_falls_back_to_direct_join():
    misfit = pd.DataFrame({
        "setup": ["A"], "model_id": [42], "cluster": [0],
        "total_mismatch_pct": [10.0],
        "dev_field_cum_pct": [1.0], "dev_field_annual_max_pct": [3.0],
        "dev_well_top80_max_pct": [6.0], "pass_all_three": [True],
    })
    conn = pd.DataFrame({
        "experiment": [1], "seed": [42], "cluster": [0],
        "frac_sand_in_largest_26": [0.5],
        "mean_inj_connections_per_producer": [3.0], "n_bodies_26": [10],
    })
    joined = history_vs_realism(misfit, conn)
    assert len(joined) == 1
    assert joined["frac_sand_in_largest_26"].iloc[0] == 0.5


def test_compliance_summary_empty():
    assert compliance_summary(pd.DataFrame()).empty


def test_model_misfit_empty():
    assert model_misfit(pd.DataFrame()).empty

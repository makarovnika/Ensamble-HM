"""Axis 1 — geology→production link (TZ §5.1, geolval-003).

Quantifies how much of the production variance is explained by **geological
descriptors** beyond the 9 θ parameters of the adapted ensemble:

  R²(θ-only)     baseline using only THICK, MAJ_R, AZIMUTH, NUMBER_CHANNELS,
                  CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP
  R²(θ + geo)    same + per-model geological aggregates (net_sand, kh,
                  frac_channel, mean_ntg, frac_sand_in_largest_26,
                  mean_inj_connections_per_producer, n_bodies_26)
  uplift = R²(θ + geo) − R²(θ)

Reports per (response × cluster-scope):

  ``r2_uplift.csv``           one row per (response, scope) with uplift +
                              bootstrap (B=2000) 95% CI for the uplift.
  ``src2_influence.csv``      per-(response, predictor) standardised
                              squared regression coefficient with bootstrap
                              stability fraction across the B resamples.
  ``corr_descriptor_production.csv``
                              Pearson correlations of every descriptor
                              against every response with the canonical
                              3/√N significance threshold.

Production data is the adapted (Exp2-geomodelling) ensemble — there is no
matched-seed production set for Exp1, so this axis is single-experiment
by construction. The Exp1/Exp2 comparison on this axis is impossible
without re-simulating Exp1 decks, which is out of scope per CLAUDE.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)


PARAM_COLS = [
    "THICK", "MAJ_R", "AZIMUTH", "NUMBER_CHANNELS", "CHANNELS_WIDTH",
    "LEN", "AMPLITUDE", "RELATIVE", "PROP",
]


# ──────────────────────────────────────────────────────────────────────────
# Response extraction — year-end cumulative oil/water/gas (field-total)
# ──────────────────────────────────────────────────────────────────────────


def _detect_metric_keys(cum_index, expected_count: int = 3) -> list[str]:
    """Return the unique metric strings found in ``cum_index`` (3 expected)."""
    keys = []
    seen = set()
    for c in cum_index:
        metric = str(c[0])
        if metric not in seen:
            keys.append(metric)
            seen.add(metric)
    if len(keys) < expected_count:
        log.warning(f"only {len(keys)} metric keys found, expected "
                    f"{expected_count} — got {keys}")
    return keys


def extract_year_end_responses(
    d_sim_cum: np.ndarray,
    cum_index: list,
    year: int = 2018,
    producers: tuple[str, ...] = ("WELL5", "WELL7", "WELL3A", "WELL1", "WELL9"),
) -> pd.DataFrame:
    """Per-well year-end cumulative oil + per-well water-cut.

    Critical empirical note (session 026):
    field-total cum oil / water / gas / watercut are mutually constrained
    by mass balance — Pearson |r| > 0.9999 in this ensemble. The geological
    signal lives in **how production is redistributed across wells**, not
    in the total. We therefore expose per-well responses.

    Columns: ``cum_oil_<well>`` and ``watercut_<well>`` for each producer
    in ``producers`` that has both oil and water year-``year`` data.
    """
    metric_keys = _detect_metric_keys(cum_index)
    if len(metric_keys) < 2:
        raise ValueError(f"need at least 2 metrics, got {metric_keys}")
    oil_key, water_key = metric_keys[0], metric_keys[1]
    out: dict[str, np.ndarray] = {}
    for well in producers:
        oil_idx = [
            i for i, c in enumerate(cum_index)
            if str(c[0]) == oil_key and c[1] == well and c[2].year == year
        ]
        water_idx = [
            i for i, c in enumerate(cum_index)
            if str(c[0]) == water_key and c[1] == well and c[2].year == year
        ]
        if not oil_idx or not water_idx:
            continue
        oil = d_sim_cum[:, oil_idx].sum(axis=1)
        water = d_sim_cum[:, water_idx].sum(axis=1)
        out[f"cum_oil_{well}"] = oil
        denom = oil + water
        out[f"watercut_{well}"] = np.where(denom > 0, water / denom, np.nan)
    return pd.DataFrame(out)


# ──────────────────────────────────────────────────────────────────────────
# Geological descriptors — per-model aggregates
# ──────────────────────────────────────────────────────────────────────────


def aggregate_descriptors_per_model(
    descriptors_df: pd.DataFrame,
    connectivity_df: pd.DataFrame,
) -> pd.DataFrame:
    """One row per seed: aggregated well-block descriptors + connectivity."""
    df = descriptors_df.copy()
    df["seed"] = df["seed"].astype(int)
    agg = df.groupby("seed").agg(
        total_net_sand=("net_sand_penetrated", "sum"),
        total_kh=("kh_penetrated", "sum"),
        mean_frac_channel=("frac_channel_cells", "mean"),
        mean_ntg=("mean_ntg_along_well", "mean"),
    ).reset_index()
    if not connectivity_df.empty:
        cn = connectivity_df.copy()
        cn["seed"] = cn["seed"].astype(int)
        cn_cols = ["seed", "n_bodies_26",
                   "frac_sand_in_largest_26",
                   "mean_inj_connections_per_producer"]
        agg = agg.merge(cn[cn_cols].drop_duplicates("seed"), on="seed", how="left")
    return agg


def join_theta_geo_response(
    ensemble_data,
    descriptors_agg: pd.DataFrame,
    responses: pd.DataFrame,
    model_seed_map: pd.DataFrame,
) -> pd.DataFrame:
    """Join θ + geo aggregates + response for every model that has all three."""
    theta = pd.DataFrame(ensemble_data.theta, columns=PARAM_COLS)
    theta["model_id"] = ensemble_data.model_ids
    theta["cluster"] = ensemble_data.cluster_ids
    theta = theta.join(responses)
    # Map MODEL → SEED to attach geo aggregates (rounded SEED is the geo key)
    merged = theta.merge(
        model_seed_map[["MODEL", "SEED_rounded"]],
        left_on="model_id", right_on="MODEL", how="left",
    ).rename(columns={"SEED_rounded": "seed_real"})
    merged = merged.drop(columns=["MODEL"], errors="ignore")
    merged = merged.merge(descriptors_agg, left_on="seed_real",
                          right_on="seed", how="left")
    return merged


# ──────────────────────────────────────────────────────────────────────────
# Regression — R², uplift, bootstrap CI
# ──────────────────────────────────────────────────────────────────────────


GEO_COLS = [
    "total_net_sand", "total_kh", "mean_frac_channel", "mean_ntg",
    "n_bodies_26", "frac_sand_in_largest_26",
    "mean_inj_connections_per_producer",
]


def _fit_r2(X: np.ndarray, y: np.ndarray) -> float:
    X = StandardScaler().fit_transform(X)
    return float(LinearRegression().fit(X, y).score(X, y))


def _fit_src2(X: np.ndarray, y: np.ndarray, names: list[str]) -> dict[str, float]:
    Xs = StandardScaler().fit_transform(X)
    ys = (y - y.mean()) / (y.std(ddof=1) + 1e-12)
    coef = LinearRegression().fit(Xs, ys).coef_
    return {n: float(c ** 2) for n, c in zip(names, coef)}


def r2_uplift_with_bootstrap(
    X_theta: np.ndarray,
    X_geo: np.ndarray,
    y: np.ndarray,
    B: int = 2000,
    seed: int = 42,
) -> dict[str, float]:
    """In-sample R² for θ-only and θ+geo + bootstrap CI for the uplift."""
    rng = np.random.default_rng(seed)
    n = len(y)
    if n < len(PARAM_COLS) + len(GEO_COLS) + 5:
        return {"R2_theta": float("nan"), "R2_theta_geo": float("nan"),
                "uplift": float("nan"),
                "ci_low": float("nan"), "ci_high": float("nan"),
                "n": int(n)}
    r2_theta = _fit_r2(X_theta, y)
    X_full = np.hstack([X_theta, X_geo])
    r2_full = _fit_r2(X_full, y)
    uplift = r2_full - r2_theta
    uplifts = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        Xt_b, Xg_b, y_b = X_theta[idx], X_geo[idx], y[idx]
        Xf_b = np.hstack([Xt_b, Xg_b])
        try:
            uplifts[b] = _fit_r2(Xf_b, y_b) - _fit_r2(Xt_b, y_b)
        except Exception:
            uplifts[b] = np.nan
    uplifts = uplifts[~np.isnan(uplifts)]
    ci_low = float(np.percentile(uplifts, 2.5)) if uplifts.size else float("nan")
    ci_high = float(np.percentile(uplifts, 97.5)) if uplifts.size else float("nan")
    return {"R2_theta": r2_theta, "R2_theta_geo": r2_full, "uplift": uplift,
            "ci_low": ci_low, "ci_high": ci_high, "n": int(n)}


def src2_with_bootstrap(
    X: np.ndarray, y: np.ndarray, names: list[str],
    B: int = 2000, seed: int = 42,
) -> pd.DataFrame:
    """Per-predictor SRC² + stability fraction (fraction of bootstrap
    samples whose sign matches the in-sample sign)."""
    n = len(y)
    rng = np.random.default_rng(seed)
    point = _fit_src2(X, y, names)
    sign_in = {n_: 1 if v >= 0 else -1
               for n_, v in zip(names,
                                 LinearRegression().fit(
                                     StandardScaler().fit_transform(X), y).coef_)}
    sign_matches = {n_: 0 for n_ in names}
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        Xb, yb = X[idx], y[idx]
        try:
            Xs = StandardScaler().fit_transform(Xb)
            coef = LinearRegression().fit(Xs, yb).coef_
            for n_, c in zip(names, coef):
                if (c >= 0 and sign_in[n_] == 1) or (c < 0 and sign_in[n_] == -1):
                    sign_matches[n_] += 1
        except Exception:
            continue
    return pd.DataFrame([
        {"predictor": n_, "src2": point[n_],
         "stability_fraction": sign_matches[n_] / B}
        for n_ in names
    ]).sort_values("src2", ascending=False)


# ──────────────────────────────────────────────────────────────────────────
# Correlations + 3/√N gate
# ──────────────────────────────────────────────────────────────────────────


def descriptor_response_correlations(
    df: pd.DataFrame,
    descriptors: list[str],
    responses: list[str],
) -> pd.DataFrame:
    n = len(df)
    threshold = 3.0 / np.sqrt(n) if n > 0 else np.inf
    rows = []
    for d in descriptors:
        for r in responses:
            sub = df[[d, r]].dropna()
            if len(sub) < 3:
                rows.append({"descriptor": d, "response": r,
                             "n": len(sub), "pearson_r": np.nan,
                             "abs_r": np.nan, "passes_3_over_sqrt_N": False})
                continue
            r_val = float(np.corrcoef(sub[d], sub[r])[0, 1])
            rows.append({
                "descriptor": d, "response": r,
                "n": len(sub),
                "pearson_r": r_val,
                "abs_r": abs(r_val),
                "passes_3_over_sqrt_N": abs(r_val) >= threshold,
            })
    return pd.DataFrame(rows).sort_values("abs_r", ascending=False)


# ──────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ProductionLinkArtefacts:
    r2_uplift: pd.DataFrame
    src2: pd.DataFrame
    corr: pd.DataFrame
    joined: pd.DataFrame
    threshold: float


def build_production_link(
    root: Path,
    B: int = 2000,
    seed: int = 42,
) -> ProductionLinkArtefacts:
    """End-to-end builder; assumes Phase-0 cache + geolval-001/002 artefacts exist."""
    from cmp_ensemble.io.tnav_loader import load_tnav_ensemble
    from cmp_ensemble.geology.history import load_model_seed_map

    cache = root / "outputs/cache/ensemble.h5"
    d = load_tnav_ensemble(
        root / "models_near_adapted_centroids.xlsx",
        root / "Показатели динамики.xlsx",
        cache_path=cache, use_cache=cache.exists(),
    )
    responses = extract_year_end_responses(d.d_sim_cum, d.cum_index, year=2018)
    descs = pd.read_csv(root / "outputs/geology_validation/descriptors_exp2.csv")
    conn = pd.read_csv(root / "outputs/geology_validation/connectivity_summary.csv")
    desc_agg = aggregate_descriptors_per_model(descs, conn)
    seed_map = load_model_seed_map(root / "models_near_adapted_centroids.xlsx")
    joined = join_theta_geo_response(d, desc_agg, responses, seed_map)

    response_cols = [c for c in responses.columns]
    available_geo = [c for c in GEO_COLS if c in joined.columns]

    # R²-uplift + bootstrap, scope = all and per cluster
    rows_uplift = []
    for resp in response_cols:
        for scope_name, scope_mask in [
            ("all", joined[resp].notna()),
            *[(f"cluster_{c}", (joined["cluster"] == c) & joined[resp].notna())
              for c in (0, 1, 2)],
        ]:
            sub = joined[scope_mask].dropna(subset=[resp] + PARAM_COLS + available_geo)
            if len(sub) < len(PARAM_COLS) + len(available_geo) + 5:
                rows_uplift.append({
                    "response": resp, "scope": scope_name, "n": len(sub),
                    "R2_theta": np.nan, "R2_theta_geo": np.nan,
                    "uplift": np.nan, "ci_low": np.nan, "ci_high": np.nan,
                    "status": "TOO_FEW_SAMPLES"
                })
                continue
            X_th = sub[PARAM_COLS].to_numpy(dtype=float)
            X_geo = sub[available_geo].to_numpy(dtype=float)
            y = sub[resp].to_numpy(dtype=float)
            r = r2_uplift_with_bootstrap(X_th, X_geo, y, B=B, seed=seed)
            r["response"] = resp
            r["scope"] = scope_name
            r["status"] = "OK"
            rows_uplift.append(r)

    # SRC² for the all-cluster fit per response
    src2_frames = []
    for resp in response_cols:
        sub = joined.dropna(subset=[resp] + PARAM_COLS + available_geo)
        if len(sub) < 20:
            continue
        names = PARAM_COLS + available_geo
        X = sub[names].to_numpy(dtype=float)
        y = sub[resp].to_numpy(dtype=float)
        f = src2_with_bootstrap(X, y, names, B=B, seed=seed)
        f["response"] = resp
        src2_frames.append(f)
    src2_df = pd.concat(src2_frames, ignore_index=True) if src2_frames \
        else pd.DataFrame()

    # Correlations
    corr_df = descriptor_response_correlations(joined, available_geo, response_cols)
    threshold = 3.0 / np.sqrt(len(joined)) if len(joined) else float("nan")
    return ProductionLinkArtefacts(
        r2_uplift=pd.DataFrame(rows_uplift),
        src2=src2_df,
        corr=corr_df,
        joined=joined,
        threshold=threshold,
    )

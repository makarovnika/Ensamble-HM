# Methodology

Cross-references to Evensen, Oliver & Hanea (2026) — referred below as **EOH**.

## ES update (Phase 1, Task 1.2)

For each ensemble member i ∈ {1, …, N} we apply the one-pass Ensemble Smoother
(EOH eq. 5.13):

```
z_post[i] = z_prior[i] + K · (d_obs + ε[i] − d_sim[i])
K         = C_zd · (C_dd_ens + C_dd)⁻¹
```

with:

| Symbol | Meaning | Shape |
|---|---|---|
| `z` | stacked state vector `(θ, u)`; here `u=None`, so `z = θ` | (N, n_z) |
| `d_obs` | observed data | (n_d,) |
| `d_sim[i]` | per-member predicted observations | (N, n_d) |
| `C_zd` | sample cross-covariance `Z'⊤ D' / (N-1)` | (n_z, n_d) |
| `C_dd_ens` | sample ensemble covariance `D'⊤ D' / (N-1)` | (n_d, n_d) |
| `C_dd` | observation-noise covariance (diagonal here) | (n_d, n_d) |
| `ε[i]` | iid perturbation `~ N(0, C_dd)`, fixed seed | (N, n_d) |

### Subspace regularisation (EOH Ch. 6)

For N≪n_d the (n_d × n_d) inverse is numerically singular; we replace it with the projection
into the leading ensemble subspace. Let

```
E = D' / √(N-1)               so that  E⊤ E = C_dd_ens
E = U Σ V⊤                    truncated SVD, smallest r retaining ≥ 99% energy
```

Then

```
(C_dd_ens + C_dd)⁻¹  ≈  V_r · (Σ_r² + V_r⊤ C_dd V_r)⁻¹ · V_r⊤
K                    =  C_zd · V_r · inner⁻¹ · V_r⊤
```

The default subspace energy is **0.99**. On the real ensemble we keep **16 of 149** components
(99.16% energy).

### Adaptive correlation-based localization (Phase 1, Task 1.1)

ES with N≈150 has noisy long-range correlations. We build a mask

```
L[k, j] = 1   if  |corr(Z[:, k], D[:, j])| ≥ factor / √N
L[k, j] = 0   otherwise
```

and apply `K ← K ⊙ L` element-wise. With `factor = 3.0` (EOH Ch. 6 default) and N=149 the
threshold is **0.246**, which rejects ~99.7% of independent-Gaussian-pair correlations as noise.

**Empirical observation on the real ensemble**: only **60 of 3456** K-entries survive (1.74%),
and they are concentrated in three rows — `THICK`, `AZIMUTH`, `NUMBER_CHANNELS`. The remaining
six θ components have all-zero K rows and never move. This is documented in
`outputs/qc/spread_retention.csv` (six values at exactly 1.00) and visualised in
`outputs/figures/fig02_qc_spread.png`.

The `compare-phase1` subcommand renders three variants side-by-side:

| Variant | threshold | K kept | Components that move |
|---|---|---|---|
| `a` (default) | 3/√N = 0.246 | 1.74% | THICK, AZIMUTH, NUMBER_CHANNELS |
| `b` | 2/√N = 0.164 | 9.20% | all 9 |
| `c` | 3/√N, `d_obs_type=hybrid` | 3.52% | same 3 as variant a |

The `--localization-method soft_taper` option swaps the hard threshold for a cosine ramp through
`|corr| ∈ [threshold − 0.05, threshold + 0.05]`.

## QC checks (Phase 1, Task 1.3)

| Check | Threshold | Outcome |
|---|---|---|
| Spread retention `σ_post / σ_prior` per θ | `< 0.1` | ERROR (collapse) |
| Spread retention per θ | `> 1.5` for the majority | WARNING (blow-up) |
| `rank(Z_post)` | `< min(N-1, n_z)` | WARNING (rank loss) |
| Bimodality coefficient of Mahalanobis migration | `> 0.3` | INFO |
| **Physical-bounds violation** (added in session 005) | any θ outside its `theta_schema.yaml` range | WARNING with per-component count |
| **Duplicate-model summary** (added in session 005) | count of model_ids with > 1 cluster row | INFO with noise/signal ratio |

The collapse and blow-up thresholds are normative (EOH Ch. 14). The physical-bounds and
duplicate-summary checks are project-specific; both populate the `outputs/qc/qc_report.html`
table.

## Linear forecast proxy (Phase 2, Task 2.2)

For each cluster c with 24 ≤ M_c ≤ 50 training members:

```
S_c = C_zz_c⁻¹ · C_zd_c       (n_z, n_d_forecast)
d̂(z) = d̄_c + (z − z̄_c) · S_c
```

A small ridge (`1e-8`) regularises `C_zz` when `M_c` is small. Prediction is one-shot — no
iteration. The training data come from the **decoded_results.xlsx** forecast workbook (2019-2024,
123 models), cumulatively projected: see `cumulative_anomaly` in `docs/data_format.md`.

### In-envelope flag

A `LinearProxy.in_envelope(z)` predicate returns `True` iff every component of `z` lies in the
per-cluster `[min, max]` box of the training set. After ES, **138 of 149 θ_post** are
out-of-envelope — the proxy extrapolates wildly in every direction. `--keep-ooe` retains them
for Phase 3; default drops them, leaving only 9 to 11 in-envelope members.

### Proxy validation (Task 2.4)

Leave-out 12% per cluster (stratified), retrain, compare. Median relative error vs σ_train:

| Mode | Median rel err | Verdict |
|---|---|---|
| forecast (default) | 0.642 | PASS (< 1.0) |
| forecast + `--dedup-ensemble` | 0.604 | PASS |
| hindcast (`--hindcast`) | 0.779 | PASS |

The validation set is drawn from `models_proxy.csv` (the 69 models not earmarked for re-simulation).
For cluster 0 specifically, only ~3 validation members fit at val_fraction=0.12, so the cluster-0
verdict is statistically thin even when it passes.

## Mahalanobis ranking + compute planner (Phase 2, Tasks 2.1 + 2.3)

For each member i, compute `||Δθ||_M = sqrt((θ_post[i] − θ_prior[i])⊤ C_zz_prior⁻¹ (·))` where
`C_zz_prior` is the sample covariance of θ_prior. Sort descending. Then partition:

| File | Count | Selection |
|---|---|---|
| `models_to_resimulate.csv` | 80 (`selection.default_top_x`) | top-X by `||Δθ||_M` |
| `models_proxy.csv` | 69 | the rest |
| `validation_subset.csv` | 10 (`selection.proxy_validation_n`) | stratified across clusters from `models_proxy.csv` |

Deterministic given `seed = es_update.perturbation_seed = 42`.

## Phase 3 ablation (Task 3.5)

Three setups per ТЗ §6 Task 3.1; the third currently degenerates to the second because workflow
controls are absent.

| Setup | ES | Localization | Control unc. | d_obs_type |
|---|---|---|---|---|
| `setup1_naive` | off | off | off | cumulative |
| `setup2_localized` | on | on | off | cumulative |
| `setup3_full` (→ setup2) | on | on | **n/a** | hybrid |

Per-setup metrics computed in `cmp_ensemble.forecast.metrics.compute_metrics`:

- `width_ratio` — `(P90 − P10)_post / (P90 − P10)_prior` per (metric, well, time)
- `median_shift` — `P50_post − P50_prior`
- `coverage_p10p90` — fraction of `d_truth` entries inside `[P10, P90]`. Populated **only** under
  `--hindcast` (val slice provides d_truth); otherwise `None`.
- `crps_per_column` — Hersbach (2000) estimator: `E|X − y| − 0.5 · E|X − X'|`. Populated only under
  `--hindcast`.
- `cumulative_error` — `|∫d_pred − ∫d_truth| / ∫d_truth` via the trapezoidal rule. Populated only
  under `--hindcast`. Uses `np.trapezoid` with a fallback to `np.trapz` for NumPy < 2.0.

### evaluation_mode

Every Phase 3 artefact carries an `evaluation_mode` stamp (in `metrics_summary.csv` first column
and in sidecar metadata). Three values:

| Mode | When | What it means |
|---|---|---|
| `no_truth_baseline_only` | default (forecast against 2019-2024 simulator output) | width/shift only; coverage/CRPS are `None` |
| `train_val_hindcast_6+2` | `--hindcast` | val slice supplies d_truth; coverage/CRPS populated |
| `forecast_vs_truth` | never (would require real 2019-2024 observations, which do not exist) | — |

The session-005 audit retired the `train_val_hindcast` path as the **primary** evaluation
strategy because the val slice is still drawn from `Исторические значения.xlsx` — the same data
the adaptation already saw. We keep the hindcast flag as a diagnostic and label outputs honestly
via the `evaluation_mode` stamp.

## Limitations — interpreting `width_ratio > 1` in `metrics_summary.csv`

The Phase 3 default forecast run reports (real-data, 2019-2024 forecast period):

| Setup | mean width_ratio (oil) | mean width_ratio (water) | mean width_ratio (gas) |
|---|---|---|---|
| `setup1_naive` | 1.000 (identity) | 1.000 | 1.000 |
| `setup2_localized` | **1.466** | **2.221** | **1.466** |
| `setup3_full` | 1.466 (≡ setup2) | 2.221 | 1.466 |

A naive reading is "setup2 makes the forecast worse — the spread widens". This is **not** what
the numbers actually say. The asymmetry comes from how the two ensembles are constructed:

* **Baseline (`setup1_naive`)** is the raw collection of 123 deterministic tNavigator forecast
  runs from `decoded_results.xlsx`. Each model has one trajectory; there is no perturbation,
  no proxy, no ES re-projection.
* **`setup2_localized`** maps each model's ES-updated `θ_post` (149 values, including the 26
  duplicates) through the per-cluster linear proxy. The proxy is a function of θ, so the spread
  of `d_forecast_post` reflects the spread of `θ_post` — which is *deliberately* wider than
  `θ_prior` by the ε perturbation that the ES algorithm adds.

In other words, the comparison is between a deterministic baseline (zero ε noise) and a
proxy-projected ensemble that carries ES perturbation variance. **`width_ratio > 1` is therefore
expected and is not by itself evidence the method is failing.** The honest interpretation:

* If you want a like-for-like comparison, pass the baseline through the same proxy pipeline
  (`d̂_baseline = proxy(θ_prior)`) and recompute `width_ratio`. This is straightforward but was
  not done in the present run — it would change every Phase 3 number on disk.
* If you want to claim ES tightens forecast uncertainty in a specific sense, restrict to
  `--keep-ooe=False` (drop the 138 extrapolating members) — the 11 in-envelope members show
  width_ratio < 1 for oil (≈0.86, see `outputs/phase1_variants/` for a related side-by-side).

For the manuscript, present `width_ratio` together with the construction asymmetry caveat above.
Do NOT claim "ES widens the forecast" without acknowledging that the baseline carries no
perturbation while setup2 does.

## Why no Phase 4

`Phase 4` (APS soft-category, EOH Ch. 8) is documented in ТЗ §6 but explicitly out of scope per
ТЗ §12. The inputs (`geology/latents_v2.csv`, `geology/gmm_k3.csv`,
`geology/workflow_combined.xlsx`) are absent from this dataset and adding them is the user's
decision. The `phase4-stub` placeholder in `feature_list.json` reserves the slot but contains no
code.

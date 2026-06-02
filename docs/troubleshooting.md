# Troubleshooting

Common failures and their fix paths. Each section assumes you have already run `pytest -q` and
verified the test suite passes — if it doesn't, the failure is in code, not data.

## 1. `pytest -q` itself fails

| Symptom | Diagnosis | Fix |
|---|---|---|
| `ImportError: pydantic` / `click` / `plotly` / `jinja2` | Editable install used `--no-deps` and these were not pre-installed | `pip install pydantic click plotly jinja2` |
| `AttributeError: module 'numpy' has no attribute 'trapezoid'` | NumPy < 2.0 | Already handled: `src/cmp_ensemble/forecast/metrics.py` falls back to `np.trapz`. If you still see this, your `metrics.py` is stale — `git pull` and re-run. |
| `RuntimeError: No models loaded — check input paths and linkage` | Excel paths in `configs/default.yaml` → `io.paths` are wrong, or all the dynamics sheets failed the linkage rule | Check `pwd`; check that the four Excel files are at the repo root; re-run `--phase 0`. |

## 2. Phase 0 — data ingest

### Sheet/seed mismatch

```
WARNING  dynamics sheet '51-1_1-99999' (cluster=1, seed=99999) has no
         matching parameter row — skipping
```

The dynamics sheet name format is `51-<cluster>_<X>-<round(SEED)>`. The parameter manifest stores
`SEED` as a float that rounds to that integer suffix. If the suffix and `round(SEED)` disagree
across all 150 models, the linkage failed entirely — most likely because of an Excel re-export
that changed the SEED column precision.

Diagnosis:
```python
import pandas as pd
xl = pd.ExcelFile("models_near_adapted_centroids.xlsx")
df = pd.read_excel(xl, sheet_name="Кластер_0_адаптация", header=3)
print(df["SEED"].head().round())
```
Compare with the sheet-name suffixes in `Показатели динамики.xlsx`.

### Truncated timeline

```
WARNING  sheet '51-1_1-173' has truncated timeline (n_d_rates=5110 vs canonical 6790).
         Skipping this model.
```

One model has 74 rows instead of 97. The ensemble shrinks from 150 → 149. This is expected and
documented; ES tolerates it.

### NaN in dynamics

```
ValueError: Sheet '51-2_1-XYZ' contains NaN values in dynamics — refusing to load.
```

The loader rejects partial / corrupt sheets. Fix the input file rather than the loader. Do **not**
silently fill NaN — ES is sensitive to it.

### Dummy well `B`

The historical and dynamics workbooks both contain a well named `B` whose every column is zero.
The loaders drop it on load (`DUMMY_WELL = "B"`). Active well count after filtering:
**16 producers + 6 injectors = 22 wells**.

## 3. Phase 1 — ES update

### Ensemble collapse (`spread_retention < 0.1`)

```
ERROR  ensemble collapse: spread_retention < 0.1 for 2 component(s): ['THICK', 'AZIMUTH']
```

The QC report fails. Causes:

- C_dd is far too small for the true noise (the ES update believes the observations more than
  the prior allows).
- Localization is too permissive (large factor or `soft_taper` with a wide ramp).
- Repeated ES iterations (we use 1-pass ES, not ESMDA — if you've patched in iterations, expect
  this).

Fixes:

- Inflate `noise_spec.yaml → relative_sigma` from 0.15 to 0.30 and re-run.
- Use the default `localization_method: hard` with `factor = 3.0`.
- If the collapse persists, check `outputs/qc/per_well_misfit.csv` for systematic simulator bias
  (e.g. gas residuals 5×10⁷ on 10⁸ values means the data demands a θ shift the parameters
  cannot deliver — this is a model-adequacy issue, not an ES bug).

### Hard 3/√N localization "freezes" 6 of 9 parameters

This is **the dominant Phase 1 finding** on the real ensemble, not a bug. At N=149 the threshold
0.246 rejects almost all correlations as noise, including some real ones. Six θ rows of K end up
all-zero → those parameters never update.

Fixes:

- `python -m cmp_ensemble.cli run --phase 1 --localization-factor 2.0` — loosen the threshold.
- `python -m cmp_ensemble.cli compare-phase1` — side-by-side variants A/B/C in `outputs/phase1_variants/`.

### θ_post outside the prior support

```
WARNING  out-of-prior-bounds: 82 θ_post entries beyond the prior support.
         Offending components: THICK(19), AZIMUTH(55), NUMBER_CHANNELS(4), ...
```

ES can push θ outside the physical range — e.g. THICK below 4 m (one model down to 1.29 m),
AZIMUTH above 93° (one model to 111°). These are unphysical and would crash a re-simulation.

Fixes:

- `--clip-to-prior` clamps to the `theta_schema.yaml` box and re-runs QC.
- For the article, report both clipped and unclipped numbers in the discussion — the unclipped
  ones show ES's raw demand, the clipped ones show what is actually re-simulable.

### Duplicate models (26/149)

Same `model_id` appears in two cluster sheets (a model "near both centroids"). θ_prior is
identical; after ES, θ_post diverges by the ε perturbation only. Logged as `INFO` with a
noise/signal ratio (median 0.10, max 0.36 in the real ensemble).

Fixes:

- `--dedup-ensemble` in Phase 2 averages the duplicated θ_post copies. Reduces ranking noise.
  Default is to keep all 149 rows for consistency with the rest of the pipeline.

## 4. Phase 2 — selection + proxy

### BHP sparsity

```
WARNING  BHP-zero entries: 1325 of 1552 BHP slots. Their C_dd diagonal will be inflated.
```

Only 227 of 2231 historical BHP entries are non-zero. The loader inflates `σ = 10⁶` on the zero
entries, which makes them effectively invisible to ES (their `1/σ²` contribution to K vanishes).
This keeps the d_obs / d_sim indices aligned without forcing them through the ES update.

If you want BHP **dropped** entirely instead of inflated, edit
`configs/noise_spec.yaml → bhp_handling.drop_zero_entries: true` (already the default behaviour).

### Proxy verdict `WARN` instead of `PASS`

`validate_proxy` returns `WARN` when the median relative error is in `[1.0, 2.0)`:

```
INFO  proxy verdict: WARN  median=1.118, mean=1.165, max=1.327
```

On the real ensemble this happens for **cluster 0 only** (the survivable subset, 24 models).
Likely cause: small training set + non-representative subset.

Fixes:

- Run `--phase 3` with the proxy as-is and label cluster 0 as "diagnostic" rather than
  "predictive" in the article.
- Or: enlarge cluster 0's training set by re-simulating the missing 26 models (this is a manual,
  out-of-pipeline step — pressure depletion is a physics issue, not an ES one).

## 5. Phase 3 — ablation forecast

### `forecast.h5` cache not found

```
ERROR  outputs/cache/forecast.h5 not present. Run `cmp-ensemble run --phase 2` first.
```

Phase 3 depends on the forecast workbook being parsed and cached. Run `--phase 2` first (or
`--phase all`).

### `decoded_results.xlsx` not reachable

```
WARNING  forecast path \\W11069\...: [WinError 1265] контроллер домена не отвечает
ERROR    decoded_results.xlsx is not reachable at any configured path.
         Either restore the UNC share or copy the file into
         data/forecast/decoded_results.xlsx (local fallback).
```

The forecast workbook lives on a UNC share that's often unavailable. The pipeline tries each
path in `configs/default.yaml → io.forecast_paths` in order; the first entry is the local
fallback. Copy the file:

```powershell
Copy-Item '\\W11069\watt-adapt\...\decoded_results.xlsx' `
          'F:\СМП\Статья 2.0\Ensamble HM\data\forecast\decoded_results.xlsx'
```

### Setup3 == Setup2 byte-for-byte

```
INFO  setup3_full: M=149, notes: Workflow controls (workflow_params.csv) absent from
       dataset — setup3 degenerates to setup2 (no control uncertainty applied).
```

`setup3_full` requires a `workflow_params.csv` of shape (150 × 12) — absent from this dataset.
The runtime logs a `WARNING` and copies setup2's results to setup3. The ablation table is
effectively a 2-setup comparison.

### `coverage_p10p90` column is empty

The default evaluation regime (`no_truth_baseline_only`) does **not** populate coverage / CRPS /
cumulative_error because there is no real out-of-sample truth. This is by design — the project
honestly admits we cannot score the forecast against ground truth.

Two diagnostic options:

- `--hindcast --train-years 6 --val-years 2` — splits the history into train + val, uses the val
  slice as d_truth. Populates coverage / CRPS / cumulative_error but stamps everything as
  `train_val_hindcast_6+2` because the val slice was already seen by the original adaptation.
- Compare `width_ratio` and `median_shift` between setups instead. These are populated in every mode.

### `width_ratio ≈ 600` for setup2 looks wrong

Real-data observation: under `--hindcast --keep-ooe`, setup2's per-metric `mean_width_ratio` is
≈600, not ≈1.5 as in the default forecast mode. Cause: in hindcast mode the val slice has a much
smaller absolute scale than the full forecast, so `(P90 − P10)_prior` is tiny — small
denominators inflate the ratio. The number is technically correct but visually misleading.

Recommendation for the article: report **median** width_ratio and per-metric scatter, not the
mean — and explicitly say what the comparison axis is in each setup.

## 6. Report / figures

### `cmp-ensemble report` crashes with `jinja2 not found`

```
ImportError: No module named 'jinja2'
```

Install: `pip install jinja2`. Not bundled in the `--no-deps` install path.

### Figures missing — `cmp-ensemble figures` writes "skip ..." warnings

```
WARNING  skip fig02: outputs/qc/spread_retention.csv not found (run --phase 1 first)
```

The `figures` subcommand does not re-run any phase. fig02 needs Phase 1 outputs; fig03/04 need
Phase 3 outputs. Run the corresponding phase first.

### Plotly cluster3 diagnostic looks dark in my browser

All three HTML dashboards force a light theme regardless of browser dark mode (see
`tests/test_report.py::test_report_forces_light_theme`). If you still see a dark background,
your browser is **caching** an older version of the file — hard-refresh (Ctrl-F5 in Chrome/Edge).

## 7. Reproducibility

Every artefact under `outputs/` has a `*.meta.yaml` sidecar with:

```yaml
git_sha: <commit hash>
git_dirty: <true if working tree had uncommitted changes>
config_hash: <SHA-256 prefix of resolved config>
seed: 42
written_at_utc: ...
```

If two runs disagree, compare their sidecars. Differences in `git_sha` or `config_hash` explain
99% of mismatches; `git_dirty=true` flags the rest (uncommitted edits at the time of write).

# Data format

This document specifies what the four Excel inputs at the repo root contain, how the loaders
parse them, and the pydantic schemas they map onto. The mapping is **frozen by session 002**;
do not silently coerce schema mismatches — extend the schemas + add a regression fixture instead.

## Input files (four Excel workbooks)

### `models_near_adapted_centroids.xlsx`

Source of `θ_prior`, manifest, and cluster centroid reference.

- 3 sheets, one per cluster: `Кластер_0_адаптация`, `Кластер_1_адаптация`, `Кластер_2_адаптация`.
- Each sheet has 50 rows of models + a header at row 3 and an "Адаптированный центроид →" row at row 1.
- 15 columns: `MODEL`, `distance_to_centroid`, `cluster_k3_orig`, `prob_k3_orig`, `maha_k3_orig`,
  `THICK`, `MAJ_R`, `AZIMUTH`, `NUMBER_CHANNELS`, `CHANNELS_WIDTH`, `LEN`, `AMPLITUDE`, `RELATIVE`,
  `PROP`, `SEED`.
- **n_θ = 9** — the continuous parameters from THICK to PROP. The other columns are metadata.

### `Показатели динамики.xlsx`

Per-model simulator output over the historical period.

- **150 sheets**, one per model. Sheet-name pattern: `51-<cluster>_<X>-<round(SEED)>`
  (e.g. `51-0_4-32434`). The cluster prefix is informational; the `(cluster, round(SEED))` pair
  is the unique join key.
- Each sheet is **97 monthly rows × 581 columns** spanning 2011-01-01 → 2018-12-13.
- Column headers: `Дата` + `<metric>` field totals + `<metric> (<well>)` per-well.
- Metrics used by Phase 0:
  - Per-well rates: `Дебит нефти`, `Дебит воды`, `Дебит газа`, `Забойное давление` (sparse).
  - Per-well cumulative: `Накопл. нефть`, `Накопл. вода`, `Накопл. газ`.
  - Per-injector: `Приёмистость воды`.

One sheet (`51-1_1-173`) has a truncated timeline (74 rows). It is dropped with a `WARNING`;
the effective ensemble size becomes **N = 149**.

### `Исторические значения.xlsx`

Real-world observations from the 22 active wells.

- 1 sheet, long format: 2231 rows = 23 wells × 97 months (the 23rd well is the dummy `B` placeholder
  filtered on load).
- 50 columns including `Скважина`, `Дата`, all `Дебит *` rates, `Добыча *` cumulative,
  `Забойное давление` (sparse — only 227 of 2231 entries non-zero).
- Time column uses drifted end-of-step dates (`2011-01-01`, `2011-02-01`, `2011-03-04`, ...).
  These match the `Показатели динамики.xlsx` date column 97-of-97.

### `Кроссплоты.xlsx`

End-of-history cumulative snapshot. Used for cross-checks only — not the primary data source.

- 5 sheets: `Накопл. нефть/вода/жидкость/газ/закачка`.
- 154 rows × 47 columns: 150 models + 1 "История" + 3 layout rows.

## Linkage rule

The same physical model can appear in two cluster sheets if it is near both centroids; in that
case `model_id` and `seed` are identical, but `cluster_id` differs.

The unique key is **`(cluster_id, seed_int)`** where `seed_int = round(SEED_float)`. Validated
**150/150** in session 002 and re-confirmed at every Phase 0 cache rebuild.

26 of 149 ensemble rows are duplicate `model_id`s under this rule. The duplicates carry identical
θ_prior; after ES they diverge by the ε perturbation only. The `--dedup-ensemble` flag collapses
them by averaging θ_post; default behaviour keeps all 149 rows.

## Forecast workbook (external)

`decoded_results.xlsx` — 123 of 150 models re-simulated over 2011-01 → 2024-10 (167 monthly steps).

- Loaded by `cmp_ensemble.io.forecast_loader.load_tnav_forecast`.
- Search order: `data/forecast/decoded_results.xlsx` (local fallback), then the UNC share
  configured under `io.forecast_paths` in `configs/default.yaml`.
- 27 missing models: 26 from cluster 0 that failed by pressure depletion + the truncated-timeline
  `51-1_1-173`. Cluster 0 is therefore a **survivable subset** in Phase 3.
- The historical portion of `decoded_results.xlsx` (rows 1-97) **does not match** the
  `Показатели динамики.xlsx` outputs for the same models — 210 of 580 columns differ by up to
  ~30%. The two are treated as separate simulation runs:
  - Phase 1 (adaptation) uses `Показатели динамики.xlsx`.
  - Phase 3 (forecast) uses `decoded_results.xlsx`.

## Pydantic schemas (`src/cmp_ensemble/io/schemas.py`)

### `EnsembleData`

Returned by `load_tnav_ensemble`. Aligns θ, d_sim, identifiers, and the (metric, well, time) indexes.

- `model_ids: (N,) int` · `cluster_ids: (N,) int in {0,1,2}` · `seeds: (N,) int` · `sheet_names: list[str]`
- `theta: (N, 9)` · `theta_names: list[str]` length 9
- `d_sim_rates: (N, 6790)` · `rate_index: list[(metric, well, datetime)]`
- `d_sim_cum: (N, 384)` · `cum_index: list[(metric, well, datetime)]`
- `time_steps: (97,) datetime64[ns]`
- `producer_wells: list[str]` (16) · `injector_wells: list[str]` (6)

Validators enforce shape consistency across all fields. Any NaN in `d_sim_*` causes a hard
`ValueError`.

### `ObservationData`

Returned by `load_observations`. Same (metric, well, time) index as `EnsembleData`, so
`d_obs[i]` always aligns with `d_sim[:, i]`.

- `d_obs_rates: (6790,)` · `d_obs_cum: (384,)`
- `C_dd_rates: (6790, 6790) diagonal` · `C_dd_cum: (384, 384) diagonal`
- `n_bhp_zero_dropped: int` — number of zero-BHP entries whose σ was inflated to 1e6
  (effectively dropping them from the ES update while keeping the index aligned)

C_dd uses a **per-metric soft floor**: `σ_i = max(0.15·|d_obs_i|, 0.01·median(|d_obs|_metric), 0.001)`.
This avoids the numerical instability of a single absolute floor across cumulative gas (10⁹ scale)
and rates (10⁰ scale).

### `StateVectorSchema`

Returned by `build_state_vector`. Records the slice indices needed to round-trip `z = (θ, u)`
back into components. `u` is `None` for this dataset because workflow controls are absent.

### `ForecastData`

Returned by `load_tnav_forecast`. Forecast-period analogue of `EnsembleData`.

- `model_ids: (M,) int` — typically M=123 (after dropping the missing 27 sheets)
- `d_forecast_cum: (M, 288)` · `d_forecast_rates: (M, 3360)`
- `cum_index`, `rate_index` over the forecast period only
- `forecast_time_steps: (70,) datetime64[ns]` (2019-01-01 → 2024-10-01)
- `history_cutoff: datetime` — first day of the forecast window
- `cumulative_anomaly: bool` — when `True` (default), each cumulative entry is offset by the
  at-cutoff value, so it represents production added in the forecast period only (not since 2011)

## Year-end aggregation cadence

`Накопл. *` columns are computed monthly. Phase 0 extracts the **last monthly row per calendar
year** as the year-end anchor. With drifted dates the 8 anchors are:
`2011-12-08`, `2012-12-14`, `2013-12-09`, `2014-12-04`, `2015-12-29`, `2016-12-23`, `2017-12-18`,
`2018-12-13`. This is documented in every `*.meta.yaml` sidecar via the timestamp metadata.

## Output sidecars

Every `outputs/*.npy` and `outputs/*.csv` written by the pipeline carries a companion
`<artefact>.meta.yaml` produced by `cmp_ensemble.metadata.write_sidecar`:

```yaml
artefact: K.npy
written_at_utc: '2026-06-02T05:37:44+00:00'
git_sha: 34299f1080ce55414e419002e96f92502043e5e5
git_dirty: false
config_hash: e621bdef25cf5165
seed: 42
extra:
  phase: 1
  d_obs_type: cumulative
  localization_factor: 3.0
  localization_method: hard
  ...
```

The config hash is a SHA-256 prefix of the order-independent JSON serialisation of the resolved
config. Two runs with the same hash should produce byte-identical artefacts (modulo the
timestamp).

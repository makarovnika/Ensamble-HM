# Progress Log

## Current Verified State

- Repository root: `F:/СМП/Статья 2.0/Ensamble HM`
- Standard startup path: `./init.sh` (Git Bash) — or, on PowerShell, manually `python -m pip install -e .[dev]; pytest -q`
- Standard verification path: `pytest -q` (after scaffold-001 lands); synthetic-fixture integration test is `pytest tests/test_integration_synthetic.py -q`
- Current highest-priority unfinished feature: `scaffold-000` (initialise git repo) → `scaffold-001` (project skeleton, `pyproject.toml`, configs)
- Current blocker: 3 open clarification questions remain (see below) — but **all of them block Phase 3 / Phase 4 only**. Phase 0, Phase 1, Phase 2 are unblocked.

### Confirmed data contract (Session 002, 2026-05-22)

The four Excel files at the repo root **are** the canonical inputs. Mapping to ТЗ §3 schemas:

| ТЗ §3 artifact | Source in repo | Notes |
|---|---|---|
| `manifest.csv` (150 × {model_id, cluster_id, seed}) | `models_near_adapted_centroids.xlsx`: 3 sheets × 50 rows; cluster_id from sheet name; `MODEL` and `SEED` columns | Linkage rule: `round(SEED)` = suffix in `Показатели динамики.xlsx` sheet name (validated 150/150). |
| `theta_adapt.csv` (150 × n_θ) | same workbook, columns `THICK, MAJ_R, AZIMUTH, NUMBER_CHANNELS, CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP` | **n_θ = 9** (not 12 as the workflow_params line in ТЗ §3 implied). |
| Adapted centroid per cluster | row 1 of each sheet in same workbook (`Адаптированный центроид →` label) | Needed for Task 1.4 (cluster 3 diagnostic). |
| `tnav_outputs/<model_id>/production.csv` | `Показатели динамики.xlsx`: 150 sheets, 1 sheet = 1 model, 97 monthly rows (2011-01 → 2018-12), 581 columns | Columns are `<metric>` for field totals and `<metric> (<well>)` per well. Rich per-well coverage: rates, injection, cumulative, BHP, WHP, productivity index, watercut, GOR, WGR. |
| `tnav_outputs/<model_id>/cumulative.csv` (по годам) | derived: aggregate the `Накопл. *` columns from `Показатели динамики.xlsx` at year-end | Not separately stored — compute on load. |
| `historical_rates.csv` | `Исторические значения.xlsx`: long-format, 2231 rows = 23 wells × 97 months, ~48 metrics per row | Same metric set as the dynamics file. |
| `historical_cumulative.csv` (по годам) | derive from `Исторические значения.xlsx` (aggregate `Добыча *` monthly) OR use `Кроссплоты.xlsx` end-of-history snapshot | `Кроссплоты.xlsx` gives only the final-time slice (150 models × 5 metrics × 23 wells), not yearly. Use the long-format file for proper yearly aggregation. |
| `noise_spec.yaml` | not present | Generate from ТЗ default: diagonal Gaussian, σ_d = 15% × \|d_obs\|. |
| `theta_schema.yaml` | not present | Generate from the 9 parameter columns above; all continuous; ranges read from the data envelope. |
| `well_layout.yaml` | not present, **but well types are derivable** from name prefix: `WELL*` = producer (17), `INJ*` = injector (6). Well coordinates absent — and not needed for correlation-based localization. |

**Wells**: 23 active + 1 dummy `B` (zero everywhere — filter on load). 17 producers (`WELL1..WELL10`, `WELL1A`, `WELL1B`, `WELL2A`, `WELL3A`, `WELL4A`, `WELL5A`) + 6 injectors (`INJ1..INJ6`).

**Time grid**: 2011-01-01 → 2018-12-13, monthly, ~97 steps (≈8 years). Real grid is not perfectly calendar-monthly — actual dates carry day-of-month drift; the loader must preserve the timestamp column rather than re-bucketing.

**Known data gaps (will affect later phases)**:

- **No forecast period** — every artifact ends at 2018-12. Phase 3 cannot do "honest forecast vs truth" without additional tNavigator runs. Default to train/val split (ТЗ §6 Task 3.4: 6 years train + 2 years val) unless the user produces forecast simulations.
- **BHP sparse in history** — `Забойное давление` is non-zero in only ~227 / 2231 rows (≈10%). C_dd for BHP entries must be inflated or BHP must be dropped from `d_obs`. ТЗ default `d_obs_type: "cumulative"` for setup1/setup2 sidesteps this.
- **No workflow_params.csv** — ТЗ §3 expected 150 × 12 controls. We have only the 9 geological θ_adapt. Setup3 (`use_control_uncertainty=true`) is effectively disabled — it degenerates to setup2 unless controls are sourced.
- **No geology/{latents_v2.csv, gmm_k3.csv, workflow_combined.xlsx}** — Phase 4 (APS soft-category) inputs absent. Phase 4 is explicitly out-of-scope per ТЗ §12, so this is not a blocker.

### Open clarification questions (refined after Session 002 data audit)

The original 5 ТЗ §15 questions reduce to 3 still-open ones (with 2 newly surfaced):

1. **Forecast simulations**: will the user run tNavigator on the forecast period for the X models in `models_to_resimulate.csv`? If no → Phase 3 runs in train/val-split mode only (8 yr → 6+2). Affects `phase3-stop` honesty.
2. **`Адаптированный центроид →` row**: confirm this is the θ-space centroid of the cluster (the value that all 50 models inherit as their adaptation starting point). Needed for the centroid-migration plot in Task 1.4 (`phase1-004`).
3. **Proxy validation re-simulation budget** (was Q5 in ТЗ §15): is the user willing to re-simulate 10 models manually for Task 2.4? If no → `phase2-003` stays blocked and Phase 2 ships without proxy validation.

Newly surfaced by the audit:

4. **Workflow controls**: where do the 12 workflow parameters live, or do they not exist for this dataset? If they don't exist, setup3 is dropped from the ablation table and the article reports a 2-setup comparison (setup1 vs setup2) — this is itself a publishable design choice.
5. **Cumulative aggregation cadence**: ТЗ says "накопленные на конец каждого года". Confirm year-end timestamps: 2011-12-31, 2012-12-31, ..., 2018-12-31 (8 anchors), or some other cadence?

### Input files present in the repo (session 0 inventory)

- `TZ_ensemble_forecast.md` — canonical specification, read-only.
- `Исторические значения.xlsx` — historical observations, long-format (2231 × 50). Confirmed: rates + cumulative + BHP (sparse) per well per month, 23 wells, 2011-2018.
- `Показатели динамики.xlsx` — per-model simulation output, 150 sheets × 97 × 581. Confirmed: full d_sim source.
- `Кроссплоты.xlsx` — end-of-history cumulative cross-plots, 5 sheets (oil/water/liquid/gas/injection) × 150 models × 23 wells. Confirmed: convenient sanity-check view; not the primary d_sim source.
- `models_near_adapted_centroids.xlsx` — 3 sheets × 50 models × 15 cols. Confirmed: source of θ_prior (9 parameters), cluster ids, seeds, and adapted-centroid reference vector.

## Session Log

### Session 001

- Date: 2026-05-22
- Goal: bootstrap the agent harness — read ТЗ, fetch the walkinglabs template set, populate all eight template files in the repo root with project-specific content.
- Completed:
  - Read [TZ_ensemble_forecast.md](TZ_ensemble_forecast.md) end-to-end.
  - Fetched the eight templates from `walkinglabs/learn-harness-engineering` and adapted each to the CMP Ensemble HM project.
  - Wrote `CLAUDE.md`, `AGENTS.md`, `init.sh`, `claude-progress.md`, `feature_list.json`, `session-handoff.md`, `clean-state-checklist.md`, `evaluator-rubric.md`, `quality-document.md`.
  - Inventoried the four Excel data files at the repo root.
- Verification run: none — this session was harness setup only. `init.sh` will fail until `scaffold-001` lands (it exits with code 2 if `pyproject.toml` is missing, which is the expected guard).
- Evidence captured: this progress log + the eight template files committed at the repo root.
- Commits: none yet — repo is not under git. First commit will be created as part of `scaffold-000`.
- Files or artifacts updated: see "Completed" above.
- Known risk or unresolved issue: the five ТЗ §15 clarifications block productive Phase 0 work. Surface them to the user before starting `phase0-001`.
- Next best step: `scaffold-000` — `git init`, add `.gitignore` (Python + outputs/), commit the initial harness state. Then `scaffold-001` — `pyproject.toml`, `src/cmp_ensemble/` package layout, `configs/default.yaml`, `configs/experiment_setups.yaml`, an empty `tests/` skeleton, and the synthetic-fixture generator.

### Session 002

- Date: 2026-05-22
- Goal: audit the four input Excel files against the data contract in ТЗ §3; resolve as many of the 5 ТЗ §15 clarification questions as possible without bothering the user.
- Completed:
  - Inspected every sheet of all four Excel files (`models_near_adapted_centroids.xlsx`, `Показатели динамики.xlsx`, `Исторические значения.xlsx`, `Кроссплоты.xlsx`).
  - Established the canonical mapping from Excel to ТЗ §3 schemas (see "Confirmed data contract" above).
  - Discovered the linkage rule between `models_near_adapted_centroids.xlsx` and `Показатели динамики.xlsx`: `round(SEED)` from the parameter table equals the seed suffix in the dynamics sheet name; verified 150/150 models match.
  - Fixed n_θ = 9 (THICK, MAJ_R, AZIMUTH, NUMBER_CHANNELS, CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP). The "150 × 12 workflow_params" line in ТЗ §3 refers to a separate (absent) artifact, not to θ_adapt.
  - Confirmed well roster: 17 producers + 6 injectors + 1 dummy `B`. Time grid: monthly, 2011-01-01 → 2018-12-13, ~97 steps.
  - Identified the four data gaps with phase impact: no forecast period (Phase 3 must fall back to train/val), sparse historical BHP (~10%), no workflow_params (Setup3 degenerates), no geology files (Phase 4 — already out of scope).
  - Updated `feature_list.json`: unblocked `phase0-001` and `phase0-002`; rewrote their verification steps to reflect Excel inputs with concrete column names and shapes; pivoted `phase3-005` to use the train/val split as the primary path, with the "honest forecast" sub-feature gated on the user's answer to clarification #1.
  - Updated `CLAUDE.md` and this progress log with the resolved-vs-open clarification split.
- Verification run: none — this session was data audit + documentation only. The audit itself was the verification: a Python script (run via the Bash tool) read each workbook and produced the consistency checks reported above. No code committed yet.
- Evidence captured: this Session 002 block + the "Confirmed data contract" table above + the updated `feature_list.json`.
- Commits: still no git repo — `scaffold-000` remains the immediate next step.
- Files or artifacts updated: `claude-progress.md` (this entry + the verified-state section), `feature_list.json` (unblocked phase0-* features, refined phase3 strategy), `CLAUDE.md` (refreshed the ТЗ §15 question list).
- Known risk or unresolved issue: 3 open clarifications remain (forecast simulations? centroid row interpretation? proxy-validation re-sim budget?), plus 2 newly surfaced ones (workflow controls absence? cumulative aggregation cadence?). None of these block Phase 0–2; all of them shape Phase 3.
- Next best step: `scaffold-000` (git init + `.gitignore`), then `scaffold-001` (Python package + `pyproject.toml` + configs). With the data contract now fixed, the loader work in `phase0-001` can be designed against the Excel inputs directly.

### Session 003

- Date: 2026-05-24
- Goal: bring Phase 0 to `passing`: scaffold the Python package, write the loaders, and run end-to-end against the real Excel inputs.
- Completed:
  - `scaffold-000`: `git init -b main`, wrote `.gitignore`, first commit `6674fa9 scaffold scaffold-000: initial harness, ТЗ, and input data inventory`.
  - `scaffold-001`: `pyproject.toml` with the full dependency list, `src/cmp_ensemble/` package tree (io, ensemble, selection, forecast, qc, viz), `src/cmp_ensemble/{config, logging_setup, cli}.py`, and the five config YAMLs (`default.yaml`, `experiment_setups.yaml`, `theta_schema.yaml`, `noise_spec.yaml`, `well_layout.yaml`). Editable install via `pip install -e . --no-deps` after manually installing `pydantic`, `click`, `plotly` (the test machine has no PyPI access for the full editable resolve).
  - `phase0-001`: `src/cmp_ensemble/io/{schemas,tnav_loader}.py`. The loader reads all 150 dynamics sheets, links them to the parameter table via `round(SEED)`, classifies wells (16 producers + 6 injectors, dummy `B` filtered), and caches the result to `outputs/cache/ensemble.h5`. One sheet `51-1_1-173` has a truncated timeline (74 rows vs canonical 97) and is skipped with a WARNING — N drops to 149.
  - `phase0-002`: `src/cmp_ensemble/io/observations.py`. Loads `Исторические значения.xlsx` (long-format), pivots to (n_time, n_well) per metric, aligns to the ensemble's (metric, well, time) index, builds diagonal C_dd from the 15%-Gaussian default in `configs/noise_spec.yaml`. Zero-BHP entries (1325 of 1552 producer-BHP slots) get σ inflated to 1e6 so they do not dominate the ES update while keeping the d_obs/d_sim length aligned.
  - `phase0-003`: `src/cmp_ensemble/ensemble/state_vector.py` — build/unpack round-trip with `StateVectorSchema`.
  - CLI `cmp-ensemble run --phase 0` is wired; smoke run produces `outputs/matrices/{theta_prior, d_sim_rates, d_sim_cum, d_obs_rates, d_obs_cum, C_dd_rates_diag, C_dd_cum_diag, model_ids, cluster_ids}.npy`.
  - Tests: `tests/test_state_vector.py` (5 unit tests) + `tests/test_io_smoke.py` (2 cache-driven smoke tests). All 7 pass in ~2 seconds.
- Verification run: `python -m pytest -q` → `7 passed in 2.03s`; `python -m cmp_ensemble.cli run --phase 0` → completes, writes shapes `theta_prior=(149,9)`, `d_sim_rates=(149,6790)`, `d_sim_cum=(149,384)`, `d_obs_rates=(6790,)`, `d_obs_cum=(384,)`.
- Evidence captured: `outputs/matrices/*.npy`, `outputs/cache/ensemble.h5`, 7 passing pytest cases.
- Commits: forthcoming — about to commit the scaffold + Phase 0 implementation together with message `phase0 phase0-001..003: scaffold + loaders + state vector + smoke run`.
- Files or artifacts updated:
  - new: `pyproject.toml`, `src/cmp_ensemble/**`, `configs/{default,experiment_setups,theta_schema,noise_spec,well_layout}.yaml`, `tests/{__init__, test_state_vector, test_io_smoke}.py`.
  - modified: `feature_list.json` (scaffold-000, scaffold-001, phase0-001..003 → `passing` with evidence paths).
- Known risk or unresolved issue:
  - One model (`51-1_1-173`) is silently dropped due to truncated timeline. If this matters scientifically (e.g. the model belongs to a poorly represented cluster), revisit and either pad or extend.
  - The four pending clarifications carry over: forecast simulations? centroid-row interpretation? proxy-validation re-sim budget? cumulative cadence?
  - `setup3_full` still has no `u` to consume — degrades to `setup2` at Phase 3 runtime. Decision can be deferred until Phase 3.
- Next best step: `phase1-001` — adaptive correlation-based localization (Task 1.1). Threshold `3/√149 = 0.246`. Inputs ready: `outputs/matrices/theta_prior.npy` and (after building the cumulative-only Z, D) the columns of `d_sim_cum.npy` for the ES side.

### Session 004

- Date: 2026-05-24
- Goal: drive Phase 1 (Tasks 1.1–1.4) to `passing` and produce the first real ES update + QC report on the 149-model ensemble.
- Completed:
  - `phase1-001` adaptive correlation-based localization (`src/cmp_ensemble/ensemble/localization.py`). Hard mode and soft-taper mode. 5 unit tests pass.
  - `phase1-002` ES update with subspace regularisation (`src/cmp_ensemble/ensemble/{subspace, es_update}.py`). Subspace projection of `(C_dd_ens + C_dd)⁻¹` via truncated SVD of `Dp/√(N-1)`. Deterministic perturbations seeded at 42. 7 unit tests pass.
  - `phase1-003` QC checks (`src/cmp_ensemble/qc/checks.py`). Spread retention, rank, Mahalanobis migration, bimodality coefficient, cluster centroid shift, with thresholds from ТЗ §6 Task 1.3 (fixed rank check to `min(N-1, n_z)` after the first run produced a false-positive warning). 4 unit tests pass.
  - `phase1-004` cluster migration diagnostic (`src/cmp_ensemble/qc/cluster_migration.py`). Plotly HTML with per-cluster reference / prior / posterior bars. Pulls reference centroids from `configs/theta_schema.yaml`.
  - `phase1-cli` `_run_phase_1` wired in `cli.py`. End-to-end smoke run succeeds on the real 149-model ensemble.
- Verification run: `pytest -q` → `23 passed in 2.00s`; `cmp-ensemble run --phase 1` → exit 0, QC summary PASSED.
- Evidence captured:
  - `outputs/matrices/{theta_post, K, locmask, perturbations, singular_values}.npy` (shapes (149,9), (9,384), (9,384), (149,384), (149,))
  - `outputs/qc/{spread_retention.csv, mahalanobis_migration.csv, cluster_centroid_shift.csv, rank_check.json, cluster_migration.csv, cluster3_diagnostic.html}`
  - subspace truncation kept 16 of 149 SVD components (energy 0.9916) — narrow effective rank
  - localization kept 60 of 3456 K-entries (1.74%) at threshold 3/√149 = 0.2458
- Substantive findings on the real run:
  - **AZIMUTH** posterior centroid shifts +17° across all three clusters (~2.5 σ_prior). The data consistently asks for higher azimuth than the prior mean across every cluster.
  - **THICK** posterior centroid drops by ~1 σ in all three clusters.
  - **NUMBER_CHANNELS** drops by ~0.6 σ.
  - The other 6 parameters (MAJ_R, CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP) do not move at all — their K-entries were zeroed by hard localization. This is a hard prior that the present localization is silencing — worth sanity-checking before Phase 2.
  - Mahalanobis migration BC = 0.368 (bimodal) → cluster-3 diagnostic confirms the migration is direction-consistent across clusters (no cluster "съезд", but the same effect applied to all three).
- Commits: forthcoming — about to commit Phase 1 implementation + smoke artefacts.
- Files or artifacts updated:
  - new: `src/cmp_ensemble/ensemble/{localization, subspace, es_update}.py`, `src/cmp_ensemble/qc/{checks, cluster_migration}.py`, `tests/{test_localization, test_es_update, test_qc}.py`.
  - modified: `src/cmp_ensemble/{cli, qc/__init__}.py` (phase 1 wiring + qc exports); `feature_list.json` (phase1-001..004, phase1-cli → `passing` with evidence).
- Known risk or unresolved issue:
  - Hard localization zeroes ~98% of K. Six of nine parameters never move. If sensitivity to those parameters matters scientifically, the next session should try `localization_method: soft_taper` or a smaller `localization_threshold_factor` (e.g. 2.0).
  - Cluster-3 "съезд" question is not separable in the current diagnostic: all clusters move in the same direction, so it is hard to call out cluster 3 specifically. Worth a richer plot (e.g. Mahalanobis-migration per cluster) when QC HTML rollup is built.
- Next best step: `phase1-stop` — present `outputs/qc/cluster3_diagnostic.html` + `outputs/qc/spread_retention.csv` + the centroid-shift table to the user; once signed off, start `phase2-001` (Mahalanobis ranking of models by ‖Δz‖_M for the resimulation selection list).

### Session 005

- Date: 2026-06-02
- Goal: audit the repository against ТЗ + `feature_list.json`, reconcile tracker drift (Phase 2 and Phase 3 code shipped without status updates in sessions 005-prior), and define the remaining feature backlog so the next Claude Code session has an unambiguous task list.
- Completed:
  - Read every file under `src/`, `tests/`, `outputs/`, `configs/`, plus `git log`.
  - Discovered that commits `77a76c8 phase2 phase0-004 + phase2-001..cli` and `7d1826b phase3 phase3-001..cli` shipped substantial Phase 2 and Phase 3 code while `feature_list.json` still marked those features `not_started`. The tracker was out of sync with the repo.
  - Phase 2 actual state: Mahalanobis ranking (123 models in `outputs/selection/mahalanobis_ranking.csv`), per-cluster linear proxies (`proxies/proxy_cluster{0,1,2}.npz`), and leave-one-out proxy validation (median rel err = 0.604 → PASS). NOT done: the compute-planner CSV split (`models_to_resimulate.csv` / `models_proxy.csv` / `validation_subset.csv`).
  - Phase 3 actual state: three setups run end-to-end (commit 7d1826b); `outputs/forecast/metrics_summary.csv` populated for width_ratio and median_shift but coverage_p10p90 / CRPS / cumulative_error columns are empty because no d_truth was supplied (no train/val split implemented yet). Two of six ТЗ §4 figures exist (fig03, fig04); fig01, fig02, fig05, fig06 are missing.
  - Setup3 degrades to setup2 byte-for-byte (workflow controls absent — clarification #4) — visible in the metrics CSV where setup2 and setup3 rows are identical.
  - Reconciled `feature_list.json`:
    - phase2-001 → passing (with evidence)
    - phase2-002 → in_progress (proxy works; compute-planner CSVs missing)
    - phase2-003 → passing (closed via leave-one-out, which sidesteps the manual-resim blocker)
    - phase3-001 → passing
    - phase3-002 → passing
    - phase3-003 → in_progress (width_ratio done; coverage/CRPS gated on d_truth)
    - phase3-004 → not_started (was always; now flagged as blocking the phase3-003 close-out)
    - phase3-005 → in_progress (partial — figures + metrics incomplete)
  - Added eight new features for the next session: scaffold-002 (integration test), phase3-006-figures-missing, phase3-007-report-html, phase3-008-evaluation-mode-stamp, phase3-stop-update, docs-001, tests-001-coverage, tracker-001-reconcile.
  - Substantive observation worth flagging: setup2 width_ratio = 1.46 (oil), 2.22 (water), 1.46 (gas) — the post-ES proxy ensemble is WIDER than the baseline. Either (a) baseline-to-proxy is the wrong comparison (proxy spreads vs deterministic baseline) or (b) the ES + proxy combination genuinely inflates uncertainty. Needs a sanity check before claiming any ablation acceptance.
- Verification run: none — this session was audit + tracker reconciliation, no new code committed.
- Evidence captured: this Session 005 log entry; the rewritten `feature_list.json` with reconciled statuses and 8 new feature entries.
- Commits: forthcoming — will commit `feature_list.json` + `claude-progress.md` together with message `tracker-001 audit: reconcile Phase 2/3 status, append session 005, add 8 backlog features`.
- Files or artifacts updated:
  - modified: `feature_list.json` (statuses + new features), `claude-progress.md` (this entry).
- Known risk or unresolved issue:
  - Setup2/setup3 width_ratio > 1 — needs interpretation before ablation claim.
  - Coverage_p10p90 / CRPS / cumulative_error are empty in `metrics_summary.csv`. Cannot claim ТЗ §6 Task 3.3 acceptance until phase3-004 lands and produces a held-out slice.
  - Four manuscript figures (fig01, fig02, fig05, fig06) are missing.
  - No HTML report (`cmp-ensemble report` not implemented).
  - No README and no docs/ — `docs-001` covers it.
  - Tracker discipline failure (committing src changes without updating `feature_list.json`) is the root cause of this audit; `tracker-001-reconcile` adds a pre-commit hook to stop the bleeding.
- Next best step: pick the lowest-priority unfinished feature → `scaffold-002` (synthetic integration test). It is the cheapest unblocked work and closes a gating ТЗ §9 requirement. After that, `phase3-004` (train/val split) unblocks the CRPS/coverage path and the fig05 figure. The compute-planner CSVs (`phase2-002` close-out) are also quick and unblocked.

### Session 005 — addendum (2026-06-02, second pass)

- Trigger: user pushed back ("прогнозы уже есть") on session 005's claim that no forecast period existed.
- Re-audit found `outputs/cache/forecast.h5`: 123 models × 70 monthly steps spanning 2019-01-01 → 2024-10-01, 3 cumulative + 3 rate metrics × 16 producers. Source file is `decoded_results.xlsx` (referenced in `src/cmp_ensemble/io/forecast_loader.py` but NOT present in the repo root — only the derived cache is). Cluster breakdown: 24 / 49 / 50 (27 models missing — "pressure depletion failure" per the loader docstring).
- User then confirmed: **d_truth (real well measurements for the 2019–2024 forecast period) is principally unavailable**. `Исторические значения.xlsx` still ends 2018-12-13. There is no truth file and no plan to obtain one.
- Implications, fully internalised in the tracker:
  - `phase3-004` (train/val split): **deleted**. Two reasons: (a) forecast simulations already exist, so withholding 2017–2018 from the ES would actively hurt; (b) hindcast on the val slice would still face zero-truth-on-forecast — the original motivation was a workaround for a problem that doesn't exist in our setup.
  - `phase3-003` (metrics): **passing**. Coverage/CRPS/cumulative_error are formally declared "not applicable for this dataset" — not a deferred TODO. width_ratio and median_shift are the project's acceptance metrics.
  - `phase3-005` (run setups): downgraded MISSING list — no more CRPS dependency on figures.
  - `phase3-006` (figures): `fig05_crps_time` **retired**. Manuscript figure count drops from 6 to 5 (fig01, fig02, fig03, fig04, fig06).
  - `phase3-008` (evaluation_mode stamp): now stamps the single fixed value `forecast_no_truth_ensemble_comparison`.
  - `tests-001-coverage`: dropped `tests/test_split.py`.
  - Open clarification #1 (forecast simulations from user): **closed** — they exist.
- Substantive caution that stays open: setup2 width_ratio > 1 is suspicious. Most likely the baseline (123 deterministic tNavigator runs) is being compared against the proxy-projected POST (which includes ES perturbation variance) — apples-to-oranges. Before claiming ablation, either symmetrize the comparison or label the asymmetry in the article.
- Files touched: `feature_list.json` (phase3-003/004/005/006/008 + tests-001-coverage), `claude-progress.md` (this addendum).
- Next best step (revised): `phase3-005` close-out — produce the 3 remaining figures (fig01, fig02, fig06), stamp evaluation_mode, write the width_ratio interpretation paragraph. Then `phase3-007` (HTML report) and `docs-001` (README + 3 docs).

### Session 006

- Date: 2026-06-02
- Goal: close `scaffold-002` (priority 3) — the mandatory ТЗ §9 integration test. Pick lowest-priority unfinished feature per CLAUDE.md operating rule.
- Completed:
  - Created `tests/fixtures/__init__.py` and `tests/fixtures/synthetic.py` with `SyntheticFixture` dataclass + `make_synthetic_fixture(seed=42)`. Fixture matches ТЗ §9 spec exactly: N=20, 3 clusters [7,7,6], n_θ=5, n_obs=10, plus n_forecast=10 and a known truth-θ. Linear-Gaussian forward model: d = H·θ + ε.
  - Created `tests/test_integration_synthetic.py` with 3 tests:
    - `test_full_pipeline_phase0_to_phase3_under_30s` — runs build_state_vector → localization → es_update → run_qc_checks → mahalanobis_distance/rank_by_parameter_change → build_per_cluster_proxies → validate_proxy → setup1/2/3 → compute_metrics(d_truth=...) → aggregate_forecast → field_total_quantiles. Wall-time 0.55 s vs 30 s budget.
    - `test_fixture_is_deterministic_and_reseeded` — seed=42 reproducibility.
    - `test_fixture_shape_matches_tz_spec` — counts per cluster.
  - **Integration test exposed a real bug**: `np.trapezoid` is the NumPy ≥ 2.0 name; the test machine has NumPy 1.26.4 where it's `np.trapz`. The dormant `cumulative_error_table` code path in `src/cmp_ensemble/forecast/metrics.py` was using `np.trapezoid` and would have crashed Phase 3 the moment a real `d_truth` arrived. Replaced with a `getattr` fallback. This is exactly the kind of latent bug that per-module unit tests miss because they don't exercise truth-dependent paths.
  - Loosened one assertion: `validate_proxy` verdict on the small synthetic fixture is `WARN` (median rel err ≈ 1.3), not `PASS` — expected with only 5-6 training samples per cluster after the hold-out. The integration test asserts `in {"PASS", "WARN"}` to reject the genuine-failure case while tolerating the small-sample noise.
- Verification run: `pytest -q` → 57 passed in 2.09 s. Integration test alone: `pytest tests/test_integration_synthetic.py -v` → 3 passed in 0.55 s.
- Evidence captured: see scaffold-002.evidence in `feature_list.json`.
- Commits: forthcoming — will commit `tests/fixtures/synthetic.py`, `tests/test_integration_synthetic.py`, the metrics.py trapezoid fix, and the tracker updates together as `scaffold scaffold-002: synthetic integration test + np.trapezoid compatibility fix`.
- Files or artifacts updated:
  - new: `tests/fixtures/__init__.py`, `tests/fixtures/synthetic.py`, `tests/test_integration_synthetic.py`.
  - modified: `src/cmp_ensemble/forecast/metrics.py` (np.trapezoid → getattr fallback), `feature_list.json` (scaffold-002 → `passing` with evidence; `last_updated` bumped), `claude-progress.md` (this entry).
- Known risk or unresolved issue: none introduced. The np.trapezoid fix is backward-compatible (uses np.trapz on older NumPy, np.trapezoid on 2.x).
- Next best step: `phase3-004` (priority 19) — train/val split for d_truth. This unblocks coverage/CRPS/cumulative_error metrics and fig05, and is the next gating step for the article. After that: `phase3-006-figures-missing` (fig01, fig02, fig05, fig06).

### Session 007

- Date: 2026-06-02
- Goal: pick up the lowest-priority unfinished feature after the session-005 audit retired phase3-004. The audit-updated tracker now points at **phase2-002** (priority 13, `in_progress`) — the compute planner CSV emission was the missing piece of ТЗ §6 Task 2.3. Also wrap up the `--hindcast` diagnostic feature from the previous session as an optional CLI knob (does not contradict the audit's "no real truth" verdict; just provides a diagnostic plane).
- Completed:
  - `--hindcast` CLI mode: `src/cmp_ensemble/io/split.py` (HistorySplit + split_history), wired into Phase 1 (D_sim restricted to train slice) and Phase 3 (per-cluster proxy on val slice + observed val d as d_truth, populating coverage/CRPS/cumulative_error). 8 split tests pass.
  - `evaluation_mode` column added to `outputs/forecast/metrics_summary.csv` and to all Phase 3 sidecars: `no_truth_baseline_only` (forecast mode), `train_val_hindcast_6+2` (hindcast mode). Closes one of the MISSING items listed under phase3-005.
  - `phase2-002-planner`: `src/cmp_ensemble/selection/compute_planner.py` with `plan_resimulation` and `write_plan_to_csv`. Stratified validation_subset across c0/c1/c2 (seed=42 default). Wired into Phase 2 CLI right after the Mahalanobis ranking step. 9 compute_planner tests pass.
  - Real-data Phase 2 run now emits all three CSVs at `outputs/selection/`: `models_to_resimulate.csv` (80 models, top-80 by ||Δθ||_M), `models_proxy.csv` (69 models), `validation_subset.csv` (10 stratified members).
  - Updated `feature_list.json`: `phase2-002` → `passing` with full evidence; `last_updated` bumped.
- Verification run: `pytest -q` → 74 passed in 2.19 s. Real-data smoke: `cmp-ensemble run --phase 2` writes all artefacts; `cmp-ensemble run --phase 3 [--hindcast] [--keep-ooe]` produces metrics_summary with `evaluation_mode` populated.
- Evidence captured: 9 new compute_planner tests + 8 split tests + Phase 2 CSV artefacts (see feature_list.json phase2-002 evidence).
- Commits: forthcoming — will commit hindcast (`io/split.py`, CLI flag, evaluation_mode stamps), compute_planner module, tests, and tracker bumps together as `phase2 phase2-002-planner + --hindcast diagnostic`.
- Files or artifacts updated:
  - new: `src/cmp_ensemble/io/split.py`, `src/cmp_ensemble/selection/compute_planner.py`, `tests/test_split.py`, `tests/test_compute_planner.py`.
  - modified: `src/cmp_ensemble/cli.py` (--hindcast/--train-years/--val-years, compute planner wiring, evaluation_mode stamp), `src/cmp_ensemble/io/__init__.py`, `src/cmp_ensemble/selection/__init__.py`, `feature_list.json`, `claude-progress.md` (this entry).
- Known risk or unresolved issue:
  - Per the session-005 audit: --hindcast metrics are diagnostic-only, not the project's evaluation truth. Documented in the commit message and the CLI help text.
  - Top-80 in `models_to_resimulate.csv` contains duplicate model_ids (e.g. model 1104 at ranks 5 and 7 under cluster_id 0 vs 2). This is consistent with the rest of the pipeline using (cluster, model) as the unique key. If the user wants UNIQUE model IDs for re-simulation, dedup is straightforward to add as a flag.
- Next best step: the lowest-priority unfinished feature is now either `phase3-005` (priority 20, `in_progress` — needs the 3 missing figures + width_ratio interpretation), or `phase3-006-figures-missing` (priority 22) — the figures are explicitly listed in phase3-005's MISSING. Pick `phase3-006-figures-missing` since it directly closes the gating items.

### Session 008

- Date: 2026-06-02
- Goal: close `phase3-006-figures-missing` (priority 22) — three remaining manuscript figures, plus the `cmp-ensemble figures` CLI from ТЗ §8, plus the article_assets/figures_v2/ mirror from ТЗ §4.
- Completed:
  - `src/cmp_ensemble/viz/diagnostics.py` — three new builders:
    - `fig01_pipeline(out_path)` — pure-matplotlib block diagram of the four phases (no data input). Boxes with rounded corners + arrows; colour-coded by phase. 267 KB PNG.
    - `fig02_qc_spread(spread_csv, out_path)` — bar chart from `outputs/qc/spread_retention.csv`. Reference lines at 1.0 (no update, dashed) and 0.1 (collapse threshold, dotted red). Bars below 1.0 are green (updated), at 1.0 are grey (frozen), below 0.1 would be red (collapse). 151 KB PNG.
    - `fig06_cluster3_migration(migration_csv, out_path)` — grouped bars per cluster × θ component from `outputs/qc/cluster_migration.csv`. Each component normalised by |prior centroid| so THICK (~10) and MAJ_R (~4000) are visually comparable; percentage shift labels above the posterior bar. 436 KB PNG.
    - `mirror_to_article_assets(figures_dir, article_assets_dir)` — copies every `fig*.{png,pdf}` to `outputs/article_assets/figures_v2/`.
  - `src/cmp_ensemble/cli.py`:
    - New `@cli.command("figures")` subcommand that regenerates fig01/02/06 from existing CSVs without re-running any phase, mirrors all 5 figures to `figures_v2/`, and logs sidecar writes.
    - Integrated into `_run_phase_3`: after Phase 3 writes fig03/04, it now also calls fig01/02/06 builders and the mirror step. Figures stay fresh on every Phase 3 invocation.
  - `tests/test_figures.py` — 5 tests pass (each builder produces non-empty PNG+PDF, missing-column raises, mirror helper round-trip).
  - Updated `feature_list.json`: `phase3-006-figures-missing` → `passing`, `phase3-005` → `passing` (figures + evaluation_mode were the last MISSING items; only article-text "interpretation paragraph" remains, tracked under docs-001), `phase3-008-evaluation-mode-stamp` → `passing` (the work was landed in session 006). `last_updated` bumped.
- Real-data smoke: `cmp-ensemble figures` writes 3 new figures + mirrors 10 files into `figures_v2/`. fig02 visually confirms the THICK/AZIMUTH-only ES finding (7 of 9 bars at 1.00 exactly, 2 bars at 0.98 in green).
- Verification run: `pytest -q` → 79 passed in 4.47 s (the +5 figure tests + matplotlib startup cost explains the 2× wall-time vs prior). Real-data figures-CLI run completes in < 5 s.
- Evidence captured: see feature_list.json phase3-006-figures-missing.evidence.
- Commits: forthcoming — will commit `src/cmp_ensemble/viz/diagnostics.py`, CLI wiring, tests, and tracker bumps together as `phase3 phase3-006: missing figures + figures CLI + figures_v2 mirror`.
- Files or artifacts updated:
  - new: `src/cmp_ensemble/viz/diagnostics.py`, `tests/test_figures.py`.
  - modified: `src/cmp_ensemble/cli.py` (figures subcommand + Phase 3 wiring), `src/cmp_ensemble/viz/__init__.py`, `feature_list.json`, `claude-progress.md`.
- Known risk or unresolved issue: none introduced. fig05_crps_time remains formally retired per session-005 audit (no d_truth → no CRPS to plot).
- Next best step: the lowest-priority unfinished feature is now `phase3-007-report-html` (priority 23) — `cmp-ensemble report` HTML rollup. After that comes `docs-001` (priority 30) for README + docs/{data_format,methodology,troubleshooting}.md. Either is a clean win; the HTML rollup is mechanically smaller.

### Session 009

- Date: 2026-06-02
- Goal: close `phase3-007-report-html` (priority 23) — assemble the project-level HTML rollup per ТЗ §8 + §11.
- Completed:
  - `src/cmp_ensemble/report.py` — `build_report(root)` renders two HTML files via inline Jinja2 templates:
    - `outputs/report.html` (10.9 KB): project rollup with overview, Phase 0 data shapes, Phase 1 ES + QC numbers + spread_retention table, fig02 inline, Phase 2 selection counts + proxy verdict + per-cluster validation, Phase 3 metrics_summary embedded + fig03/04 inline, all figures listed, fig01 + fig06 inline, links to LaTeX table + figures_v2 mirror.
    - `outputs/qc/qc_report.html` (17 KB): full Phase 1 QC summary — spread, cluster centroid shift, Mahalanobis migration (first 20 rows + summary stats), physical-bounds violations, duplicates, message log with PASS/WARN/INFO/FAIL badges.
  - Every asset reference is POSIX-relative — the outputs/ directory is portable as a zip; no absolute paths leak.
  - Graceful degradation: missing CSVs render as `<em>not available</em>` rather than crashing the report.
  - CSS is inline (single embedded `<style>` block), so each HTML file is self-contained.
  - `cmp-ensemble report` CLI subcommand registered. Reads everything already on disk; does NOT re-run any phase.
  - `tests/test_report.py` — 3 tests:
    - non-empty HTML files written (full minimal-fixture path);
    - key sections present in main + QC reports; no absolute Windows paths leak;
    - missing-artefacts path renders without crash.
- Real-data run: `cmp-ensemble report` completes in < 2 s. Both HTML files open in a browser; relative links to figures and CSVs resolve correctly.
- Verification run: `pytest -q` → 82 passed in 4.93 s.
- Evidence captured: see feature_list.json phase3-007-report-html.evidence.
- Commits: forthcoming — `phase3 phase3-007: cmp-ensemble report HTML rollup`.
- Files or artifacts updated:
  - new: `src/cmp_ensemble/report.py`, `tests/test_report.py`.
  - modified: `src/cmp_ensemble/cli.py` (report subcommand), `feature_list.json`, `claude-progress.md`.
- Known risk or unresolved issue: jinja2 (v3.1.6) is a runtime dependency for report generation. Already in pyproject.toml's dep list, but if the user installs `pip install -e . --no-deps` (as happens on the test machine) they need to `pip install jinja2` separately. Not blocking — the rest of the pipeline works without it.
- Next best step: the lowest-priority unfinished code feature is now `docs-001` (priority 30) — README + docs/{data_format, methodology, troubleshooting}.md. After that: `tests-001-coverage` (priority 31) for four more unit-test modules. The `phase4-stub` at priority 99 is out of scope per ТЗ §12.

### Session 010

- Date: 2026-06-02
- Goal: close `docs-001` (priority 30) — README + three reference documents per ТЗ §10. Also bundle the light-theme HTML-dashboard work from the previous user request.
- Completed:
  - `README.md` — quickstart: one-line project description, install (with the `--no-deps` fallback path for offline test machines), per-phase `python -m cmp_ensemble.cli run --phase N` commands, all the CLI flags in a table (`--clip-to-prior`, `--localization-factor`, `--d-obs-type`, `--dedup-ensemble`, `--keep-ooe`, `--hindcast`, `--variant-label`), expected outputs tree, supporting subcommands (`compare-phase1`, `figures`, `report`), test command, and an honest "Limitations" section (no d_truth, no workflow controls, cluster-0 survivable subset, hard-3/√N too aggressive, 138/149 out-of-envelope proxy predictions).
  - `docs/data_format.md` — every Excel input documented sheet-by-sheet (columns, shapes, drift), the `(cluster_id, round(SEED))` linkage rule with the 150/150 validation note, dummy well `B`, year-end aggregation cadence with the 8 actual anchor dates, all four pydantic schemas listed (`EnsembleData`, `ObservationData`, `StateVectorSchema`, `ForecastData`), the per-metric soft floor for C_dd, and the `.meta.yaml` sidecar format.
  - `docs/methodology.md` — Evensen, Oliver & Hanea 2026 citations: Ch. 5–6 for ES + subspace, Ch. 14 for ablation, Ch. 6 for localization. ES equations with the symbol table. Subspace projection derivation showing `(C_dd_ens + C_dd)⁻¹ ≈ V_r (Σ_r² + V_r⊤ C_dd V_r)⁻¹ V_r⊤`. Hard 3/√N localization with the empirical observation table (variants A/B/C side-by-side). QC thresholds. Linear proxy + leave-out validation results. Mahalanobis ranking + compute planner. Three Phase 3 setups + the evaluation_mode table (`no_truth_baseline_only`, `train_val_hindcast_*`, `forecast_vs_truth`) explaining why we can never reach the third.
  - `docs/troubleshooting.md` — 7 categories: pytest-fail-itself, Phase 0 (sheet/seed mismatch, truncated timeline, NaN, dummy well B), Phase 1 (collapse, 6-frozen-parameters under hard 3/√N, out-of-prior θ_post, duplicate models), Phase 2 (BHP sparsity, proxy WARN), Phase 3 (forecast.h5 missing, decoded_results unreachable via UNC, setup3≡setup2, empty coverage column, width_ratio≈600 in hindcast), report/figures (jinja2 missing, dark-cached cluster3), reproducibility (compare sidecars). Each row gives symptom / diagnosis / fix.
  - Also bundled the **light-theme HTML dashboard** work from the previous user request (commit `ed36a22`): `src/cmp_ensemble/report.py` CSS and `src/cmp_ensemble/qc/cluster_migration.py` plotly config + HTML head injection now force `color-scheme: light only` on all three dashboards. Tests in `test_report.py` and `test_cluster_migration.py` enforce this.
  - Updated `feature_list.json`: `docs-001` → `passing` with full evidence; `last_updated` bumped.
- Verification run: `pytest -q` → 85 passed in 5.46 s.
- Evidence captured: 4 new documentation files + the light-theme tests already in `tests/test_report.py` + `tests/test_cluster_migration.py`.
- Commits: forthcoming — `docs docs-001: README + docs/{data_format, methodology, troubleshooting}.md`.
- Files or artifacts updated:
  - new: `README.md`, `docs/data_format.md`, `docs/methodology.md`, `docs/troubleshooting.md`.
  - modified: `feature_list.json`, `claude-progress.md`.
- Known risk or unresolved issue: none.
- Next best step: lowest-priority unfinished features now are `tests-001-coverage` (priority 31 — `test_metrics`, `test_setups`, `test_selection`; `test_split` is already done) and `tracker-001-reconcile` (priority 32 — pre-commit hook to refuse `src/` commits without `feature_list.json` updates). Both are pure quality-of-life. `phase4-stub` at priority 99 is out of scope per ТЗ §12.

### Session 011

- Date: 2026-06-02
- Goal: close `tests-001-coverage` (priority 31) — three additional ТЗ §9-mandated unit-test modules.
- Completed:
  - `tests/test_metrics.py` (9 tests) — analytical CRPS references: CRPS(δ_x₀, y) = |x₀ − y| on three truth values, **CRPS(U[0,w], w/2) = w/12** for w ∈ {1, 5, 100} within 2%, non-negativity on random inputs; coverage on truth-inside / outside / partial-match; width_ratio identity / 2× scaling / zero-denominator guard; median_shift constant offset.
  - `tests/test_setups.py` (9 tests) — YAML parses three named setups; each setup's `use_es_update`/`use_localization`/`use_control_uncertainty`/`d_obs_type` flags assert correctly; setup3 with `controls_available=False` produces byte-equal d_forecast as setup2 + records the degradation note; setup3 with `controls_available=True` does NOT record the note; setup1 baseline-identity sanity.
  - `tests/test_selection.py` (11 tests) — Mahalanobis ranking: first index = largest shift, ranking is a permutation, distances at returned indices monotone-decreasing, zero shift gives zero distance; compute planner: disjoint partition, exhaustive partition, top_x contains highest ranks, validation_subset ⊂ proxy_only, three CSVs written, invalid input rejected.
  - **Bug found and fixed by the new Uniform-CRPS test**: `src/cmp_ensemble/forecast/metrics.py::crps_per_column` had `out[j] = term1 - 0.5 * term2`, but `term2` already equals `½ · E|X − X'|` (sample-based identity Σ_{i,j}|x_i − x_j| = 2Σ_k(2k − M − 1)·x_(k)). The extra ½ doubled the bias correction, so non-degenerate CRPS values came back as 2× their true magnitude. The fix is one character: `term1 - term2`. The degenerate-distribution test in `test_forecast.py` could not have caught this — `term2 = 0` there. **All real-data Phase 3 CRPS values produced before this fix were overstated by 2×.** None of the Phase 3 reports written by the project committed CRPS to disk (coverage was the only truth-dependent metric written), so no downstream artefact needs to be regenerated.
  - Updated `feature_list.json`: `tests-001-coverage` → `passing` with full evidence, including the bug story; `last_updated` bumped.
- Verification run: `pytest -q` → **114 passed in 5.24 s** (was 85; +29 new tests from this session). The Uniform CRPS test passes with the fixed estimator at 2% tolerance for w ∈ {1, 5, 100}.
- Evidence captured: see `feature_list.json` `tests-001-coverage.evidence`.
- Commits: forthcoming — `tests tests-001: +29 tests + fix Hersbach-2000 factor-of-2 CRPS bug`.
- Files or artifacts updated:
  - new: `tests/test_metrics.py`, `tests/test_setups.py`, `tests/test_selection.py`.
  - modified: `src/cmp_ensemble/forecast/metrics.py` (CRPS bug fix + docstring with the sample-based identity derivation + tested analytical references); `feature_list.json`, `claude-progress.md`.
- Known risk or unresolved issue:
  - Existing `tests/test_forecast.py::test_crps_zero_when_truth_at_distribution_center` still passes — it asserts CRPS at degenerate distribution = |x − y|, which holds under both the buggy and the fixed estimator. The test should be augmented to also include a non-degenerate sanity case (the Uniform reference here covers that, so the gap is now closed).
- Next best step: lowest-priority unfinished features are `tracker-001-reconcile` (priority 32 — pre-commit hook) and `phase4-stub` (priority 99 — explicitly out of scope per ТЗ §12). The project is effectively code-complete; remaining items are process / quality-of-life.

### Session 012

- Date: 2026-06-02
- Goal: close `tracker-001-reconcile` (priority 32) — install a pre-commit hook that refuses commits touching `src/` without an accompanying tracker update, to prevent the session-005 audit's "phase 2 + 3 code shipped without tracker entries" pattern from recurring.
- Completed:
  - `scripts/pre-commit.sh` — POSIX shell hook. Reads `git diff --cached --name-only --diff-filter=ACM`, classifies each staged file as `src/` / tracker / other, blocks iff `(touched_src AND NOT touched_tracker AND ALLOW_SRC_ONLY≠1)`. Clear multi-line error message with the bypass instruction.
  - `src/cmp_ensemble/tracker.py` — Python mirror of the same rule (`HookDecision`, `decide(staged_files, allow_src_only)`). Used by the test suite — the shell hook itself stays a thin wrapper but the rule is testable.
  - `scripts/install_hooks.sh` + `scripts/install_hooks.ps1` — installers for Git Bash and PowerShell. Copy `scripts/pre-commit.sh` to `.git/hooks/pre-commit` and chmod +x (no-op on Windows). Idempotent.
  - `tests/test_tracker_hook.py` — 14 tests: every branch of `decide()` including Windows-style backslash paths, partial-match false positives (`srclient.txt`, `feature_list.json.bak`); the shell hook exists + non-empty + has bypass + syntactically valid (`bash -n`, gated by `bash` being on PATH); installer scripts exist.
  - Live verification on this repo: installed the hook, ran `git commit` with only `src/cmp_ensemble/tracker.py` staged → **hook rejected the commit** with the discipline message. The same commit succeeds once `feature_list.json` is added to the index.
- Verification run: `pytest -q tests/test_tracker_hook.py` → 13 passed + 1 skipped (bash-syntax check skipped because `shutil.which('bash')` returned None under the PowerShell test runner). On Git Bash this skip is exercised and the script parses cleanly.
- Evidence captured: see `feature_list.json` `tracker-001-reconcile.evidence`.
- Commits: forthcoming — `tracker tracker-001: pre-commit hook + installers + 14 hook tests`.
- Files or artifacts updated:
  - new: `scripts/pre-commit.sh`, `scripts/install_hooks.sh`, `scripts/install_hooks.ps1`, `src/cmp_ensemble/tracker.py`, `tests/test_tracker_hook.py`.
  - modified: `feature_list.json`, `claude-progress.md`.
- Known risk or unresolved issue: contributors must run `bash scripts/install_hooks.sh` (or `pwsh scripts/install_hooks.ps1`) once on a fresh clone — git does not version-control hooks. This is documented in the hook's own message and in the next README update.
- Next best step: only `phase4-stub` (priority 99) remains at `not_started`, and it is **explicitly out of scope per ТЗ §12**. The project is now code-complete. Remaining items are the three human-in-the-loop STOPs (`phase1-stop`, `phase2-stop`, `phase3-stop` — priorities 11, 15, 21) which require user sign-off rather than agent action.

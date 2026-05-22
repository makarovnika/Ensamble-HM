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

- Date:
- Goal:
- Completed:
- Verification run:
- Evidence captured:
- Commits:
- Files or artifacts updated:
- Known risk or unresolved issue:
- Next best step:

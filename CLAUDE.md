# CLAUDE.md

You are working on **CMP Ensemble HM** — a Python pipeline that performs a post-hoc Ensemble Smoother (ES) update with localization and a three-setup ablation forecast on 150 pre-computed tNavigator models for the CMP / Watt Field history-matching study.

Methodology source: Evensen, Oliver, Hanea (2026), Chapters 5–6 (ES, subspace regularisation), Chapter 14 (ablation reporting).
Operational reference: [TZ_ensemble_forecast.md](TZ_ensemble_forecast.md) — the canonical technical specification. Treat it as authoritative when it conflicts with anything else.

Prioritize reliable completion, continuity across sessions, and explicit verification over speed.

## Operating Loop

At the start of every session:

1. Run `pwd` and confirm you are in `F:/СМП/Статья 2.0/Ensamble HM` (Git Bash) or `F:\СМП\Статья 2.0\Ensamble HM` (PowerShell).
2. Read `claude-progress.md`.
3. Read `feature_list.json`.
4. Review recent commits with `git log --oneline -5` (note: the repo is not yet git-initialised — Feature `scaffold-000` covers that).
5. Run `./init.sh` from Git Bash, or `pwsh ./init.ps1` if a PowerShell variant exists. On Windows without Git Bash, run the equivalent commands manually: `python -m pip install -e .[dev]` and `pytest -q`.
6. Check whether the baseline smoke / synthetic-integration test (`pytest tests/test_integration_synthetic.py`) is still green.

Then select exactly one unfinished feature (lowest `priority` number first, status `not_started` or `in_progress`) and work only on that feature until you either verify it or document why it is blocked.

## Rules

- **One active feature at a time.** Only one feature in `feature_list.json` may have status `in_progress`.
- **Do not claim completion without runnable evidence.** "Passing" requires either a pytest run log or a saved artifact under `outputs/` referenced in the `evidence` field.
- **Do not rewrite the feature list to hide unfinished work.** If a feature turns out larger than expected, split it — do not retroactively narrow its scope.
- **Do not remove or weaken tests just to make the task look complete.** If a synthetic-dataset test fails, fix the implementation, not the assertion.
- **Use repository artifacts as the system of record.** Numerical results live in `outputs/`, not in chat. Decisions live in `claude-progress.md`.
- **Do not implement Phase 4 (APS soft-category) until Phases 0–3 are all `passing`.** Phase 4 is explicitly out-of-scope for the first iteration per [TZ_ensemble_forecast.md](TZ_ensemble_forecast.md) §12.
- **Do not modify the input data files** (`Исторические значения.xlsx`, `Кроссплоты.xlsx`, `Показатели динамики.xlsx`, `models_near_adapted_centroids.xlsx`). They are the system of record for inputs. If a format issue blocks loading, document it and ask before touching the file.
- **Do not auto-launch tNavigator.** The pipeline writes a list of model IDs to `outputs/selection/models_to_resimulate.csv`; the user runs the simulator and returns the results.

## Required Files

- `feature_list.json` — feature tracker
- `claude-progress.md` — session log
- `init.sh` — startup + baseline verification path
- `session-handoff.md` — compact handoff for end-of-session
- `clean-state-checklist.md` — pre-stop checklist
- `TZ_ensemble_forecast.md` — canonical specification (do not edit without user approval)

## Completion Gate

A feature moves to `passing` only when **all** of the following hold:

1. Implementation merged into `src/cmp_ensemble/`.
2. Targeted unit test(s) for that feature exist under `tests/` and pass.
3. The integration test on the synthetic fixture (20 models, 5 params, 10 obs) still passes end-to-end in under 30 seconds.
4. Evidence (pytest output path or output-artifact path) is recorded in the `evidence` field of the feature entry.

For phase-level features whose evidence is a numerical artifact rather than a unit test (e.g. `qc-report-001`), evidence must be a path under `outputs/qc/` that the next session can re-open without re-running the pipeline.

## Before You Stop

1. Update `claude-progress.md` — append a Session NNN block.
2. Update `feature_list.json` — adjust statuses, add evidence paths.
3. Record any unresolved risk or blocker in the session log AND in the active feature's `notes` field.
4. Run through `clean-state-checklist.md`.
5. Commit once the repository is safe to resume. Commit message format: `phase<N> <feature-id>: <short description>`.
6. Leave a clean restart path: the next session must be able to run `./init.sh` immediately without manual repair.

## Project-Specific Conventions

- **Language**: Python 3.11+. No JavaScript / npm in this project — the template's npm references in `init.sh` have been replaced with pip + pytest.
- **Determinism**: any function that draws random numbers takes a `seed: int` argument with a documented default. The default ES perturbation seed is `42` (see [configs/default.yaml](configs/default.yaml) once scaffolded).
- **Linear algebra**: prefer `numpy.linalg` + explicit SVD truncation over `scipy.sparse.linalg.svds`. Subspace energy default is `0.99`.
- **Reproducibility**: every script that writes to `outputs/` also writes a sidecar `*.meta.yaml` with git SHA, seed, config hash, and timestamp.
- **Validation**: input file schemas live in `src/cmp_ensemble/io/schemas.py` as pydantic v2 models. If a real input file deviates from the schema, update the schema and add a regression fixture — do not silently coerce.
- **Logging**: use `rich.logging.RichHandler` at INFO level for CLI, DEBUG to file `logs/<timestamp>.log`.
- **Plots**: matplotlib + seaborn. Save both `.png` (300 dpi, for the article) and `.pdf` (vector, for `article_assets/figures_v2/`).

## Known Initial State (as of session 2)

- The repository contains the ТЗ, four input Excel files, and this harness. No Python source tree, no `pyproject.toml`, no `tests/`, no `data/` subdirectory yet.
- **Data contract resolved in session 002** (see `claude-progress.md` → "Confirmed data contract"). Summary: inputs are Excel-only; loaders read `.xlsx` directly via `openpyxl`/`pandas`; n_θ = 9; 17 producers + 6 injectors; time grid 2011-2018 monthly; **no forecast period exists** (Phase 3 runs on a 6+2 train/val hindcast).
- Phase 0, Phase 1, Phase 2 are **unblocked**. Phase 3 runs in hindcast mode unless the user produces forecast tNavigator simulations. Phase 4 inputs are absent — and Phase 4 is out of scope per ТЗ §12 regardless.

## When To Ask The User

After the session-002 data audit, three of the original five ТЗ §15 questions are resolved (the data contract supplies the answers). The remaining open questions, each affecting only Phase 3 or later:

1. **Forecast simulations**: will the user run tNavigator on a forecast period after history (post-2018-12) for the X models in `models_to_resimulate.csv`? If no → Phase 3 stays in train/val hindcast mode (6 yr train, 2 yr val).
2. **`Адаптированный центроид →` row** in each sheet of `models_near_adapted_centroids.xlsx`: confirm this is the θ-space centroid of the cluster (the starting point shared by all 50 models in that cluster). Needed for the centroid-migration plot in `phase1-004`.
3. **Proxy-validation re-simulation budget**: is the user willing to manually re-simulate 10 models in tNavigator (Task 2.4)? If no → `phase2-003` stays blocked.

Newly surfaced by the audit:

4. **Workflow controls**: where do the 12 workflow parameters live (ТЗ §3 mentions `workflow_params.csv` 150 × 12) — or do they not exist for this dataset? If absent, setup3 (`use_control_uncertainty=true`) degrades to setup2 and the ablation table reports a 2-setup comparison.
5. **Cumulative aggregation cadence**: confirm year-end anchors for the annual-cumulative aggregation (2011-12-31 … 2018-12-31), or specify a different cadence.

Surface unresolved questions in the next user-facing reply rather than guessing.

# Evaluator Rubric

Use this rubric after implementation and before final acceptance of any feature in `feature_list.json`. Score each category on a 0–2 scale where 0 = clearly fails, 1 = partially meets, 2 = clearly meets. The rubric is consulted *after* the per-feature verification has already passed — it grades the surrounding quality of the work, not the binary "did it pass."

The evaluator's score is advisory. Final accept / revise / block sits with the user.

| Category | Question | Score (0-2) | Notes |
| --- | --- | --- | --- |
| Correctness | Does the implemented behavior match the feature's `user_visible_behavior` and the relevant ТЗ task? Are edge cases (NaN inputs, empty ensemble, missing truth, mismatched dimensions) handled? |  |  |
| Verification | Did the required checks listed in the feature's `verification` array actually run, and is the evidence (pytest output, artifact path, plot file) recorded in `evidence`? Synthetic-fixture integration test still green? |  |  |
| Scope discipline | Did the session stay inside the chosen feature? If a supporting fix was needed, is it documented in `notes`? No drive-by refactors, no started-but-unfinished side features? |  |  |
| Reliability | Does the result survive restart? Re-running `./init.sh` then the feature's verification on a fresh clone produces the same outputs (same numerical results modulo the documented seed)? |  |  |
| Maintainability | Code follows the project conventions in `CLAUDE.md` (Python 3.11+, pydantic schemas at boundaries, rich logging, sidecar `*.meta.yaml` for outputs)? Docstrings on public functions? No dead code? |  |  |
| Handoff readiness | Can a fresh session continue work from repo artifacts only? `claude-progress.md` is updated, `feature_list.json` reflects reality, the active feature's `notes` field is honest about what remains. |  |  |

## Project-Specific Pass / Fail Anchors

These anchors disambiguate the 0/1/2 boundary for the most common cases on this project. Update them whenever the rubric drifts from human judgment (see ТЗ §evaluation discipline).

- **Correctness 2** on ES update (`phase1-002`): on the synthetic fixture, median over components of `|mean(Z_post) - truth| / std(Z_prior) < 1.0`, AND no warnings in QC report.
- **Correctness 0** on Phase 1 generally: any `spread_retention < 0.1` for any component without an explanatory `notes` entry (collapse must be either fixed or explicitly accepted with reasoning).
- **Verification 2** on Phase 3 (`phase3-005`): all six figures produced AND `metrics_summary.csv` has one row per (setup × cluster × phase), AND the ablation acceptance inequality from ТЗ §6 is either satisfied or explicitly recorded as a negative result with the actual numbers (per ТЗ instruction "не подгоняем").
- **Verification 0**: any feature marked `passing` whose `evidence` array is empty or refers to a path that does not exist on disk.
- **Scope discipline 0**: APS-related code added before all of Phases 0–3 are `passing` (per ТЗ §12).
- **Reliability 0**: a re-run of the same `cmp-ensemble run --phase N` with the same config produces numerically different `outputs/matrices/*.npy` — indicates a missing seed or non-deterministic dependency.
- **Maintainability 0**: a public function with no type hints, or an output artifact without a sidecar `*.meta.yaml`.
- **Handoff readiness 0**: `claude-progress.md` Session block omits `Next best step` or `Known risk or unresolved issue`.

## Verdict

- Accept — meets the bar; the feature can be marked `passing` and the next priority can be picked up.
- Revise — needs specific fixes before acceptance. List them under "Required Follow-Up" with a target session for each.
- Block — fundamental issues (missing data contract, broken baseline, ТЗ ambiguity). Surface to the user; do not start the next feature.

## Required Follow-Up

- Missing evidence:
- Required fixes:
- Next review trigger: which feature ID should re-trigger this rubric (typically the next phase's STOP feature, e.g. `phase1-stop`, `phase2-stop`, `phase3-stop`).

## Calibration Log

Per the walkinglabs template guidance, the rubric needs 3–5 calibration rounds. Record each round here.

| Round | Date | Feature evaluated | Agent verdict | Human verdict | Divergence | Rubric adjustment |
| --- | --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |

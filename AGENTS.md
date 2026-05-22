# AGENTS.md

This repository hosts **CMP Ensemble HM** — a Python implementation of a post-hoc Ensemble Smoother (ES) update + ablation forecast for the CMP / Watt Field reservoir history-matching study, per Evensen, Oliver & Hanea (2026). The canonical specification is [TZ_ensemble_forecast.md](TZ_ensemble_forecast.md).

This repository is designed for long-running coding-agent work. The goal is not to maximize raw code output. The goal is to leave the repo in a state where the next session can continue without guessing.

Note for Claude Code agents: prefer [CLAUDE.md](CLAUDE.md) — it is the same content with Claude-specific phrasing. Both files are kept in sync; if they diverge, CLAUDE.md wins.

## Startup Workflow

Before writing code:

1. Confirm the working directory with `pwd` — expected: `F:/СМП/Статья 2.0/Ensamble HM`.
2. Read `claude-progress.md` for the latest verified state and next step.
3. Read `feature_list.json` and choose the unfinished feature with the lowest `priority` integer.
4. Review recent commits with `git log --oneline -5`. If the repo is not yet under git, Feature `scaffold-000` handles `git init`.
5. Run `./init.sh` (Git Bash on Windows). On native PowerShell, run the equivalents manually: `python -m pip install -e .[dev]` then `pytest -q`.
6. Run the synthetic-fixture integration test (`pytest tests/test_integration_synthetic.py -q`) before starting new work.

If baseline verification is already failing, fix that first. Do not stack new feature work on top of a broken starting state.

## Working Rules

- Work on one feature at a time. Exactly one entry in `feature_list.json` may have `status: "in_progress"`.
- Do not mark a feature complete just because code was added. Completion requires the verification listed in the feature entry, with evidence pointing to a pytest result or an artifact under `outputs/`.
- Keep changes within the selected feature scope unless a blocker forces a narrow supporting fix. If a supporting fix is needed, document it in the feature's `notes` field.
- Do not silently change verification rules during implementation. If a verification step is wrong, propose an update in the session log and wait one cycle before applying it.
- Prefer durable repo artifacts (committed files, saved `.npy` / `.csv`, pytest logs) over chat summaries.
- Do not implement Phase 4 (APS soft-category, `phase4-*`) until all Phase 0–3 features are `passing`. Phase 4 is explicitly out-of-scope for the first iteration per [TZ_ensemble_forecast.md](TZ_ensemble_forecast.md) §12.
- Do not modify input Excel files in the repository root.

## Required Artifacts

- `feature_list.json` — source of truth for feature state.
- `claude-progress.md` — session log and current verified status.
- `init.sh` — standard startup and verification path.
- `session-handoff.md` — compact handoff for end-of-session.
- `clean-state-checklist.md` — pre-stop checklist.
- `TZ_ensemble_forecast.md` — read-only canonical specification.

## Definition Of Done

A feature is done only when **all** of the following are true:

- the target behavior is implemented in `src/cmp_ensemble/`;
- the required verification (unit test, integration test, or artifact generation) actually ran;
- evidence (pytest output path or output-artifact path) is recorded in `feature_list.json` for the feature;
- the synthetic-fixture integration test still passes end-to-end in under 30 seconds;
- the repository remains restartable via `./init.sh` without manual repair.

## End Of Session

Before ending a session:

1. Update `claude-progress.md` — add a Session NNN block with what was done, what verification ran, and the next best step.
2. Update `feature_list.json` — set statuses, fill `evidence`.
3. Record any unresolved risk or blocker in the session log and in the affected feature's `notes` field.
4. Run through `clean-state-checklist.md`.
5. Commit with a descriptive message once the work is in a safe state. Commit prefix: `phase<N> <feature-id>:`.
6. Leave the repo clean enough for the next session to run `./init.sh` immediately.

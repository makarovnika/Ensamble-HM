# Session Handoff

## Verified Now

- What is currently working: harness skeleton only. The eight template files (`CLAUDE.md`, `AGENTS.md`, `init.sh`, `claude-progress.md`, `feature_list.json`, `session-handoff.md`, `clean-state-checklist.md`, `evaluator-rubric.md`, `quality-document.md`) exist at the repo root and are tailored to the CMP Ensemble HM project per [TZ_ensemble_forecast.md](TZ_ensemble_forecast.md).
- What verification actually ran: none — this session was harness setup. `init.sh` intentionally exits with code 2 when `pyproject.toml` is missing (the expected state until `scaffold-001` lands).

## Changed This Session

- Code or behavior added: none — no Python source yet.
- Infrastructure or harness changes: created the eight harness files. Customised the `init.sh` template from `npm` to `pip` + `pytest` and added a Python-version guard plus a `pyproject.toml` existence guard.

## Broken Or Unverified

- Known defect: the repo is not yet under git; `git status` will fail. Fixed by `scaffold-000`.
- Unverified path: every code path — no implementation exists.
- Risk for the next session: starting Phase 0 before ТЗ §15 clarifications are answered will lock the loader into the wrong input contract. The repo only contains Excel files; the ТЗ assumes CSV+YAML. The schemas need to match reality, not the spec, before any loader code is written.

## Next Best Step

- Highest-priority unfinished feature: `scaffold-000` (initialise git + `.gitignore`).
- Why it is next: every future commit message relies on git being initialised. It is the cheapest unblocking action.
- What counts as passing: the verification list inside `feature_list.json` for `scaffold-000` — `git status` runs, the bootstrap commit exists, `.gitignore` excludes `outputs/`, `logs/`, `__pycache__/`, `.venv/`, `*.npy`.
- What must not change during that step: the eight harness files just written, the ТЗ, and the four input Excel files. Do not generate Python code in this step — that is `scaffold-001`.

## Commands

- Startup: `./init.sh` (Git Bash on Windows). On native PowerShell: `python -m pip install -e .[dev]; pytest -q` (will fail until `scaffold-001` lands).
- Verification: `pytest -q` (full suite); `pytest tests/test_integration_synthetic.py -q` (synthetic-fixture smoke test, < 30 s budget).
- Focused debug command: `cmp-ensemble run --phase <N>` for N in 0..3, plus `cmp-ensemble run --phase all`. `cmp-ensemble report` builds the final HTML.

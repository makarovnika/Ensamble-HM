# Clean State Checklist

Run through this list before ending every session. The repo must be safe enough that the next session can pick up by reading `claude-progress.md` and running `./init.sh` — nothing else.

- [ ] The standard startup path still works: `./init.sh` exits 0 (or with the documented "scaffold-001 not done" guard code 2 when applicable), and `pytest -q` runs from a clean clone.
- [ ] The standard verification path still runs: `pytest tests/test_integration_synthetic.py -q` finishes in under 30 seconds against the synthetic fixture.
- [ ] Current progress is recorded in `claude-progress.md` — a new `Session NNN` block exists, with `Verification run`, `Evidence captured`, `Commits`, and `Next best step` all filled in.
- [ ] Feature state in `feature_list.json` reflects reality: exactly zero or one feature is `in_progress`; any feature claimed `passing` has a non-empty `evidence` array pointing to a real path or test name.
- [ ] No half-finished step is left undocumented. Mid-implementation code, half-written QC checks, or unrun verifications are called out in the active feature's `notes` field.
- [ ] No input data file (`Исторические значения.xlsx`, `Кроссплоты.xlsx`, `Показатели динамики.xlsx`, `models_near_adapted_centroids.xlsx`, `TZ_ensemble_forecast.md`) has been modified during the session.
- [ ] Outputs are reproducible: every artifact under `outputs/` written this session has a sidecar `*.meta.yaml` recording git SHA, seed, and config hash.
- [ ] The next session can continue without manual repair: it should not need to install extra packages outside `pyproject.toml`, fix a corrupted file by hand, or re-derive a missing fixture.
- [ ] If any ТЗ §15 clarification was answered this session, the answer is reflected both in `claude-progress.md` (Current Verified State) and in the affected feature entries (e.g. `phase0-001.status` flips from `blocked` to `not_started`).
- [ ] Final commit is made; `git status` shows a clean working tree.

# Quality Document

A quality snapshot for each pipeline phase and architectural layer of **CMP Ensemble HM**. Both agents and humans use this document to quickly understand where the codebase is strong and where it needs work.

**Update cadence:** after each significant session, or before starting a new phase of work (Phase 0 → Phase 1 → Phase 2 → Phase 3).

**Grading scale:**

- **A**: All verification passing, clean architecture, agent-legible, stable tests, reproducible numerics.
- **B**: Verification passing, mostly clean, minor gaps in legibility or test coverage.
- **C**: Partially working, known gaps, some code areas hard for agents to understand or hard to reproduce.
- **D**: Not working, or major structural issues (missing data contract, broken baseline, NaN in outputs).
- **—**: Not yet started.

---

## Pipeline Phases (Product Domains)

| Phase | Grade | Verification | Agent Legibility | Test Stability | Key Gaps | Last Updated |
|-------|-------|--------------|------------------|----------------|----------|--------------|
| Scaffold (project skeleton, configs) | — | — | — | — | `pyproject.toml`, `src/cmp_ensemble/` tree, synthetic fixture not yet created. | 2026-05-22 |
| Phase 0 — Data ingest (tNavigator loader, observations, state vector) | — | — | — | — | Blocked on ТЗ §15 clarifications #1 and #3. Real inputs are Excel-only; ТЗ assumes CSV+YAML. | 2026-05-22 |
| Phase 1 — ES update + QC (localization, subspace, QC, cluster-3 diagnostic) | — | — | — | — | No implementation. | 2026-05-22 |
| Phase 2 — Model selection (Mahalanobis ranking, linear proxy, compute planner, proxy validation) | — | — | — | — | Proxy validation requires user-driven tNavigator re-sims (ТЗ §15 #5). | 2026-05-22 |
| Phase 3 — Ablation forecast (three setups, aggregation, metrics, figures) | — | — | — | — | Depends on user re-simulating selected models in tNavigator. | 2026-05-22 |
| Phase 4 — APS soft-category | — | — | — | — | Explicitly out of scope for first iteration per ТЗ §12. | 2026-05-22 |

## Architectural Layers

| Layer | Grade | Boundary Enforcement | Agent Legibility | Key Gaps | Last Updated |
|-------|-------|----------------------|------------------|----------|--------------|
| `io/` — loaders + pydantic schemas | — | — | — | Module does not exist yet. Schemas must align with Excel inputs, not the ТЗ's hypothetical CSV tree. | 2026-05-22 |
| `ensemble/` — ES update, localization, state vector, subspace | — | — | — | Module does not exist yet. | 2026-05-22 |
| `selection/` — Mahalanobis, linear proxy, compute planner | — | — | — | Module does not exist yet. | 2026-05-22 |
| `forecast/` — setups, aggregation, metrics | — | — | — | Module does not exist yet. | 2026-05-22 |
| `qc/` — checks + HTML reports | — | — | — | Module does not exist yet. | 2026-05-22 |
| `viz/` — ablation + diagnostic figures | — | — | — | Module does not exist yet. All six figures (`fig01_pipeline.png` … `fig06_cluster3_migration.png`) outstanding. | 2026-05-22 |
| `cli.py` — `cmp-ensemble` entry point | — | — | — | Not yet wired. Targets: `run --phase {0..3,all}`, `report`, `figures`. | 2026-05-22 |
| `tests/` — pytest suite + synthetic fixture | — | — | — | Integration test (20 models, 5 params, 10 obs) must run in < 30 s. Does not exist yet. | 2026-05-22 |

## Reproducibility Layer (project-specific)

Numerical reproducibility is a first-class concern for this study — the paper depends on it. Track it separately.

| Aspect | Status | Notes |
|--------|--------|-------|
| Per-output `*.meta.yaml` sidecars (git SHA, seed, config hash, timestamp) | Not implemented | Convention defined in `CLAUDE.md`. Must land with `scaffold-001`. |
| ES perturbation seed (`es_update.perturbation_seed`) | Default `42` per ТЗ §7 | Should be overrideable via CLI. |
| Synthetic fixture seed | TBD | Must be fixed so the integration test is byte-identical across runs. |
| Deterministic SVD truncation | Implementation TBD | Use `numpy.linalg.svd` with explicit truncation at `subspace_energy=0.99`. |

## Change History

### 2026-05-22

- Changes: harness bootstrap. The eight template files from `walkinglabs/learn-harness-engineering` were filled in for CMP Ensemble HM.
- Domains promoted: none.
- Domoted: none.
- New gaps identified: data-contract mismatch — repo contains Excel files at the root, ТЗ assumes a `data/ensemble_150/` CSV tree. Logged as blocker on `phase0-001` and `phase0-002`.
- Gaps closed: ambiguity about agent workflow — `CLAUDE.md` and `feature_list.json` now define a clear feature order and definition of done.

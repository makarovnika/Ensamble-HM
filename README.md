# CMP Ensemble HM

Post-hoc Ensemble Smoother (ES) update with localization and three-setup ablation forecast on
150 pre-computed tNavigator models for the **CMP / Watt Field** history-matching study.

Methodology follows Evensen, Oliver & Hanea (2026) — Ch. 5–6 (ES + subspace regularisation) and
Ch. 14 (ablation reporting). Canonical specification: [TZ_ensemble_forecast.md](TZ_ensemble_forecast.md).

## What the pipeline does

```
Phase 0   Excel ingest   → outputs/cache/ensemble.h5, outputs/matrices/*.npy
Phase 1   ES + QC        → outputs/matrices/{theta_post,K,locmask,...}, outputs/qc/*
Phase 2   selection      → outputs/selection/{ranking, proxies, plan CSVs}
Phase 3   ablation       → outputs/forecast/, outputs/figures/, outputs/article_assets/
report                   → outputs/report.html, outputs/qc/qc_report.html
figures                  → regenerate fig01..06 from existing artefacts
```

Reads four Excel inputs at the repo root + an external forecast workbook over UNC / local path.
Writes everything under `outputs/` with `*.meta.yaml` sidecars for reproducibility (git SHA, seed,
config hash, timestamp).

## Install

Python **3.11+** required. Editable install with dev extras:

```bash
python -m pip install -e ".[dev]"
```

On machines without PyPI access, install the package skeleton without resolving deps:

```bash
python -m pip install -e . --no-deps
# Then install the missing third-party packages individually:
python -m pip install pydantic click plotly jinja2
```

Pre-existing system packages (`numpy`, `scipy`, `pandas`, `openpyxl`, `h5py`, `pyyaml`, `rich`,
`matplotlib`, `seaborn`, `scikit-learn`, `pytest`) are reused.

## Quickstart

Run each phase in turn (or `--phase all`):

```bash
# Phase 0 — parse Excel inputs, cache to outputs/cache/ensemble.h5
python -m cmp_ensemble.cli run --phase 0

# Phase 1 — ES update + QC; produces theta_post.npy and qc/ tables
python -m cmp_ensemble.cli run --phase 1

# Phase 2 — Mahalanobis ranking + per-cluster linear proxy + compute planner
python -m cmp_ensemble.cli run --phase 2

# Phase 3 — three-setup ablation forecast + figures + LaTeX table
python -m cmp_ensemble.cli run --phase 3

# Assemble the final HTML rollup
python -m cmp_ensemble.cli report
```

Useful flags:

| Flag | Phase | Effect |
|---|---|---|
| `--clip-to-prior` | 1 | Clip θ_post to the prior support box from `configs/theta_schema.yaml` |
| `--localization-factor 2.0` | 1 | Loosen hard threshold from 3/√N (default) to 2/√N |
| `--localization-method soft_taper` | 1 | Use a cosine ramp instead of a hard mask |
| `--d-obs-type {cumulative,rates,hybrid}` | 1 | Pick the observation vector composition |
| `--variant-label LABEL` | 1 | Write outputs under `outputs/phase1_variants/<LABEL>/` instead of the default tree |
| `--dedup-ensemble` | 2 | Collapse the 26 duplicate model_ids by averaging their θ_post copies |
| `--keep-ooe` | 3 | Keep proxy predictions whose θ_post is outside the training envelope |
| `--hindcast --train-years 6 --val-years 2` | 1+3 | Optional diagnostic: ES on the train slice, val slice used as d_truth |

Supporting subcommands:

```bash
python -m cmp_ensemble.cli compare-phase1   # run 3 localization variants side by side
python -m cmp_ensemble.cli figures          # rebuild fig01/02/06 + mirror to article_assets
python -m cmp_ensemble.cli report           # rebuild outputs/report.html
```

## Expected outputs

After `--phase all`:

```
outputs/
├── cache/                      ensemble.h5, forecast.h5 (HDF5 caches)
├── matrices/                   *.npy + *.meta.yaml sidecars
├── qc/                         spread_retention, cluster_centroid_shift,
│                                physical_bounds_violations, duplicate_models,
│                                mahalanobis_migration, rank_check.json,
│                                per_well_misfit, cluster3_diagnostic.html
├── selection/                  mahalanobis_ranking, proxies/, validation*.csv,
│                                models_to_resimulate, models_proxy,
│                                validation_subset, d_forecast_post_via_proxy
├── forecast/                   metrics_summary, setup{1,2,3}_field_total_quantiles
├── figures/                    fig01_pipeline, fig02_qc_spread,
│                                fig03_ablation_p10p90, fig04_cumulative_scatter,
│                                fig06_cluster3_migration  (each as PNG 300 dpi + PDF)
├── article_assets/             ablation_table.tex, figures_v2/ (manuscript copies)
├── report.html                 project rollup with relative links
└── phase1_variants/            optional per-variant subtrees (`compare-phase1`)
```

## Tests

```bash
python -m pytest -q        # ~85 tests, ~5 s
```

The synthetic integration test (`tests/test_integration_synthetic.py`) runs Phase 0→1→2→3
end-to-end in process on a 20-model fixture and must complete in under 30 s (ТЗ §9). It is the
primary regression gate.

## Documentation

| File | Topic |
|---|---|
| [`docs/data_format.md`](docs/data_format.md) | Excel input layout + pydantic schemas + linkage rule |
| [`docs/methodology.md`](docs/methodology.md) | ES + subspace + localization derivation + evaluation_mode rationale |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Common failures and how to diagnose |
| [`CLAUDE.md`](CLAUDE.md) | Agent operating rules + session workflow |
| [`TZ_ensemble_forecast.md`](TZ_ensemble_forecast.md) | Canonical ТЗ (do not edit without approval) |
| [`feature_list.json`](feature_list.json) | Per-feature status, verification, evidence |
| [`claude-progress.md`](claude-progress.md) | Session log |

## Limitations of the present pipeline (be honest)

- **No d_truth for 2019-2024** — the forecast period observations do not exist. Phase 3 reports
  `width_ratio`, `median_shift`, and `coverage_p10p90` only when used in `--hindcast` mode. Default
  evaluation regime is `no_truth_baseline_only`.
- **Workflow controls absent** — `setup3_full` degenerates to `setup2_localized` at runtime. The
  ablation table is effectively a 2-setup comparison.
- **Cluster 0 is a "survivable subset"** — only 24 of 50 models completed the forecast simulation
  (26 failed by pressure depletion). Per-cluster numbers in `setup1` reflect that bias.
- **Hard 3/√N localization is too aggressive at N≈150** — only 1.74% of K-entries survive, and 6
  of 9 θ parameters never move. Use `--localization-factor 2.0` for a more balanced update; the
  `compare-phase1` subcommand renders the trade-off explicitly.
- **138 of 149 θ_post are outside the proxy training envelope** — the per-cluster proxy
  extrapolates for almost every member of `setup2`. `--keep-ooe` retains those extrapolations,
  the default drops them.

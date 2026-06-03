# Figure captions

Manuscript-ready captions for the five Tier A figures, in the style preferred by Q1
oil-and-gas and applied-ML journals. Each is ≤ 80 words, names panels, colours and
markers, and cross-references the relevant section of
[`docs/methodology.md`](methodology.md). None of the captions claims accuracy against
truth — no out-of-sample observations exist for 2019-2024 (see
[`docs/methodology.md` § evaluation_mode](methodology.md)).

Copy-paste these directly under the corresponding `\includegraphics{}` in LaTeX.

---

## Figure 1 — Pipeline schematic

**File:** [`outputs/figures/fig01_pipeline.{png,pdf}`](../outputs/figures/fig01_pipeline.png)

> Schematic of the post-hoc Ensemble Smoother pipeline. Four boxes, left to right:
> Phase 0 ingests four Excel workbooks into pydantic-validated matrices; Phase 1 runs
> the ES update with adaptive correlation-based localisation and 99 %-energy subspace
> truncation; Phase 2 ranks posterior shifts by Mahalanobis distance and trains the
> per-cluster linear forecast proxy; Phase 3 evaluates the three-setup ablation on
> the 2019–2024 forecast window. Arrows mark artefact handoffs. Numerical evidence
> appears in figures 2–4 and 6.

*Word count: 78.*

---

## Figure 2 — QC spread retention per θ component

**File:** [`outputs/figures/fig02_qc_spread.{png,pdf}`](../outputs/figures/fig02_qc_spread.png)

> Spread retention σ\_post / σ\_prior per parameter after Phase 1. Green bars:
> ratio below 1 (parameter updated by ES). Grey bars: ratio exactly 1 (frozen by
> hard 3/√N correlation localisation at N = 149). Dashed reference at 1.0 (no
> update); dotted red at 0.1 (collapse threshold). Six of nine parameters are
> frozen because their gain-matrix rows are zeroed; the three that move are
> THICK, AZIMUTH, NUMBER_CHANNELS. See `docs/methodology.md` § Adaptive
> correlation-based localisation.

*Word count: 71.*

---

## Figure 3 — Ablation P10–P50–P90 by setup and phase

**File:** [`outputs/figures/fig03_ablation_p10p90.{png,pdf}`](../outputs/figures/fig03_ablation_p10p90.png)

> Field-total cumulative production over the 2019–2024 forecast window. Columns:
> setup1 naïve baseline, setup2 ES + localisation, setup3 with control uncertainty.
> Rows: oil, water, gas. Shaded band: P10–P90 quantile envelope across the ensemble;
> central line: P50. **Setup3 reproduces setup2 byte-for-byte** because workflow
> controls are absent for this dataset and the runtime degrades setup3 to setup2 with
> a warning. The width asymmetry between setup1 (deterministic) and setup2 (proxy +
> ε) is discussed in `docs/methodology.md` § Limitations.

*Word count: 80.*

---

## Figure 4 — End-of-forecast cumulative per ensemble member

**File:** [`outputs/figures/fig04_cumulative_scatter.{png,pdf}`](../outputs/figures/fig04_cumulative_scatter.png)

> Field-total cumulative production at the 2024-10-01 anchor for every ensemble
> member, per setup (colour) and per phase (panels oil, water, gas). Values are
> forecast-period **anomalies** — production added after the 2019-01-01 history
> cutoff, not totals since 2011 (`docs/data_format.md` § Cumulative anomaly
> convention). Setup1 carries 123 deterministic tNavigator runs; setup2 carries 149
> proxy-projected members of which 138 are out-of-envelope of their per-cluster
> training box (retained because `--keep-ooe` was set).

*Word count: 79.*

---

## Figure 6 — Cluster centroid migration in θ-space

**File:** [`outputs/figures/fig06_cluster3_migration.{png,pdf}`](../outputs/figures/fig06_cluster3_migration.png)

> Per-cluster centroid migration in the nine-dimensional θ-space (Phase 1, Task 1.4).
> One row per cluster; nine grouped bars per row, one per parameter: reference
> centroid from `models_near_adapted_centroids.xlsx` (grey), prior centroid (cluster-
> coloured, light), posterior centroid (cluster-coloured, solid). Heights are
> normalised by |prior centroid| so heterogeneous units compare on one axis; percent
> shifts from prior to posterior annotated above the posterior bar. The dominant
> signal is **AZIMUTH** (≈ +17 ° ≈ +2.5 σ\_prior) in all three clusters.

*Word count: 79.*

---

## Note on figure 5

Figure 5 (`fig05_crps_time`) was retired in the session-005 audit. CRPS as a metric
requires real out-of-sample observations against which to score the forecast; the
project's `evaluation_mode = no_truth_baseline_only` regime states that no such
observations exist for 2019–2024. The five Tier A figures above are therefore the
complete manuscript figure set.

---

## Authorship notes

* Each caption avoids the phrasing "matches the observed production" — there is no
  measurement of forecast-period production to match. The closest legitimate phrasing
  is "matches the simulator forecast" (for the proxy validation) and "matches the
  historical observation" (for the 2011-2018 adaptation residuals, not shown in any
  Tier A figure).
* Cluster colours follow the unified palette in `docs/visualization_plan.md`. The
  exact RGB values in the code (`src/cmp_ensemble/viz/diagnostics.py::CLUSTER_COLORS`)
  use the Tableau-10 set; the plan recommends matplotlib-default Tab-10. This is a
  stylistic delta noted in the cleanup-006 closure — captions are colour-agnostic so
  no rewrite is needed if the palette is harmonised later.
* Reproducibility metadata (git SHA, seed, config hash) accompanies every PNG as
  `<file>.png.meta.yaml`. Cite the git SHA in the manuscript's "Code availability"
  statement.

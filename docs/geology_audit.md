# Critical Audit of `outputs/geology_validation/` — session 026

**Date:** 2026-06-21 (post-geolval-004 closure)
**Reviewer:** self-audit triggered by user request "проверь все критически по чести геологии"
**Scope:** all 8 geolval-* features and the artefacts they produced

---

## Summary

Four issues found. Two **invalidate** published claims; one is a methodological caveat that should be added to the limitations; one is the well-known but un-quantified inflation risk in small-sample regression.

| # | Severity | Where | Effect on the article |
|---|---|---|---|
| 1 | **CRITICAL** | `calibrate_perm_cutoff` outlier on 2 seeds | Invalidates axis 2 "Exp2 eliminates pathological tail" claim |
| 2 | **CRITICAL** | In-sample R² in `r2_uplift_with_bootstrap` | Invalidates axis 1 "geology explains +12% beyond θ" claim |
| 3 | **HIGH** | `mean_ntg` aggregate vs per-well WELL7 | Demolishes the "TZ §5.1 mechanistic signal" interpretation |
| 4 | LOW | `frac_largest_26` median saturation | Already noted in report.md; affects how we read all axis 2 medians |

The empirically robust findings that **survive** all four corrections:

- **Stage 0** topological churn (`frac_netflag_changed` = 0.40-0.43) — unaffected.
- **Axis 4** (history-mismatch reduction via ES update): cluster 2 mismatch 38.4% → 17.0%, 8.6.4 pass-rate 30% → 92%, cross-axis r ≈ 0. Unaffected by issues 1-3 — uses Phase-1 outputs directly.
- **Axis 2 (concept conformance from θ)**: cluster 2 all-three pass-rate = 2% (1/50). Cluster 2 migrated into cluster 1's design box. Independent of issues 1-3.

---

## Issue 1 — `calibrate_perm_cutoff` outlier on 2 Exp1 seeds (CRITICAL)

**Bug.** `calibrate_perm_cutoff` finds the bi-modal trough of log₁₀(PERMX) and uses
that as the sand threshold. On seeds 40007 and 69797 in Experiment 1 the
algorithm latched on to the *noisy upper edge* of the distribution and produced
**cutoff = 10759.9 mD**.

That cutoff rejects 99.9 % of all positive-PERMX cells (max PERMX ≈ 12 700 mD).
With this many cells excluded, the sand mask is sparse and shatters into many
small bodies.

**Evidence (audit 2026-06-21):**

```
Exp1 seed=40007:
  PERMX cube: min=0, max=12693, frac_zero=0.506, frac_one(NTG)=0.507
  cutoff=10760 mD: total_sand=    826 cells, n_bodies=143, frac_largest=0.154
  cutoff=    0 mD: total_sand=264548 cells, n_bodies=  7, frac_largest=0.9996

Exp1 seed=69797:
  cutoff=10760 mD: total_sand=    915 cells, n_bodies=197, frac_largest=0.068
  cutoff=    0 mD: total_sand=264517 cells, n_bodies=  7, frac_largest=0.9923
```

Both seeds — when re-analysed with `cutoff = 0 mD` (PERMX > 0) — look
**identical to every other model** (frac_largest ≈ 0.99, ~7 bodies).

**What I claimed because of this bug.**

| Artefact | Published claim | Actual signal |
|---|---|---|
| `connectivity_summary.csv` | Exp1 has 2/124 patho models | 0/124 patho models |
| `summary_comparison.csv` | "BETTER: Exp1 → Exp2, 0.068 → 0.924 worst-case" | NEUTRAL (both ~0.99) |
| `diversity_width_ratio.csv` | width_ratio frac_largest = 0.17 | 1.35 (Exp2 actually slightly *broader*) |
| `report.md` | "two pathological Exp1 seeds (40007, 69797)" | calibration artefacts |
| `geol_fig04_geobody_connectivity.png` | shows Exp1 long lower tail | tail is the calibration outliers |

**Width-ratio recomputed without the two patho seeds:**

| Metric | width_ratio (published) | width_ratio (clean) |
|---|---:|---:|
| `frac_sand_in_largest_26` | 0.14 | **1.35** |
| `mean_inj_connections_per_producer` | 0.45 | 0.87 |
| `top1_orientation_deg` | 0.34 | 0.91 |

**The three "tightening" signals on axes 2 and 3 are driven by the calibration outliers, not by a real geological difference between experiments.**

**Fix.** Switch `calibrate_perm_cutoff` from "bi-modal trough" to a **fixed
fallback at 0 mD by default**, because PERMX==0 already encodes the non-reservoir
fraction. The bi-modal branch can stay but should be capped (reject any cutoff
> 99th-percentile of positive PERMX, ≈ 9 500 mD on this dataset). Regenerate
`connectivity_summary.csv`, `diversity_*` artefacts, `summary_comparison.csv`,
`report.md`, and `geol_fig04/05`.

---

## Issue 2 — In-sample R²-uplift inflated by overfitting (CRITICAL)

**Bug.** `r2_uplift_with_bootstrap` computes both R²(θ) and R²(θ+geo) as
in-sample fits via `LinearRegression().fit(X, y).score(X, y)`. With n=149
samples and p = 9 + 7 = 16 predictors in the full model, the in-sample R²
is inflated by ≈ p/n × (1 - R²) per the standard formula.

The bootstrap CI I built also evaluates each resample with in-sample R², so
it doesn't catch the bias.

**Evidence (audit 2026-06-21, 5-fold cross-validation):**

| Response | in-sample uplift | CV uplift |
|---|---:|---:|
| `cum_oil_WELL5` | **+12.4%** | **−31.8%** |
| `cum_oil_WELL7` | +9.2% | −10.2% |
| `cum_oil_WELL3A` | +5.0% | −12.5% |
| `cum_oil_WELL1` | +4.0% | −196% |
| `cum_oil_WELL9` | +2.2% | −1729% |

Out-of-sample, **adding geological descriptors makes the prediction worse**,
sometimes catastrophically (the CV R² for WELL9 with θ + geo is −17.5 — the
linear model with 16 predictors and 149 points is hopelessly over-parameterised
for this signal).

**What this means.** The published axis-1 claim that "geological descriptors
explain an additional 5-12 percentage points of production variance beyond θ"
is **NOT** supported. The honest finding is that **at n = 149 and this set of
linear predictors, geological descriptors do not add genuine predictive value
over θ alone.**

**Fix.** Switch the metric to cross-validated R² (`sklearn.model_selection.cross_val_score`)
or use adjusted R² with a clear formula. Re-classify the axis-1 status in
`summary_comparison.csv` from BETTER to NEUTRAL/INCONCLUSIVE. Update report.md.

A genuinely positive uplift might emerge with a different model (e.g. random
forest, regularised regression with cross-validated hyperparameters) — but
that is a follow-up, not a fix to the current code.

---

## Issue 3 — `mean_ntg ↔ cum_oil_WELL7` is not a per-well mechanistic signal (HIGH)

**Bug.** `aggregate_descriptors_per_model` defines
`mean_ntg = mean(mean_ntg_along_well across all 23 wells)`. The "mechanistic
correlation" `mean_ntg ↔ cum_oil_WELL7` therefore measures **how
channel-density across the whole pattern correlates with WELL7's production**
— a global volume effect, not a per-well mechanism.

**Evidence:**

```
r(mean_ntg AGGREGATE-23,        cum_oil_WELL7) = +0.279  (published)
r(NTG along WELL7 specifically, cum_oil_WELL7) = +0.046  (real per-well signal)
threshold 3/√149 = 0.246
```

The per-well-specific correlation — which is what TZ §5.1 actually asks for
("AZIMUTH → channel intersection at WELL7 → WELL7 response") — does **not**
clear the significance threshold.

**Fix.** Two options:
1. Replace `mean_ntg` aggregate with per-well features and recompute correlations.
   Then either the per-well r remains insignificant (honest answer: no
   mechanistic signal at n=149) or a different well/parameter clears 3/√N.
2. Keep the aggregate but rename it to `field_mean_ntg` and explicitly
   relabel the correlation as a "global volume effect", not "mechanistic".

Either way, the "TZ §5.1 mechanistic signal" sentence in report.md is wrong
and must be removed.

---

## Issue 4 — Median saturation at frac_largest_26 ≈ 0.999 (LOW)

**Observation.** Both experiments have median `frac_sand_in_largest_26` ≈
0.999. This means almost every model in both ensembles is dominated by a
single, near-grid-spanning sand body. The median is saturated, so any
median-on-median comparison is uninformative; all useful signal lives in the
tail.

**Impact.** This isn't a bug — the report already notes "the medians are
saturated and the interesting story is in the tails". But it should be the
*headline*, not a side note, because:

- It implies all axis-2 connectivity differences between experiments live in
  the tails, which are exactly where calibration artefacts (Issue 1) and
  small-N statistical noise dominate.
- It explains why our concept-conformance (axis 2 facies / Notion §5 boxes
  cluster 2 = 2%) is a stronger axis-2 signal than the connectivity-tail
  comparison — concept-conformance distinguishes models on the bulk of the
  distribution, not on tail outliers.

---

## What stays true after all four corrections

The article's core empirical claims survive on three axes:

1. **Stage 0 topological churn:** mean / variance of PORO and NTG stable to
   1e-4 between experiments, but 40-43% of cells flip net/non-net status.
   New methodology is a *spatial redistribution* of the same overall budget.
   *Unaffected by all four issues.*

2. **Concept conformance (axis 2):** cluster 2 all-three-params pass rate
   = 2%. Median THICK and MAJ_R for cluster-2 models fall in cluster 1's
   design boxes — empirical confirmation of the "cluster-2 migration" the TZ
   §5.4 hypothesised. Comes from the adapted θ in the Excel workbook directly,
   independent of cubes and cutoffs.
   *Unaffected.*

3. **History mismatch reduction (axis 4):** ES update halves cluster-2
   mismatch (38 → 17 %) and triples cluster-2 8.6.4 pass-rate (30 → 92 %).
   Cross-axis Pearson r ≈ 0 → reduction is not bought by degrading topology.
   Uses Phase-1 outputs which were validated earlier — *unaffected by axis-1
   regression bug and axis-2 cutoff bug.*

The article should be rewritten so these three are the headline, and the
axis-1 R²-uplift / axis-2 patho-tail / axis-3 width_ratio claims are either
removed or marked as inconclusive at this sample size.

---

## Required actions before article submission

| Action | Where | Priority |
|---|---|---|
| Switch `calibrate_perm_cutoff` default to 0 mD with sanity cap | `src/cmp_ensemble/geology/descriptors.py` | P0 |
| Re-run `geolval-002` + `geolval-005` artefacts with the fix | `outputs/geology_validation/` | P0 |
| Add `cv_r2_uplift` column in `r2_uplift.csv` and use CV uplift as the headline | `src/cmp_ensemble/geology/production_link.py` | P0 |
| Update `summary_comparison.csv` axis-1 + tail-axis-2 rows | `src/cmp_ensemble/geology/comparison.py` | P0 |
| Rewrite `report.md` headline numbers | `outputs/geology_validation/report.md` | P0 |
| Re-render `geol_fig04`, `geol_fig05`, `geol_fig06` after data refresh | `src/cmp_ensemble/viz/geology.py` | P1 |
| Add explicit "what stays true / what doesn't" section to `report.md` | `outputs/geology_validation/report.md` | P1 |
| Add a `cv` parameter to all linear-model evidence functions | `src/cmp_ensemble/geology/production_link.py` | P2 |

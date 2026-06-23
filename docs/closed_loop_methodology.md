# Closed-loop pure-ensemble History Matching (ES-MDA) — methodology

Companion to `docs/methodology.md` for the **closed-loop** experiment
(`TZ_closed_loop_ESMDA.md`). Where the post-hoc experiment runs a single ES
update over 150 pre-computed models, the closed loop assimilates by re-running
the simulator inside an ES-MDA iteration.

## Method

ES-MDA (Emerick & Reynolds 2013; Evensen, Oliver & Hanea 2026 §3.6, §6.4)
performs `n_alpha` recursive ES updates. At step *i* the measurement-error
covariance is inflated by `alpha_i` and perturbations are resampled from
`N(d, alpha_i · C_dd)`, with weights chosen so `Σ 1/alpha_i = 1` — the total
assimilated information equals one ES update. Each step reuses the existing
subspace ES update (`cmp_ensemble.ensemble.es_update`), so **ES-MDA(n_alpha=1) is
byte-identical to a single ES update** (regression-tested).

- Default schedule: `n_alpha = 4`, uniform weights `alpha_i = n_alpha`.
- Adaptive correlation localization (threshold `3/√N`) at every step.
- Subspace SVD truncation at 0.99 energy.

```
sample_prior(N) -> Theta0
repeat i = 0 .. n_alpha-1:
    D_i      = forward(Theta_i)            # tNavigator: build + simulate, read summary
    loc      = localization(Theta_i, D_i)
    Theta_i1 = es_update(Theta_i, D_i, d_obs, alpha_i·C_dd, loc)
    checkpoint(outputs/closed_loop/iter_i/)
Theta_post = Theta_{n_alpha}
D_forecast = forward_forecast(Theta_post)  # post-2018
```

## Parameter vector theta (n_z = 148)

Sampled by `closed_loop.prior.sample_prior` from
`configs/closed_loop_theta_schema.yaml`:

- **Group A — geology (9)**: envelope-uniform (THICK, MAJ_R, AZIMUTH,
  NUMBER_CHANNELS, CHANNELS_WIDTH, LEN, AMPLITUDE, RELATIVE, PROP).
- **Group B — relperm (full set, ~128)**: truncated-normal around the base value
  (`tnav_autorun.BASE_VARIABLES`) with σ = 0.15·|base|, physics-clipped —
  saturations / kr / KH ∈ [0,1], Corey exponents N_OW/N_W ∈ [1,8].
- **Group C — contacts/multipliers (11)**: WOC depth (positive), PERMX
  (log-normal), F1–F9 (fractions).

At N=150 this is a high-dimension / modest-ensemble regime; collapse is
controlled by localization. (User decision, session 027.)

## Observations

`d_obs` = annual cumulative oil/water/gas per producer at year-end anchors
2011-12-31 … 2018-12-31 (3 metrics × 16 producers × 8 anchors = 384), loaded via
`io.observations` on the same `cum_index` the simulator reader fills, so
`d_sim[i]` and `d_obs[i]` align entry-for-entry. `C_dd` diagonal, σ = 15%·|d_obs|
with a per-metric soft floor. Simulator output is read from the Eclipse summary
(`result.SMSPEC`/`.UNSMRY`) via `resdata` (`results_reader`); cumulative values
are interpolated to the anchors and clamped past the last simulated step.

## Forecast & metrics

Post-2018 (2019-01 … 2024-10) forecast for prior and posterior ensembles;
field-total P10/P50/P90 corridors (`forecast.aggregation`). Acceptance metrics:
**width_ratio** (corridor narrowing) and **median_shift**. Coverage / CRPS are
computed only if a forecast truth is supplied — principally unavailable for this
dataset (history ends 2018-12), as in the post-hoc experiment.

## Run policy

The orchestrator writes `iter_0/run_plan.csv` + the θ-matrix and STOPS by default
(CLAUDE.md no-auto-launch). `--execute` (user-approved, session 027) wires a live
`TNavForward`. **Known integration gap (session 027):** the geology workflow
`clust_0_4` builds the static model but does not run the flow simulation, so a
separate dynamic-model run is required to produce `result.SMSPEC` — to be wired
once the simulation-trigger mechanism is confirmed.

## Artifacts

`outputs/closed_loop/`: `iter_i/{Theta,D,meta}` checkpoints, `Theta_post.npy` +
sidecar, `misfit_history.npy`, `figures/{misfit_evolution,theta_migration,
forecast_corridors}.{png,pdf}`, `forecast/{prior,post}_corridor.csv` +
`width_ratio.csv` + `median_shift.csv` + `metrics_summary.csv`, and `report.html`
(`cmp-ensemble closed-loop-report`).

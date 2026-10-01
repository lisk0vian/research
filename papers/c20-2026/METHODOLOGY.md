# Methodology — C20-2026 (design v2.0)

> **SUPERSEDED IN PART — revision pending.** This document still describes the
> single-station Huancayo design (2018–2025). That design has been replaced. The
> study of record is **five SENAMHI GBON/RBON stations over a 2054 m altitude
> gradient, 2015–2024**, with cross-station generalisation (leave-one-station-out)
> as the engineering contribution. `E2_multistation` is no longer disabled.
>
> What changes: §1 question and scope, §4 predictors (wind and accumulated rain
> unavailable; large-scale set is Niño 3.4, Niño 1+2 and RMM; ERA5 deferred), §6
> validation (fold window 2015–2024, plus a separate LOSO experiment), §10
> extensions (E2 reopened), §11 open decisions (D1 reversed, D5 no longer
> pending). What does not: §2 notation, §3 temporal design, §5 models, §7 metrics,
> §8 inference.
>
> Do not implement from this file as it stands. The evidence behind each change,
> the rejected alternatives, and the full revision checklist are in
> [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md).

English methodology extract. The Spanish original (full design, v2.0, 2026-09-28)
lives outside the repo at `C:\Users\Aron\Downloads\README.md` and remains the
source of truth for the design. This file states the concept and methods only.

No duplication by rule:

- Data description → `data/docs/metadata.md`, `data/docs/data_dictionary.md`,
  `data/README.md` (includes V1–V6 source checks).
- Operating parameters → `experiments/config.yaml` (literal §18).
- Run order + anti-leakage checklist → `experiments/README.md`.
- Numbers and figures → `outputs/manifest_index.json` (T1–T4/F1–F4).

Scope: probabilistic subseasonal forecast skill of 2 m air-temperature anomalies
at one high-Andean station (EMA Observatorio de Huancayo, Huayao, Junin:
-12.0401, -75.32049, 3329 m). Hourly data, 2018–2025. This study measures the
skill of a statistical forecasting system (forecast skill), not the
predictability of the phenomenon, and makes no causal claims about forcings.
Single site only; no generalization to the Central Andes without E2.

## 1. Research question and objective

Question: to what extent do local meteorological information and large-scale
atmospheric/oceanic forcings add skill to the probabilistic subseasonal forecast
of air-temperature anomalies at a high-Andean station in the Mantaro Valley,
against climatology and damped persistence? How does skill evolve across W1,
W2 and W3–4?

Objective: quantify deterministic and probabilistic skill of statistical
subseasonal temperature forecasts at Huayao; determine the incremental
predictive value of large-scale forcings over local information, against
climatological and persistence baselines, with out-of-sample temporal
validation.

Working title (EN): *Probabilistic Subseasonal Temperature Forecast Skill at a
High-Andean Station in the Mantaro Valley, Peru: Contributions of Local
Observations and Large-Scale Forcing*.

## 2. Notation

`t`: day (local calendar). `d`: issuance date (only data dated ≤ d, plus §7.2
latencies). `h ∈ {W1, W2, W3–4}`; `J_W1 = {1..7}`, `J_W2 = {8..14}`,
`J_W3–4 = {15..28}`. `TT_t`: observed daily mean temperature. `C_t`: daily
climatology fitted on training only. `A_t = TT_t − C_t`: daily anomaly.
`T^h_d`, `C^h_d`, `A^h_d`: period-mean observed, climatology and anomaly
(**target**). `A^0_d`: trailing 7-day anomaly mean. `q(d)`: quarter
(DJF/MAM/JJA/SON). `X_L`, `G`, `X_LG`: local, large-scale and combined
predictors. `F̂^h_d`: predictive distribution of `A^h_d`. Reconstruction:
`T̂^h_d = C^h_d + Â^h_d`.

## 3. Temporal design

Evaluation issuance is weekly on a fixed weekday (default Monday; Thursday as
sensitivity) to avoid inflating the sample with near-identical forecasts.
Training may use daily issuance; overlapping targets do not bias point
estimates but require the 28-day embargo. Target validity: ≥ 5/7 valid days
(W1/W2) or ≥ 10/14 (W3–4), else the issuance is excluded for that horizon;
the target is never imputed. Weekly W3–4 targets of consecutive issuances share
7 days, so errors are autocorrelated by construction (handled in §8).

## 4. Climatology and predictors

Climatology C2 (harmonic, K = 3 on day-of-year, fitted on daily training data
then aggregated to horizons) is the primary reference fixed a priori; C1
(±15-day window) and C3 (C2 + linear trend) are sensitivity runs. Switching
references changes the meaning of skill and both variants are reported.
Seasonal dispersion `σ_h,q` (residual SD by horizon and quarter, training only)
feeds the Gaussian predictive distributions.

Local predictors (`X_L`, all dated ≤ d, as anomalies vs own training
climatology): TT lags/means/`A^0`, DTR/TTmax/TTmin, HR, log1p RR sums, PP level
+ tendency, 7-day u/v means, target-midpoint day-of-year sin/cos. Wind uses
FF-weighted vector components; calms contribute u = v = 0.

Large-scale predictors (`G`, fixed a priori list): weekly Nino 3.4 and Nino 1+2
(last week centered ≤ d − 7), RMM1/RMM2 at d − 1 (operational provider to
verify), ERA5 PCs at d − 5 emulating ERA5T latency, refit per fold on training
only (k = 5; sensitivity 3/10). ONI and ICEN are excluded (centered 3-month
smoothing leaks future information). See `experiments/config.yaml` for lags,
domain defaults and `excluded_leaky`.

## 5. Models

Direct strategy: one model per horizon. Clim (empirical ±15-day window
distribution, point 0); Damp (OLS by horizon × quarter on `A^0`, gaussian
`σ_h,q`; main skill reference); Pers (deterministic only, secondary); Ridge_L /
Ridge_LG (standardized Ridge, gaussian); GBM_L / GBM_LG (L2 GBM + quantile GBM
on the 19-level grid with rearrangement). Ridge_L nests Damp; Ridge_LG nests
Ridge_L. Hyperparameters use inner temporal validation with embargo. Primary
model M* is the better of {Ridge_LG, GBM_LG} by mean dev-fold CRPS, frozen
before opening the blind test (with its L counterpart).

## 6. Validation

Expanding rolling-origin with annual folds (see `experiments/config.yaml`):
D1–D3 for development (hyperparameters + M* selection; sign consistency
reported descriptively), B1–B2 (2024, 2025) as blind test with frozen
hyperparameters/M* and refits at each year start. Expected blind size ≈ 104
weekly issuances per horizon (limited power: report effect sizes with
intervals, not p-values alone). Regime caveat: La Nina 2020–2023 and El Nino
2023–2024; ENSO effects rest on few events.

## 7. Metrics

Deterministic: MAE/RMSE/ACC descriptive; primary axis is MSSS vs Clim and vs
Damp, plus Murphy (1988) decomposition against the evaluation-sample mean
(reported separately from MSSS_clim since out-of-sample Clim MSE includes drift).
Probabilistic: CRPS on the shared 19-quantile grid for all models
(quantile-score integral approximation), CRPSS vs Clim/Damp, tercile RPSS
(training ±15-day empirical thresholds, CDF linearly interpolated for quantile
models), PIT histograms, tercile reliability (small-sample binned), 50/90%
interval coverage and width. No fair-score versions (parametric/quantile
distributions, not finite ensembles).

## 8. Hypotheses and inference (blind test only)

H1 (incremental large-scale value, per h): one-sided mean-loss difference L
vs LG. Ridge pair: Clark-West (2007) MSPE-adjusted with Newey-West HAC
(bandwidth max of rule-of-thumb and overlap order), normal critical values.
GBM pair: CW invalid (non-parametric); moving block bootstrap of ΔMSE,
one-sided. Probabilistic H1 component: block bootstrap of ΔCRPS for both pairs.
H2 (W3–4 skill vs Damp for M*): one-sided 95% block-bootstrap lower bound of
MSSS_damp > 0 (plus CW complement when M* is Ridge). H3 (probabilistic skill
per h): CRPSS_clim > 0 by block bootstrap; preregistered secondary criterion:
90% interval coverage in [0.85, 0.95]. Bootstrap: consecutive weekly issuances,
8-week blocks (sensitivity 4/13), B = 10000, percentile intervals, ratio-of-sums
per replicate. Multiplicity: Holm within families (H1: 3, H2: 1, H3: 3);
unadjusted + adjusted p reported. Nulls with ≈ 104 issuances are inconclusive
without effect sizes.

## 9. Secondary analyses and output contract (summary)

Descriptive only: skill by quarter and by ENSO phase / MJO activity at d,
permutation importance of G vs X_L (non-causal), sensitivities (C1/C3,
Thursday issuance, block length, PC count, daily-issuance + HAC evaluation).
Contract IDs (details in `outputs/manifest_index.json`): tables T1
(completeness/QC), T2 (blind skill + 95% CI), T3 (H1–H3 tests), T4 (Murphy);
figures F1 (skill vs horizon), F2 (PIT + reliability for M*), F3
(quarter/ENSO), F4 (robustness D1–D3 vs B1–B2).

## 10. Extensions and limitations (summary)

Extensions E1–E5 disabled (`extensions_enabled: false`): E1 LSTM/TFT, E2
multi-station (only then may inference extend to the Central Andes, with
leave-station-out and spatial FDR), E3 S2S reforecast benchmark, E4 long
climatology, E5 TT_min frost objective. Known limitations: single site; short
record (3–7-year climatologies, unstable trend); few ENSO events; wide CIs
with ≈ 104 autocorrelated blind issuances; partial non-stationarity; skill as a
lower bound on predictability; undocumented source QC/conventions (V1–V6).

## 11. Open decisions (defaults frozen for start)

D1 E2 multi-station: No (single station). D2 blind period: B1 + B2 (2024–2025).
D3 issuance day: Monday (Thursday sensitivity). D4 ERA5 domain/variables:
25°S–5°N, 85°W–60°W; T2m/Z500/U200/q600 (defaults; marked TO_CONFIRM_D4 in
config). D5 target journal: pending. D6 E5 TT_min: No.

# Methodology — C20-2026 (design v3.0)

Design of record, frozen 2026-10-02 **before any model was scored on real
data**. It supersedes v2.0 (single-station Huancayo, IGP-LAMAR). The evidence
behind each choice and the rejected alternatives are in
[`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md). Operating parameters live in
`experiments/config.yaml`; this file states concept and method, not numbers.
Each decision is checked against the published literature, with the supporting
references and the open recommendations (R1–R4), in
[`LITERATURE_REVIEW.md`](LITERATURE_REVIEW.md).

## 1. Question, scope and contribution

**Question.** How much probabilistic skill do statistical, gradient-boosting,
deep and foundation models have for 1–4-week air-temperature anomalies at
high-Andean stations, which information sources supply that skill (local
observations vs ENSO/MJO), and does a model trained on other stations transfer
to an unseen one across a 2054 m altitude gradient?

**Data.** SENAMHI GBON/RBON automatic stations, hourly, 2015-01-01 to
2024-06-30, one provider (instrument not confounded with site): Matucana
(2421 m), San José de Uzuna (3269 m), Candarave (3410 m), Carania (3840 m),
Imata (4475 m). Variables: hourly-mean temperature, relative humidity,
precipitation. No wind, no pressure.

**AI contribution (EAAI).** (i) A leakage-controlled benchmark of seven model
families on a shared quantile grid; (ii) cross-station generalisation
(leave-one-station-out) as the engineering test of whether a data-driven
forecaster can serve a station without its own training history; (iii) a
zero-shot time-series foundation model as a modern baseline.

**Application.** High-altitude agriculture and frost risk, through a frost
index (see §6). Skill measured here is that of a forecasting system, a lower
bound on predictability; no causal claim about forcings is made.

## 2. Notation

`d` issuance date (only data dated ≤ d, plus source latencies). Horizons
`W1 = days 1–7`, `W2 = 8–14`, `W3_4 = 15–28`. `C_t` daily harmonic
climatology fitted per station and fold on training data only;
`A_t = T_t − C_t`. Target `A^h_d`: mean of `A_t` over the horizon window,
valid with ≥ 5/7 (W1, W2) or ≥ 10/14 (W3_4) valid days, never imputed.
Targets: `TT_mean` (primary), `TT_min`, `TT_max` (secondary, each with its own
climatology). `A0_7d`: trailing 7-day anomaly mean.

## 3. Temporal design

Weekly evaluation issuance on Mondays; daily training issuance with a 28-day
embargo before each test window (no training target reaches it). Rolling-origin
expanding folds with July–June test windows (the record ends 2024-06-30):

| Fold | Test window | Role |
|---|---|---|
| D1 | 2019-07 – 2020-06 | dev |
| D2 | 2020-07 – 2021-06 | dev |
| D3 | 2021-07 – 2022-06 | dev |
| B1 | 2022-07 – 2023-06 | blind |
| B2 | 2023-07 – 2024-06 | blind |

Training always starts 2015-01-01. Hyperparameter procedures, the ensemble
weights and the primary model M* are fixed on D1–D3 and frozen before B1–B2.
About 52 weekly issuances per fold and station: roughly 520 blind issuances
pooled over five stations, of which about 104 are distinct dates (the effective
sample for inference, since stations share forcing).

## 4. Climatology and predictors

Primary reference C2: harmonic, K = 3, per station and fold, training only
(K chosen on evidence, DESIGN_DECISIONS §3.1). Sensitivities: C1 (±15-day
window) and C3 (C2 + linear trend in elapsed years; until v3 the trend column
was day-of-year, a defect now fixed).

Local predictors `L` (~20): TT anomaly lags 0–6, trailing means 7/14/30 days,
DTR/Tmax/Tmin and HR anomalies (each against its own harmonic), HR 30-day
anomaly, log1p precipitation sums 7/30 days, target-midpoint day-of-year
sin/cos. The calendar terms are reported as climatology correction, not skill.

Large-scale predictors `G`, as known on `d`: weekly Niño 3.4 and Niño 1+2 SST
anomalies (CPC OISST, last week centred ≤ d−7) and real-time OMI (ROMI1/2 and
amplitude, NOAA PSL, d−1). Excluded for leakage: ONI and ICEN (centred 3-month
means) and OMI (centred band-pass filter). RMM is not used (no stable public
source); ERA5 is deferred and stated as a limitation.

## 5. Models

Direct strategy, one prediction per horizon, all on the 19-level quantile grid
(0.05–0.95).

| Model | Role | Specification |
|---|---|---|
| Clim | reference | empirical ±15-day distribution of training targets; point 0 |
| Pers | reference, deterministic | `A0_7d` |
| Damp | main reference | OLS on `A0_7d` by station × horizon × quarter; Gaussian |
| Ridge_L / Ridge_LG | statistical | per station × horizon; alpha by embargoed inner validation; Gaussian with out-of-sample residual SD by quarter |
| GBM_L / GBM_LG | ML | LightGBM pooled over stations with elevation/lat/lon; quantile loss per level; rearrangement |
| LSTM_LG | deep | pooled; 60-day sequence of daily anomalies + G + static; pinball loss, all horizons jointly; early stopping on embargoed tail |
| Chronos | foundation, zero-shot | Chronos-T5-small on daily TT_mean anomalies; window means per sample path |
| Ensemble | combination | level-wise quantile average, weights ∝ 1/CRPS on D1–D3 |

M* = lowest mean dev CRPS among {Ridge_LG, GBM_LG, LSTM_LG, Ensemble}.

**LOSO.** On B1–B2, the pooled models (GBM, LSTM) are refitted without the
held-out station and scored on it; Chronos is station-agnostic by construction.
Held-out stations differ in difficulty: Matucana and Imata are extrapolation
cases at the ends of the altitude range, the others interpolation. This is
reported as a finding (skill change vs elevation), not averaged away.

## 6. Metrics

Deterministic: MAE, RMSE, ACC, MSSS vs Clim and vs Damp, Murphy decomposition
against the sample mean. Probabilistic: CRPS on the grid (same quadrature for
every model), CRPSS vs Clim and Damp, tercile RPSS with thresholds from the
training distribution of the *period-mean* anomaly, PIT, tercile reliability,
50/90 % coverage and width. Skill scores are ratios of sums over shared rows.

**Frost index** (TT_min target): P(window-mean TT_min < 0 °C) from the
anomaly quantiles plus the window climatology; Brier score and BSS vs Clim.
`TEMP` is an hourly mean, so this understates true frost; it is called a frost
index throughout.

## 7. Hypotheses and inference (blind folds only, pre-registered)

Stations are pooled per issue date; the moving-block bootstrap (blocks of 8
weekly issuances; sensitivity 4 and 13; B = 10 000) resamples the same dates
for all stations. Skill intervals are percentile intervals of ratio-of-sums
replicates.

- **H1** incremental value of `G`, per horizon: Ridge_L vs Ridge_LG by
  Clark–West with Newey–West HAC (bandwidth max of rule of thumb and overlap
  order); GBM_L vs GBM_LG by block bootstrap of ΔMSE; ΔCRPS for both pairs.
  One-sided. Holm over the three horizons.
- **H2** M* beats damped persistence at W3_4: one-sided 95 % lower bound of
  MSSS_damp > 0 (plus Clark–West if M* is a Ridge model).
- **H3** M* has probabilistic skill: CRPSS_clim > 0 per horizon, Holm over
  three; secondary criterion 90 % coverage in [0.85, 0.95].

## 8. Pre-registered decision rule

Written before any real score exists, so the framing cannot follow the numbers.

1. **EAAI framing holds** if at least one of: (a) M* has CRPSS_damp > 0 with a
   95 % interval excluding 0 at W2 or W3_4 on the blind folds; (b) a pooled
   model under LOSO keeps CRPSS_clim > 0 at the held-out station for at least
   three of five stations at W1–W2, i.e. the transfer works; (c) H1 is
   rejected (Holm) for at least one horizon, i.e. ENSO/MJO add measurable
   skill.
2. **Otherwise** the result is a rigorous negative ("statistical and AI
   forecasters do not beat damped persistence beyond week 2 at high-Andean
   stations"). The paper is then re-targeted to a climate venue (Weather and
   Forecasting or International Journal of Climatology), where such a negative
   is a first-class result. Hyperparameters and models are not re-tuned to
   rescue the EAAI framing.
3. Whatever the outcome, the dev-fold numbers, LOSO by station and every null
   result are reported.

## 9. Secondary analyses (descriptive)

Skill by quarter and by ENSO phase at issuance (Niño 3.4 ≥ 0.5 / ≤ −0.5),
dev vs blind robustness, the TT_min/TT_max targets and the frost index,
sensitivities (C1/C3, Thursday issuance, bootstrap block length).

## 10. Output contract

Tables (`outputs/tables/`): T1 completeness, T2 blind skill + CI, T3 tests,
T4 Murphy, T5 LOSO gap, T6 secondary targets and frost, `metrics_long.csv`.
Figures (`outputs/figures/`): F1 skill vs horizon, F2 PIT and reliability of
M*, F3 skill by season and ENSO phase, F4 dev vs blind, F5 LOSO vs elevation,
F6 predictability budget (L vs LG). Every number in the manuscript is a claim
in `manifest.yaml` pointing at one of these files.

## 11. Limitations stated in the paper

Five stations in one country; 9.5 years, so climatologies rest on 4.5–8.5
training years and few ENSO events (La Niña 2020–23, El Niño 2023–24); no wind,
pressure or ERA5 predictors; hourly-mean temperature for the frost index; no
dynamical S2S benchmark (ECMWF reforecasts are future work); skill as a lower
bound on predictability.

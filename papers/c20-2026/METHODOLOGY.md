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
amplitude, NOAA PSL, d−1). Sensitivity: Takahashi's E and C indices replace the
Niño pair (official IGP monthly series from ERSSTv5, a month known 10 days
after it ends), in `Ridge_LG@EC` and `GBM_LG@EC`; these never enter M* or the
ensemble. Excluded for leakage: ONI and ICEN (centred 3-month
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
| CFS_BC | dynamical reference (amendment A1) | NOAA CFSv2, 4 members of the Monday 00Z run, 2 m temperature interpolated to the station; calibrated by train-only anomaly regression. Blind folds only; never a candidate for M* nor an ensemble member |

M* = lowest mean dev CRPS among {Ridge_LG, GBM_LG, LSTM_LG, Ensemble}.

**LOSO.** On B1–B2, the pooled models (GBM, LSTM) are refitted without the
held-out station and scored on it; Chronos is station-agnostic by construction.
Held-out stations differ in difficulty: Matucana and Imata are extrapolation
cases at the ends of the altitude range, the others interpolation. This is
reported as a finding (skill change vs elevation), not averaged away. With
only four training stations, latitude and longitude act as station identifiers,
so LOSO runs three static-descriptor variants: elevation, latitude and
longitude; elevation only (`@elev`); none (`@none`).

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

- **H4** (amendment A1) M* against the dynamical reference: ΔCRPS =
  CRPS(CFS_BC) − CRPS(M*) > 0 per horizon on B1–B2, one-sided block bootstrap
  on the dates both scored, Holm over three horizons. A non-rejection is
  reported as is; it does not change the decision rule below.

### Amendment A1 (2026-10-03, before any real score)

R1 of the literature review asked for an ECMWF S2S benchmark and a hybrid.
ECMWF S2S needs an account on the ECMWF Data Store, which the author declined,
so A1 uses the open NOAA CFSv2 archive instead and drops the hybrid:

- **Scope.** Blind folds only. The bucket's first forecast is 2018-10-31, which
  leaves 8 months of history before D1 and 3.7 / 4.7 years before B1 / B2.
- **Why not a hybrid.** CFS as a predictor cannot be trained in D1-D2, and M* is
  chosen on D1-D3; a model that exists only in some dev folds cannot compete.
- **Calibration.** Per station and horizon, on training Mondays only: remove the
  CFS window-mean climatology (harmonic, K = 2, fitted on the CFS forecasts
  themselves), regress the observed anomaly on the CFS anomaly, Gaussian
  residual by quarter as for Damp.
- **What this cannot say.** CFSv2 is not the ECMWF system the S2S literature
  treats as the reference, and 1° grid cells do not resolve the stations.
  Results against CFS_BC are evidence about observation-only models versus a
  dynamical system, not versus the state of the art.

### Amendment A2 (2026-10-03, post hoc: written after the blind scores)

Unlike A1, A2 was written **after** the blind folds were scored, and is
reported as post hoc. It changes nothing above: H3, M* (the Ensemble, frozen on
dev) and every pre-registered number stand as computed. H3's secondary
criterion failed: M*'s central 90 % interval covered 0.75 / 0.69 / 0.63 of the
blind outcomes (W1 / W2 / W3_4) against the pre-registered 0.85-0.95, while its
CRPSS_clim was positive (0.29-0.35).

Diagnosis (from the scored rows, blind folds included, hence post hoc):

- **Vincentization averages widths.** The Ensemble's 90 % width is exactly the
  weighted mean of its members' widths, so disagreement between members never
  widens it. Chronos is the narrowest member by far (90 % width 0.43 °C against
  1.9-2.3 °C; 90 % coverage 0.22-0.31) and carries ~22 % of the weight; without
  it the Ensemble would be 16-21 % wider. A likely cause, not tested: each
  Chronos sample path is averaged over the 7-28-day window, and paths with less
  persistence than the real anomalies shrink that average's spread.
- **Under-dispersion is already there in dev.** The dev PIT puts 13-15 % of the
  outcomes in *each* tail (5 % expected): a spread problem, not a bias. The GBM
  quantile members also under-cover (0.67-0.73 in dev).
- **The blind years were warmer and more variable.** Mean observed anomaly
  −0.06…−0.47 °C in dev against +0.07…+0.43 °C in blind; SD 0.74-0.82 →
  1.15-1.21 °C at the three southern Andean stations (040514, 040114, 230201).
  Even Clim drops from 0.81-0.86 to 0.69-0.77 coverage, and the Ensemble's
  blind PIT becomes asymmetric (15-25 % above q95), consistent with the
  2023-24 El Niño.

Secondary analyses added (stage `09b_calibration`, table T9):

- **Spread recalibration.** Quantiles stretched around the median by a factor
  k per horizon, chosen so the central 90 % interval covers 90 % of the
  outcomes it is fitted on. k uses the dev folds only: each dev fold is scored
  with k fitted on the other two (cross-fitting), and the blind folds with k
  fitted on D1-D3. The blind folds never choose their own k.
- **Ensemble without Chronos,** the frozen dev weights renormalised over the
  other three members, as a sensitivity analysis. It does not replace M*.
- **Chronos,** reported as a mis-calibrated member with the diagnosis above.
- **Chronos' narrow windows, tested** (stage `09c_chronos_diagnostic`, table
  T10): on the daily sample paths, the daily 90 % coverage, the lag-1
  autocorrelation of the paths against that of the real errors, and how much
  the spread shrinks from daily values to the window mean in each.

What this cannot say: k was conceived after the blind coverage was seen, so a
blind coverage near 0.90 after recalibration is evidence that the spread
deficit is stable between dev and blind, not a confirmatory test. The warm,
variable blind period is a property of those two years and would also affect a
recalibration fitted on any earlier window.

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

Skill by season, by ENSO phase at issuance (Niño 3.4 ≥ 0.5 / ≤ −0.5) and by
MJO activity (ROMI amplitude ≥ 1), reported as windows of opportunity (T7, F3),
dev vs blind robustness, the TT_min/TT_max targets and the frost index,
sensitivities (C1/C3, Thursday issuance, bootstrap block length).

## 10. Output contract

Tables (`outputs/tables/`): T1 completeness, T2 blind skill + CI, T3 tests,
T4 Murphy, T5 LOSO gap, T6 secondary targets and frost, T7 conditional skill,
T8 CFS calibration, T9 calibration of M* and T10 Chronos diagnostic (A2, post
hoc), `metrics_long.csv`.
Figures (`outputs/figures/`): F1 skill vs horizon, F2 PIT and reliability of
M*, F3 skill by season and ENSO phase, F4 dev vs blind, F5 LOSO vs elevation,
F6 predictability budget (L vs LG). Every number in the manuscript is a claim
in `manifest.yaml` pointing at one of these files.

## 11. Limitations stated in the paper

No ECMWF benchmark and no hybrid (dynamical forecasts as predictors); the only
dynamical reference is the open CFSv2, on the blind folds. Five stations in one country; 9.5 years, so climatologies rest on 4.5–8.5
training years and few ENSO events (La Niña 2020–23, El Niño 2023–24); no wind,
pressure or ERA5 predictors; hourly-mean temperature for the frost index; no
dynamical S2S benchmark (ECMWF reforecasts are future work); skill as a lower
bound on predictability.

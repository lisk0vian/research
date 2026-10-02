# Design decisions — C20-2026

Working record of the design of this paper: what was decided, what was rejected,
and what evidence forced each choice. Written while the study was still at the
feature layer, so it records *why* rather than results.

Read this before changing anything in `experiments/`. Several decisions below
contradict `METHODOLOGY.md`; §7 lists what still has to be revised.

## 1. Status

| Stage | State |
|---|---|
| `00`–`05` implemented and run | yes, on the **Huancayo** record |
| `06`–`10` | stubs (`NotImplementedError`) |
| Design of record | **multi-station, SENAMHI** — not yet implemented |
| Data of record | **not yet downloaded**; the pipeline still runs on Huancayo |
| `references.bib` | 34 of 36 entries are network community-detection papers |
| `paper/main.qmd` | 19 lines of prose out of 132, no research question |
| `manifest.yaml` | untouched scaffold; its only claim points at a path that does not exist |

The split state is deliberate and temporary: the pipeline on disk is
single-station because that is what was run, while the design of record is
multi-station because that is what was decided. Sections 3 to 6 explain the
evidence; §7 lists what closes the gap.

## 2. The study

**Claim.** The subseasonal predictability *budget* of 2 m air temperature at
high-Andean tropical stations: how much skill exists at 1–4 week lead, which
information source supplies it, and where it dies.

**Engineering contribution.** Cross-station generalisation — a model trained on
N−1 stations and evaluated on the Nth, over a 2054 m altitude gradient. This is
what reconciles a careful statistical study with an AI-engineering venue.

**Intended application.** High-altitude agriculture and frost risk.

**Venue.** Engineering Applications of Artificial Intelligence (Elsevier).

**Floor.** Q1.

## 3. Evidence that forced a decision

### 3.1 The climatology leaves a seasonal residual out of sample

Measured on the Huancayo record: variance of the monthly-mean residual divided
by the total residual variance.

| | in sample (train 2018–2022) | D1 2021 | D2 2022 | D3 2023 | B1 2024 | B2 2025 |
|---|---|---|---|---|---|---|
| C2 (K=3, design default) | 0.012 | 0.097 | 0.110 | **0.235** | 0.137 | 0.110 |
| C3 (K=3 + trend) | 0.012 | 0.102 | 0.111 | 0.237 | 0.137 | **0.242** |
| K=1 | 0.149 | 0.154 | 0.283 | 0.425 | 0.290 | 0.242 |
| K=5 | 0.008 | 0.107 | 0.113 | 0.233 | 0.127 | 0.101 |

Three consequences:

1. **K=3 is the right choice, with evidence rather than convention.** K=1 leaves
   0.149 in sample (Huancayo's cycle is flat through JJA; one harmonic cannot
   carry it). K=5 buys almost nothing over K=3.
2. **C3 must not be reported as a neutral sensitivity.** It is identical in
   sample and worse out of sample, badly so on B2 (0.242 against 0.110). The
   degradation is extrapolation, not substance.
3. **The residual is not a fitting failure.** In D3 the monthly anomaly runs from
   −0.95 °C in June to +0.99 °C in October: a phase shift between the training
   window and 2023, not noise.

**Consequence for the models.** `doy_sin_target_midpoint` correlates −0.48 with
the target in D3 and appears near the top in D1 and B2. That is not a leak — a
calendar feature is known arbitrarily far ahead and the climatology was fitted on
training data only — but it is *not forecast skill either*. It is the model
reconstructing the seasonal shape the harmonic missed. Report it as such.

### 3.2 Feature strength is at the edge of the noise

Correlations against the W1 target on evaluation issuances, n ≈ 51 per fold, so
the standard error of a correlation is roughly 0.14:

| fold | strongest feature | r (W1) | r (W2) |
|---|---|---|---|
| D1 2021 | `TT_anom_mean_30` | −0.19 | +0.18 |
| D2 2022 | `TT_anom_lag_0` | +0.49 | +0.31 |
| D3 2023 | `doy_sin_target_midpoint` | −0.48 | −0.48 |
| B1 2024 | `PP_anom_7d` | +0.31 | +0.28 |
| B2 2025 | `PP_anom_7d` | −0.29 | +0.20 |

Only D2 and D3 clear the noise, and neither is what a forecast should rest on:
D2 is persistence, which `Damp` already supplies; D3 is the climatology
mismatch from §3.1. This is why `07`–`09` must run before any variable is
selected or dropped.

### 3.3 The literature niche is empty — and already occupied conceptually

Ten CrossRef queries, free and credential-free. There is **no** published
probabilistic subseasonal temperature forecast verified at a high-altitude
tropical Andean station. Huancayo appears only in electricity-demand and
cosmetic-dentistry contexts; Andes glacier work is mass-balance reconstruction
from observations, with nobody serving those users a verified forecast.

But the framing is not new. Two papers occupy it:

- Miller et al. 2019, *J. Climate*, `10.1175/jcli-d-18-0389.1` — assessing
  predictability sources and windows of high predictability.
- Allen 2023, *QJRMS*, `10.1002/qj.4478` — a conditional decomposition of
  proper scores quantifying sources of information.

So "decompose the predictability budget" is Miller's framing with Allen's
machinery. Novelty has to come from *where* it is applied (subseasonal, high
altitude, tropics) and *what it finds*, not from the idea.

An empty niche is ambiguous evidence. It can mean untapped opportunity or that
nobody thought it worth doing because the signal is weak — and §3.2 says the
signal is weak. Being first at an empty niche with a thin result is how a desk
reject happens.

### 3.4 IGP/LAMAR has exactly one meteorological station

The Plataforma Nacional de Datos Abiertos carries four IGP/LAMAR datasets. They
are four instrument systems at a single observatory (the 3329 m automatic
weather station, a BSRN radiation station, a 30 m eddy-covariance tower, a UV
radiometer) spanning **22 m of elevation** (3307 / 3315 / 3316.78 / 3329). No
second site appears anywhere in the catalogue or in CrossRef/PubMed.

**This invalidated the design.** Multi-station was the load-bearing assumption
that reconciled the climate framing with EAAI, and it was adopted before anyone
checked whether the data existed. It did not.

### 3.5 SENAMHI GBON/RBON does have a usable network

Dataset `b884a001-f444-4c87-91b2-bee1891e6eb7` on the same platform (ODC-By).
Downloaded and enumerated directly; 416 273 rows.

| Station | UBIGEO | Elev (m) | Department | Mean °C | SD | lag-1 r |
|---|---|---|---|---|---|---|
| MATUCANA | `150701` | 2421 | Lima / Huarochirí | 15.32 | 3.38 | 0.707 |
| SAN_JOSE_DE_UZUNA | `040114` | 3269 | Arequipa / Arequipa | 10.32 | 5.46 | 0.711 |
| CANDARAVE | `230201` | 3410 | Tacna / Candarave | 9.80 | 4.26 | 0.713 |
| CARANIA | `151007` | 3840 | Lima / Yauyos | 8.44 | 4.33 | 0.707 |
| IMATA | `040514` | 4475 | Arequipa / Caylloma | 3.04 | 6.30 | 0.708 |

Verified properties:

- **Coverage 2015-01-01 to 2024-06-30**, 83 253–83 256 rows per station,
  ≈99.8 % of the possible hours. Not interpolated — lag-1 autocorrelation is
  0.707–0.713, which is what hourly mean temperature looks like; interpolation
  would sit near 1.0. Distinct values are consistent with 0.1 °C rounding.
- **Apparent lapse rate −5.98 °C/km** between Matucana and Imata, matching the
  expected Andean rate. The stations are real and distinct.
- **Genuine data.** Span 2054 m over five stations.

Four consequences that were not obvious in advance:

1. **`TEMP` is an hourly *mean***, per the dataset dictionary ("Temperatura
   promedio horaria"). The daily minimum of hourly means is **not** the daily
   minimum; the true minimum falls between hour marks, near dawn. A frost score
   built on this understates both frost frequency and severity. It is still a
   consistent, comparable index across stations and horizons — but it must be
   called a *frost index from hourly-mean temperature*, never "frost
   occurrence", and the limitation belongs in the methods.
2. **Only three variables**: `TEMP`, `HR`, `PP`. No wind, no accumulated rain.
   Of the 22 local predictors, `u_mean_7d`, `v_mean_7d` and
   `log1p_RR_sum_7_30` are lost. The temperature side survives intact, because
   `Tmin`, `Tmax` and `DTR` are derived from hourly values in stage `02`.
3. **`UBIGEO` arrives as a float with inconsistent width** — `40514.0` and
   `40114.0` have lost their leading zero and must be zero-padded to the 6-digit
   INEI form. Without that, two stations are mis-identified.
4. **Data is cut at 2024-06-30.** Portal metadata was touched 2025-09-08 but the
   content did not change. The portal's `package_search` endpoint returns 404
   and the SENAMHI station portal is under maintenance, so no newer snapshot
   could be found. Going further requires contacting SENAMHI.

### 3.6 A property of the network that shapes the LOSO experiment

The five stations are not five replicates of the same kind of place — they are
points along a lapse-rate line, 12.3 °C apart in mean temperature. Holding out
IMATA (4475 m) asks the model to **extrapolate** beyond its training altitude
range; holding out MATUCANA (2421 m) asks it to interpolate. LOSO folds are
therefore not equiponderable: difficulty rises with the altitude held out.

That is information, not a defect. It answers a better question than "does the
model generalise to another station" — namely how far the method degrades when
asked to leave its altitude range. Frame it that way from the start, or it will
look like a bug when it appears in the results.

## 4. Decision record

Every row was chosen deliberately; the rejected column records what was given up.

| # | Decision | Rejected |
|---|---|---|
| 1 | Claim = predictability-budget decomposition | model benchmark (needs skill that may not exist); methodological protocol (reads as careful-but-thin); operational product (no demonstrated skill) |
| 2 | Three-plus stations, single provider | heterogeneous providers (column-mapping layer, instrument confound) |
| 3 | Switch from Huancayo/IGP to SENAMHI | keeping IGP (one station exists); mixing providers |
| 4 | `TT_mean` primary, `Tmin`/`Tmax` secondary | `Tmin` primary (breaks continuity); window-minimum target (different pipeline, not comparable across horizons) |
| 5 | EAAI | `Weather and Forecasting` / `Climate Dynamics` (better fit, but EAAI retained) |
| 6 | Q1 floor | Q2/Q3 floor (safer, less ambitious) |
| 7 | Cross-station generalisation as the AI contribution | negative-result framing (hostile to EAAI's readership) |
| 8 | Niño 3.4 + Niño 1+2 + RMM; ERA5 deferred | full set incl. ERA5 (needs D4 domain/variables, a CDS account, per-fold PCA) |
| 9 | RMM from CPC/CIRES | AO/NAO as proxy (extratropical, weakly relevant to the tropics) |
| 10 | Accept losing wind and rain, ~14–16 predictors | ERA5 substitution (reintroduces what was deferred); hunting other SENAMHI datasets |
| 11 | Temporal blind as primary; LOSO as a separate experiment | both blind at once (6 sparse cells, "blind" stops meaning one auditable thing); LOSO replacing rolling origin (discards the embargo/issuance design) |
| 12 | Frost Brier as a metric, not a target type | window-minimum as a fourth target (separate climatology and aggregation) |
| 13 | Station loop on top, per-station API intact | a `station` column in every table (breaks the `groupby`, the column contracts the tests assert); a per-station output tree (duplicates paths everywhere) |
| 14 | Reopen E2 formally in `METHODOLOGY.md` | leave the doc saying single-station while the code runs five |
| 15 | Rebuild `references.bib` now, in parallel | after results (leaves the paper with no introduction until the end) |
| 16 | Do not touch `paper/`; the author writes `main.qmd` | rewrite it here (framing not yet supported by numbers) |
| 17 | Agriculture / frost as the engineering application | glaciers (no public product either); no use case (weakest for EAAI); hydrology (needs a link to impact) |
| 18 | Six months to submission | one month (forces a single station and Q2/Q3) |

## 5. Design of record

**Folds.** Rolling-origin expanding, redefined for the 2015–2024 window:

```
D1  train 2015-2019  test 2020  dev
D2  train 2015-2020  test 2021  dev
D3  train 2015-2021  test 2022  dev
B1  train 2015-2022  test 2023  blind
B2  train 2015-2023  test 2024  blind
```

Hyperparameters and the primary model freeze before B1. D1 gains five training
years against the three it had on Huancayo, which repairs the weakest fold in
§3.2.

**Targets.** `TT_mean` primary; `Tmin` and `Tmax` secondary. All three are
period-mean anomalies, each with **its own harmonic climatology per fold** — the
`DTR` lesson from stage `05`: subtracting the temperature climatology from a
variable with a different phase leaves a seasonal artefact that reads as skill.
Train-only, never fitted on the test year.

**Predictors.** ~14–16 local, from `TEMP`/`HR`/`PP`. Wind and accumulated rain
are absent and documented as a limitation. Large-scale: weekly Niño 3.4 and
Niño 1+2 (CPC, centre ≤ d−7), RMM1/RMM2 (CPC/CIRES, d−1), train-only per fold.
ERA5 PCs deferred, recorded as a limitation.

**Metrics.** CRPS on a shared 19-quantile grid, CRPSS, tercile RPSS, MSSS
against `Clim` and `Damp`, Murphy decomposition, PIT, reliability, 50/90 %
coverage — plus the **frost index**: Brier score for the probability that the
window minimum crosses the frost threshold, on the same issuance.

**Models.** References `Clim`, `Damp`, `Pers`. Candidates `Ridge` and `GBM`, each
in a local-only and a local-plus-large-scale variant, direct per horizon, GBM
quantiles on the 19-level grid with rearrangement to fix crossings.

## 6. Multi-station refactor inventory

The science is already parameterised — QC thresholds, fold windows, horizons,
embargo, weekday, harmonics and window coverage are all read from `config.yaml`.
What is hardcoded is the plumbing. Exact locations:

| What | Where | Why it breaks |
|---|---|---|
| single-station assertion | `00_verify_source.py:115,119` | `len(values) == 1 == n_expected` fails for any N > 1 |
| station identity dropped | `01_qc_hourly.py:143` | `UBIGEO` is discarded, so no table below carries a station key |
| row collapse | `02_aggregate_daily.py:57` | `groupby("date")` with no station key — two stations on one date silently become one row |
| manifest overwrite | `_common.py:78-88` | `write_manifest` merges shallowly at the top level; a second station replaces the first's blocks |
| import-time path singletons | `_common.py:29-38` | `DATA_DIR`, `OUTPUTS`, `RAW_CSV`, `PROCESSED`, `TABLES`, `FIGURES`, `LOGS` resolved once, with no station dimension |
| fixed output names | all stages | `daily.csv`, `daily_clim.csv`, `issuances.csv`, `features_<fold>.csv`, `climatology/<fold>.json`, `T1_completeness.csv` all lack a station suffix |
| fold-keyed accumulators | `03:253,265-268`, `04:273-285`, `05:216-230` | one `daily_clim.csv` accumulated across folds; `feature_cols` taken from the first fold and reused |
| target hardcoded | `03_climatology.py:59` | `TARGET = "TT_mean"` ignores the declared `data.target_variable` |
| predictor constants hardcoded | `05_features_local.py:41-48` | `LAGS`, `MEAN_WINDOWS`, `RR_WINDOWS`, … ignore `config.predictors.local` |
| year assumed present | `00_verify_source.py:101` | `per_day.loc[str(y)]` raises `KeyError` if a blind year is absent; stations have different coverage windows |

Declared in `config.yaml` but never read by any code: `station.name`,
`station.provider`, `station.lat`, `station.lon`, `station.elev_m`,
`data.target_variable`, `data.non_predictors`, `predictors.local`,
`predictors.large_scale.*`, `climatology.primary`, `models.*`, `metrics.*`,
`inference.*`, `extensions_enabled`.

**The 112 tests in `papers/c20-2026/tests/` should keep passing unchanged** if the
per-station frame API is preserved and the loop is added above it. That is why
decision 13 prefers the loop.

## 7. Open before the paper can be written

1. **Revise `METHODOLOGY.md`.** It still describes single-station Huancayo,
   `E2_multistation: false` (§10), `D1 E2 multi-station: No` (§11), and
   `journal: pending` (§11) while the format block and `manifest.yaml` both name
   EAAI. Sections 2, 4, 6 and 10 need updating; the fold table changes to the
   2015–2024 window; three targets replace one.
2. **Download the SENAMHI file to Drive** and split it per station with `UBIGEO`
   zero-padded to 6 digits.
3. **`pytest.ini` sets `testpaths = tests`**, so CI runs the repository suite but
   never the paper's 112 tests.
4. **`manifest.yaml` is scaffold.** Its single claim cites
   `experiments/exp-01/results/metrics.json`, which does not exist, and its only
   figure points at `media/image2.png`, which does not exist either.
5. **`references.bib` needs a 30–50 entry rebuild.** None of the load-bearing
   citations are present: Clark-West 2007, Murphy 1988, Newey–West, Niño indices,
   Madden–Rolin for RMM, Hersbach, plus the SENAMHI dataset itself.
6. **`paper/main.qmd` describes a third design** that exists nowhere else — an
   anomaly-decomposition ablation with raw and residual arms, horizons of 1, 2, 3
   and 4 weeks. It has no research question, 19 lines of prose out of 132, and
   `Results`, `Discussion` and `Conclusions` are empty. The author owns it.
7. **ERA5 remains `TO_CONFIRM_D4`** and the RMM provider was resolved to
   CPC/CIRES but never exercised.
8. **The honest risk.** §3.2 predicts that `Damp` will not be beaten. That is a
   publishable result, but it is a skill paper rather than an AI paper, and
   EAAI is a harder sell for it. The floor is Q1; a Q2/Q3 outcome is the more
   likely one.
## 8. Run observability

Two decisions were taken because the compute runs in Colab and the runtime is
disposable: a run that cannot be inspected after the fact is a run that has to
be babysited, and that does not scale past a handful of stages.

**A stage log that stands on its own.** `run_all.py` writes
`outputs/logs/<stage>.log` with a header (stage, command, start timestamp,
`paths_report()`, which mode is active), the child's merged output, and a footer
with the real exit code and elapsed time. Read through the Drive MCP with no
notebook and no console, that file answers which stage failed, why, and how long
it took.

**The footer has to be written by Python.** The obvious shell design —
`python stage.py 2>&1 | tee log`, then `echo "exit=$?"` — silently fails: the
footer goes to the shell's stdout, which is downstream of `tee`, so it never
reaches the file, and a footer written earlier cannot know the exit code. Hence
`_common.run_stage` owns the whole file and streams it itself.

That split is also what makes `tqdm` usable in both places at once: raw bytes go
to the terminal so the bar animates, and the same bytes go to the log with
carriage returns collapsed and ANSI stripped, so the file is plain text. On
Windows the child's text-mode stdout delivers every newline as `\r\n`, and a
bare `\r` is indistinguishable from it until you read the next byte. Reading the
child in text mode instead of binary is not a style choice: universal newlines
rewrites `\r` to `\n` before the splitter can see it, and the log comes out
empty while the terminal looks perfect. That is what the regression tests in
`tests/test_stage_logging.py` pin down.

**Fixed filenames, overwritten each run.** A timestamped log name would mint a
new Drive file per run, and a new Drive file means a new Colab URL and a new
runtime session. `paper_drive_sync.py` lists only logs that exist, so a fresh
clone syncs code alone and a half-finished run syncs exactly what it produced.

**Bars only where there is time.** `tqdm` sits on the fold loops in `03`, `04`
and `05` and on the offset-day loop in `seasonal_sigma_hq`, which is the slowest
operation in `03`. Stages `01` and `02` are vectorised pandas and carry no bar:
a progress indicator over an instant operation is decoration.

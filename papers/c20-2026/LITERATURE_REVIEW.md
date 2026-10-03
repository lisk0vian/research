# Literature validation of the design — C20-2026

Checks each decision of design v3 ([`METHODOLOGY.md`](METHODOLOGY.md)) against
the published literature, records which references support it, and lists what
the literature says should change. Written 2026-10-02, before any real-data
score exists, so nothing here was chosen to fit a result.

Keys in brackets are the citation keys of `paper/references.bib`.

## 1. How the references were verified

- **94 entries** in `paper/references.bib`, rebuilt from scratch. The previous
  file had 36 entries, 32 of which were the Elsevier template sample
  (community detection in networks) and unrelated to this paper.
- **88 entries** were resolved by DOI against the CrossRef API, and the BibTeX
  was generated from the returned metadata, not typed by hand. Two of those are
  NeurIPS proceedings DOIs (`10.52202/...`).
- **6 manual entries** have no CrossRef DOI and were checked against OpenAlex:
  Chronos (arXiv preprint), LightGBM (NeurIPS 2017), Holm 1979 (JSTOR DOI), and
  the three data sources (SENAMHI dataset, CPC weekly Niño SST, PSL ROMI).
- **Claims, not only existence.** For the references a design choice actually
  depends on (ROMI, Chronos, Allen 2023, Miller & Wang 2019, the adaptive bias
  correction paper), the abstract was read to confirm the paper says what we
  cite it for.
- Discovery searches ran on OpenAlex (24 topical queries). The academic-search
  MCP was not mounted in this session, so Scopus/Web of Science were not used.
  Citation counts below are CrossRef counts on 2026-10-02.

### Errors found and corrected

| Where | Was | Is |
|---|---|---|
| `DESIGN_DECISIONS.md` §7.5 | "Toth & Buizza, `10.1002/qj.2619`" | That DOI is Buizza & Leutbecher 2015, *The forecast skill horizon* [BuizzaLeutbecher2015] |
| `DESIGN_DECISIONS.md` §3.3 | Miller & Wang 2019 "occupies the framing" of a subseasonal predictability budget | The paper is about **seasonal** ENSO/NAO predictability in CFSv2 reforecasts. It does not occupy the subseasonal framing; it is not cited |
| `DESIGN_DECISIONS.md` §7.5 | `Climatology++`/`Persistence++` from a 2021 NeurIPS workshop | That workshop paper could not be resolved. Cite the published SubseasonalClimateUSA (NeurIPS 2023 Datasets & Benchmarks) [Mouatadid2023usa] and the adaptive bias correction paper [Mouatadid2023abc] instead; confirm in their full text which one defines the baselines before quoting it |
| `DESIGN_DECISIONS.md` §7.5 | Clark & West 2007 and Hersbach 2000 "not obtainable" | Both resolved by DOI [ClarkWest2007, Hersbach2000] |
| candidate list | Genest 1992 DOI `10.1214/aos/1176348784` | That DOI is a different Annals paper (Lahiri 1992). Correct DOI `10.1214/aos/1176348676` [Genest1992] |
| candidate list | Mariotti et al. 2018 in BAMS | It is in *npj Climate and Atmospheric Science* [Mariotti2018] |
| candidate list | Silini et al. 2021, ML prediction of the MJO | **Retracted.** Not cited |

## 2. Is the topic right? The gap, checked

**What exists.**

- Subseasonal (S2S) prediction is an established field with a shared database
  and reforecast protocol [Vitart2017, VitartRobertson2018, Robertson2015,
  Pegion2019, Merryfield2020] and a clear demand from applications
  [White2017, White2022, Domeisen2022].
- The case for machine learning in S2S has been argued explicitly [Cohen2019],
  and benchmark datasets drove progress in data-driven weather prediction
  [Rasp2020, Reichstein2019].
- Machine learning for subseasonal **temperature** is active, almost entirely
  over the contiguous US and Europe [Hwang2019, He2021, Mouatadid2023abc,
  Mouatadid2023usa, Vijverberg2020, vanStraaten2022, Scheuerer2020, Peng2020],
  and data-driven global models now rival dynamical S2S systems [Weyn2021,
  Chen2024].
- Station-level subseasonal temperature skill has been measured after bias
  correction against surface observations [Monhart2018].
- For South America, subseasonal work focuses on **precipitation**
  [Klingaman2021, deAndrade2019]. The MJO is documented to modulate surface
  air temperature over the continent [Alvarez2016], and ENSO's imprint on
  Peruvian climate is well documented [LavadoEspinoza2014, Sulca2018, Cai2020,
  Garreaud2009, Garreaud2009b].
- High-Andean temperature studies are climatological (trends, variability,
  elevation dependence) rather than predictive [VuilleBradley2000,
  LopezMoreno2015, Imfeld2020, Pepin2015, Poveda2020].

**What does not exist.** No search returned a probabilistic subseasonal
temperature forecast verified at high-altitude tropical Andean stations, by
any method. The gap reported in `DESIGN_DECISIONS.md` §3.3 holds.

**What the gap does not prove.** The ML subseasonal literature consistently
finds weak skill beyond week 2 for temperature from observations alone, and the
largest gains come from **combining dynamical forecasts with ML**
[Mouatadid2023abc, Monhart2018, Slater2023]. An empty niche plus a weak signal
is the desk-reject risk already named in §3.2 of `DESIGN_DECISIONS.md`;
recommendation R1 below addresses it.

**Verdict:** the topic is right and the gap is real. The framing must be
honest that skill is expected to be modest, and the pre-registered decision
rule (METHODOLOGY §8) is the correct protection.

## 3. Decision by decision

Verdicts: **supported** (the literature backs it as designed), **supported,
with caveat** (backed, but a limitation must be stated or a detail changed),
**gap** (the literature points at something the design lacks).

### 3.1 Targets and horizons — supported

Period-mean anomalies over weeks 1, 2 and 3–4 are the S2S convention
[Vitart2017, Robertson2015, Pegion2019]; the weeks 3–4 window is where
operational and ML studies report skill [Hwang2019, He2021,
Mouatadid2023usa]. The `TT_min` target and the frost index serve a documented
need: frost is a major risk for high-Andean potato and quinoa farming
[Condori2014].

### 3.2 Climatology — supported, with caveat

A harmonic fit of the annual cycle is the standard way to obtain smooth daily
climatologies [Epstein1991]; fitting it on training data only is what makes
skill against climatology honest. **Caveat:** 4.5–8.5 training years is far
short of a 30-year normal. The harmonic smoothing mitigates sampling noise but
not a short-record bias, and elevation-dependent warming in the Andes [Pepin2015,
VuilleBradley2000] is why the trend variant C3 belongs among the sensitivities.

### 3.3 Reference forecasts — supported

Skill only means something relative to a reference [Murphy1993]. Climatology
and damped persistence are the standard references for statistical
subseasonal forecasts [Mouatadid2023usa, DelSoleTippett2014]. Damped
persistence is the right bar to beat, because station anomalies are strongly
autocorrelated.

### 3.4 Probabilistic verification — supported

| Choice | Basis |
|---|---|
| CRPS as the primary score; strictly proper | [GneitingRaftery2007, Hersbach2000] |
| CRPS from the quantile grid (2 × mean pinball loss) | the quantile-score representation of CRPS [GneitingRanjan2011, LaioTamea2007] |
| PIT histograms and calibration subject to sharpness | [Gneiting2007, Hamill2001] |
| Reliability diagrams with few samples | [BrockerSmith2007] |
| Tercile RPSS | [Epstein1969] |
| Brier score for the frost index | [Brier1950] |
| MSSS and its decomposition | [Murphy1988] |
| General reference | [Wilks2019] |

The grid approximation is about 5 % off the Gaussian closed form (tested in
`tests/test_models_pipeline.py`), identical for every model, so skill ratios
are unaffected.

### 3.5 Statistical inference — supported

- **Clark–West for nested models.** Ridge_L is nested in Ridge_LG, and the
  Diebold–Mariano test [DieboldMariano1995] is mis-sized for nested models,
  which is exactly the case Clark–West corrects [ClarkWest2007].
- **HAC errors.** Weekly issuances with overlapping W3–4 windows are serially
  correlated, so Newey–West errors are needed [NeweyWest1987].
- **Moving-block bootstrap.** It preserves serial dependence [Kunsch1989].
  Resampling the same dates for all stations follows the advice to account for
  the correlation between compared forecasts [DelSoleTippett2014].
- **Multiplicity.** Holm within families [Holm1979] answers the multiple-testing
  critique common in atmospheric science [Wilks2016].

### 3.6 Validation design — supported

- **Rolling origin.** Expanding-window, rolling-origin evaluation is the
  recommended out-of-sample protocol for time series [Tashman2000,
  Bergmeir2012].
- **Structured cross-validation.** Blocking by time, plus leave-one-group-out
  by station, is the structure-aware cross-validation recommended when data
  have temporal and spatial dependence [Roberts2017]. The embargo is the
  temporal buffer that review asks for.

### 3.7 Large-scale predictors — supported, with caveat

- **Niño 3.4 and Niño 1+2.** Both are justified for Peru because the eastern
  (coastal) and central Pacific modes act differently on Peruvian climate
  [Takahashi2011, Sulca2018, LavadoEspinoza2014]. The SST source is OISST
  [Reynolds2002, NOAACPCWeeklySST].
- **ROMI rather than OMI.** Kiladis et al. state that OMI's filtering "cannot
  be done in real time" and give the real-time approximation [Kiladis2014];
  ROMI is that approximation, used in MJO predictability studies [Wang2018,
  NOAAPSLROMI]. RMM [WheelerHendon2004] is the alternative index.
- **Caveat 1:** MJO influence on South American surface temperature is
  documented mostly away from the high Andes [Alvarez2016]. For these stations
  it is a hypothesis to test (H1), not an expectation.
- **Caveat 2:** ROMI's spatial EOF patterns were computed from the whole OLR
  record. That is standard for every MJO index, RMM included, and is not a
  leak in the target, but state it.

### 3.8 Models — supported

| Model | Basis |
|---|---|
| Quantile regression, crossing fixed by rearrangement | [KoenkerBassett1978, Chernozhukov2010] |
| Gradient boosting (LightGBM) | [Ke2017] |
| Pooled LSTM over sites with static descriptors | [Hochreiter1997, Kratzert2019hess] |
| Probabilistic deep forecasters (context for the LSTM design) | [SalinasDeepAR2020, Lim2021] |
| Zero-shot foundation model | [Ansari2024, Liang2024] |
| Quantile averaging (Vincentization) for the ensemble | [Genest1992, Lichtendahl2013, Busetti2017, BatesGranger1969] |

Distributional neural networks for station temperature are established in
weather post-processing [RaspLerch2018]; reviews of ML air-temperature
forecasting [Cifuentes2020] and of forecasting in general [Petropoulos2022]
frame the benchmark. **Caveat on Chronos:** it claims zero-shot accuracy
*comparable* to trained models [Ansari2024], and LLM-based forecasters have
been shown not to beat simple baselines [Tan2024]. Keep Chronos as a modern
baseline, not as the paper's contribution.

### 3.9 Cross-station transfer (LOSO) — supported, with caveat

The closest precedent is hydrology's "prediction in ungauged basins": an LSTM
trained on many basins, with static catchment attributes, predicts basins it
never saw [Kratzert2019hess, Kratzert2019wrr]. That is the framing LOSO should
borrow ("forecasting at a station without its own training history"), and it
gives EAAI a recognised AI question.

**Caveat:** Kratzert et al. trained on hundreds of basins. With four training
stations, static descriptors (elevation, latitude, longitude) cannot be
*learned* as a mapping: they act as station identifiers, and at held-out
Imata or Matucana they are pure extrapolation. See R2.

### 3.10 Data quality — supported, with caveat

The data are the SENAMHI GBON/RBON automatic stations [SENAMHI2024].
Peruvian station records carry documented quality problems: inhomogeneities,
undocumented practices and gaps [Hunziker2017]. The V1–V6 checks and the QC
stage answer this. The automatic GBON/RBON stations differ from the manned
stations studied there, so cite it as motivation, not as a measured property
of this file.

## 4. What the literature says should change

| # | Recommendation | Why | Cost | Priority |
|---|---|---|---|---|
| R1 | Add the dynamical benchmark: ECMWF S2S reforecasts of 2 m temperature interpolated to the five stations, as a model and as a predictor (hybrid) | It is the state of the art the field compares against [Vitart2017, Monhart2018, Mouatadid2023abc, Chen2024, Slater2023]. Without it a reviewer can call the benchmark incomplete, and the hybrid is where the literature finds the largest gains | ECMWF account, extraction for 5 points × 2015–2024, a new stage | **High**: needs the author's decision |
| R2 | LOSO with elevation only, or no static features, next to the current variant | With 4 training stations, lat/lon act as station IDs [Kratzert2019hess needs many sites] | small: one config flag | Medium |
| R3 | Report skill conditioned on active MJO (ROMI amplitude ≥ 1), next to the ENSO-phase split already in F3 | "Windows of opportunity" is how the field reads conditional skill [Mariotti2020]; Allen et al. give the formal tool [Allen2023] | small: stage 10 | Medium |
| R4 | Takahashi E and C indices as a sensitivity to Niño 1+2 / 3.4 | They are near-orthogonal by construction and were built for Peru [Takahashi2011]; Niño 1+2 and 3.4 are collinear | small: stage 06 | Low |
| R5 | Cite the TFT and DeepAR family only as context; do not add them | The design already has a deep model; more architectures add compute, not a new question [Tan2024] | none | done |

## 5. Venue fit

EAAI asks for an AI contribution and an engineering application. Here they are
the pooled and zero-shot models, the station-transfer test framed as
prediction at unmonitored sites [Kratzert2019wrr], and the frost-risk
application [Condori2014]. EAAI publishes ensemble deep-learning methodology
[Ganaie2022]. If the pre-registered rule sends the paper to a climate venue,
the closest precedents appear in *Weather and Forecasting* [Klingaman2021,
Robertson2023] and *Monthly Weather Review* [Scheuerer2020, Vijverberg2020,
vanStraaten2022].

## 6. Reproducing this check

The verification scripts were run outside the repository (they hit public APIs
and are not part of the pipeline). To re-verify any entry, query
`https://api.crossref.org/works/<doi>` and compare title, authors and year with
`paper/references.bib`.

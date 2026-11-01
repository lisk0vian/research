# Decision 0001 — Core contribution of c19-2026

- **Status:** accepted (2026-10-30, Moisés Evangelista Gamarra, with agent support)
- **Scope:** this paper (`papers/c19-2026`)
- **Supersedes:** the implicit framing of the manuscript as "a classifier that predicts
  health vulnerability from the INVS" (abstract, highlights, §4).
- **Target journal:** Applied Geography (`templates/journals/applied-geography/`)

## 1. Context

The Colab run of 2026-10-30 (`outputs` from the pipeline) and the diagnostics on the
resulting frames established the following:

1. The classifier does not generalize across regions: Leave-One-Region-Out AUC
   0.4537 ± 0.0439, below chance in all three macro-regions.
2. The target is circular with the features: `ratio_adulto_mayor` has ρ = 0.9179
   with the INVS and 79 % of positive labels come from the spatial anomaly flag,
   not from a health outcome.
3. The census join silently gave population 0 to 212 districts, including all 196
   province capitals (see the INEI fix: `experiments/_etl.py`).
4. The unit of analysis is effectively the district (target and predictors are
   constant within each of the 1,889 districts), not the facility.

Conclusion: a predictive classifier built on these inputs cannot carry the paper.
A manuscript whose main result is "the model does not transfer" is a negative
result about the model, not a contribution to health geography.

## 2. Decision

The paper's contribution is a **district-level measurement of spatial access to
complex hospital care in Peru**, that accounts for travel time and population, and
that shows how much the resulting priorities depend on method choices.

The classifier is removed from the main argument. It may appear, at most, as a
sensitivity check. The INVS is no longer the central object; if kept, it is one
of several access or need indicators.

## 3. Research questions

- **RQ1 (main).** Which districts have deficient access to complex hospital care
  (level II-2 and above), measured as travel time and weighted by population, and
  where are they concentrated by region?
- **RQ2 (method sensitivity).** How much do the priority rankings change when the
  method changes: straight-line distance versus travel time, catchment size,
  distance decay, facility level, and the treatment of unlocated facilities?
- **RQ3 (validity).** Does the access index agree with an outcome that is
  independent of RENIPRESS and INEI (see open item O1)?

## 4. Claims the paper must be able to support (falsifiable)

- C-A: Straight-line distance misclassifies access for a stated share of districts
  relative to travel time, and the misclassification is spatially structured.
- C-B: The top-k priority districts change by a stated amount across defensible
  method choices. If they do not change, the paper says so and the contribution
  becomes the robustness result itself.
- C-C: The index has a stated (positive or null) association with the independent
  outcome, with uncertainty.

A result that refutes C-A, C-B or C-C is still publishable as long as the
manuscript states it. The question must not be re-scoped to fit the result.

## 5. What is kept, what is dropped

| Component | Decision |
|---|---|
| RENIPRESS + INEI ETL, cleaning, census fix | keep (corrected) |
| Distance metric (haversine to nearest hospital) | replace by travel time / E2SFCA as the main metric; keep haversine as the baseline in RQ2 |
| INVS (PCA/EWM composite) | demote to one indicator; report its sensitivity to weighting (PCA vs EWM ρ = 0.66) |
| Random Forest / HistGrad / Optuna classifier | remove from the main text; keep only as sensitivity if it still adds anything |
| Target `VULNERABLE` | drop as the outcome; it is circular |
| Moran / LISA / Getis | keep, rebuilt on district polygons with all districts (no 1,500 facility sample) and FDR correction |
| Cost–benefit (`24_economico`) | defer; re-scope only after RQ1–RQ3 exist |
| 46 output blocks | prune to what supports RQ1–RQ3; the rest moves to the supplement or is removed |

## 6. Open items

Owners are proposals; change them freely.

| ID | Item | Blocks | Proposed owner |
|---|---|---|---|
| O1 | Choose the independent outcome for RQ3 (candidates: beds or specialists per 10,000 population from MINSA/SUSALUD; referral or transfer records; amenable mortality; emergency response times) and confirm the data can be obtained | RQ3, validity | user |
| O2 | Source the road/river network for travel time (MTC, OSM, or a global friction surface such as Weiss et al.); confirm licence and coverage in the Amazon | RQ1, RQ2 | agent (to research), user (to decide) |
| O3 | Decide the scope: national (1,873 districts) or a pilot of 2–3 regions | feasibility | user |
| O4 | Define the access model precisely: E2SFCA vs. travel-time catchments, catchment size, decay function, which facility levels count as "complex" | RQ1, RQ2 | agent drafts, user approves |
| O5 | Decide the district-level region assignment (replace department-level mapping, which puts Arequipa, Moquegua and Tacna in "Costa" and Huánuco in "Selva") | equity claims | user (source), agent (implement) |
| O6 | Verify all literature for the access and friction methods with `paper-search`; no citation is accepted from memory | introduction, methods | agent |
| O7 | Check Applied Geography's guide for abstract and highlight limits and the review model with `paper-guide` before rewriting | submission | agent |
| O8 | Treat the 16 post-2017 districts (38 facilities) excluded by the census fix as a documented limitation or find a population source | sample | user (decide), agent (document) |

## 7. Revisit criteria

Reopen this decision if:

- O1 cannot be resolved with any available data (then fall back to contribution B:
  a methodological warning about composite-index validation, with a weaker venue fit);
- O2 shows that travel-time data for the Amazon are too poor to be credible;
- the results contradict C-A or C-B in a way that would make the question
  uninteresting.

## 8. Consequences for the manuscript

The current title, abstract, highlights and §4 must be rewritten around RQ1–RQ3.
The numbers in the current `main.qmd` (AUC 0.8369, LORO 0.4537, prevalence 6.19 %,
the Sierra "inequity" finding) are not valid evidence for the new paper and must not
be carried over.

## 9. Data sources update (2026-10-30)

Checked during the data review. Items marked *verified* were read from a source;
items marked *unverified* were reported by a secondary source and need confirmation.

**RENIPRESS (establishments)**

- *Verified:* the portal (datosabiertos.gob.pe, dataset "registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress") publishes one CSV per month from "Abril 2026" to "Octubre 2026"; dataset modified 2026-10-30, release 2025-11-13, frequency monthly, license ODC-By.
- *Verified locally:* the copy in `data/raw/renipress.csv` has 35,371 rows and 26,638 "ACTIVO". `data/README.md` identifies it as the 2026-03-31 cut (the file itself records no date), which is the cut just before the portal's editions start in April 2026. The October 2026 edition is seven months newer and was adopted. (An earlier note here called the old file a 2023 snapshot; that was wrong, it was inferred from a photo-update date.)
- *Action:* download the latest monthly file, record its date and SHA-256, and update the registered snapshot constant in `experiments/00_verify_datasets.py` (currently hard-coded to the old hash and row count).

**Population**

- *Verified:* INEI released first results of the Censos Nacionales 2025 (XIII de Población) on 29 May 2026: total population 34,157,732; counted 32,706,028; estimated omitted 1,451,704; omission rate 4.25%.
- *Unverified:* INEI published district-level results (one secondary source cites 1,892 districts) and a presentation titled "Resultados a nivel provincial y distrital" (July 2026). The INEI pages could not be read from this environment (HTTP 404 and 418).
- *Verified:* the most recent district-level projections found are the INEI "Perú: Proyecciones de Población, 2018-2022" (Boletín Especial N° 27). They are built on the 2017 census, so they do not add new information.
- *Action:* confirm the district-level 2025 census table or REDATAM base is published, check that it has total population, population aged 60+ and population with disability (the variables the pipeline uses), and download it. If the 2025 district counts cover all districts, the 16 post-2017 districts excluded in §4 of the Q1 review (M4) disappear.

**Consequences for the pipeline (not yet applied)**

- Replacing the census changes `RUTA_INEI`, the `state_inputs` in `experiments/colab.yaml` and the Drive `data/` folder. Keeping the file names avoids changes in code and Drive ids.
- The district count changes from 1,874 (2017) to the 2025 count. The assertion in `00_verify_datasets.py` must be updated to match.
- The age and disability variable names will almost certainly differ in the 2025 census. The ETL column mapping in `experiments/_etl.py` must be checked against the real headers before any run.

## 10. Data adaptation done (2026-10-30)

Follow-up to section 9. The data items are resolved in code; the analytic ones remain open.

- **Census 2025 verified and adopted.** The district tables were downloaded from the INEI portal (1,893 districts; totals equal the national row). The pipeline now reads `data/raw/censo-2025-distrital.csv`, built by `experiments/census2025_prepare.py`. Links, dates and hashes: `data/SOURCES.md`.
- **O8 is almost closed.** Districts with active facilities and no census row went from 16 (38 facilities, census 2017) to 1 (UBIGEO 160109, 2 facilities). They are excluded and reported (`UBIGEO_SIN_CENSO`), never given population 0.
- **RENIPRESS October 2026 adopted**, with UTF-8 reading. `III-E` is now level 7 (10 national hospitals and institutes) and category `0` is level 0, no longer primary care. 685 active facilities are complex hospitals (level II-1 or above) and only 625 of them have valid coordinates; 60 cannot enter any distance or travel-time calculation until located. This matters for RQ1 and should be reported.
- **English names.** Raw columns and derived variables use English snake_case. The old names were mapped once by `_schema.IDENTIFIER_RENAMES`; `INVS` and `VULNERABLE` keep their names. `tasa_vulnerabilidad_regional` is now `region_pop_ratio` because it is not a rate.
- **Data dictionary** in `data/dictionary/` (YAML and CSV), generated from the schema and kept in sync by a test.
- **Still open:** O1 (independent outcome), O2 (travel-time network), O3 (scope), O4 (access model), O5 (district-level region). The legacy stages 05-13 still run on the old classifier design and will be reworked under this decision.

## 11. Decisions confirmed at gate G0 (2026-10-30)

- **O1 resolved — outcome:** SINADEF, deaths outside a health facility
  (`TIPO LUGAR != 'EESS'`), with district of residence from `COD# UBIGEO
  DOMICILIO`. Feasibility evidence: `reviews/g0-feasibility-2026-10-30.md` §1.
- **O4 resolved — destination rule:** the main destination set is the public
  general-access hospital: **MINSA + Gobierno Regional, level II-1 and above**
  (`care_level >= 5`). EsSalud, private, armed-forces/police and the 20
  hospital-like uncategorised facilities are sensitivity variants only. The
  "II-2 and above" wording of §3 is superseded: **II-1 is the threshold**.
- **Thresholds:** every "proposed" threshold in the methodology plan is approved
  as written and is frozen when `experiments/analysis_plan.yaml` is created.
- **Still open after G0:** O5 (DEM source and Amazon-basin flag), O2 (which
  travel-time source to register; the friction-surface license is confirmed
  CC BY 4.0), and the INEI license terms for the census tables and boundaries.
- **O5 resolved (2026-10-30):** district mean altitude from **Copernicus DEM
  GLO-30**; the Amazon flag is the **HydroBASINS Amazon basin** clipped to Peru.
  Costa/Sierra/Selva is not used as an analytic category.
- **INEI license decided (2026-10-30):** INEI data are **not redistributed**.
  The reproducibility package ships the derivation scripts and aggregated
  district results only; users rebuild the census tables and boundaries from
  INEI. This also applies to the boundary layer.
- **Boundary source decided (2026-10-30):** `ide.inei.gob.pe` returned 503, so
  the district polygons come from **OCHA COD-AB Peru** (`cod-ab-per`, Admin 3,
  reviewed 2025-10-30, CC BY 4.0). 1,873 units vs 1,893 census districts; the
  gap is reported, never imputed. Join key `adm3_pcode`.
- **RQ3 premise resolved (2026-10-31):** "place of death as an access indicator"
  now has a Peru-wide source: Miranda-Chavez et al. 2026, *Archives of Public
  Health* 84, DOI 10.1186/s13690-026-01872-9 (SINADEF 2017–2024; >40 % of deaths
  at home; home death reflects limited access rather than preference). The
  outcome stays "death outside a health facility"; amenable causes (Nolte &
  McKee 2003; Tobias & Yeh 2009) define the H3a/H3b contrast.
- **Analysis plan v3/v4 (2026-10-31):** v3 corrects the measured polygon gap (21
  census districts without a polygon: 19 created after 2017 + 2 older HDX gaps).
  v4 declares the hospital audit rule before RQ2/RQ3: a hospital more than 20 km
  from its own district polygon is `gross`, leaves the main destination set and
  is re-placed at its district centroid in a sensitivity; the 95 %
  point-in-polygon criterion is evaluated after that declared exclusion and both
  shares are reported. The change log in `analysis_plan.yaml` records each
  version with `sinadef_outcome_data_accessed: false`.
- **Access engine fixes (2026-10-31):** stability compares the worst-access set
  (not the best), unreachable population counts as deficient in the shares,
  multi-source Dijkstra uses `min_only=True`, the grid is 30 arcsec aligned to
  the source rasters, and the east-west pixel width follows latitude.
- **ML reinstated as auxiliaries (2026-10-31, plan v6):** after G3, two
  subordinated uses — (A) calibrate the friction travel time against OSRM
  (regularized linear + isotonic, gradient boosting only if it wins
  leave-one-department-out validation; enters RQ2 as the model-based
  `calibrated_min` variant) and (B) a predictive check that access improves
  out-of-department prediction of death outside a facility (monotonic
  HistGradientBoosting; delta-Brier CI bootstrapped by district and a
  within-department permutation). Refutation criteria are pre-registered;
  a null result is reported. Neither substitutes RQ1–RQ3.
  Verified citations: Roberts et al. 2017 (10.1111/ecog.02881), Ploton et al.
  2020 (10.1038/s41467-020-18321-y), Niculescu-Mizil & Caruana 2005
  (10.1145/1102351.1102430), Grinsztajn et al. 2022 (arXiv:2207.08815).
- **G1 decision confirmed (2026-10-31):** the access engine is accepted for
  **ranking districts**, not for absolute minutes at 120. Main threshold 60 min,
  120 secondary with the caveat (median OSRM/friction 1.24 on long trips, kappa
  0.36 at 120). No engine switch to OSM; `calibrated_friction` enters RQ2. The
  three G1 deviations (department Amazon proxy, friction-quintile strata,
  point-estimate threshold) are recorded in plan v5 and are redone with the DEM
  and the HydroBASINS basin in the region stage.

# G3b gate note — region stage and ML A/B (plan v10/v11)

- **Status:** submitted for human review (2026-10-31); follows the closed G3.
- **Scope:** `papers/c19-2026`, stages `02_regions`, `08_validation_models`
  (altitude), `09_ml_checks` (ML A and B).
- **Verdict:** altitude is added once to RQ3 (H3a stays null). ML A is used
  (Ridge calibration) and ML B is **not refuted** on all causes and on amenable
  causes; both are reported as subordinate, never as confirmatory inference.

## 1. Region stage (02_regions)

- Copernicus DEM GLO-30 averaged to the 30 arcsec grid, then to the district:
  altitude for **1,873/1,873 districts**, 2.2–4,821 m (`regions_missing = 0`).
- HydroBASINS level 4, largest South American basin (the Amazon): **1,018 of
  1,873 districts (54 %)** have their centroid inside it.
- **Wording for the paper:** this flag is the *hydrographic Amazon basin*, not
  the jungle. Whole Sierra departments (Apurímac, Junín, Huánuco, Pasco) are
  100 % inside it; the low jungle is defined by altitude, not by this flag.
- Collinearity (VIF in `controls.json`): altitude 1.33, Amazon 1.33 — no issue.
  38 % of the altitude variance is within-department, so the department fixed
  effects do not absorb it.
- OSM re-stratification (`osm_stratified.csv`, sample column): on the
  **pre-registered 200**, outside the basin rho = 0.850 [0.752, 0.912] (n=86),
  inside rho = 0.653 [0.489, 0.790] (n=113) → the G1 refutation rule is **not triggered**.
  The enriched 150 (remote oversample) is reported separately (0.511 outside)
  and must never be pooled with the 200; a pooled 0.746 was a stage bug,
  corrected.

## 2. RQ3 with altitude (plan v10, stage 08)

- H3a amenable, n=70,496: OR 1.005 (0.986–1.025), p = 0.607; placebo p = 0.610.
  The null stands; altitude did not change it.
- Exploratory all causes: 1.037 (1.023–1.052). GEE 0.992 (0.977–1.009).
- Simulation: FP 7.6 % (> 7 % pre-registered), coverage 90.0 % at OR 1.1;
  RQ3 stays descriptive/negative (G3 note).

## 3. ML A — friction calibration (used)

- Candidates: Ridge, isotonic on friction, monotone GBM; LODO validation vs the
  constant-ratio baseline; the simplest winner is used.
- **Winner: Ridge** (plan v6 rule): MAPE 0.585 vs baseline 2.056; remote
  Spearman 0.602 vs 0.431; kappa 60 = 0.691 vs 0.686; kappa 120 = 0.490 vs
  0.371. `calibrated_min.csv` for 1,872 districts.
- **Cautions for the paper (human review, 2026-10-31):**
  1. The kappa-60 win over the baseline is 0.005 — noise, not evidence of a
     substantially better calibration. The honest summary is that the Ridge
     model dominates on MAPE and in the remote tail, not on the 60-min
     classification.
  2. MAPE is still 59 %; the calibration fixes systematic bias, not route
     noise.
  3. The training sample is 249/348 (72 %) remote routes (the enriched 150 are
     in it). The model is applied to district means, so it is a **sensitivity
     variant** in RQ2, reported next to the uncalibrated measure and the G1
     band calibration — never the headline number.

## 4. ML B — predictive check (not refuted, both populations)

HGB with a monotonic (non-decreasing) constraint on access time; target death
outside a facility; LODO (26 departments); delta-Brier with district-block
bootstrap CI (row-weighted); within-department permutation of access.

| Population | n | delta-Brier | CI | perm drop | CI | Refuted |
|---|---:|---:|---:|---:|---:|---|
| All causes (pre-registered, v6) | 593,438 | 0.00313 | 0.00173–0.00479 | 0.00395 | 0.00382–0.00408 | no |
| Amenable (H3a population, v11) | 70,496 | **−0.00292** | −0.00574 – −0.00012 | 0.00282 | 0.00260–0.00305 | no positive contribution |

- **Interpretation (human review, 2026-10-31):** B measures predictive value,
  not causal effect. On all causes it reproduces the same non-specific
  gradient as the exploratory `other` group (1.053); it does not contradict
  the null H3a.
- **Amenable population (v11):** the delta-Brier is **negative** and its CI
  excludes zero on the negative side: access time adds no out-of-sample
  predictive value among amenable causes (the model with access is slightly
  worse), even though the fitted model responds to it (permutation drop
  +0.0028). The letter of the refutation rule says "not refuted" (the CI does
  not include 0), but the rule assumed a positive sign; the honest wording for
  the paper is "no positive predictive contribution among amenable causes,
  consistent with the null H3a", with the all-causes result reported next to
  it. The human decides the exact sentence at writing time.

## 5. Status of the open Q1 findings

Findings 4–11 of `q1-review-2026-10-30-run2.md` (automatic verdict, silent
conformal fallback, facility-level bootstrap, economic analysis, circular
sensitivity, stale tables, Moran/LISA) all live in the legacy stages
(02_spatial_clusters … 13_reproducibility_package). They are closed by
**retiring those stages** from the pipeline: authorized by the researcher
(2026-10-31), moved to `code/_legacy/` on Drive (not discovered by the runner)
and to `experiments/_legacy/` in the repo (kept, excluded from sync). The
active pipeline is 11 stages (00–09).
Findings 6–7 (unit of analysis, RQ1) are addressed by the new grid-based
pipeline.

**Runner hardening (2026-10-31):** two legacy files that Drive would not let
us move (`06_evaluate_classifier.py`, `07_explain_shap.py`) still appeared in
`code/`, so the first clean "Run all" executed them and rewrote orphan outputs
(`28_metricas_extendidas/bootstrap.csv`, `05_shap/*`). `run_all.py` now passes
the stages declared in `colab.yaml` to the runner instead of the glob, so no
undeclared file can ever run again (`--only 06_evaluate_classifier` answers
"unknown stage"). The orphan outputs stay on Drive as evidence of the legacy
run; the manuscript does not cite them.

## 6. Open items for the human

- **Legacy stages in `colab.yaml`** — a "Run all" still executes the discarded
  design and packages orphan outputs. Move them to `code/_legacy/` on Drive
  (kept in the repo): decision required.
- **District alias table** (Carmen de la Legua-Reynoso; Nazca/Vista
  Alegre/Marcona in Ica): optional, does not affect H3a (G3 note).
- **AI-use declaration and novelty check**: belong to the G4/paper stage, not
  to the pipeline.

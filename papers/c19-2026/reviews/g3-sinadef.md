# G3 gate note — SINADEF outcome, RQ3 models and validation

- **Status:** submitted for human review (gate G3, 2026-10-31, final)
- **Model:** plan v10, with district mean altitude as the pre-registered covariate
  (added once after the region stage; result reported as is).
- **Scope:** `papers/c19-2026`, stages `02_regions`, `07_outcome_sinadef`,
  `08_validation_models`
- **Verdict:** **RQ3 is a negative result.** H3a (amenable causes) and H3b are
  null; the all-cause association is exploratory, driven by non-amenable causes,
  and not specific to access (cancer does not discriminate). The simulation's
  false-positive rate is **7.6 %**, above the pre-registered 7 %, so the model is
  **not used for confirmatory inference**. The paper's weight stays on RQ1/RQ2.

## 1. Data (stage 07, real SINADEF, v3)

- File `TB_SINADEF_2026-10-30.csv` (sha256 `bb4058…`), 1,439,302 rows.
- **601,092 deaths in 2022–2025**; 1,092,727 in 2020–2025 (period sensitivity).
- RENIEC→INEI crosswalk by names: 1,079,548 resolved; 13,179 unmatched names;
  **Callao is now matched by name** (no deaths assigned to Tumbes).
- Excluded places (empty/SIN REGISTRO/IGNORADO) are removed from the model.
- Model frame: **593,438 deaths**; main amenable population **70,496 deaths**.
- Access recorded in plan v7/v9 and `sinadef_accessed.json` (06:18:40 UTC).

## 2. H3a — amenable causes (main, name-resolved districts)

Logistic GLM, department fixed effects, district-cluster robust SEs,
population-averaged OR (plan v8); covariates age, sex, cause group,
**district mean altitude** and department FE (plan v10). Altitude is available
for all 1,873 districts (2.2–4,821 m; `regions_missing = 0`).

| Metric | Value |
|---|---|
| n | 70,496 |
| OR per +60 min | **1.005** |
| 95 % CI | 0.986 – 1.025 |
| p | 0.607 |
| Placebo (200 permutations within department) | p = 0.610 |

**H3a is null.** The association does not appear among causes amenable to
hospital care.

## 3. Exploratory (post hoc) — all causes, and amenable sensitivities

**All causes (exploratory, not the H3a population):**

| Population | n | OR per +60 min | 95 % CI |
|---|---:|---:|---|
| All causes | 590,654 | 1.037 | 1.023 – 1.052 |

**Amenable causes (H3a population) — sensitivity subsamples:**

| Subsample | n | OR per +60 min | 95 % CI |
|---|---:|---:|---|
| Excluding low-completeness districts | 69,569 | 1.007 | 0.986 – 1.028 |
| Excluding `OTRO` place | 69,371 | 1.004 | 0.985 – 1.024 |
| Period 2020–2021 | 45,047 | 1.022 | 0.986 – 1.059 |

The all-cause association is exploratory and disappears in every amenable
subsample.

## 4. H3b — by cause group

| Cause group | n | OR per +60 min | 95 % CI |
|---|---:|---:|---|
| Amenable acute | 56,485 | 1.000 | 0.977 – 1.023 |
| Amenable chronic | 14,011 | 1.020 | 0.986 – 1.054 |
| Cancer (negative control) | 29,112 | 1.032 | 0.978 – 1.090 |
| External | 1,930 | 1.026 | 0.960 – 1.096 |
| Other | 391,960 | **1.053** | 1.034 – 1.071 |
| Unknown cause | 97,156 | **0.972** | 0.951 – 0.993 |

Time x cause interaction acute vs chronic: **p = 0.251** (with altitude,
plan v12): H3b is null. The
gradient lives in `other`; cancer does not discriminate (same point estimate as
the exploratory all-cause model).

## 5. Estimator sensitivity

- GEE exchangeable, 50k sample: OR 0.992 (0.977 – 1.009), p = 0.357. Null, and
  **opposite sign** to the main estimate; the "same sign" criterion fails.
- Both estimators agree that the amenable association is null.

## 6. Known-truth simulation (cells, full size, district random intercept)

Cells: 6,889 (district x age x sex x cause), 70,496 deaths; district SD 0.551;
real baseline odds.

| Planted OR | Mean OR | Bias | Coverage | Power |
|---:|---:|---:|---:|---:|
| 1.1 | 1.097 | −0.2 % | 90.0 % | 0.99 |
| 1.2 | 1.201 | +0.05 % | 92.5 % | 1.00 |
| 1.5 | 1.485 | −1.0 % | 93.5 % | 1.00 |

Null (500 reps): **false-positive rate 7.6 %**, above the pre-registered 7 %
(Monte Carlo SE ≈ ±1.2 points; at the boundary). Coverage at 1.1 is 90.0 %,
below the 92 % target; 1.2 and 1.5 are inside or at the edge; bias and power
pass.

**Consequence (pre-registered):** the false-positive rate exceeds 7 %, so the
model is **not used for confirmatory inference**. Since H3a is null anyway, the
failure does not create a positive claim; it confirms that RQ3 must be reported
as descriptive/negative, not as evidence of absence of effect.

## 7. What this means for the paper

- RQ3: **negative result and limitation**. Distance to a complex hospital is not
  associated with dying outside a facility among causes amenable to hospital
  care. The all-cause association is exploratory, non-specific, and does not
  survive the amenable restriction, the GEE or the negative control.
- The paper's weight is RQ1 (measurement) and RQ2 (method sensitivity).
- The negative result matches the plan's rule: "A null result is reported as it
  is. The question is not changed to fit the result."

## 8. What the researcher checks at G3

- Accept the null H3a/H3b and the negative RQ3 (§2, §4).
- Accept that the simulation FP (7.6 %) disqualifies confirmatory use (§6), and
  that RQ3 is reported as descriptive.
- The Callao fix and the 13,179 unmatched names (§1): check whether the
  unmatched concentrate in one department before writing the limitation.
  **Known residue (2026-10-31):** 1,041 deaths of "Carmen de la Legua-Reynoso"
  still miss the name match (hyphen vs space) and fall to Tumbes by code; they
  are outside the main H3a population but remain in the all-cause exploratory
  model. The 7,354 unmatched deaths in 2022–2025 are 2,507 non-district entries
  ("SIN REGISTRO", "EXTRANJERO"), 1,491 in Ica (Nazca, Vista Alegre, Marcona)
  and isolated cases; a district alias table fixes them later.
- The next steps: region stage (DEM + HydroBASINS, collinearity of altitude and
  the Amazon flag), then ML A/B (plan v6), then G4.

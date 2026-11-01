# G2 gate note — RQ1, RQ2, need × access and spatial statistics

- **Status:** submitted for human review (gate G2, 2026-10-31)
- **Scope:** `papers/c19-2026`, stages `04_access_sensitivity`, `05_need_priority`, `06_spatial_stats`
- **Verdict:** all three stages run clean (Colab 02:52–02:54, `errors.log` empty).
  RQ1 is delivered; RQ2 shows that the **method changes the priorities** (the
  paper's C-B), while destination sets do not; M5 is **weight-dependent**; M7
  finds robust **global** clustering but unstable **local** clusters. Each
  result is reported with the qualification the frozen plan requires.

## 0. Update 2026-11-01 — G5 forced full run (plan v14)

One forced Colab run (session `20261101T045039Z`, 12/12 stages `ok`,
`errors.log` empty, `run_meta.json` code hashes equal to commit `0c28cf7`).
Against the pre-G5 snapshot, stages 02, 03, 05, 07, 09 and the core of 08 are
byte-identical; only the corrected parts changed. **This section supersedes the
kappa column of §2, the 2SFCA rows of §2 and the cluster counts of §4.**

Why: `stability()` compared every variant with `> 60`, so the straight-line
kappa compared ">60 km" with ">60 min", and the negated 2SFCA score never
crossed 60 (constant class, kappa 0.0 by construction). v14 uses the same
thresholds for variants in minutes and quantile matching (flag as many districts
as the main measure: 746 at 60 min, 235 at 120 min) for km and 2SFCA; 2SFCA now
counts hospitals per cell and is person-weighted (plan: "supply = count").

| Variant | Spearman (95 % CI) | Kendall | Jaccard top-100 | κ 60 | κ 120 |
|---|---|---:|---:|---:|---:|
| Straight line, district centre (km) | 0.902 (0.891–0.914) | 0.742 | 0.429 | 0.739 | 0.582 |
| Straight line, population-weighted (km) | 0.923 (0.912–0.934) | 0.787 | 0.351 | 0.777 | 0.538 |
| Travel time at the centre cell (M2) | 0.810 (0.788–0.830) | 0.652 | 0.538 | 0.664 | 0.448 |
| Calibrated friction (G1 band ratios) | 0.995 (0.994–0.996) | 0.971 | 1.000 | 0.819 | 0.906 |
| Public + EsSalud | 0.993 (0.988–0.996) | 0.977 | 0.980 | 0.990 | 0.998 |
| All complex hospitals | 0.992 (0.987–0.995) | 0.967 | 0.980 | 0.979 | 0.993 |
| All + uncategorised | 0.991 (0.987–0.995) | 0.964 | 0.980 | 0.978 | 0.988 |
| Walking time | 0.958 (0.951–0.964) | 0.843 | 0.527 | 0.136 | 0.062 |
| 2SFCA, 60-min catchment | 0.524 (0.483–0.562) | 0.361 | undefined (ties) | 0.539 | 0.545 |
| 2SFCA, 120-min catchment | 0.306 (0.256–0.348) | 0.215 | 0.504 | 0.271 | 0.494 |

Source: `outputs/04_access_sensitivity/stability.csv`. 2SFCA "no hospital in
the catchment" vs >60 min: κ 0.418 (60-min catchment; 14.9 % of districts and
4.2 % of people score zero) and 0.326 (120-min; 2.7 % and 1.2 %).

Reading, against the frozen criteria:

- **C-A (straight line misclassifies) is not refuted:** ρ 0.90–0.92 < 0.95 and
  κ60 0.74–0.78 < 0.90. The corrected kappas are higher than the old 0.40/0.38,
  so the honest wording is "ranks alike, disagrees on about one district in ten
  near the cut" (100 + 100 discordant districts of 1,872 for the population-
  weighted line), not "agrees poorly".
- **M2 is not refuted:** the centre cell gives ρ 0.810 < 0.95, and flags 1,010
  districts instead of 746 at 60 min. Person weighting changes who is flagged.
- **Destination sets** stay invariant (ρ ≥ 0.991, κ ≥ 0.978).
- **2SFCA** orders districts differently (ρ 0.52/0.31); the old κ 0.0 was an
  artefact and is not used anywhere.
- **Walking** ranks districts like motorized time (ρ 0.958) but at 60 min flags
  1,686 of 1,872 districts; 46.5 % of people live over 60 min on foot.
- **Province exclusion** (12 provinces holding the 21 census districts without a
  polygon; the plan text said 11): 1,759 districts, share >60 min 10.6 %
  (all: 10.9 %), >120 min 4.4 % (4.6 %).
- **M7 with a seed:** local clusters 235 / 266 / 456 (queen / k4 / k8),
  variation 69 % vs the 25 % maximum: still unstable, global I unchanged.
- Correction to earlier notes: the polygon without a census row is
  **120699 "Mazamari - Pangoa"** (Satipo, no population assigned); 160109 is a
  RENIPRESS ubigeo without a census row, not a polygon.

## 1. RQ1 — district access (main measure)

Person-weighted mean travel time **37.8 min**; district-weighted mean 91.6 min
(the contrast is the point: small remote districts carry little population).

- Population beyond **60 min: 10.9 %**; beyond **120 min: 4.6 %**.
- 371 districts in the "high need + poor access" quadrant (2.3 % of population).
- Full table: `outputs/03_access_travel_time/district_access.csv`.

## 2. RQ2 — method sensitivity (Spearman / Jaccard top-100 overlap / kappa 60)

| Variant | Spearman | Jaccard top-100 | kappa 60 |
|---|---:|---:|---:|
| Straight line from centroid | 0.902 | 0.429 | 0.396 |
| Population-weighted straight line | 0.923 | 0.351 | 0.380 |
| Calibrated friction (G1 ratios) | 0.995 | 1.000 | 0.819 |
| Public + EsSalud | 0.993 | 0.980 | 0.990 |
| All hospitals | 0.992 | 0.980 | 0.979 |
| All + uncategorised | 0.991 | 0.980 | 0.978 |
| 2SFCA 60 min (inverted: higher = better) | 0.553 | 0.093 | — |
| 2SFCA 120 min | 0.371 | 0.399 | — |

Reading:

- **C-A holds.** The straight line keeps a high global correlation but
  **misclassifies the worst-access top-100 set**: Jaccard 0.35–0.43 against the
  pre-registered 0.60. Travel time adds information exactly where priorities
  are decided.
- **C-B holds.** 2SFCA and the straight line reorder the priorities
  (2SFCA-60 Jaccard 0.11); the paper reports the priority list as
  method-dependent.
- Destination sets and the calibrated friction do **not** change the ranking
  (Jaccard ≥ 0.98): the public-only choice is not what drives the result.
- 2SFCA was computed on a factor-4 coarse grid (declared simplification).

## 3. M5 — need × access (no PCA)

- Need = z(share 60+) + z(share with disability), equal weights.
- Priority quadrant (need z > 0 and access > 60 min): **371 districts**,
  739,935 people (2.3 %).
- Membership stability across 5 weighting schemes: **97.3 %** (≥ 80 %).
- Kendall tau against the equal-weight scheme: 0.97 (min-max), 0.95 (rank),
  0.76 (60+ only), **0.73 (disability only)** → the pre-registered minimum 0.80
  is **not met**.
- Per the plan, **no single composite is presented**: the priority list is
  declared weight-dependent, and both components are reported separately.

## 4. M7 — spatial statistics

| Neighbourhood | Global Moran I | p (9,999) | Local clusters (FDR q < 0.05) |
|---|---:|---:|---:|
| Queen | 0.662 | 0.0001 | 239 |
| k = 4 | 0.656 | 0.0001 | 253 |
| k = 8 | 0.547 | 0.0001 | 451 |

- Global clustering is **stable** (same sign, significant in all three).
- Local cluster counts vary by **67 %** (pre-registered maximum 25 %), so local
  clusters are **not claimed as stable**; they are reported with this
  qualification and per-neighbourhood.

## 5. What the researcher checks at G2

- The stability table (§2) and the top-100 overlap and the
  district-level variant file (`outputs/04_access_sensitivity/district_variants.csv`).
- The weight-dependence of the priority list (§3): accept "no single composite".
- The local-cluster instability (§4): accept reporting clusters per
  neighbourhood rather than one map.
- Destination-set invariance (§2): the public-only main set is defended by the
  variants, not by preference.

## 6. Not established here

(2026-11-01: the walking variant and the discordance map now exist, see §0
and `outputs/10_figures_tables/Fig3_methods.png`; the bullets below record the
state at G2.)

- Walking-time variant: the walking friction surface is not downloaded; declared.
- DEM and HydroBASINS: not built yet; district altitude, the Amazon basin and
  the G1 re-stratification arrive with the region stage.
- Discordance is delivered as CSV, not as map images.
- The 2SFCA coarse grid and the calibrated ratios inherit the G1 caveats.

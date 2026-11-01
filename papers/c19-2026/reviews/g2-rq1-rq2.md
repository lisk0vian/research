# G2 gate note — RQ1, RQ2, need × access and spatial statistics

- **Status:** submitted for human review (gate G2, 2026-10-31)
- **Scope:** `papers/c19-2026`, stages `04_access_sensitivity`, `05_need_priority`, `06_spatial_stats`
- **Verdict:** all three stages run clean (Colab 02:52–02:54, `errors.log` empty).
  RQ1 is delivered; RQ2 shows that the **method changes the priorities** (the
  paper's C-B), while destination sets do not; M5 is **weight-dependent**; M7
  finds robust **global** clustering but unstable **local** clusters. Each
  result is reported with the qualification the frozen plan requires.

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

- Walking-time variant: the walking friction surface is not downloaded; declared.
- DEM and HydroBASINS: not built yet; district altitude, the Amazon basin and
  the G1 re-stratification arrive with the region stage.
- Discordance is delivered as CSV, not as map images.
- The 2SFCA coarse grid and the calibrated ratios inherit the G1 caveats.

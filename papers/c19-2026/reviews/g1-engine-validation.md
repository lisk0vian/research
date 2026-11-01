# G1 engine validation — travel time and population

- **Status:** submitted for human review (gate G1, 2026-10-31)
- **Scope:** `papers/c19-2026`, plan "c19-2026 methodology plan", Order of work §3
- **Verdict:** the engine passes the pre-registered G1 check for **ranking
  districts** (200-centroid sample: 0.801 outside Amazon), not for absolute
  minutes at 120. The enriched 350-centroid sample (which deliberately
  oversamples the remote tail) gives 0.724 outside Amazon and 0.475 over 60 min:
  it does not replace the pre-registered test, it maps where the engine fails.
  Plan v5 therefore sets **60 min as the main threshold and 120 as secondary
  with a caveat**, and adds a calibrated friction variant to RQ2. The engine is
  not switched to OSM: no pre-registered rule requires it.

## 1. Synthetic tests (no real data)

`experiments/_access.py` and `experiments/_simulate.py`, 37 c19 tests passing:

- Uniform row: time = distance x cost exactly; source pixel = 0 min.
- Diagonal costs sqrt(2); a blocked cell forces the expected detour.
- Physical consistency: time >= straight distance x minimum cost, random surfaces.
- East-west pixel width follows `cos(latitude)` (tested at 18 S).
- Population allocation keeps every census total exactly; a district with no
  cells is reported, never invented.
- Unreachable cells count as deficient in the shares and are reported separately.
- Stability compares the **worst** districts (best and worst sets differ in the test).
- Planted OR per +60 min recovered (1.5) and null OR near 1.

## 2. Real-data checks (Colab run 2026-10-31 01:42–01:55, 30 arcsec grid)

`outputs/03_access_travel_time/checks.json`:

| Check | Result |
|---|---|
| Population allocated vs census (with polygon) | 32,411,730 = 32,411,730 (relative error 9e-16) |
| Hospitals at 0 minutes | pass |
| Time >= distance / max speed | pass |
| Unreachable cells | 0 % |
| Public destinations in the grid | 174 unique pixels (182 located, 180 in grid) |
| Hospital audit, raw | 172/182 = 94.5 % |
| Hospital audit, after excluding gross misplacements | 172/179 = 96.1 % |
| Gross misplacements (excluded) | 2: Camaná 222.6 km, Llata 228.7 km |
| M6 sensitivity (misplacements at district centroid) | 21/1,873 districts change class = 1.12 % (threshold 5 %) |

## 3. Independent engine: OSM (OSRM demo, cached)

Sample: 200 district centroids stratified by access quintile; 199 routed (one
district has no OSRM road segment; OSRM returned HTTP 400 / NoSegment).
Each district is routed to its 3 nearest hospitals by straight line and the
minimum OSRM time is used, matching "nearest by travel time" on the friction
surface.

| Subset | n | Spearman | Bootstrap 95 % CI |
|---|---:|---:|---|
| All | 199 | 0.738 | [0.637, 0.823] |
| Outside the Amazon proxy (5 departments) | 174 | **0.801** | **[0.732, 0.855]** |

Median OSRM / friction ratio: 1.17.

**Caveat:** the pre-registered refutation rule is "Spearman < 0.80 outside the
Amazon -> switch the main engine to OSM routing". The point estimate is 0.801,
so the rule is not triggered; the CI lower bound (0.732) is below the threshold,
so the margin is thin. The paper must report the CI and the Amazon separately.

**Basin re-stratification (2026-10-31, region stage, `osm_stratified.csv`):**
with the real HydroBASINS flag instead of the departmental proxy, and the two
samples kept apart, the pre-registered 200 gives outside-basin rho = **0.850**,
CI [0.752, 0.912] (n=86) and Amazon-basin rho = 0.653, CI [0.489, 0.790] (n=113). The rule is
still not triggered on its own sample. The enriched 150 must never be pooled
with it: their outside-basin rho is 0.511 (n=73); pooling produced a misleading
0.746, which is corrected in the stage output.

## 3b. Post-G1 secondary metrics (declared post hoc, no pass/fail)

Added after seeing the first 200-centroid table; registered in plan v5. Two
samples, two different questions:

- **Pre-registered 200** (stratified by access quintiles): outside Amazon
  rho = 0.801, CI [0.732, 0.855].
- **Enriched 350** (the same 200 plus 150 districts with district mean > 45 min,
  i.e. deliberately oversampling the remote tail, so it is **not**
  representative): outside Amazon rho = 0.724; Amazon rho = 0.454 (n=40).

| Subset (enriched 350) | n | Spearman | kappa 60 | kappa 120 |
|---|---:|---:|---:|---:|
| All | 348 | 0.661 | 0.66 | 0.34 |
| Outside Amazon proxy | 308 | 0.724 | 0.69 | 0.35 |
| Amazon proxy | 40 | 0.454 | 0.31 | 0.17 |
| OSRM > 30 min | 302 | 0.595 | — | — |
| OSRM > 60 min | 241 | **0.475** | — | — |

Median OSRM/friction ratio: 1.07 overall, 1.12 outside Amazon. Leave-one-
department-out (outside Amazon, enriched): rho 0.709–0.748.

Reading: the pre-registered test passes on its own sample; the enriched sample
shows the engine is weak precisely in the remote tail. The paper therefore
limits itself to **ranking districts at 60 min**, reports 120 as secondary with
the caveat, and never interprets absolute minutes in the tail.

## 4. City pairs (friction vs OSRM)

| From | To | Friction (min) | OSRM (min) | APE |
|---|---|---:|---:|---:|
| Lima | Ica | 284.2 | 336.3 | 15 % |
| Trujillo | Chiclayo | 213.3 | 199.5 | 7 % |
| Cusco | Puno | 392.2 | 470.5 | 17 % |
| Arequipa | Moquegua | 176.9 | 200.8 | 12 % |
| Huancayo | Ayacucho | 216.8 | 350.3 | 38 % |
| Piura | Tumbes | 274.3 | 230.3 | 19 % |

**MAPE 18.0 %** (threshold <= 30 %), max 38.1 % (Huancayo–Ayacucho; the friction
surface is optimistic on that Sierra route).

## 5. What the researcher checks at G1

- The synthetic tests (§1) and the real-data tables (§3, §3b, §4).
- Population conservation (§2) and the audit numbers.
- **Decision confirmed (2026-10-31):** accept the engine for ranking districts;
  60 min is the main threshold and 120 secondary with the caveat; do not migrate
  to OSM; the calibrated-friction variant enters RQ2. The remote sample and the
  DEM/HydroBASINS stratified recheck (§6) close the remaining gaps before
  RQ1/RQ2 are interpreted.

## 6. Not established here

- The OSRM public demo is the independent reference, not field-measured travel
  time; its reliability is not audited here.
- Absolute minutes carry a declared metric bias (30 arcsec cells, 927 m at the
  equator; up to ~5 % east-west).
- The Amazon is reported apart: the OSM proxy is departmental, and 3 pilot
  districts fall in it.
- The DEM (Copernicus GLO-30) is not built yet; district altitude and the
  altitude stratification of the sample arrive with the region stage.

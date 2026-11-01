# G0 feasibility note — SINADEF, polygons, destinations and licenses

- **Status:** submitted for human review (gate G0, 2026-10-30)
- **Scope:** `papers/c19-2026`, plan "c19-2026 methodology plan", Order of work §0
- **Author:** implementing agent
- **Verdict:** O1 (SINADEF deaths outside a health facility) is **feasible**. The gate
  condition "if SINADEF lacks place of death or district of residence, stop and
  reconsider O1" is **not** triggered. One residual check is deferred to step 2
  (per-year completeness of 2024–2025 in the open-data snapshot; §1.3).

How this was verified: the MINSA hosts sit behind Cloudflare, so `curl` is blocked
from this machine. The dictionaries and the data file headers were fetched through
a headless browser (HTTP 200/206 partial content) on 2026-10-30; every URL and
number below comes from that session or from the repository files named.

## 1. Outcome O1 — SINADEF

### 1.1 What the publisher exposes

Two open datasets on the Plataforma Nacional de Datos Abiertos, both under
**ODC-By** (http://opendefinition.org/licenses/odc-by/):

| Dataset | CKAN id | Data resource | Dictionary |
|---|---|---|---|
| Información de Fallecidos del SINADEF (launched 2020-05-21) | `ba538c68-c5e0-4098-985d-c5e271c973a6` | `https://drive.minsa.gob.pe/s/PigmdwnCGEdyqos/download` — CSV, `\|`-separated, UTF-8, 383,534,277 bytes, 1,110,168 rows (checked 2026-10-30) | `Diccionario_Datos_SINADEF.xlsx` (10.4 KB) |
| SINADEF: Certificado Defunciones (launched 2021-08-19, **frequency daily**) | `e583e8c7-800b-4dd1-b88b-e3692180b17a` | `https://cloud.minsa.gob.pe/s/g9KdDRtek42X3pg/download` — 7z archive, 39,320,897 bytes, containing `TB_SINADEF.csv` | `DD_TB_SINADEF_0.xlsx` (11.27 KB) |

The 2017–2019 rows in the first file are the historical series; the second file is
the current daily cut. Both datasets are tagged `covid19` on the portal, but the
content is all-cause mortality ("defunciones generales"), not COVID-only.

### 1.2 Fields — verified against the official dictionaries and the real header

`Diccionario_Datos_SINADEF.xlsx` (sheet `Hoja1`) lists 31 columns; the real CSV
header carries one extra, `ETNIA` (drift to document in the schema notes):

`Nº, TIPO SEGURO, SEXO, EDAD, TIEMPO EDAD, ESTADO CIVIL, NIVEL DE INSTRUCCIÓN,
ETNIA, COD# UBIGEO DOMICILIO, PAIS DOMICILIO, DEPARTAMENTO DOMICILIO,
PROVINCIA DOMICILIO, DISTRITO DOMICILIO, FECHA, AÑO, MES, TIPO LUGAR, INSTITUCION,
MUERTE VIOLENTA, NECROPSIA, DEBIDO A (CAUSA A), CAUSA A (CIE-X), …,
DEBIDO A (CAUSA F), CAUSA F (CIE-X)`.

The daily table (`DD_TB_SINADEF_0.xlsx`, sheet `TB_SINADEF`) adds `ID_UBIGEO`,
`FALLECIDO_CAUSA_COVID` and `ID_PERSONA`, and is otherwise the same schema.

Mapping to the M8 design:

| M8 need | Field(s) | Evidence |
|---|---|---|
| Place of death | `TIPO LUGAR` (values seen in real rows: `EESS`, `DOMICILIO`, `VIA PUBLICA`, `OTRO`) and `INSTITUCION` (`MINSA`, `GOBIERNO REGIONAL`, `ESSALUD`, `PRIVADO`, `SIN REGISTRO`) | dictionary + real rows |
| District of residence | `COD# UBIGEO DOMICILIO`; its last six digits are the six-digit UBIGEO (checked: `92-33-14-01-32-000` ↔ Villa María del Triunfo, UBIGEO 140132) | dictionary + real rows |
| Cause | `DEBIDO A (CAUSA A..F)` + `CAUSA A..F (CIE-X)` | dictionary |
| Age | `EDAD` + `TIEMPO EDAD` | dictionary |
| Sex | `SEXO` | dictionary |
| Date | `FECHA`, `AÑO`, `MES` | dictionary |

Consequence: "death outside a health facility" is computable as
`TIPO LUGAR != 'EESS'`. No field is missing for H3a/H3b.

### 1.3 Date coverage — resolved at step 2 (2026-10-30)

The bulk `fallecidos_sinadef.csv` snapshot ends on **2024-05-05** (1,110,168
rows; only 39,691 of them in 2024). The daily `TB_SINADEF.csv`, extracted from
the 39 MB 7z (504,120,128 bytes, 1,439,302 rows), covers
**2017-01-01 → 2025-11-30**:

| Year | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Deaths | 99,939 | 116,540 | 130,096 | 230,752 | 260,883 | 161,277 | 128,023 | 158,445 | 153,347 |

The M8 window **2022–2025 stands**, with `TB_SINADEF_2026-10-30.csv` as the
analysis source. 2025 covers January–November; the per-year completeness check
of M8 still applies, as does the known limitation of rural under-registration
and preference for dying at home.

## 2. INEI polygons

- Census 2025 table: **1,893 districts** (`censo-2025-distrital.csv`, registered
  in `_schema.DATASETS`).
- `geoperu` 0.0.1 (CRAN), dataset `peru`: **1,874 district polygons**, source
  `https://ide.inei.gob.pe/`, WGS84 → **expect about 19 census districts without
  a polygon**.
- **Measured on the real HDX layer (stage 02, 2026-10-31): 1,873 polygons, 21
  census districts without one** (19 created after 2017 + 2 older HDX gaps:
  120604 and 120606 in Chanchamayo). One polygon has no census row.
- Official layer to register at step 2: `https://ide.inei.gob.pe/files/Distrito.rar`
  ("Distrital, actualizado al 2023", GeoPackage).
- A third-party mirror advertises a "Censo 2025" layer with **1,892** districts;
  the 1,892 vs 1,893 discrepancy must be explained when the layer is reconciled.
- SDOT states that INEI census limits are referential and have no demarcatory
  effect; carry that caveat into the methods.
- **Step-2 action:** download the official layer, reconcile UBIGEOs against the
  1,893 census districts and document the list of districts without a polygon.

## 3. Located destinations per department (RENIPRESS October 2026)

Computed from `renipress_2026-10-30.csv` with the rules of `experiments/_etl.py`
(active rows, validated coordinates, `care_level >= 5` = II-1 and above):

- **685** complex hospitals, **625 located (91.2 %)**; 60 without coordinates.
- By institution: public (MINSA + Gobierno Regional) **182/184 (98.9 %)**,
  EsSalud 76/80, private **349/402 (86.8 %)**; other public 18/20.
- 20 hospital-like uncategorised facilities (7 located) — sensitivity input only.
- For M1's validation rule (located share ≥ 90 %): public-only set passes at
  98.9 %, the all-institution set passes at 91.2 %, the private set fails at
  86.8 % (irrelevant if private is not the main destination).

Located complex hospitals per department (MINSA / Gob. Regional / EsSalud /
private; `unlocated` = complex hospitals without valid coordinates):

| Department | MINSA | Gob. Reg. | EsSalud | Private | Unlocated |
|---|---:|---:|---:|---:|---:|
| Lima | 26 | 7 | 17 | 165 | 31 |
| La Libertad | 0 | 23 | 7 | 21 | 3 |
| Ancash | 0 | 12 | 0 | 4 | 7 |
| Puno | 0 | 11 | 4 | 8 | 1 |
| Ayacucho | 0 | 10 | 1 | 1 | 0 |
| Junín | 0 | 10 | 4 | 12 | 1 |
| Cajamarca | 0 | 9 | 3 | 14 | 2 |
| Cusco | 0 | 8 | 3 | 14 | 1 |
| San Martín | 0 | 8 | 2 | 9 | 0 |
| Arequipa | 0 | 7 | 4 | 21 | 4 |
| Ica | 0 | 6 | 4 | 12 | 3 |
| Apurímac | 0 | 5 | 2 | 3 | 0 |
| Amazonas | 0 | 5 | 3 | 3 | 0 |
| Loreto | 1 | 4 | 2 | 7 | 0 |
| Piura | 0 | 5 | 5 | 21 | 1 |
| Huánuco | 0 | 4 | 2 | 7 | 0 |
| Huancavelica | 1 | 3 | 1 | 0 | 0 |
| Callao | 0 | 3 | 2 | 5 | 1 |
| Lambayeque | 0 | 3 | 2 | 12 | 4 |
| Ucayali | 0 | 3 | 0 | 5 | 1 |
| Pasco | 0 | 3 | 3 | 0 | 0 |
| Moquegua | 0 | 2 | 2 | 2 | 0 |
| Madre de Dios | 0 | 1 | 1 | 0 | 0 |
| Tacna | 0 | 1 | 1 | 2 | 0 |
| Tumbes | 0 | 1 | 1 | 1 | 0 |

**Departments with fewer than 2 located public (MINSA + Gob. Regional) complex
hospitals: Madre de Dios, Tacna and Tumbes — one each.** They will be flagged
wherever departmental results are reported.

## 4. Licenses

| Source | License | Status |
|---|---|---|
| RENIPRESS (SUSALUD) | ODC-By | registered, `data/SOURCES.md` |
| SINADEF (both datasets) | ODC-By | verified 2026-10-30 on both dataset pages |
| WorldPop population grid | CC BY 4.0 | verified 2026-10-30 (worldpop.org FAQ); Peru 1 km 2025 available (R2025A) |
| MAP friction surface / travel time (Weiss et al.) | CC BY 4.0 | verified 2026-10-30 (Earth Engine catalog terms; direct downloads at malariaatlas.org) |
| INEI census 2025 tables | not stated on the portal | **unconfirmed — human decision** |
| INEI boundaries (ide.inei.gob.pe) | not stated; free use/dissemination, GEOIDEP terms apply; limits are referential | **unconfirmed — human decision** |
| OpenStreetMap (independent-engine check) | ODbL | to re-confirm when actually used at step 2 |

## 5. References verified with `paper-search` (no citation from memory)

| Reference | DOI | Verified |
|---|---|---|
| Weiss et al. 2020, Global maps of travel time to healthcare facilities, *Nature Medicine* 26(12):1835–1838 | 10.1038/s41591-020-1059-1 | ✓ |
| Weiss et al. 2018, A global map of travel time to cities, *Nature* 553(7688):333–336 | 10.1038/nature25181 | ✓ |
| Luo & Wang 2003, Measures of spatial accessibility to health care (2SFCA), *Environment and Planning B* 30(6):865–884 | 10.1068/b29120 | ✓ |
| Luo & Qi 2009, An enhanced two-step floating catchment area (E2SFCA), *Health & Place* 15(4):1100–1107 | 10.1016/j.healthplace.2009.06.002 | ✓ |
| Nolte & McKee 2003, Measuring the health of nations: amenable mortality, *BMJ* 327:1129 | 10.1136/bmj.327.7424.1129 | ✓ |
| Tobias & Yeh 2009, Amenable mortality trends in New Zealand 1981–2004, *Australian and New Zealand Journal of Public Health* | 10.1111/j.1753-6405.2009.00342.x | ✓ |
| Meara et al. 2015, Global Surgery 2030 (2-hour access target), *The Lancet* 386(9993):569–624 | 10.1016/S0140-6736(15)60160-X | ✓ |
| Miranda-Chavez et al. 2026, Trends in place of death in Peru, 2017–2024, *Archives of Public Health* 84 | 10.1186/s13690-026-01872-9 | ✓ |

**Place of death as an access indicator is verified for Peru** (Miranda-Chavez
et al. 2026: SINADEF 2017–2024; 41.3 % of deaths at home, home death associated
with structural inequity and limited access rather than preference). The
60/120-minute thresholds remain **proposed**; the only literature-anchored
benchmark verified so far is the 2-hour surgical access target (Meara et al.
2015).

## 6. Decisions requested from the researcher (not decided here)

All five were answered on 2026-10-30; the live record is
`reviews/decision-0001-contribution.md` §11.

1. **Main destination set (M1).** Recommended: public general-access hospitals
   (MINSA + Gobierno Regional, II-1 and above). 402 of 685 hospitals are private,
   so this choice changes the result.
2. **Region definition (M9).** Source for the DEM (district mean altitude) and
   for the Amazon-basin flag.
3. **II-1 versus II-2.** Decision 0001 says "II-2 and above"; `_etl.py` uses
   `care_level >= 5` (II-1). All numbers in this note are II-1+. Fix whichever is
   wrong before the analysis plan is frozen.
4. **Approval of every "proposed" threshold** when `analysis_plan.yaml` is frozen.
5. **INEI license handling** for the census tables and the boundary layer.

## 7. What this note does not establish

- That the open snapshot contains every 2024–2025 death (step-2 by-year count).
- That SINADEF completeness is uniform across districts (M8 validation).
- That the polygon layer covers all 1,893 census districts (step-2 reconciliation).
- That the Amazon is represented correctly by the friction surface (M3 reports it
  apart; the plan already carries this risk).

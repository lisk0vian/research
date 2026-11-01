# Data sources — c19-2026

Provenance for the files under `data/raw/` (which is not committed). Every file
was retrieved on **2026-10-30**. SHA-256 lets anyone check that a re-download is
the same file.

What each column means: the machine-readable data dictionary in
[`dictionary/`](dictionary/) (`renipress.yaml`, `census2025.yaml`,
`derived_variables.yaml`, and the flat `columns.csv`). It is generated from
`experiments/_schema.py` by `experiments/_build_dictionary.py`; a test fails if
the two drift apart. The hashes below are also registered in `_schema.py`
(`DATASETS`) and checked by stage 00.

## 1. RENIPRESS — health establishments (current)

- **Publisher:** Superintendencia Nacional de Salud (SUSALUD), via the Plataforma Nacional de Datos Abiertos.
- **Dataset page:** https://www.datosabiertos.gob.pe/dataset/registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress
- **Metadata API:** https://www.datosabiertos.gob.pe/api/3/action/package_show?id=registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress
- **Dataset modified:** 2026-10-30; update frequency monthly; license ODC-By (http://opendefinition.org/licenses/odc-by/).
- **Monthly files available at retrieval:** April 2026 to October 2026 (one CSV per month).

| Local file | Source URL | SHA-256 |
|---|---|---|
| `renipress_2026-10-30.csv` (October 2026 edition, 19.9 MB) | https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_30-10-2026.csv | `0c8f51e57d56ae83c03a3e3b8a52cc3f781c1b8a67b23f7270a1ec26c8b3269d` |
| `renipress_diccionario_datos.pdf` (official data dictionary) | https://www.datosabiertos.gob.pe/sites/default/files/Diccionario%20de%20datos%20RENIPRESS.pdf | `730f2fa2ac1510a6fd5f38471ed05b97cd0a8262f446e5f5f2dad7280b8e6bab` |

Checked after download: 36,246 rows; 27,017 with `ESTADO = ACTIVO`; same 31 columns as
the previous file; 1,891 distinct UBIGEO; 36.4 % of rows without coordinates.

The **official dictionary is out of date**: it names other columns (`CODIGO_IPRESS`,
`CATEGORIA_IPRESS`, `LONGITUD_NORTE`, ...), its descriptions are shifted by one row,
and it describes `NORTE` as longitude and `ESTE` as latitude although the values show
the opposite. Use `dictionary/renipress.yaml`, which was checked against the file.

How the ETL treats what changed from the previous file:

- **Encoding:** UTF-8 with BOM (the old file was `latin1`). `_etl.py` reads `utf-8-sig` and falls back to `latin1`.
- **`CATEGORIA = III-E`** (10 active facilities): all are national or high-complexity hospitals and institutes (Hospital Nacional Madre Niño, Instituto Nacional Cardiovascular, Hospital de Alta Complejidad de La Libertad, ...). They are level 7 (tertiary), like III-1, as II-E is level 5 like II-1. Before, they fell to level 1.
- **`CATEGORIA = 0`** (4,915 active facilities): not a category. They are medical support services (2,855: laboratories, imaging, dialysis, ambulances), doctors' offices and similar (1,984), and a few others. They are now `care_level = 0`, neither primary care nor hospital. Before, they fell to level 1 and inflated primary care. Of them, 20 have a hospital-type classification and are flagged `is_hospital_like_uncategorized` for a sensitivity analysis; they are not counted as complex hospitals.
- **Unknown categories** on an active facility abort the ETL instead of falling back to level 1.

The previous copy (`renipress.csv`, 35,371 rows; `data/README.md` identifies it as the 2026-03-31 cut and the
file itself records no date; SHA-256
`5e7997680201f87737666530ebcb9215eda5a7b6157919445c9c47b201b44f5c`) is kept untouched
but is no longer read by the pipeline.

## 2. Census 2025 — population by district

- **Publisher:** INEI, Censos Nacionales 2025 (XIII de Población, VIII de Vivienda, IV de Comunidades Indígenas).
- **Portal:** https://censos2025.inei.gob.pe/
- **Where the tables come from:** Resultados → Descarga de datos → Cuadros estadísticos → Cuadros interactivos, level "Distrital", all departments, then "Generar cuadro" and "Descargar Excel". Page: https://censos2025.inei.gob.pe/resultados/descarga-de-datos/cuadros-estadisticos/cuadros-interactivos
- **REDATAM (not used yet):** https://redatamcpv2025.inei.gob.pe/
- **Reference date:** the workbooks state "Datos censales al 15 de julio de 2026 de acuerdo con la documentación oficial sobre límites territoriales vigentes del Registro Nacional de Límites – RENLIM". The INEI presentation of July 2026 says 11 June 2026; the workbook footnote is the one attached to these tables.

| Local file | What it is | SHA-256 |
|---|---|---|
| `census2025_source/cpv2025_grandes_grupos_edad_distrital.xlsx` | Population by broad age group (0–14, 15–59, 60+), 1,893 districts | `b303dc381b3b801fe49e1e839a2657fd2f4a110cb19401c58115f091a5a64757` |
| `census2025_source/cpv2025_discapacidad_distrital.xlsx` | Population aged 5+ by disability condition, 1,893 districts | `7658b4bdee4aedffa8550d0b3f41d215f5a8a231a96590085b4f8b57a52fe0f5` |
| `census2025_source/inei_presentacion_resultados_provincial_distrital_2026-07.pdf` | INEI presentation "Resultados a nivel provincial y distrital" | `1074074a1c63891598ec4a1eb00b58eb1077e6b5a44ce51566b92057f1cf2692` |
| `censo-2025-distrital.csv` | The two workbooks merged by UBIGEO, English columns, UTF-8 (derived) | `6b42982a0ab5301ea9687c2ae508107fb4d45ecc7e7154d4d96536037f117e01` |
| presentation URL | https://proyectos.inei.gob.pe/dir-segmentacion-ci/postcensal/prod/adjuntos/publicaciones/Presentacion_resultados.pdf | |

Rebuild the derived CSV (from `papers/c19-2026/`):

```
python experiments/census2025_prepare.py \
  --age data/raw/census2025_source/cpv2025_grandes_grupos_edad_distrital.xlsx \
  --disability data/raw/census2025_source/cpv2025_discapacidad_distrital.xlsx \
  --out data/raw/censo-2025-distrital.csv
```

The script fails if the districts do not add up to the national row of each workbook
or if the two workbooks cover different districts.

`censo-2025-distrital.csv` columns: `ubigeo, department, province, district,
boundary_undefined, population_total, pop_0_14, pop_15_59, pop_60_plus, pop5_total,
pop5_with_disability, pop5_without_disability` (meaning: `dictionary/census2025.yaml`).

Checks run on the conversion (all passed):

- 1,893 districts, 1,893 unique UBIGEO, no missing values, no zero-population district.
- Column totals equal the national row of each workbook: population 32,706,028; age 60+ 4,839,138; with disability 1,637,090.
- The three age groups add up to the district total in 100 % of rows.
- 10 districts carry INEI footnote 3/ and are flagged `boundary_undefined`.
- Coverage against RENIPRESS October 2026: of 1,891 districts with active establishments, **1 has no census row** (UBIGEO 160109, 2 establishments). With the 2017 census it was 16 districts and 38 establishments. Those facilities are excluded, never given population 0.

Caveats to carry into the manuscript:

- The figures are **counted population** (32,706,028). INEI also publishes an omission-adjusted national total of 34,157,732 (omission rate 4.25 %), which is **not** available by district in these tables.
- Disability is defined for population aged **5 and over**; the denominator is `pop5_total`, not `population_total`. The 2017 file used a different definition and is not directly comparable.
- Lima appears as two units, "Lima Metropolitana" and "Región Lima" (footnote 2/: the provinces of Barranca, Cajatambo, Canta, Cañete, Huaral, Huarochirí, Huaura, Oyón and Yauyos), plus "Prov. Const. del Callao". UBIGEO is unaffected; do not join on the name.
- Footnote 3/: in some districts, populated centres lie where limits are not officially defined; they were censused without a UBIGEO and published under the current census limits.
- The portal does not state a license for these tables. Confirm the terms of reuse before redistributing the derived CSV (for example in the Zenodo package).
- The 2017 census (`censo-2017.csv`) is kept untouched but is no longer read by the pipeline.

## 3. Not used

- INEI population projections 2018–2022 by district (Boletín Especial N° 27): built on the 2017 census, so they add no information over the 2025 census.

## 4. SINADEF — registered deaths (outcome O1)

- **Publisher:** Ministerio de Salud (MINSA), via the Plataforma Nacional de Datos Abiertos.
- **Datasets (both ODC-By):**
  - "Información de Fallecidos del SINADEF" (`ba538c68-c5e0-4098-985d-c5e271c973a6`):
    bulk CSV at <https://drive.minsa.gob.pe/s/PigmdwnCGEdyqos/download>.
    Ends on 2024-05-05; superseded for analysis, kept as the portal's bulk
    snapshot and as a cross-check.
  - "SINADEF: Certificado Defunciones" (`e583e8c7-800b-4dd1-b88b-e3692180b17a`,
    frequency daily): 7z at <https://cloud.minsa.gob.pe/s/g9KdDRtek42X3pg/download>
    containing `TB_SINADEF.csv`. **This is the analysis source.**
- **Analysis file:** `TB_SINADEF_2026-10-30.csv` (extracted from the 7z):
  504,120,128 bytes, 1,439,302 rows, 31 columns, `;` separated, UTF-8 with BOM,
  dates 2017-01-01 to 2025-11-30.
- **Rows by year:** 2017 99,939 · 2018 116,540 · 2019 130,096 · 2020 230,752 ·
  2021 260,883 · 2022 161,277 · 2023 128,023 · 2024 158,445 · 2025 153,347
  (January–November). 2025 is 11 months; the 7z's internal file time is 2025-12-01.
- **Fields used by M8:** place of death `TIPO LUGAR` + `INSTITUCION`; residence
  `COD# UBIGEO DOMICILIO` (its last six digits are the district UBIGEO);
  cause `CAUSA A..F (CIE-X)` with descriptions; `EDAD` + `TIEMPO EDAD`; `SEXO`;
  `FECHA`, `AÑO`, `MES`. The bulk CSV also carries `ETNIA`, absent from its
  dictionary.
- **Hashes** (SHA-256), checked after download:

| Local file | Source | SHA-256 |
|---|---|---|
| `TB_SINADEF_2026-10-30.csv` (504,120,128 B) | 7z `TB_SINADEF.7z` from the daily dataset | `bb4058fa7d77049c95b2d1b1a1b53bfc64c6677a7642b75a034cc475370498a3` |
| `TB_SINADEF_2026-10-30.7z` (39,320,897 B) | <https://cloud.minsa.gob.pe/s/g9KdDRtek42X3pg/download> | `3e46551097666da0ba07f3eff967cd1e988a7a3fa5770a4e31a35ec91e446e5a` |
| `Diccionario_Datos_SINADEF.xlsx` (10,649 B) | portal dictionary (bulk dataset) | `532af115ce30228712a7258af014df261c6f3eb3dfeb20f29c62ccb0a90d34d2` |
| `DD_TB_SINADEF_0.xlsx` (11,540 B) | portal dictionary (daily dataset) | `a530aac76a67d11e7a62c75a4816e3125455235feaec314d283bacd448edac23` |

The bulk snapshot (`SINADEF_fallecidos_2026-10-30.csv`, 383,534,277 B,
1,110,168 rows, hash `f25d0e2f9e32e7d3a98a99a30c7e375762f5531996f3b84adb06d5e7fd73a83a`)
was checked but not kept in Drive: the daily table supersedes it and covers 2025.

## 5. Population grid — WorldPop

- **Publisher:** WorldPop (University of Southampton).
- **License:** CC BY 4.0 (<https://www.worldpop.org/faq>).
- **File:** `per_pop_2025_CN_1km_R2025A_UA_v1.tif` — Peru, 2025, 1 km,
  constrained, 2,511,314 bytes.
- **URL:** <https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PER/v1/1km_ua/constrained/per_pop_2025_CN_1km_R2025A_UA_v1.tif>
- **SHA-256:** `94d81bf15b87c0139209a364cfae3c706c7c9520a584a023f578449bd172fdf7`

## 6. Travel-time friction surface — Malaria Atlas Project

- **Publisher:** Malaria Atlas Project (Weiss et al. 2020, Nature Medicine).
- **License:** CC BY 4.0 (data.malariaatlas.org; Earth Engine catalog terms).
- **File:** `2020_motorized_friction_surface.zip` — motorized, 2020, 1 km;
  740,601,231 bytes; contains `2020_motorized_friction_surface.geotiff`.
- **URL:** <https://data.malariaatlas.org/geoserver/ows?service=CSW&version=2.0.1&request=DirectDownload&ResourceId=Explorer:2020_motorized_friction_surface>
- **SHA-256:** `fcde4122d7d356a731dc0aae35a7db07c74a11b3029331064e46fc55ec0f955f`

## 7. Amazon basin — HydroBASINS

- **Publisher:** HydroSHEDS (Lehner & Grill 2013); free for scientific,
  educational and commercial use under the HydroSHEDS license.
- **File:** `hybas_sa_lev01-12_v1c.zip` — South America, levels 1–12, 334,160,720 bytes.
  Level 4 is used for the Amazon-basin flag.
- **URL:** <https://data.hydrosheds.org/file/hydrobasins/standard/hybas_sa_lev01-12_v1c.zip>
- **SHA-256:** `fb012e48419bda0a7f4d0ebc56efcd906ad0e3bde324b9c70fac9693e2d21a72`

## 8. OpenStreetMap extract — independent-engine check (G1)

- **Publisher:** Geofabrik, Peru extract.
- **License:** ODbL.
- **File:** `peru-2026-10-29.osm.pbf` — 257,126,303 bytes (downloaded 2026-10-30).
- **URL:** <https://download.geofabrik.de/south-america/peru-latest.osm.pbf>
- **SHA-256:** `3f29398b86f16061026014bad5497525070e55624bc4f66cd560c95b880b9d98`

## 9. District boundaries — HDX (INEI substitute)

- **Why not INEI:** `https://ide.inei.gob.pe/files/Distrito.rar` returned **503**
  on 2026-10-30 from both `curl` and a browser. The layer is replaced, not
  awaited (decision 0001 §11).
- **Source:** OCHA COD-AB for Peru, <https://data.humdata.org/dataset/cod-ab-per>
  (Admin 0–3; Admin 3 = districts). Reviewed 2025-10-30.
- **File:** `per_admin_boundaries.shp.zip` — 42,928,872 bytes; `per_admin3.shp`
  holds the district polygons. License: CC BY 4.0 (HDX terms).
- **SHA-256:** `1d143891d3bd1392dfe2d006f4f913b0b01290a448b9aee4189a718613706ef8`
- **Coverage:** 1,873 Admin-3 units vs 1,893 census districts; the gap is
  reported and districts without a polygon are never imputed. Join key
  `adm3_pcode`; the UBIGEO crosswalk is verified in stage 02_geo_inputs.

## 10. How the raw data reaches Drive

The files are **not uploaded by hand**. `experiments/_download_inputs.py` runs in
Colab's setup cell, downloads each registry entry in `_schema.DATASETS` straight
into `DATA_DIR/raw` (the mounted Drive), resumes partial downloads, verifies
SHA-256 and leaves a `.sha256` sidecar. Later sessions only hash-check. The
SINADEF 7z is extracted to CSV and the archive deleted; no pipeline reads 7z.

## 11. Not stored

- **Copernicus DEM GLO-30:** raw Peru tiles are ~5 GB. Stage 02_geo_inputs builds
  the Peru mosaic on Colab and keeps the clipped COG in `data/raw/dem/`.

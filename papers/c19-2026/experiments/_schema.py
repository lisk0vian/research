# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Single source of truth for the c19-2026 data schema.

Three things live here and nowhere else:

- the English snake_case name of every raw column (so the pipeline never carries
  the long Spanish headers of RENIPRESS or INEI);
- the meaning of every column and derived variable (the data dictionary in
  `data/dictionary/` is generated from this module by `_build_dictionary.py`);
- the rules that turn a RENIPRESS `CATEGORIA` into a care level.

Dependency-free on purpose: `_etl.py`, `_sample_data.py`, the dictionary
generator and the tests all import it.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Care level of a facility, from the MINSA category printed in RENIPRESS.
# ---------------------------------------------------------------------------
# I-x   primary care (I-1 health post ... I-4 health centre with beds)
# II-x  secondary care, general hospital (II-1, II-2) or specialised (II-E)
# III-x tertiary care, general (III-1), institute (III-2), specialised (III-E)
# "E" (especializado) is placed in the same tier as the general category
# of its level (II-E = II-1, III-E = III-1), which keeps the pre-2026 convention.
# "0" is not a category: RENIPRESS prints it for facilities that have none
# (laboratories, imaging, dialysis, ambulances, doctors' offices). It is level 0,
# never level 1, so it can be neither primary care nor a hospital.
CARE_LEVEL_MAP = {
    "I-1": 1, "I-2": 2, "I-3": 3, "I-4": 4,
    "II-1": 5, "II-E": 5, "II-2": 6,
    "III-1": 7, "III-E": 7, "III-2": 8,
}
UNCATEGORIZED = "0"
COMPLEX_HOSPITAL_MIN_LEVEL = 5          # II-1 and above
CARE_TIER_BY_LEVEL = {0: "none", 1: "primary", 2: "primary", 3: "primary", 4: "primary",
                      5: "secondary", 6: "secondary", 7: "tertiary", 8: "tertiary"}

# Uncategorised facilities whose classification says "hospital": a sensitivity
# input, never part of the main complex-hospital set.
HOSPITAL_LIKE_CLASSIFICATIONS = ("HOSPITALES O CLINICAS", "INSTITUTOS DE SALUD ESPECIALIZADOS")

# ---------------------------------------------------------------------------
# RENIPRESS (SUSALUD) — raw column -> English name.
# ---------------------------------------------------------------------------
# role: id | geography | attribute | organisation | contact | media
RENIPRESS_COLUMNS = [
    {"original": "INSTITUCION", "name": "institution", "dtype": "string", "role": "attribute",
     "description": "Institution that operates the facility (PRIVADO, GOBIERNO REGIONAL, MINSA, ESSALUD, OTRO, the armed-forces and police health services, municipalities, INPE).",
     "notes": "12 distinct values."},
    {"original": "COD_IPRESS", "name": "facility_code", "dtype": "string", "role": "id",
     "description": "Eight-digit RENIPRESS registration code of the facility.",
     "notes": "Keep as text: it has leading zeros. Unique per row."},
    {"original": "NOMBRE", "name": "name", "dtype": "string", "role": "attribute",
     "description": "Name of the facility as registered.", "notes": "Free text."},
    {"original": "CLASIFICACION", "name": "classification", "dtype": "string", "role": "attribute",
     "description": "Classification of the facility in the RENIPRESS typology (health post, health centre, polyclinic, hospital or clinic, laboratory, imaging, dialysis, ...).",
     "notes": "About 150 distinct values. Support services can carry several classifications joined by commas."},
    {"original": "TIPO_ESTABLECIMIENTO", "name": "facility_type", "dtype": "string", "role": "attribute",
     "description": "Whether the facility is an establishment with or without inpatient beds, a medical support service, a flexible offer or a therapeutic community.",
     "notes": "Five values: ESTABLECIMIENTO DE SALUD SIN INTERNAMIENTO, ESTABLECIMIENTO DE SALUD CON INTERNAMIENTO, SERVICIO MÉDICO DE APOYO, OFERTA FLEXIBLE, COMUNIDADES TERAPÉUTICAS."},
    {"original": "DEPARTAMENTO", "name": "department", "dtype": "string", "role": "geography",
     "description": "Department of the facility, as published (uppercase, no accents).",
     "notes": "25 values; Callao is a department and Lima is a single department (no Lima Metropolitana split)."},
    {"original": "PROVINCIA", "name": "province", "dtype": "string", "role": "geography",
     "description": "Province of the facility, as published.", "notes": ""},
    {"original": "DISTRITO", "name": "district", "dtype": "string", "role": "geography",
     "description": "District of the facility, as published.",
     "notes": "District names repeat across provinces; use ubigeo to identify a district."},
    {"original": "UBIGEO", "name": "ubigeo", "dtype": "string", "role": "geography",
     "description": "Six-digit INEI district code: two digits of department, two of province, two of district.",
     "notes": "Join key with the census. Keep as text. The ETL pads to six digits."},
    {"original": "DIRECCION", "name": "address", "dtype": "string", "role": "contact",
     "description": "Street address of the facility.", "notes": "Free text, not normalised."},
    {"original": "CO_DISA", "name": "disa_code", "dtype": "string", "role": "organisation",
     "description": "Code of the Dirección de Salud (DISA/DIRESA) the facility belongs to.",
     "notes": "Stored as a float-looking string such as '25.0'. Present for about 75 % of rows."},
    {"original": "COD_RED", "name": "network_code", "dtype": "string", "role": "organisation",
     "description": "Code of the health network (Red de Salud).", "notes": "Same float-looking format. About 73 % present."},
    {"original": "COD_MICRORRED", "name": "microred_code", "dtype": "string", "role": "organisation",
     "description": "Code of the micro-network (Microred).", "notes": "Same float-looking format. About 77 % present."},
    {"original": "DISA", "name": "disa", "dtype": "string", "role": "organisation",
     "description": "Name of the DISA/DIRESA.", "notes": ""},
    {"original": "RED", "name": "network", "dtype": "string", "role": "organisation",
     "description": "Name of the health network.", "notes": ""},
    {"original": "MICRORED", "name": "microred", "dtype": "string", "role": "organisation",
     "description": "Name of the micro-network.", "notes": ""},
    {"original": "COD_UE", "name": "executing_unit_code", "dtype": "string", "role": "organisation",
     "description": "Code of the budget executing unit (unidad ejecutora).", "notes": "Present for about 26 % of rows."},
    {"original": "UNIDAD_EJECUTORA", "name": "executing_unit", "dtype": "string", "role": "organisation",
     "description": "Name of the budget executing unit.", "notes": ""},
    {"original": "CATEGORIA", "name": "category", "dtype": "string", "role": "attribute",
     "description": "MINSA category of the facility: I-1 to I-4 (primary), II-1, II-2, II-E (secondary), III-1, III-2, III-E (tertiary). '0' means the facility has no category.",
     "notes": "'0' is not a level. It marks laboratories, imaging, dialysis, ambulances, doctors' offices and a few facilities pending categorisation. See care_level."},
    {"original": "TELEFONO", "name": "phone", "dtype": "string", "role": "contact",
     "description": "Phone number of the facility.", "notes": "Personal-contact data; not used in any analysis."},
    {"original": "HORARIO", "name": "schedule", "dtype": "string", "role": "contact",
     "description": "Opening hours as free text (for example '7:00 - 19:00').", "notes": "Not normalised; about 8,600 distinct spellings."},
    {"original": "INICIO_ACTIVIDAD", "name": "activity_start", "dtype": "string", "role": "attribute",
     "description": "Date the facility started operating.",
     "notes": "Format 'YYYY-MM-DD HH:MM:SS' in the October 2026 edition. The official dictionary says ddmmyyyy and the March 2026 cut used mm/dd/yyyy; parse explicitly before use."},
    {"original": "ESTADO", "name": "status", "dtype": "string", "role": "attribute",
     "description": "Registration status: ACTIVO, CIERRE TEMPORAL DE OFICIO, CIERRE TEMPORAL DE PARTE, BAJA PROVISIONAL, BAJA PROVISIONAL DE OFICIO, BAJA DEFINITIVA, BAJA DEFINITIVA DE OFICIO.",
     "notes": "Only ACTIVO is analysed."},
    {"original": "NORTE", "name": "lat_raw", "dtype": "float", "role": "geography",
     "description": "Latitude in decimal degrees (negative in Peru), as published.",
     "notes": "Despite the name NORTE, and despite the official dictionary describing it as longitude, the values are latitudes (about -18.3 to 0). Missing for about 36 % of rows; 0.0 is a placeholder. A comma decimal separator can occur. See lat."},
    {"original": "ESTE", "name": "lon_raw", "dtype": "float", "role": "geography",
     "description": "Longitude in decimal degrees (negative in Peru), as published.",
     "notes": "Despite the name ESTE, the values are longitudes (about -81.3 to -68.6). See lon."},
    {"original": "IMAGEN_1", "name": "image_url_1", "dtype": "string", "role": "media",
     "description": "URL of the first facility photograph.", "notes": "Not used."},
    {"original": "FE_ACT_IMAGEN_1", "name": "image_date_1", "dtype": "string", "role": "media",
     "description": "Registration date of the first photograph.", "notes": "Not used. About 5 % present."},
    {"original": "IMAGEN_2", "name": "image_url_2", "dtype": "string", "role": "media",
     "description": "URL of the second facility photograph.", "notes": "Not used."},
    {"original": "FE_ACT_IMAGEN_2", "name": "image_date_2", "dtype": "string", "role": "media",
     "description": "Registration date of the second photograph.", "notes": "Not used."},
    {"original": "IMAGEN_3", "name": "image_url_3", "dtype": "string", "role": "media",
     "description": "URL of the third facility photograph.", "notes": "Not used."},
    {"original": "FE_ACT_IMAGEN_3", "name": "image_date_3", "dtype": "string", "role": "media",
     "description": "Registration date of the third photograph.", "notes": "Not used."},
]
RENIPRESS_RENAME = {c["original"]: c["name"] for c in RENIPRESS_COLUMNS}

# ---------------------------------------------------------------------------
# Census 2025 (INEI) — district table written by census2025_prepare.py.
# ---------------------------------------------------------------------------
CENSUS_COLUMNS = [
    {"original": "Ubigeo", "name": "ubigeo", "dtype": "string", "role": "id",
     "description": "Six-digit INEI district code. Join key with RENIPRESS.", "notes": "Unique per row. 1,893 districts."},
    {"original": "Departamento", "name": "department", "dtype": "string", "role": "geography",
     "description": "Department name as published by INEI, with the footnote marker removed.",
     "notes": "Lima appears as 'Lima Metropolitana' and 'Región Lima' (the provinces of Barranca, Cajatambo, Canta, Cañete, Huaral, Huarochirí, Huaura, Oyón and Yauyos), plus 'Prov. Const. del Callao'. Do not join on this name; use ubigeo."},
    {"original": "Provincia", "name": "province", "dtype": "string", "role": "geography",
     "description": "Province name as published by INEI.", "notes": ""},
    {"original": "Distrito", "name": "district", "dtype": "string", "role": "geography",
     "description": "District name as published by INEI.", "notes": ""},
    {"original": "Distrito (nota 3/)", "name": "boundary_undefined", "dtype": "bool", "role": "attribute",
     "description": "True when INEI flags the district with footnote 3/: some populated centres lie where district limits are not officially defined, so they were censused without a UBIGEO and published under the current census limits.",
     "notes": "Population of these districts may include or exclude such centres; treat their counts with caution."},
    {"original": "Total", "name": "population_total", "dtype": "int", "role": "measure",
     "description": "Census-counted resident population of the district, 2025 census.",
     "notes": "Counted population (national total 32,706,028), not omission-adjusted (adjusted national total 34,157,732, omission 4.25 %); the adjusted figure is not published by district."},
    {"original": "De 0 a 14 años", "name": "pop_0_14", "dtype": "int", "role": "measure",
     "description": "Counted population aged 0 to 14.", "notes": "pop_0_14 + pop_15_59 + pop_60_plus = population_total in every district."},
    {"original": "De 15 a 59 años", "name": "pop_15_59", "dtype": "int", "role": "measure",
     "description": "Counted population aged 15 to 59.", "notes": ""},
    {"original": "De 60 años y más", "name": "pop_60_plus", "dtype": "int", "role": "measure",
     "description": "Counted population aged 60 and over.", "notes": "National total 4,839,138."},
    {"original": "Total (5 años y más)", "name": "pop5_total", "dtype": "int", "role": "measure",
     "description": "Counted population aged 5 and over; the denominator of the disability table.",
     "notes": "National total 30,692,308."},
    {"original": "Sí tiene discapacidad", "name": "pop5_with_disability", "dtype": "int", "role": "measure",
     "description": "Population aged 5 and over with at least one disability.",
     "notes": "National total 1,637,090. Defined for ages 5+, so it is not comparable with the 2017 variable. The census footnote 'a/' applies: a person can have several disabilities."},
    {"original": "No tiene discapacidad", "name": "pop5_without_disability", "dtype": "int", "role": "measure",
     "description": "Population aged 5 and over without disability.", "notes": "pop5_with_disability + pop5_without_disability = pop5_total."},
]
CENSUS_RENAME = {c["original"]: c["name"] for c in CENSUS_COLUMNS}
CENSUS_REQUIRED = [c["name"] for c in CENSUS_COLUMNS]

# ---------------------------------------------------------------------------
# Variables derived by the pipeline. `stage` is where the column is created.
# ---------------------------------------------------------------------------
DERIVED_COLUMNS = [
    # --- created by the ETL (_etl.py) --------------------------------------
    {"name": "department_norm", "stage": "etl", "dtype": "string",
     "description": "department in uppercase without accents, used for grouping and the region lookup.",
     "formula": "normalizar_cadena(department)"},
    {"name": "natural_region", "stage": "etl", "dtype": "string",
     "description": "Costa, Sierra or Selva assigned to the whole department.",
     "formula": "lookup on department_norm (REGION_NATURAL_MAP); unmapped departments default to Sierra",
     "notes": "Coarse: one region per department, so Arequipa, Moquegua and Tacna are Costa and Huánuco is Selva. Not valid for equity claims; a district-level region is pending (decision 0001, O5)."},
    {"name": "lat", "stage": "etl", "dtype": "float",
     "description": "Validated latitude in decimal degrees.",
     "formula": "lat_raw if -18.35 <= lat_raw <= -0.02 and the paired longitude is in range, else missing"},
    {"name": "lon", "stage": "etl", "dtype": "float",
     "description": "Validated longitude in decimal degrees.",
     "formula": "lon_raw if -81.40 <= lon_raw <= -68.60 and the paired latitude is in range, else missing"},
    {"name": "coord_valid", "stage": "etl", "dtype": "int",
     "description": "1 when the facility has a valid coordinate pair, else 0.", "formula": "lat and lon not missing"},
    {"name": "is_active", "stage": "etl", "dtype": "bool",
     "description": "True when status is ACTIVO.", "formula": "status == 'ACTIVO'"},
    {"name": "care_level", "stage": "etl", "dtype": "int",
     "description": "Care level 0 to 8 from category: 1-4 primary, 5-6 secondary, 7-8 tertiary, 0 = no category.",
     "formula": "CARE_LEVEL_MAP[category]; category '0' -> 0",
     "notes": "II-E is level 5 and III-E is level 7. Before the 2026 adaptation, III-E and '0' were silently level 1. An unknown category aborts the ETL instead of falling back."},
    {"name": "care_tier", "stage": "etl", "dtype": "string",
     "description": "none, primary, secondary or tertiary.", "formula": "CARE_TIER_BY_LEVEL[care_level]"},
    {"name": "is_complex_hospital", "stage": "etl", "dtype": "bool",
     "description": "True for a categorised facility of level II-1 or above: the access target of the paper.",
     "formula": "care_level >= 5"},
    {"name": "is_hospital_like_uncategorized", "stage": "etl", "dtype": "bool",
     "description": "True when the facility has no category but its classification is a hospital, clinic or specialised institute. Sensitivity input only.",
     "formula": "category == '0' and classification starts with HOSPITALES O CLINICAS or INSTITUTOS DE SALUD ESPECIALIZADOS"},
    {"name": "dist_km_nearest_complex", "stage": "etl", "dtype": "float",
     "description": "Facility-level straight-line distance in km from a located facility to the nearest located facility with is_complex_hospital. Only in df_validas.",
     "formula": "haversine nearest neighbour (sklearn NearestNeighbors) over lat/lon, times 6371 km",
     "notes": "0 km for the complex hospitals themselves. Used for the Moran statistics; df_activos carries the district aggregates below."},
    {"name": "dist_km_district_median", "stage": "etl", "dtype": "float",
     "description": "Median, over the located facilities of the district, of the straight-line distance to the nearest located facility with is_complex_hospital.",
     "formula": "haversine nearest neighbour, then median by ubigeo",
     "notes": "Missing for districts with no located facility."},
    {"name": "dist_km_complex_hospital", "stage": "etl", "dtype": "float",
     "description": "dist_km_district_median, filled with the global median where the district has no located facility.",
     "formula": "fillna(global median of the facility-level distances)",
     "notes": "Straight-line, not travel time. It is the baseline of the sensitivity analysis, not the access measure (decision 0001)."},
    {"name": "spatial_anomaly", "stage": "etl", "dtype": "int",
     "description": "1 when at least two of IsolationForest, LocalOutlierFactor and DBSCAN flag the facility's location as an outlier; taken as the maximum within the district.",
     "formula": "(IF + LOF + DBSCAN flags) >= 2 on standardised UTM 18S coordinates, contamination 0.08",
     "notes": "A geometric outlier, not a health outcome. It supplies most positive labels of the old target."},
    {"name": "population_total", "stage": "etl", "dtype": "int",
     "description": "Census population of the facility's district (merge on ubigeo).", "formula": "census.population_total"},
    {"name": "pop_60_plus", "stage": "etl", "dtype": "int",
     "description": "Census population aged 60+ of the facility's district.", "formula": "census.pop_60_plus"},
    {"name": "pop5_with_disability", "stage": "etl", "dtype": "int",
     "description": "Census population aged 5+ with disability in the facility's district.", "formula": "census.pop5_with_disability"},
    # --- created by stage 03_build_invs ------------------------------------
    {"name": "extreme_vulnerable_ratio", "stage": "03_build_invs", "dtype": "float",
     "description": "Share of the district population aged 60+ or with disability, relative to total population.",
     "formula": "(pop_60_plus + pop5_with_disability) / (population_total + 1)",
     "notes": "The two groups overlap, so it can double count a person; the denominator mixes ages 5+ and all ages."},
    {"name": "VULNERABLE", "stage": "03_build_invs", "dtype": "int",
     "description": "Legacy binary target: 1 when the facility's district is far from a complex hospital and has a high vulnerable share, or has a spatial anomaly.",
     "formula": "(dist_km_complex_hospital > knee distance AND extreme_vulnerable_ratio > its 75th percentile) OR spatial_anomaly == 1",
     "notes": "Circular with its predictors and dominated by spatial_anomaly. Dropped as the outcome by decision 0001; kept for the legacy stages."},
    {"name": "dim1_isolation", "stage": "03_build_invs", "dtype": "float",
     "description": "INVS dimension 1: distance to a complex hospital, min-max scaled.", "formula": "minmax(dist_km_complex_hospital)"},
    {"name": "dim2_resolution", "stage": "03_build_invs", "dtype": "float",
     "description": "INVS dimension 2: lack of resolving capacity of the facility, min-max scaled.", "formula": "minmax(1 - care_level / 8)",
     "notes": "Uncategorised facilities (level 0) get the maximum lack of resolution."},
    {"name": "dim3_demand", "stage": "03_build_invs", "dtype": "float",
     "description": "INVS dimension 3: district population on a log scale, min-max scaled.", "formula": "minmax(log1p(population_total))"},
    {"name": "dim4_age_vulnerability", "stage": "03_build_invs", "dtype": "float",
     "description": "INVS dimension 4: share of population aged 60+, min-max scaled.", "formula": "minmax(pop_60_plus / (population_total + 1))"},
    {"name": "dim5_disability", "stage": "03_build_invs", "dtype": "float",
     "description": "INVS dimension 5: share with disability, min-max scaled.", "formula": "minmax(pop5_with_disability / (population_total + 1))"},
    {"name": "dim6_spatial_fragility", "stage": "03_build_invs", "dtype": "float",
     "description": "INVS dimension 6: spatial anomaly flag, scaled.", "formula": "minmax(spatial_anomaly)"},
    {"name": "INVS", "stage": "03_build_invs", "dtype": "float",
     "description": "National Health Vulnerability Index, 0 to 1: first principal component of the six standardised dimensions, min-max scaled.",
     "formula": "minmax(PCA(1).fit_transform(standardise(dim1..dim6)))",
     "notes": "PC1 explains about 45 % of the variance and loads on dimensions 3-5, not on isolation. PCA and entropy weighting rank facilities differently (Spearman 0.66 in the 2017 run)."},
    {"name": "region_pop_ratio", "stage": "03_build_invs", "dtype": "float",
     "description": "Total population of the facility's natural region divided by the district population plus one.",
     "formula": "sum(population_total by natural_region) / (population_total + 1)",
     "notes": "Formerly tasa_vulnerabilidad_regional. It is not a vulnerability rate: it encodes region and district size."},
    {"name": "share_60_plus", "stage": "03_build_invs", "dtype": "float",
     "description": "Share of the district population aged 60+.", "formula": "pop_60_plus / (population_total + 1)",
     "notes": "Formerly ratio_adulto_mayor. Same quantity as dim4 before scaling."},
]

# ---------------------------------------------------------------------------
# Old identifier -> new identifier, applied to the stage scripts once.
# ---------------------------------------------------------------------------
IDENTIFIER_RENAMES = {
    "UBIGEO": "ubigeo", "DEPARTAMENTO_NORM": "department_norm", "DEPARTAMENTO": "department",
    "PROVINCIA": "province", "DISTRITO": "district", "ESTADO": "status", "CATEGORIA": "category",
    "CLASIFICACION": "classification", "COORD_VALIDA": "coord_valid", "NIVEL": "care_level",
    "REGION_NATURAL": "natural_region", "ANOMALIA_ESPACIAL": "spatial_anomaly",
    "dist_km_hosp_complejo": "dist_km_complex_hospital", "dist_km_ubigeo": "dist_km_district_median",
    "poblacion_total": "population_total", "poblacion_adulto_mayor": "pop_60_plus",
    "poblacion_discapacidad": "pop5_with_disability", "ratio_extremo_vulnerable": "extreme_vulnerable_ratio",
    "tasa_vulnerabilidad_regional": "region_pop_ratio", "ratio_adulto_mayor": "share_60_plus",
    "Dim1_Aislamiento": "dim1_isolation", "Dim2_Resolutividad": "dim2_resolution",
    "Dim3_Demanda": "dim3_demand", "Dim4_Vulnerabilidad_Etaria": "dim4_age_vulnerability",
    "Dim5_Inclusión_Discapacidad": "dim5_disability", "Dim6_Fragilidad_Espacial": "dim6_spatial_fragility",
    "NORTE": "lat_raw", "ESTE": "lon_raw", "LAT": "lat", "LON": "lon",
}


def care_level_of(category: str) -> int:
    """Care level of one category string; unknown categories raise, they are never level 1."""
    key = str(category).strip().upper()
    if key == UNCATEGORIZED:
        return 0
    try:
        return CARE_LEVEL_MAP[key]
    except KeyError:
        raise ValueError(f"unknown RENIPRESS category {category!r}: add it to CARE_LEVEL_MAP") from None


# ---------------------------------------------------------------------------
# Provenance of the raw files. Same facts as data/SOURCES.md; stage 00 checks
# the hashes, the dictionary generator writes them out.
# ---------------------------------------------------------------------------
DATASETS = {
    "renipress": {
        "title": "Registro Nacional de Entidades Prestadoras de Servicios de Salud (RENIPRESS)",
        "publisher": "Superintendencia Nacional de Salud (SUSALUD), via Plataforma Nacional de Datos Abiertos",
        "dataset_url": "https://www.datosabiertos.gob.pe/dataset/registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress",
        "file_url": "https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_30-10-2026.csv",
        "official_dictionary_url": "https://www.datosabiertos.gob.pe/sites/default/files/Diccionario%20de%20datos%20RENIPRESS.pdf",
        "edition": "October 2026 (monthly editions are published; April to October 2026 were available)",
        "retrieved": "2026-10-30",
        "license": "Open Data Commons Attribution License (ODC-By), http://opendefinition.org/licenses/odc-by/",
        "local_file": "renipress_2026-10-30.csv",
        "format": "CSV, separator ';', UTF-8 with BOM",
        "unit": "One row per registered facility (IPRESS), all statuses.",
        "sha256": "0c8f51e57d56ae83c03a3e3b8a52cc3f781c1b8a67b23f7270a1ec26c8b3269d",
        "rows": 36246,
        "rows_active": 27017,
        "notes": [
            "The official data dictionary (PDF) is out of date: it uses other column names (CODIGO_IPRESS, CATEGORIA_IPRESS, LONGITUD_NORTE, ...) and its descriptions are shifted by one row. The names and meanings in this dictionary were checked against the file itself.",
            "The official dictionary describes NORTE as longitude and ESTE as latitude; the values show the opposite (NORTE holds latitudes).",
        ],
    },
    "census2025": {
        "title": "Censos Nacionales 2025: XIII de Población, VIII de Vivienda y IV de Comunidades Indígenas, district tables",
        "publisher": "Instituto Nacional de Estadística e Informática (INEI)",
        "dataset_url": "https://censos2025.inei.gob.pe/resultados/descarga-de-datos/cuadros-estadisticos/cuadros-interactivos",
        "file_url": None,
        "official_dictionary_url": None,
        "edition": "District results, census data to 2026-07-15 under current territorial limits (RENLIM)",
        "retrieved": "2026-10-30",
        "license": "Not stated on the INEI portal; confirm the terms of reuse before redistributing",
        "local_file": "censo-2025-distrital.csv",
        "format": "CSV, comma separated, UTF-8; built by census2025_prepare.py from two INEI workbooks",
        "unit": "One row per district (UBIGEO).",
        "sha256": "6b42982a0ab5301ea9687c2ae508107fb4d45ecc7e7154d4d96536037f117e01",
        "rows": 1893,
        "source_workbooks": {
            "cpv2025_grandes_grupos_edad_distrital.xlsx": "b303dc381b3b801fe49e1e839a2657fd2f4a110cb19401c58115f091a5a64757",
            "cpv2025_discapacidad_distrital.xlsx": "7658b4bdee4aedffa8550d0b3f41d215f5a8a231a96590085b4f8b57a52fe0f5",
        },
        "notes": [
            "Counts are census-counted population (32,706,028), not omission-adjusted (34,157,732, omission 4.25 %); the adjusted figure is not published by district.",
            "Disability is defined for ages 5 and over and is not comparable with the 2017 census variable.",
            "Footnote 3/: districts flagged boundary_undefined include populated centres where limits are not officially defined.",
        ],
    },
    "sinadef": {
        "title": "SINADEF: Certificado Defunciones (daily table, TB_SINADEF)",
        "publisher": "Ministerio de Salud (MINSA), via Plataforma Nacional de Datos Abiertos",
        "dataset_url": "https://www.datosabiertos.gob.pe/dataset/sinadef-certificado-defunciones",
        "file_url": "https://cloud.minsa.gob.pe/s/g9KdDRtek42X3pg/download",
        "edition": "Daily cut retrieved 2026-10-30; archive built 2025-12-01",
        "retrieved": "2026-10-30",
        "license": "ODC-By (http://opendefinition.org/licenses/odc-by/)",
        "local_file": "TB_SINADEF_2026-10-30.csv",
        "format": "CSV, separator ';', UTF-8 with BOM; extracted from the publisher's 7z",
        "unit": "One row per registered death",
        "sha256": "bb4058fa7d77049c95b2d1b1a1b53bfc64c6677a7642b75a034cc475370498a3",
        "rows": 1439302,
        "archive_url": "https://cloud.minsa.gob.pe/s/g9KdDRtek42X3pg/download",
        "archive_sha256": "3e46551097666da0ba07f3eff967cd1e988a7a3fa5770a4e31a35ec91e446e5a",
        "archive_member": "TB_SINADEF.csv",
        "download": True,
        "notes": [
            "Covers 2017-01-01 to 2025-11-30; 2025 has January to November only.",
            "Place of death is TIPO LUGAR + INSTITUCION; district of residence is the last six digits of COD# UBIGEO DOMICILIO.",
            "The bulk 'Información de Fallecidos' snapshot ends on 2024-05-05 and is not used.",
        ],
    },
    "worldpop": {
        "title": "WorldPop Peru 1 km population, 2025 (R2025A, constrained)",
        "publisher": "WorldPop, University of Southampton",
        "dataset_url": "https://www.worldpop.org/",
        "file_url": "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PER/v1/1km_ua/constrained/per_pop_2025_CN_1km_R2025A_UA_v1.tif",
        "edition": "R2025A, 2025",
        "retrieved": "2026-10-30",
        "license": "CC BY 4.0 (https://www.worldpop.org/faq)",
        "local_file": "per_pop_2025_CN_1km_R2025A_UA_v1.tif",
        "format": "GeoTIFF, 1 km",
        "unit": "People per pixel",
        "sha256": "94d81bf15b87c0139209a364cfae3c706c7c9520a584a023f578449bd172fdf7",
        "download": True,
        "notes": ["Rescaled to the census 2025 district totals by the population allocation."],
    },
    "friction_surface": {
        "title": "Malaria Atlas Project motorized friction surface, 2020 (1 km)",
        "publisher": "Malaria Atlas Project (University of Oxford)",
        "dataset_url": "https://malariaatlas.org/project-resources/accessibility-to-healthcare/",
        "file_url": "https://data.malariaatlas.org/geoserver/ows?service=CSW&version=2.0.1&request=DirectDownload&ResourceId=Explorer:2020_motorized_friction_surface",
        "edition": "2020, 1 km",
        "retrieved": "2026-10-30",
        "license": "CC BY 4.0 (data.malariaatlas.org; Earth Engine catalog terms)",
        "local_file": "2020_motorized_friction_surface.zip",
        "format": "ZIP containing 2020_motorized_friction_surface.geotiff",
        "unit": "Travel friction at 1 km",
        "sha256": "fcde4122d7d356a731dc0aae35a7db07c74a11b3029331064e46fc55ec0f955f",
        "download": True,
        "notes": ["Async with RENIPRESS and the census (2020 vs 2026); the plan reports this."],
    },
    "friction_walking": {
        "title": "Malaria Atlas Project walking-only friction surface, 2020 (1 km)",
        "publisher": "Malaria Atlas Project (University of Oxford)",
        "dataset_url": "https://malariaatlas.org/project-resources/accessibility-to-healthcare/",
        "file_url": "https://data.malariaatlas.org/geoserver/ows?service=CSW&version=2.0.1&request=DirectDownload&ResourceId=Explorer:2020_walking_only_friction_surface",
        "edition": "2020, 1 km",
        "retrieved": None,
        "license": "CC BY 4.0 (data.malariaatlas.org; Earth Engine catalog terms)",
        "local_file": "2020_walking_only_friction_surface.zip",
        "format": "ZIP containing 2020_walking_only_friction_surface.geotiff",
        "unit": "Travel friction at 1 km",
        "sha256": None,
        "download": True,
        "notes": ["Pre-specified walking-time variant (plan M4), restored in v14. The hash "
                  "is recorded after the first Colab download (its .sha256 sidecar)."],
    },
    "hydrobasins": {
        "title": "HydroBASINS South America, levels 1-12 (v1c)",
        "publisher": "HydroSHEDS (Lehner & Grill 2013)",
        "dataset_url": "https://www.hydrosheds.org/products/hydrobasins",
        "file_url": "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_sa_lev01-12_v1c.zip",
        "edition": "v1c",
        "retrieved": "2026-10-30",
        "license": "HydroSHEDS license: free for scientific, educational and commercial use",
        "local_file": "hybas_sa_lev01-12_v1c.zip",
        "format": "ZIP of shapefiles, levels 1-12",
        "unit": "Sub-basin polygons",
        "sha256": "fb012e48419bda0a7f4d0ebc56efcd906ad0e3bde324b9c70fac9693e2d21a72",
        "download": True,
        "notes": ["Level 4 defines the Amazon-basin flag (decision 0001 §11)."],
    },
    "osm_peru": {
        "title": "OpenStreetMap Peru extract",
        "publisher": "Geofabrik",
        "dataset_url": "https://download.geofabrik.de/south-america/peru.html",
        "file_url": "https://download.geofabrik.de/south-america/peru-latest.osm.pbf",
        "edition": "2026-10-29",
        "retrieved": "2026-10-30",
        "license": "ODbL 1.0",
        "local_file": "peru-2026-10-29.osm.pbf",
        "format": "PBF",
        "unit": "OSM extract",
        "sha256": "3f29398b86f16061026014bad5497525070e55624bc4f66cd560c95b880b9d98",
        "download": True,
        "notes": ["Used only for the independent-engine check (G1), not by the main access measure."],
    },
    "boundaries_hdx": {
        "title": "Peru administrative boundaries, COD-AB (Admin 0-3)",
        "publisher": "OCHA / Humanitarian Data Exchange (HDX)",
        "dataset_url": "https://data.humdata.org/dataset/cod-ab-per",
        "file_url": "https://data.humdata.org/dataset/54fc7f4d-f4c0-4892-91f6-2fe7c1ecf363/resource/61faa8d6-fbfa-4d44-a94d-8f3b0241277a/download/per_admin_boundaries.shp.zip",
        "edition": "Reviewed 2025-10-30; Admin 3 = 1,873 units",
        "retrieved": "2026-10-30",
        "license": "CC BY 4.0 (HDX terms of use)",
        "local_file": "per_admin_boundaries.shp.zip",
        "format": "ZIP of shapefiles (per_admin3.shp = districts)",
        "unit": "District polygons",
        "sha256": "1d143891d3bd1392dfe2d006f4f913b0b01290a448b9aee4189a718613706ef8",
        "download": True,
        "notes": [
            "Substitute for the INEI ide.inei.gob.pe layer, which returned 503 on 2026-10-30 (decision 0001 §11).",
            "1,873 Admin-3 units vs 1,893 census districts: districts without a polygon are reported, never imputed.",
            "Join key: adm3_pcode; verify the UBIGEO crosswalk in stage 02_geo_inputs.",
        ],
    },
    "dem_copernicus": {
        "title": "Copernicus DEM GLO-30",
        "publisher": "ESA / Airbus",
        "dataset_url": "https://dataspace.copernicus.eu/",
        "edition": "GLO-30",
        "retrieved": None,
        "license": "Copernicus DEM free licence (attribution)",
        "local_file": None,
        "format": "COG tiles, 30 m",
        "unit": "Elevation",
        "sha256": None,
        "download": False,
        "notes": [
            "Raw Peru tiles (~5 GB) are not stored; stage 02_geo_inputs builds the Peru",
            "mosaic on Colab and keeps the clipped COG in data/raw/dem/.",
        ],
    },
}

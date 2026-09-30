# Data for papers/c20-2026 (C20-2026-temperatura, design v2.0)

## Files

- `raw/dataset.csv` — local copy of `C:\Users\Aron\Downloads\dataset.csv` (5.2 MB,
  70129 lines with header, hourly 2018–2025). Columns:
  `FECHA_CORTE,UBIGEO,year,month,day,hour,TT,HR,RR,PP,FF,DD`.
  Gitignored by repo policy (`papers/*/data/raw/*`, `*.csv`); kept locally only.
- `docs/metadata.md` — converted from `Downloads/metadata.docx` (IGP-LAMAR EMA
  Observatorio de Huancayo, -12.0401, -75.32049, 3329 m, v2.0, updated 2026-05-26,
  ODC-By, contact lamar@igp.gob.pe). Original `.docx` stays out of the repo.
- `docs/data_dictionary.md` — converted from `Downloads/diccionary.xlsx`.
  Variable definitions (types, sizes, units). Original `.xlsx` stays out of the repo.
- `processed/` — empty; daily aggregates from `02_aggregate_daily.py` go here
  (gitignored, regenerable).

## Provenance

Source: IGP Laboratorio de Microfisica Atmosferica y Radiacion (LAMAR),
Plataforma Nacional de Datos Abiertos. License: Open Data Commons Attribution.
Coverage declared: hourly, 2018–2025, single station (Huayao, Junin).

## Verification on load (design §2.1, V1–V6)

`00_verify_source.py` must check before any aggregation:

- V1 timezone of `hour` (UTC vs UTC-5) via mean diurnal TT cycle;
- V2 `hour` convention (interval start/end), applied consistently;
- V3 missing codes (-999, 9999, empty) via out-of-range inventory (§3.1);
- V4 real coverage (first/last hour, long gaps, monthly completeness; 2025 must
  be complete for blind test B2);
- V5 `UBIGEO` constant (`nunique == 1`), report otherwise;
- V6 timestamp duplicates (deduplicate + report).

Target variable is never imputed (§12.7). UTC-to-local shift, if needed, applies
before any daily aggregation (§12.8).

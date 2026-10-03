# Data for papers/c20-2026 (design v3.0)

## Files

- `raw/senamhi.csv`: SENAMHI GBON/RBON automatic stations, hourly, written by
  `experiments/fetch_source.py` (about 50 MB, 416 273 rows, 16 columns).
  Gitignored by repo policy (`*.csv`). On Colab it lives in
  `Drive/c20-2026/data/raw/`.
- `SOURCE.json`: provenance written at fetch time (package id, resource URL,
  sha256, bytes, retrieval date, station inventory). Small and versioned.
- `raw/largescale/`: cached Niño (CPC `wksst9120.for`) and ROMI (NOAA PSL)
  text files, written by stage `06`.
- `docs/metadata.md`, `docs/data_dictionary.md`: the provider's metadata and
  variable dictionary, rendered to Markdown by `experiments/portal_docs.py`.
- `processed/`: regenerable intermediates from stages `01`–`06` (gitignored).
- `raw/dataset.csv`: the superseded IGP Huancayo file from design v2, local
  only. Nothing reads it any more (`config.source.file` is `senamhi.csv`).

## Provenance

Plataforma Nacional de Datos Abiertos (`www.datosabiertos.gob.pe`), package
`b884a001-f444-4c87-91b2-bee1891e6eb7`, licence ODC-By. The host returns HTTP
418 to non-browser User-Agents; `fetch_source.py` sends a browser one.

| UBIGEO | Station | Network | Elevation | Lat | Lon |
|---|---|---|---|---|---|
| 150701 | Matucana | GBON | 2421 m | −11.8391 | −76.3780 |
| 040114 | San José de Uzuna | RBON | 3269 m | −16.5810 | −71.3284 |
| 230201 | Candarave | RBON | 3410 m | −17.2680 | −70.2541 |
| 151007 | Carania | GBON | 3840 m | −12.3444 | −75.8722 |
| 040514 | Imata | RBON | 4475 m | −15.8427 | −71.0906 |

Coverage 2015-01-01 to 2024-06-30. Columns `FECHA` (yyyymmdd) and `HORA`
(hhmmss) give the timestamp; `TEMP` is the **hourly mean** temperature (°C),
`HR` relative humidity (%), `PP` **precipitation** (mm/h, not pressure).
Measured on the file of record: `TEMP` −16.7 to 26.3 °C, `PP` 0 to 32.5 mm/h,
about 3.3 % of hourly values missing per variable. `UBIGEO` arrives as a float
(`40514.0`) and is zero-padded at the read boundary.

## Verification on load (stage 00, V1–V6)

V1 timezone from the diurnal cycle; V2 hour convention; V3 missing codes and
whether gaps are row-wise; V4 coverage of the blind windows (B1, B2); V5 the
station set equals the declared one; V6 duplicate (station, timestamp) pairs.
The target is never imputed.

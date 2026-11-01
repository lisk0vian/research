# Data for papers/c19-2026

## Files

- `raw/` (gitignored): the files the pipeline reads. Their names are set in
  `experiments/config.yaml`: `renipress_2026-10-30.csv` (SUSALUD, October 2026
  edition) and `censo-2025-distrital.csv` (INEI census 2025, built by
  `experiments/census2025_prepare.py`). On Colab they live in
  `Drive/c19-2026/data/raw/`.
- Older files kept in `raw/` but no longer read: `renipress.csv` (the 2026-03-31
  cut, 35,371 rows x 31 columns) and `censo-2017.csv` (INEI census 2017).
- `SOURCES.md`: links, retrieval date and SHA-256 of every file, and how each
  one was obtained.
- `dictionary/`: what every column and derived variable means (YAML and CSV).
  Generated from `experiments/_schema.py`; a test fails if they drift apart.
- `processed/`: regenerable intermediates (the ETL cache).

## Verification on load (stage 00)

Both raw files are checked against the hash and size registered in `DATASETS`
(`experiments/_schema.py`): RENIPRESS 36,246 rows and 27,017 active facilities;
census 1,893 districts and a national total of 32,706,028. With any other file the
fixed checks are skipped with a warning, so the synthetic fixture can run.
The join is by `ubigeo`; active facilities in a district without a census row
are excluded and listed, never given population 0.

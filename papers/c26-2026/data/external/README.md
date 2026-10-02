# Input data

Two of the three inputs are binary or geometry files; the pipeline reads them
as they were downloaded, and `analysis_plan.json` (plan v3.3.3) records each
canonical name and its SHA-256. `../raw/dataset.csv` is the third input.

| File | Source | SHA-256 |
|---|---|---|
| `population.xlsx` | INEI, *Peru: total population projected at 30 June of each year, by department, province and district, 2018-2026* (Table No. 01); preliminary and reference projections | `9436df29b883fd4a9db3705040a6668ff4efe7047c2643249b6b6bedd90d5c8b` |
| `boundaries.geojson` | [juaneladio/peru-geojson](https://github.com/juaneladio/peru-geojson), `peru_provincial_simple.geojson`, simplified provincial layer (MPL-2.0) derived from INEI census cartography. Not the official layer; it may be replaced by the INEI/IGN one | `3663a2b58e52a6bba9c43acabe33e7d9bb065e54551edd9aa375a411fd0c7fa1` |
| `../raw/dataset.csv` | MININTER-DGIS, National Open Data Platform, resource f49ae77f-8822-45ea-aa16-911d677e303d (ODC-By) | `c41ebcced14fdf86bbf17db9f54bb381d73c0464a402f22ac5548a7899ef0e32` |

Licenses and download details are in [`../DATA_LICENSES.md`](../DATA_LICENSES.md).

## Why a workbook and not a CSV

`population.xlsx` is the canonical input on purpose: the run checks its SHA-256
against the frozen analysis plan, so the byte-for-byte file is the evidence of
what was analysed. Text extracts of it are provided in
[`../../outputs/derived/`](../../outputs/derived/) so the numbers can be read
without Excel:

| Derived file | Content |
|---|---|
| `population-provinces.csv` | the workbook as published: one row per province (`UBIGEO`, name, 2018-2026) |
| `population-units.csv` | the 26 territorial units used by the analysis, 2019-2025, long format |
| `population.json` | provenance of the extracts (source, URL, generator, row counts) |

Regenerate them with `python experiments/export_population.py`. The pipeline
reads the workbook, never the extracts.

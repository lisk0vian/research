# GeoAI-MissingPersons-Peru

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/pamelafiguer/research/blob/main/C26-202609-missingpersons/notebooks/GeoAI_MissingPersons_Peru.ipynb)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23066963.svg)](https://doi.org/10.5281/zenodo.23066963)
[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)

This folder (`C26-202609-missingpersons` in the [`pamelafiguer/research`](https://github.com/pamelafiguer/research) repository) holds the data, code and results for the following article:

> M. Evangelista Gamarra, E.A. Alama Carreño, P.E. Figueroa Rosas. *A reproducible GeoAI framework for explainable spatiotemporal analysis of national missing-person registers: multi-algorithm clustering and multilevel validation (Peru, 2019–2025).* Submitted to *Information Sciences*.

The pipeline analyses the 142,374 missing-person reports that the Peruvian Ministry of the Interior (MININTER) published for January 2019 to December 2025. It aggregates the reports into a panel of 26 territories by 84 months and runs five analytical stages:

1. rates and priority territories;
2. spatiotemporal states (multi-algorithm clustering);
3. spatial structure (global Moran's I, local Gi\* and LISA);
4. temporal dynamics;
5. multilevel validation: a territorial-identity leakage audit, a reproduction of the initial analysis and a specification multiverse.

Every number in the article is read from `results/FINAL_RESULTS.json` or `results/tables/`, and the article figures are generated from those tables and the territory-month panel.

---

## Quick Start

### Option A: Google Colab (recommended, no local setup)

1. Click the **Open in Colab** badge above.
2. Select **Runtime ▸ Run all**.

The notebook downloads only this folder of the repository, installs the two missing libraries (`libpysal`, `esda`) and checks the versions of all others against the reference environment. It then verifies the SHA-256 of the three input files, runs the automated tests and executes every stage of the analysis. When it finishes, it compares all 35 regenerated tables with the reference tables committed in this repository.

A full run takes about 30 minutes on a free Colab CPU. No GPU is needed. About 25 of those minutes are the clustering multiverse (stage 8). At the end, you can download the results as a ZIP file.

### Option B: local run (Python 3.11–3.13)

```bash
git clone https://github.com/pamelafiguer/research.git
cd research/C26-202609-missingpersons
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
python -m pytest -q tests          # 10 tests, < 1 min
python run_all.py                  # full pipeline, about 30 min
```

You can also open `notebooks/GeoAI_MissingPersons_Peru.ipynb` locally with Jupyter. It detects that it is running inside this folder and skips the download.

---

## Reproducibility safeguards

| Safeguard | Implementation |
|---|---|
| Frozen analysis plan | `src/reniped/config.py` → `config/analysis_plan.json`. The SHA-256 lock (`config/analysis_plan.lock.json`) is `3b6e0f676646baed271a107db441579d58230bbcec607f85a5f45d7e7e1f2958` (plan v3.3.2). The run stops if the plan changes without a version bump. |
| Input integrity | Each input file is checked against the SHA-256 stored in the plan before it is read (see [Data](#data)). |
| Randomness | Global seed 42 (`PLAN["semilla"]`), passed explicitly to every random operation. |
| Exact local p-values | Local Gi\* and LISA p-values use exact conditional randomization. They do not depend on the esda/numba version or on the number of CPUs. |
| Pinned environment | `requirements.txt` lists the exact versions of the reference run. `results/environment.json` records the reference run's software and hardware. |
| Single results store | `results/FINAL_RESULTS.json` plus 35 CSV tables in `results/tables/`. |
| Automated tests | `tests/test_core.py`: 10 tests of the critical components on synthetic data. |

**Reference environment:** Google Colab, 2 CPUs, Python 3.13.15. Libraries: numpy 2.1.3, pandas 2.2.3, scipy 1.16.3, scikit-learn 1.6.1, statsmodels 0.15.0, geopandas 1.1.4, libpysal 4.14.1 and esda 2.9.0.

**HDBSCAN:** the pipeline uses `sklearn.cluster.HDBSCAN` (scikit-learn ≥ 1.3), not the standalone `hdbscan` package. Do not install older library versions: the numbers would change.

**Expected differences between runs:** execution times (`tiempos_por_etapa_s`) and the hardware description. The HDBSCAN internal indices in `T03_multialgoritmo.csv` may also differ slightly across machines; the article does not report them. All other tables are reproduced to floating-point precision: across machines, the relative differences stayed below 10⁻¹⁰.

---

## Repository structure

```
C26-202609-missingpersons/
├── README.md                  this file
├── LICENSE                    MIT (code)
├── DATA_LICENSES.md           sources, licenses and hashes of the input data
├── CITATION.cff               how to cite this repository
├── .zenodo.json               metadata for the Zenodo archive (DOI)
├── requirements.txt           exact library versions of the reference run
├── run_all.py                 full pipeline without a notebook
├── config/                    frozen analysis plan and its SHA-256 lock
├── data/
│   ├── raw/                   RENIPED extract (MININTER, CSV)
│   ├── external/              INEI population projections (XLSX), provincial boundaries (GeoJSON)
│   └── processed/             intermediate files (regenerated by the pipeline, not versioned)
├── src/reniped/               Python package (one module per analytical component)
├── tests/                     automated tests
├── notebooks/
│   ├── GeoAI_MissingPersons_Peru.ipynb      clean Colab notebook (English)
│   └── archive/                             executed notebook of the reference run
└── results/
    ├── FINAL_RESULTS.json     every number reported in the article
    ├── tables/                35 CSV tables (T01–T14b)
    ├── figures_article/       Figs. 1–6 of the article (ES/EN)
    ├── figures/               supplementary diagnostic figures
    └── environment.json       software and hardware of the reference run
```

The PNG previews of the figures are versioned. The TIFF files for submission (600 dpi maps, 1000 dpi line art) are regenerated by every run and are excluded from Git by `.gitignore`.

### Modules and manuscript sections

| Stage (`pipeline.py`) | Module | Manuscript |
|---|---|---|
| `stage_init` | `config.py` | Section 4.7 |
| `stage_data` | `io_utils.py`, `population.py`, `panel.py` | Section 3; Fig. 2 |
| `stage_priority` | `prioridad.py` | Sections 4.1, 5.1; Figs. 3–4 |
| `stage_features` | `features.py` | Section 4.2; Table 1 |
| `stage_k` | `clustering.py` | Sections 4.3, 5.2; Fig. 5a–c |
| `stage_algorithms` | `clustering.py` | Sections 4.3, 5.2; Fig. 5d |
| `stage_audit` | `audit.py` | Sections 4.6, 5.5; Table 3 (Panel A) |
| `stage_temporal` | `temporal.py` | Sections 4.5, 5.4 |
| `stage_spatial` | `spatial.py`, `maps.py` | Sections 4.4, 5.3; Table 2 |
| `stage_multiverse` | `multiverse.py`, `figures.py` | Sections 4.6, 5.5; Fig. 6, Table 3 (Panel B) |
| `stage_article_figures` | `article_figures.py` | Figs. 1–6 |

---

## Where each figure and table comes from

| Article | Output file(s) | Source |
|---|---|---|
| Fig. 1 | `results/figures_article/Fig1_framework_{en,es}` | diagram (no data) |
| Fig. 2 | `Fig2_reports_*` | `data/processed/panel_departamento_mes.csv` (reports per year and per month) |
| Fig. 3 | `Fig3_priority_*` | `T14_territorios_prioritarios.csv` + geometry |
| Fig. 4 | `Fig4_persistence_*` | `T14b_razon_tasas_anual.csv`, `T14_territorios_prioritarios.csv` |
| Fig. 5 | `Fig5_states_*` | `T02_seleccion_K.csv`, `T02b_gap_desde_K1.csv`, `T04_perfiles_cluster.csv`, `T04c_distribucion_estandarizada_por_estado.csv` |
| Fig. 6 | `Fig6_validation_*` | `T12_multiverso_M1_especificaciones.csv`, `T13_multiverso_M2_especificaciones.csv` |
| Table 1 | — | `config/analysis_plan.json` (`features.espacios`); code names in the glossary below |
| Table 2, Panel A | — | `T09_moran_global.csv` |
| Table 2, Panel B | — | `T10_local_queen.csv`, `T10_local_knn4_geodesico.csv` |
| Table 3, Panel A | — | `T05_auditoria_proxy.csv` |
| Table 3, Panel B | — | `T12d_M1_soporte_afirmaciones.csv`, `T13b_M2_soporte_afirmaciones.csv` |

The sensitivity analyses cited in the text are in:

- `T14_territorios_prioritarios_consolidado_2019_2024.csv` and `T14_territorios_prioritarios_exposicion_total.csv`;
- `T08_*` (rates);
- `T11_*` (leave-one-out Moran);
- `T12c/T12e/T13c/T13d` (decision importance and support by decision);
- `T06_*` (temporal transfer).

---

## Data

The three input files are included **exactly as downloaded**, so the run does not depend on sources that may change. The open-data portal can update the RENIPED resource at any time. A fresh download may therefore have a different SHA-256, and the pipeline will stop rather than analyse different data. Full details and licenses are in [`DATA_LICENSES.md`](DATA_LICENSES.md).

| File | Source | SHA-256 |
|---|---|---|
| `data/raw/DATASET_Personas_Desaparecidas_2019-01_2025-12.csv` | MININTER, Plataforma Nacional de Datos Abiertos, [resource f49ae77f…](https://www.datosabiertos.gob.pe/dataset/personas-desaparecidas/resource/f49ae77f-8822-45ea-aa16-911d677e303d) | `c41ebcced14fdf86bbf17db9f54bb381d73c0464a402f22ac5548a7899ef0e32` |
| `data/external/INEI_poblacion_proyectada_2018-2026_cuadro01.xlsx` | [INEI population projections 2018–2026](https://www.gob.pe/institucion/inei/informes-publicaciones/6894980-peru-poblacion-total-proyectada-al-30-de-junio-de-cada-ano-segun-departamento-provincia-y-distrito-2018-2026) (Table No. 01) | `9436df29b883fd4a9db3705040a6668ff4efe7047c2643249b6b6bedd90d5c8b` |
| `data/external/limites_provinciales_peru_simplificados.geojson` | [juaneladio/peru-geojson](https://github.com/juaneladio/peru-geojson), `peru_provincial_simple.geojson` (MPL-2.0) | `3663a2b58e52a6bba9c43acabe33e7d9bb065e54551edd9aa375a411fd0c7fa1` |

Key definitions:

- **Territories.** The 26 territories are 24 departments, plus Callao, plus Lima split into Lima Metropolitana (province 150100) and Región Lima (department 150000 minus 150100).
- **Missing months.** Months without source rows are treated as missing, never as zero. The documented gaps are six departments in January 2023 (Piura, Puno, Tacna, San Martín, Moquegua and Madre de Dios) and Moquegua in May–June 2020.
- **Rates.** Rates are reports per 10,000 person-years with observed exposure (months with coverage). Total exposure is used as a sensitivity analysis.
- **2025 data.** The source marks the 2025 data as preliminary. The priority classification is repeated for 2019–2024 as a sensitivity analysis.

---

## Glossary of Spanish identifiers

The analysis plan, table names, column names and console messages are in Spanish. They are kept unchanged because any edit to the plan would change its SHA-256, which is cited in the article.

| Identifier | Meaning |
|---|---|
| `DPTO_KEY`, `ANO`, `MES` | territory, year, month |
| `REPORTES`, `CANTIDAD` | number of reports |
| `TASA_10K`, `LOG_TASA` | rate per 10,000 (person-years) and its logarithm |
| `EXPOSICION_OBSERVADA` / `_TOTAL` | observed / total exposure |
| `RR_VS_RESTO`, `IC95_INF/SUP` | rate ratio versus the rest of the country, 95% CI |
| `CLASE`: `superior` / `inferior` / `no_distinguible` | higher / lower / not distinguishable |
| `ANOMALIA`, `CAMBIO_12M`, `NIVEL_PREV12` | seasonal anomaly, 12-month change, prior 12-month level |
| `E1_relativo`, `E2_relativo_mas_nivel`, `E3_nivel` | feature spaces E1 (relative), E2 (mixed, main), E3 (level) |
| `CLUSTER`, `estado` | spatiotemporal state |
| `seleccion_K`, `perfiles`, `multialgoritmo` | choice of K, state profiles, multi-algorithm comparison |
| `auditoria_proxy`, `NMI_cluster_unidad`, `bloques_anuales` | identity-leakage audit, NMI(cluster, territory), within-year permutation null |
| `vecinos`, `pesos`, `queen`, `knn4_geodesico` | neighbours, spatial weights, contiguity, 4 nearest by geodesic distance |
| `p_bilateral`, `q_FDR`, `q_BY` | two-sided p, Benjamini–Hochberg q, Benjamini–Yekutieli q |
| `multiverso`, `especificaciones`, `afirmacion`, `soporte` | multiverse, specifications, claim, support |
| `fold principal` / `secundario` | train 2019–2023 → eval 2024 / train 2019–2024 → eval 2025 |
| `semilla` | random seed |

---

## How to cite

If you use this code or data, please cite the article and this archive:

```
M. Evangelista Gamarra, E.A. Alama Carreño, P.E. Figueroa Rosas (2026). Data and code for
"A reproducible GeoAI framework for explainable spatiotemporal analysis of national
missing-person registers"
```

GitHub's **"Cite this repository"** button reads [`CITATION.cff`](CITATION.cff).

## License

- **Code:** MIT (see [`LICENSE`](LICENSE)).
- **Input data:** redistributed under their original terms (see [`DATA_LICENSES.md`](DATA_LICENSES.md)).
- **Derived results** (`results/`): CC BY 4.0.

## Authors

- Moisés Evangelista Gamarra ([ORCID 0009-0002-5382-1390](https://orcid.org/0009-0002-5382-1390)), corresponding author, mevangelistag@senati.pe
- Edwar Abrahan Alama Carreño ([ORCID 0009-0006-8029-4302](https://orcid.org/0009-0006-8029-4302))
- Pamela Estefani Figueroa Rosas ([ORCID 0009-0007-6100-9382](https://orcid.org/0009-0007-6100-9382))

Servicio Nacional de Adiestramiento en Trabajo Industrial (SENATI), Lima, Peru.

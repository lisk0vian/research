# Design decisions — C26-2026 migration

Why `papers/c26-2026/` looks the way it does. Decisions taken on 2026-10-02 when
the pre-standardization folder `C26-202609-missingpersons/` was migrated into
the `papers/` layout. Pipeline-level decisions (variables, tests, validation)
are documented in the analysis plan's `historial`
(`experiments/config/analysis_plan.json`) and in `experiments/README.md`.

## Layout

| Legacy | Now | Why |
|---|---|---|
| `src/reniped/`, `run_all.py`, `config/`, `requirements.txt` | `experiments/` | code that produces the numbers lives in `experiments/`; `requirements.txt` became `requirements-experiments.txt` to match the repository convention |
| `results/` | `outputs/` | the repository keeps machine-readable results in `outputs/` |
| `results/FINAL_RESULTS.json` | `outputs/results.json` | short, lowercase, English name |
| `tests/` | `tests/` | per-paper suite; registered in `pytest.ini` so `pytest` collects it |
| `notebooks/GeoAI_MissingPersons_Peru.ipynb` | `notebooks/notebook.ipynb` | short name; the notebook locates the package through `experiments/src/reniped` |
| `pipeline/*.docx`, `*.pdf` | `legacy/` | the originals of the migrated manuscript |
| `CITATION.cff`, `.zenodo.json`, `authors.json`, `LICENSE` | `legacy/` | metadata of the Zenodo archive of the old folder |

## Short names for the inputs

`run_all.py` no longer carries the source description in the file name:

| Legacy name | Now | Plan field |
|---|---|---|
| `DATASET_Personas_Desaparecidas_2019-01_2025-12.csv` | `data/raw/dataset.csv` | `datos.csv_reniped.nombre_canonico` |
| `INEI_poblacion_proyectada_2018-2026_cuadro01.xlsx` | `data/external/population.xlsx` | `datos.xlsx_inei.nombre_canonico` |
| `limites_provinciales_peru_simplificados.geojson` | `data/external/boundaries.geojson` | `datos.geometria.nombre_canonico` |

Renaming them changes the frozen plan, so `version_plan` went from **3.3.2 to
3.3.3**, the `historial` entry records the change and
`config/analysis_plan.lock.json` was regenerated with the pipeline's own
`freeze_plan`. The bytes of the three files are untouched, so the SHA-256 values
in the plan and the `c41ebcce…` prefix cited in the article are unchanged.
Provenance for each file is in `data/external/README.md` and `data/DATA_LICENSES.md`.

The 35 result tables (`T01_tasas_departamentales_2019_2025.csv` and friends) and
the figure PNGs (`Fig1_framework_en.png`, `Fig_area_estudio.png`) keep their
names for now: they are the bridge between the article's "Table 1 / Fig. 3" and
the files, and a full pipeline run (~30 min, needs libpysal/esda/geopandas) is
required to prove a rename is consistent. **Known debt**, tracked here.

## Binary inputs and readable extracts

`population.xlsx` stays a workbook on purpose: the run verifies its SHA-256
against the plan, so the byte-exact file is the evidence of what was analysed.
`experiments/export_population.py` derives `outputs/derived/population-provinces.csv`,
`population-units.csv` and `population.json` so the numbers can be read without
Excel. The pipeline reads the workbook, never the extracts.

`data/.gitattributes` (moved from the legacy folder) marks the data as
non-convertible so Git never rewrites their line endings: the RENIPED CSV uses
CRLF and its SHA-256 is part of the frozen plan.

## Manuscript

`paper/main.qmd` is the English manuscript, converted from
`legacy/C26_Manuscript_InformationSciences_EN.docx` for the *Information
Sciences* target. The Spanish manuscript stays in `legacy/` as the original.

**Template.** The paper renders with the Elsevier **CAS** template
(`quarto-journals/elsevier-cas`, `cas-sc.cls`, two-column), the same bundle the
repository already ships for *Engineering Applications of Artificial
Intelligence*, so both Elsevier submissions look alike. `cas.lua` only maps
`cite-style: authoryear` to `cas-model2-names`; there is no numbered branch, so
the manuscript cites as (Author, Year). That is compliant: the Guide for Authors
sets no strict reference format at submission ("any consistent style") and the
journal reference style is applied at proof stage.

- Citations became `[@key]` against `paper/references.bib` (50 entries; the 37
  with a DOI were filled from Crossref, the 13 reports, datasets and software
  entries by hand). Acronyms in titles are braced (`{LISA}`, `{GeoAI}`,
  `{PySAL}`) so `cas-model2-names.bst` does not lowercase them.
- Figures point at `paper/media/FigN_en.png`, copies of
  `outputs/figures_article/` so that every figure traces back to `outputs/`.
  The images embedded in the DOCX are visually identical but re-compressed
  (different PNG bytes), so the pipeline output is the one kept.
- The three tables are the Word tables converted to pipe tables (pandoc pads
  them to 190 columns and they overflow the column). Their multi-panel
  structure (Table 1 has two panels, Tables 2 and 3 a Panel A and B) is kept as
  one table with bold panel headers, as in the Word original.
- Equations came from the Word OMML as TeX and are written as `$$ ... $$
  {#eq-N}`: the template numbers them in the PDF (the numbering of the Word
  original) and Quarto keeps them as Word math in the DOCX. The prose never
  refers to an equation by number, so the labels are anchors, not dependencies.
- **Unicode became TeX math.** The elsarticle build used lualatex and accepted
  raw Unicode; `cas-sc.cls` compiles with `pdflatex` + T1 and stops on Greek
  letters and superscripts. `η²~p~`, `μ~u,m(t)~`, `σ~u~`, `≤`, `≥`, `10^-10^`
  and the Unicode minus are now `$\eta^2_p$`, `$\mu_{u,m(t)}$`, `$\sigma_u$`,
  `$\le$`, `$\ge$`, `$10^{-10}$` and `-`. The Word target turns them into OMML.
- Headings lost their numeric prefixes ("4.6. Design of..." -> "Design of..."):
  the template numbers the sections, and the numbering is identical, so the
  prose references ("Section 4.6") remain correct.
- Section numbering aside, the prose is the DOCX's verbatim, except: the plan
  version (3.3.2 -> 3.3.3) and the abstract, trimmed from 236 to 200 words to
  meet the journal's limit for original research.

The front matter follows `papers/c20-2026`: `journal.*` sits at the top level so
both targets see it, the Highlights live in `journal.highlights` (the CAS class
prints them in the PDF and `cas-docx.lua` puts them in the Word front matter)
and the CRediT roles live in `author[].cas.credit` (`\printcredits` renders
them).

Sections the DOCX did not have and the journal requires at submission were
added: **Data availability** (Zenodo DOI), **Declaration of competing interest**
and **Funding** (TODO — confirm with the authors). The CRediT statement moved
into the author metadata.

## Rendered layout (verified with scripts/paper_layout_check.py)

`paper_layout_check.py --slug c26-2026` proves the render respects the column
in three layers: the engine's own `Overfull \hbox` report in
`build/render/main.log` (fails above 5 pt), the ink bounding box of every
rasterized page against the template's text block (fails outside ~2 mm), and
source assertions (no `fleqn` class option, bibliography entries with at most
10 authors, every entry cited, none rendered over 900 characters). The layouts
it guards were fixed as follows:

- **Centered equations.** The CAS bundle ships `classoption: [a4paper, fleqn]`
  and `cas.lua` forces the same base options; with them amsmath left-aligns
  every display. Both are removed for this journal only (EAAI's bundle keeps
  them), so the equations center as amsmath does by default.
- **Wrapping table columns.** `cas-common.sty` defines the bundle columns as
  `\extracolsep{\fill}` + `l/c/r`, and `l` never wraps: prose cells made the
  tables run 12-117 pt out of the column. The journal's copy of the two table
  filters (`cas-pre-ast.lua` + its mirror in `cas.lua`) now emits `p{}`
  columns of an equal share of `\tblwidth`, keeping pandoc's alignment.
- **Readable references.** The Crossref import of the many-author paper listed
  all 166 authors (a 6,400-character wall); entries with more than 10 authors
  are truncated to the first three + `others`, as the Word original wrote
  "et al.".

## TODO before submission

1. Confirm the CRediT roles and the funding statement (both marked in `main.qmd`).
2. Archive a new Zenodo version (3.3.3) and check that
   `10.5281/zenodo.23066963` resolves to it; `references.bib` cites version 3.3.3.
3. Trim the 35 table names to short English names once a full run validates the
   rename (known debt above).
4. Convert the figure references in the prose ("Fig. 1", "Table 2") to Quarto
   cross-references once a render confirms the numbering the template produces.

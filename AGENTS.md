# AGENTS.md — Research Repository Guidance

This repository contains multi-project academic research and papers.

## Project Structure

- `C15-202610-fiscal/`: Prosecutorial Congestion Risk Prediction (Springer / Journal of Big Data, under revision).
- `C20-202610-temperature/`: Subseasonal Temperature Forecasting in Andean Stations (In Progress).
- `C21-202610-birth/`: Early Prediction of Low Birth Weight, National Peruvian Cohort (under revision).

> Note: The root `README.md` table lists `C10-2026` for the temperature project — the actual directory is `C20-202610-temperature`. Use directory names, not README table entries.

---

## Available Agent Skills

Five skills are installed (see `.agents/skills/` and `skills-lock.json`). Load with the `skill` tool before use:

| Skill | When to use |
|---|---|
| `docx` | Creating/editing `.docx` files — use `docx` npm package for new docs, `unzip`+edit+`zip` for edits. Key gotchas: A4 default page size, tables need dual widths, `ShadingType.CLEAR` not `SOLID`, never use `\n`. |
| `humanize-academic-writing` | Rewriting AI-drafted academic text into natural scholarly prose. Run `python scripts/ai_detector.py` first to identify patterns. |
| `nature-academic-search` | Literature search, citation verification, MeSH strategy, .nbib/.ris/.bib conversion via MCP tools (PubMed, CrossRef, etc.). Always load `manifest.yaml` and `static/core/` files first. |
| `office-to-md` | Converting Office files to Markdown using `markitdown`. |
| `tgrep` | Content search — **use instead of `grep`/`rg`**. Trigram-indexed, ripgrep-compatible. Always `--` before pattern; `serve`/`index` once per repo. |

---

## Project C15 (`C15-202610-fiscal/`) — Key Rules

See `C15-202610-fiscal/CLAUDE.md` for exhaustive project instructions. **An agent will miss critical constraints without reading it.** Key rules:

### Truth Source & Numbers
- **`src/tables/*.xlsx` (78 files) is the single source of truth for every reported figure.** Never cite notebook cell outputs — they are stale (notebook shows `n_features=69`, `f1=0.466165`; `Tabla_76` shows 74 features, `f1=0.467967`).
- **Never write a number into a manuscript that you have not traced to a `Tabla_NN`.** If untraceable, say so.
- `src/tables/Tabla_02_Project_Scorecard.xlsx` is self-assessment — not evidence.
- `src/` contains **no `.py` files**. Only code is `notebooks/experiments.ipynb`, `papers/drafts/springer/make_figures.py`, and `context/convert.sh`.

### Context Files
- **Always check `context/INDEX.md` first** before exploring `data/` or `papers/drafts/`. The `context/` folder contains markdown mirrors of key documents (converted with markitdown/pandoc) to reduce token usage.
- `context/experiments.md` is a markdown mirror of `notebooks/experiments.ipynb` — **not listed in INDEX.md**. Use it to read pipeline code without loading the 9.8 MB notebook.
- Raw CSVs in `data/` have no markdown version — read them normally for notebooks.

### LaTeX Compilation (`papers/drafts/springer/`)
- **Do not use `latexmk`** (BibTeX fails under Git Bash). Compile manually:
  ```bash
  cd papers/drafts/springer
  mkdir -p build2 && cp references.bib sn-vancouver.bst build2/
  pdflatex -interaction=nonstopmode -output-directory=build2 main.tex
  (cd build2 && bibtex main)
  pdflatex -interaction=nonstopmode -output-directory=build2 main.tex
  pdflatex -interaction=nonstopmode -output-directory=build2 main.tex
  ```
- Then copy `main.pdf` and `main.bbl` up to folder root and into `build/`.
- Use the **Edit tool, not `sed`** — Git Bash mangles backslashes in LaTeX.
- When writing checker scripts, strip comments with `(?<!\\)%.*`, never `%.*`.
- **Acceptance bar: 0 errors, 0 undefined references/citations, 0 overfull hboxes.**

### Methodological Limits (load-bearing)
1. **2026 data is Jan–May exploratory only** — excluded from all performance ranges. Walk-forward ranges cover **six** complete-year folds (2020–2025); `Tabla_34` fold 7 evaluates 2026 and is excluded.
2. **2025 is the single locked evaluation** — model family selection was closed before 2025 was opened.
3. **The reported model is not recalibrated** — calibration is measured and characterized, never corrected.
4. **The ablation is a LightGBM result** — every mention must say so.
5. **Two data hues only** — `BLUE #1f5c99` and `ORANGE #c2571a`. Third hue uses small multiples (Fig. 4 is three stacked panels).
6. **No commas in numerical values inside tables.** Use `9593`, not `9{,}593`.
7. **Figure/table titles ≤15 words.** Figure captions need short title + legend.
8. **Declarations headings are fixed and ordered** — no "Code availability" heading.

### Known Provenance Traps
- `derived_dca.csv` and `derived_strata.csv` are reconstructions from `Tabla_49` bin-rounded data — cannot refine below 0.10 steps.
- `Tabla_72` records all 8 models omitted from external validation due to logging bug (`append_to_csv` undefined). `Tabla_71` holds real 2026 metrics.
- `Tabla_03` says all 8 years come from one consolidated CSV, but `data/` holds eight per-year CSVs and the consolidated file is not in the repo.

### Figure Constraints
- All ten figures generated by `make_figures.py` from `src/tables/*.xlsx`. **Never edit PNGs by hand or hard-code numbers into the script.**
- Partial 2026 file always marked with `PARTIAL` wash, hollow marker, dashed connector.
- Width ≤170 mm at 300 dpi (≤2008 px). Verify with: `python -c "from PIL import Image;import glob,os;[print(os.path.basename(f), Image.open(f).size[0]/300*25.4) for f in sorted(glob.glob('figures/*.png'))]"`

### Open Items
- `Availability of data and materials` has placeholders `[REPOSITORY NAME]` and `[PERSISTENT IDENTIFIER...]` — **manuscript cannot be submitted until a public Zenodo DOI is archived.**
- Second author has no ORCID (`TODO(submission)`).
- Generative-AI disclosure has `TODO(authors)`.
- `remarks/senati/reviewer.md` references wrong file path and section numbers.

### C15 `.claude/` Commands & Settings
- **`build-latex` command**: Builds LaTeX via `make` (Unix) or `.\build-latex.ps1` (Windows). Copies PDF to `papers/renders/`.
- **`settings.local.json`**: Pre-approves `pdflatex`, `bibtex`, `python`, `curl`, `awk`, `grep`, and `node` commands. Denies `rm -rf`, `sudo`, and `curl | bash`.

---

## Project C21 (`C21-202610-birth/`) Notes
- Dataset **not in repo** (exceeds GitHub 100 MB limit) — download from official source, place in configured data directory.
- Pipeline runs in **Google Colab**. Notebook: `notebooks/early_prediction_colab.ipynb`.
- Manuscript: `C03-202610-Nacimiento_CORREGIDO.docx` (use `docx` skill to edit).
- `correction_objectives.md` describes the methodological corrections.
- `references.bib` contains BibTeX for data sources.
- **Do not generate PDFs/figures/model binaries unless reproducible from the notebook.**

---

## Project C20 (`C20-202610-temperature/`) Notes
- Pipeline runs in notebooks only (`notebooks/preprocess-andean-dataset.ipynb`, `notebooks/huayao-pipeline.ipynb`).
- Data: `data/IGP_EstacionEMA_data_2018_2025.csv`.
- Uses zero-leakage climatology decomposition — training partition (2018–2023) only for climatology signal.
- Models benchmarked: RF, XGBoost, LightGBM, CatBoost, LSTM, Temporal Fusion Transformer.

---

## Repository-Level Conventions
- **Licensing**: Code = MIT (`./LICENSE`). Research content = CC BY 4.0 (`./LICENSE-CONTENT`).
- **Each project has its own `README.md`** with project-specific details.
- **`context/` folders** (C15): Markdown mirrors of documents, always check `context/INDEX.md` first.
- **No `opencode.json`**, `.cursorrules`, or `.github/copilot-instructions.md` exist at the root.

---

## How to Investigate a New Project
1. Read the project's `README.md` for overview and status.
2. Check for `CLAUDE.md` (C15) or `correction_objectives.md` (C21) for project-specific rules.
3. Check `context/INDEX.md` if it exists before opening raw data files.
4. Inspect `notebooks/` for the actual analysis pipeline.
5. Check `papers/` for manuscripts and their build instructions.

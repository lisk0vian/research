---
name: paper-build
description: >
  Render a paper's main.qmd to PDF and/or Word using its journal's Quarto
  format. Use whenever the user wants to build, render, compile, export or
  generate the PDF/Word of a paper, or produce a submission file. Runs
  `scripts/paper_build.py`, which verifies the environment first (quarto, LaTeX
  engine, journal extension) and reports what is missing WITHOUT installing
  anything, then renders into papers/<slug>/build/.
---

# paper-build

Turn `papers/<slug>/paper/main.qmd` into a submission-ready PDF/DOCX and the
`<slug>-latex.zip` source package for the journal. All the logic is in
`scripts/paper_build.py`; never render with ad-hoc commands.

## Workflow

1. Resolve the paper (`--slug`) and format (`pdf` | `docx` | `all`; default all).

2. **Verify first** (does not install anything):

   ```bash
   python scripts/paper_build.py --slug <slug> --check-only
   ```

   If something is missing it prints the exact fix from the `[MISS]` lines, e.g.
   `quarto install tinytex` or
   `cd papers/<slug>/paper && quarto add <extension>`.
   **Do not install toolchain components yourself** — report and stop.

3. **Render**:

   ```bash
   python scripts/paper_build.py --slug <slug> --format all
   ```

   Output lands in `papers/<slug>/build/` as `<slug>.pdf`, `<slug>.docx` and
   `<slug>-latex.zip` (tex + class/style/bst + figures + bib/bbl +
   highlights.txt, ready to compile standalone). Only the final PDF is
   committed; `.tex`, `.aux`, `.log`, `_files/`, `.docx` and `.zip` are
   gitignored.

4. **On render errors**, map the message to the cause using
   `references/common-errors.md` (math trapped in tables, unwrapped inline math,
   undefined citation key, engine/font mismatch, duplicated section numbers).
   Report the failing line and the fix; do not silently edit the paper body.

## Core rules

- The journal drives the format: `manifest.yaml` → `journal` → 
  `templates/journals/<journal>/type.yaml` → `quarto_format`/`extension`.
  Never hardcode `elsevier-pdf` etc.
- Never edit content to force a render to pass.

## What this skill does NOT do

- Choose or change the journal (`paper-journal`).
- Install toolchain components.
- Validate the repository structure (`paper-validate`).

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

   Render `all` (or the PDF first): the DOCX post-processor
   (`tools/cas_docx_post.py` for elsevier-cas) reads the PDF to put floats on
   the same pages and the zip's `.bbl` to copy the references and citations.

4. **Check parity** (DOCX and LaTeX zip against the PDF; needs Word on
   Windows, else LibreOffice):

   ```bash
   python scripts/paper_parity.py --slug <slug>
   ```

   It reports levels L0 pages, L1 words on the same page, L2 identical lines,
   L3 word positions, L4 ink XOR, plus a strict zip-vs-PDF check, and writes
   `build/parity/` (report.json, `*-side.png`, `*-overlay.png`: red = PDF only,
   blue = DOCX only). Read the overlays to see where they differ. Thresholds
   live under `parity:` in the journal's `type.yaml`. Fonts for Word:
   `powershell -ExecutionPolicy Bypass -File scripts/install_stix_fonts.ps1`.

5. **On render errors**, map the message to the cause using
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

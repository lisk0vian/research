---
name: paper-build
description: >
  Render a paper's main.qmd to PDF and/or Word (DOCX) using its journal's Quarto
  format. Use whenever the user wants to build, render, compile, export, or
  generate the PDF/Word of a paper, or produce a submission file. Verifies the
  environment first (quarto, LaTeX engine, journal extension) and reports what is
  missing WITHOUT installing anything, then renders to the paper's build/
  directory. Reads the journal from manifest.yaml so the output matches the
  chosen venue.
---

# paper-build

Turn `papers/<slug>/paper/main.qmd` into a submission-ready PDF and/or DOCX.

## Output policy (versionable)

- All rendered output goes to `papers/<slug>/build/`.
- Only the final **PDF** is committed to git; intermediates (`.tex`, `.aux`,
  `.log`, `.bbl`, Quarto's `_files/`) are gitignored. This is already encoded in
  the repo `.gitignore` (`build/*` ignored except `*.pdf`).
- The DOCX is also written to `build/`. By default it is NOT committed (it is
  regenerable); if the user wants the Word file versioned for a coauthor who
  doesn't build locally, they can `git add -f build/<slug>.docx`.

## Core rule

**The journal drives the format.** Read `papers/<slug>/paper/manifest.yaml` to
get the `journal` slug, then read `templates/journals/<journal>/type.yaml` for
`quarto_format` and `extension`. Do not hardcode `elsevier-pdf` etc. — always
derive it from the paper's current target.

## Workflow

### 1. Resolve the paper and format

- `<slug>` = first command argument (else list `papers/` and ask).
- Output format = second argument: `pdf`, `docx`, or `all`. **Default: `all`.**

### 2. Verify the environment (report, do NOT install)

Run `scripts/check_env.py --repo-root . --slug <slug> --format <fmt>`. It checks:

- `quarto` is on PATH (and prints version).
- For PDF: a LaTeX engine is available (`tinytex` via quarto, or system
  `xelatex`/`pdflatex`).
- The journal's Quarto extension is installed in
  `papers/<slug>/paper/_extensions/` (if the journal defines one).
- `references.bib` exists and is non-empty (warn if empty — bibliography will be
  blank).

If anything required is missing, STOP and report exactly what to run, e.g.:
- `quarto install tinytex`
- `cd papers/<slug>/paper && quarto add <extension>`

Do not install these yourself — the user chose "verify and warn only".

### 3. Render

From the paper directory, render each requested format using the journal's
Quarto format for PDF and Quarto's native `docx`:

```bash
cd papers/<slug>/paper

# PDF (journal format from type.yaml, e.g. elsevier-pdf)
quarto render main.qmd --to <quarto_format> --output-dir ../build

# DOCX (generic; add reference-doc later if the journal needs Word styling)
quarto render main.qmd --to docx --output-dir ../build
```

Notes:
- If the journal has NO extension (`extension: ""`), render PDF with plain
  `--to pdf` and note the final journal PID needs a manual template.
- `--output-dir ../build` keeps generated files out of `paper/`. If the Quarto
  version ignores it for some formats, move the outputs into `build/` after.
- Rename outputs to `<slug>.pdf` / `<slug>.docx` in `build/` for clarity.

### 4. Handle render errors

Quarto/LaTeX errors on a freshly migrated paper are common. Read the error and
map it to the likely cause (see `scripts/check_env.py` output and
`references/common-errors.md`):

- `\symbb allowed only in math mode` / math escaped as text → an equation is
  trapped inside a pandoc table or missing its `$$` fences.
- `Missing $ inserted` → inline math not wrapped in `$...$`.
- `Undefined control sequence` → a LaTeX macro the class doesn't provide.
- `Citation 'x' undefined` / empty bibliography → key not in `references.bib`,
  or `bibliography:` not set.
- Font/`fontspec` errors → engine mismatch; the Elsevier/IEEE formats expect a
  specific engine.

Report the failing line and the fix; do not silently patch the paper's content.

### 5. Report

List what was produced (`build/<slug>.pdf`, `build/<slug>.docx`), the journal
format used, and remind which files are versioned (PDF yes, intermediates no).

## What this skill does NOT do

- It does not choose or change the journal (that's `set-journal`).
- It does not install toolchain components (verify-and-warn only).
- It does not edit paper content to force a render to pass.
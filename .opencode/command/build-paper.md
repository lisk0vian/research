---
description: Build a paper to PDF and/or Word using its journal format. Verifies the environment first (warns what's missing), outputs to build/.
agent: build
---

Use the **paper-build** skill (`.agents/skills/paper-build/SKILL.md`) to render a
paper. Read that SKILL.md now and follow it.

## Arguments

The user invoked: `/build $ARGUMENTS`

Interpret positionally:

- **`$1`** = the paper **slug** (e.g. `c15-2026`) under `papers/`. If missing,
  list `papers/` and ask.
- **`$2`** = output format: `pdf`, `docx`, or `all`. **Default `all`** if omitted.

## What to do

1. Read `.agents/skills/paper-build/SKILL.md`.
2. Resolve `$1` (paper) and `$2` (format, default `all`).
3. Run the environment check FIRST:
   `python .agents/skills/paper-build/scripts/check_env.py --repo-root . --slug $1 --format $2`
   - If it exits non-zero (something required is missing), STOP and show the
     user exactly what to run (e.g. `quarto install tinytex`,
     `cd papers/$1/paper && quarto add <extension>`). Do NOT install it yourself.
4. If the environment is OK, read the journal's `quarto_format` from
   `templates/journals/<journal>/type.yaml` (the check prints it) and render from
   `papers/$1/paper`:
   - PDF: `quarto render main.qmd --to <quarto_format> --output-dir ../build`
   - DOCX: `quarto render main.qmd --to docx --output-dir ../build`
   Render only the requested format(s). Rename outputs to `<slug>.pdf` /
   `<slug>.docx` inside `build/`.
5. On render error, map the message to a cause using
   `.agents/skills/paper-build/references/common-errors.md`, report the failing
   line and the fix. Do not silently edit paper content to force a pass.
6. Report what was produced in `build/`, the journal format used, and remind the
   user: the PDF is versioned; intermediates and (by default) the DOCX are not.
---
name: paper-validate
description: >
  Validate the repository's paper structure against the rules in AGENTS.md. Use
  before opening a pull request, when a paper folder looks wrong or incomplete,
  when CI fails the validate workflow, or whenever the user asks "is the
  structure correct", "check the repo", or "why did validation fail". Runs
  `scripts/paper_validate.py` and explains each error.
---

# paper-validate

Run the structure contract over the repository. This is the same check CI runs
in `.github/workflows/validate.yml`, so passing locally means passing the PR
gate.

## Workflow

1. Run it:

   ```bash
   python scripts/paper_validate.py
   ```

   Add `--json` for a machine-readable report, `--quiet` to print only errors.

2. **Explain each `[ERROR]`** and point at the fix (missing directory, `paper`
   field not matching the folder, author id with no `authors/<id>.yaml`, journal
   not in `templates/journals/`, a banned `.xlsx` in `outputs/`, a tracked
   secret, a skill whose `SKILL.md` name does not match its folder).

3. Do **not** silence an error by editing the validator or weakening a rule;
   fix the structure. The rules live in `scripts/_structure.py`.

## What it checks

- Paper folder naming and required directories.
- `paper/manifest.yaml`, `paper/references.bib`, `paper/main.qmd`
  (or `MIGRATION_PENDING.txt`).
- Manifest fields: `paper` == folder, `journal` in catalog, authors with
  `id`/`role`/`order` and ids present in `authors/`.
- `main.qmd` front-matter has `title` and `format`.
- No spreadsheet artefacts under `paper/`, `outputs/`, `experiments/`.
- No tracked secrets/credentials.
- Every `.agents/skills/<name>/SKILL.md` declares `name: <name>`.

## What this skill does NOT do

- It does not fix the structure for you — report and let the user/or a follow-up
  decide, unless the user explicitly asks for the fix.
- It does not build (`paper-build`) or edit metadata (`paper-journal`).

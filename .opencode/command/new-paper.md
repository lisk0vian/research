---
description: Add a new paper to the repository (scaffold structure, wire journal + authors, optionally start from a Word/PDF draft).
agent: build
---

Use the **new-paper** skill (`.agents/skills/new-paper/SKILL.md`) to add a new
paper to this repository. Read that SKILL.md now and follow its workflow.

## Arguments

The user invoked: `/new-paper $ARGUMENTS`

Interpret the arguments positionally:

- **`$1`** = the paper **slug / internal code** (e.g. `c15-2026`). This is the
  folder name `papers/<slug>/`. Apply the slug rule from the skill's
  `references/naming.md` (lowercase an institutional code; otherwise expect a
  short kebab-case slug). If `$1` is missing, ask for it.

- **`$2`** = an **optional path to a starting draft** (`.docx` or `.pdf`),
  typically passed as `@path/to/file.docx`. If present:
    - Treat this as the "migrate" path in the skill (do NOT start from the blank
      template).
    - Copy the file into `papers/<slug>/legacy/` as part of scaffolding.
    - After the folder is scaffolded, hand off to the `paper-migrate` skill to
      produce `papers/<slug>/paper/main.qmd` from it. If `paper-migrate` does
      not exist yet, leave the `MIGRATION_PENDING.txt` marker the scaffold
      creates and tell the user migration is still pending.
    - If `$2` is missing, ask the user (single choice): start **empty** or
      **migrate** an existing draft.

## What to do

1. Read `.agents/skills/new-paper/SKILL.md` and its `references/` as needed.
2. Resolve `$1` (slug) and validate `papers/<slug>/` does not already exist.
   If it exists, STOP and offer a different slug.
3. Determine start mode from `$2` (migrate if a path was given, else ask).
4. Run the skill's interview for the remaining metadata — title, internal code,
   institution, funding, journal (from `templates/journals/`), and authors
   (read the `authors/` directory and offer existing coauthors; allow adding a
   new one).
5. Call `.agents/skills/new-paper/scripts/scaffold.py` with the gathered values.
6. If migrating, copy `$2` into `legacy/` and continue per the migrate path.
7. Finish by listing everything still pending (per the skill's final step).

Do not invent folder structure or file contents — always copy from the skill's
`assets/` templates.
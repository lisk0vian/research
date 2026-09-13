---
description: Set or change a paper's target journal — by catalog slug or by pasting the journal's link — and sync manifest, main.qmd, and the Quarto extension.
agent: build
---

Use the **set-journal** skill (`.agents/skills/set-journal/SKILL.md`) to set or
change the target journal for a paper. Read that SKILL.md now and follow it.

## Arguments

The user invoked: `/set-journal $ARGUMENTS`

Interpret positionally:

- **`$1`** = the paper **slug** (e.g. `c15-2026`) under `papers/`. If missing,
  list `papers/` and ask.
- **`$2`** = optional. Either:
    - a **journal slug** already in `templates/journals/` (use it directly), OR
    - a **URL** (starts with `http`) → add/update that journal from its link
      (scrape name/publisher/ISSN, deduce the Quarto extension from the
      publisher per `references/publisher-extensions.md`).
  If `$2` is missing, list catalog journals plus "Add a new journal by link"
  and ask; accept a pasted URL interactively.

## What to do

1. Read `.agents/skills/set-journal/SKILL.md`.
2. Resolve `$1` (paper); report its CURRENT journal from manifest.yaml.
3. Resolve the target:
   - URL → fetch it, extract metadata, derive a kebab-case journal slug. If that
     slug already exists in the catalog, ASK whether to update (re-scrape,
     `--force`) or keep it. Write via `scripts/add_journal_from_link.py`, then
     show the resulting type.yaml and confirm.
   - Catalog slug → use as-is.
4. Run `scripts/set_journal.py --repo-root . --slug $1 --journal <journal-slug>`
   to update manifest.yaml and rewrite the main.qmd format block.
5. Install the extension if present:
   `cd papers/$1/paper && quarto add <extension>` (skip if quarto unavailable,
   tell the user to run it locally).
6. Report old → new journal, whether it was added from a link, files changed,
   extension status, and new-journal requirements (from the journal's `notes:`).

Only the format block and the manifest journal field change on the paper. Never
touch title, authors, abstract, keywords, bibliography, or body.
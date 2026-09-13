---
name: set-journal
description: >
  Set or change the target journal for a paper and propagate the change
  everywhere it matters. Use whenever the user wants to choose a journal, change
  journals, re-target or resubmit a paper to a different venue, add a journal by
  its website link, or set up formatting for a specific journal. Reads
  templates/journals/ for existing venues, can add a NEW journal from just its
  URL (scraping name/publisher/ISSN and deducing the Quarto extension from the
  publisher), then updates the paper's manifest.yaml, rewrites the main.qmd
  front-matter, and installs the Quarto extension. Never invents journal
  metadata — it reads the catalog, scrapes the link, or asks.
---

# set-journal

Point a paper at a journal (or move it to a different one) and keep every
dependent file in sync. Changing journals touches three places; this skill does
all three so they never drift:

1. `papers/<slug>/paper/manifest.yaml` — the `journal` field (source of truth).
2. `papers/<slug>/paper/main.qmd` — the `format:` block.
3. `papers/<slug>/paper/_extensions/` — the Quarto extension, via `quarto add`.

New in this version: you can add a journal by **pasting its link**; the skill
scrapes the editorial metadata and deduces the Quarto extension from the
publisher.

## Core rule

**Journal metadata lives in `templates/journals/<slug>/type.yaml`, and that is
the single source.** The manifest references a journal by slug; the main.qmd
front-matter is filled FROM the journal's `type.yaml`. Never hardcode journal
values into a paper — always route through the catalog.

## Workflow

### 1. Identify the paper

Determine the `<slug>` under `papers/` (first command argument, else list
`papers/` and ask). Read its `manifest.yaml` and report the CURRENT journal
before changing anything.

### 2. Determine the target journal

The second argument may be either a **journal slug** already in the catalog OR a
**URL** (starts with http). Also accept a link interactively if none was given.

- **Journal slug in catalog** → read its `type.yaml`, go to step 5.
- **URL given** → go to step 3 (add/update from link).
- **Nothing given** → list journals under `templates/journals/` as options, plus
  "Add a new journal by link". If the user picks that, ask for the URL.

### 3. Add or update a journal from a link

1. **Fetch the link** with your web tools. From the page + domain, extract:
   - `journal` (full name)
   - `publisher` (or infer from the domain — see
     `references/publisher-extensions.md`)
   - `issn`
   - `cite_style` IF the Guide for Authors states one (else leave empty; the
     script fills a sensible default per publisher)
   - `notes` — anything submission-relevant: APC, whether highlights /
     graphical abstract are required, single vs double column, special reference
     style.
2. **Derive the slug** for the journal folder: kebab-case of the journal name
   (e.g. `machine-learning-with-applications`). Keep it stable.
3. **Check if it already exists** in `templates/journals/<slug>/`. If it does,
   ASK the user whether to update it (re-scrape) or keep the current file. Only
   pass `--force` to the script if the user says update.
4. Write `meta.json` with the extracted fields and run:
   ```
   python .agents/skills/set-journal/scripts/add_journal_from_link.py \
       --repo-root . --slug <journal-slug> --meta meta.json [--force]
   ```
   The script maps publisher → Quarto extension + quarto_format + default
   cite_style (per `references/publisher-extensions.md`) and writes
   `type.yaml`.
5. Show the resulting `type.yaml` to the user and confirm before continuing.

### 4. (deduction detail — publisher → extension)

The extension is NEVER on the journal's website. It is deduced from the
publisher via `references/publisher-extensions.md`:
Elsevier→`quarto-journals/elsevier`, IEEE→`quarto-journals/ieee`,
MDPI→`quarto-journals/mdpi`, etc. Publishers without an official extension
(Springer, Frontiers, Wiley, Taylor & Francis) get an empty extension and a
generic `pdf`/`docx` format, with a note that the final PDF needs a manual
template.

### 5. Update the manifest

Set `journal: <journal-slug>` in `papers/<slug>/paper/manifest.yaml`. Leave
everything else untouched.

### 6. Rewrite the main.qmd front-matter

Run:
```
python .agents/skills/set-journal/scripts/set_journal.py \
    --repo-root . --slug <paper-slug> --journal <journal-slug>
```
This rewrites ONLY the `format:` block from the journal's `type.yaml`. Title,
author, abstract, keywords, bibliography and body are left exactly as-is. If the
journal has no extension, it writes generic `pdf` + `docx` with a note.

### 7. Install the Quarto extension

If `type.yaml` has an `extension:`, run in the paper directory:
```
cd papers/<paper-slug>/paper && quarto add <extension>
```
`_extensions/` is gitignored (regenerated); CI runs the same `quarto add` before
rendering. If `quarto` is unavailable here, skip and tell the user to run it
locally.

### 8. Report

Summarize: old journal → new journal, whether the journal was added/updated from
a link, which files changed, extension status, and any new-journal requirements
to watch (from `notes:` — e.g. graphical abstract, highlights, cite-style).

## What this skill does NOT do

- It does not render (that's `paper-build`).
- It does not rewrite paper content or re-number citations.
- It does not migrate a docx (that's `paper-migrate`).
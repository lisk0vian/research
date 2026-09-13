---
name: new-paper
description: >
  Add a new research paper to this repository with the correct, consistent
  folder structure and seed files. Use this whenever the user wants to start a
  new paper, add a paper, begin a manuscript, or set up a paper's directory —
  including when they already have a Word/PDF draft to migrate. Interviews the
  user for the needed metadata (title, journal, authors, funding), reads the
  authors/ catalog to reuse existing coauthors, wires up the journal template,
  and never invents the folder layout — it copies from assets/ templates.
---

# new-paper

Create a new `papers/<slug>/` from the repository's seed templates. The goal is
**zero structural drift**: every paper is born with the same layout and the same
front-matter conventions, so the rest of the pipeline (build, refs, reviewers)
always finds what it expects.

## Core rule

**Never generate structure from memory.** All seed files live in `assets/` as
`*.template` files with `{{PLACEHOLDER}}` markers. Copy the template, then
substitute placeholders with values gathered from the user or read from the
repo. If a file has a fixed shape, its model is in `assets/` — use it.

## Workflow

Follow these steps in order. Ask questions using the interactive question tool
(tappable options) whenever possible, not free-form prose, so the user can
answer fast on mobile.

### 1. Resolve the slug

The slug is the folder name `papers/<slug>/`. Ask the user for it, then apply
the naming rule (see `references/naming.md`):

- If the paper has an institutional/internal code (e.g. `C15-2026`) → use it
  lowercased as the slug (`c15-2026`).
- If not → a short 2-4 word kebab-case descriptive slug (`carrion-clustering`),
  never the full title.

**Validate**: if `papers/<slug>/` already exists, STOP and tell the user — do
not overwrite existing work. Offer a different slug.

### 2. Ask how the manuscript starts

Ask the user (single choice):

- **Empty** — start `main.qmd` from the blank template to write from scratch.
- **Migrate** — the user has an existing `.docx` (or `.docx` + `.pdf`) to
  convert. In this case, hand off to the `paper-migrate` skill for the actual
  conversion AFTER the folder is scaffolded, then place its output in
  `paper/main.qmd`. Do not re-implement migration here.

### 3. Gather metadata (interview)

Collect these values. Ask them one at a time, preferring tappable options:

| Field | How to obtain |
|---|---|
| Title | Ask the user (free text). May be left as `TODO` — see step 7. |
| Internal code | Ask; empty string if none. |
| Institution | Ask, or default to the repo's usual (`SENATI`) offered as an option. |
| Funding statement | Ask; may be `TODO`. |
| Journal | See step 4. |
| Authors | See step 5. |

### 4. Choose the journal template

- List the available journals by reading the directory names under
  `templates/journals/` and offer them as tappable options, plus an option
  "Not decided yet".
- If the user picks one, read that journal's `type.yaml` to pull
  `journal_name`, `quarto_format`, `cite_style`, `publisher`, `format`, `issn`.
  These fill the front-matter placeholders.
- If "Not decided yet", set the format block to a generic `pdf` + `docx` and
  mark the journal as a pending item (step 7). The paper can be re-targeted
  later without rewriting content.

### 5. Choose authors from the catalog

**Always read the `authors/` directory first** and list the existing authors
(`authors/*.yaml` → show each `name` and `id`) as multi-select options. Then:

- Let the user select which existing authors are on this paper.
- Offer an "Add a new author" option. If chosen, collect name, affiliation,
  email, ORCID, and create `authors/<new-id>.yaml` from
  `assets/author.yaml.template`. Only then add them to the paper.
- For each selected author, ask their **role** (corresponding / author /
  advisor) and **order** for THIS paper. Role and order live in the paper's
  `manifest.yaml`, never in the shared `authors/<id>.yaml`.

Do not duplicate author details into the manifest — reference by `id` only.

### 6. Scaffold the folder

Run `scripts/scaffold.py` (or perform the equivalent copy+substitute) to:

1. Create the full folder tree (see `references/structure.md`), with
   `.gitkeep` in empty dirs.
2. Copy every `assets/*.template` to its destination, substituting all
   `{{PLACEHOLDER}}` values gathered above. Placeholder reference is in
   `assets/README.md`.
3. If a journal was chosen, record the journal slug in `manifest.yaml`. (The
   actual Quarto extension is installed later by `paper-build` via
   `quarto add`, so `_extensions/` is not created here.)
4. If migrating, leave `main.qmd` as the migrated file instead of the blank
   template.

### 7. Report pending items

At the very end, ask nothing more — instead **list everything left pending** so
the user knows what to finish before the paper is submission-ready. Scan for:

- Any field left as `TODO` (title, abstract, funding).
- Journal marked "Not decided yet".
- `references.bib` still empty.
- `main.qmd` body still on placeholder sections (if started empty).
- Whether `paper-migrate` still needs to run (if migrate was chosen).

Present this as a short checklist the user can act on next. Do not mark the
paper "done" — surface the gaps honestly.

## What this skill does NOT do

- It does not render PDFs/Word — that's `paper-build`.
- It does not convert `.docx` — that's `paper-migrate`.
- It does not validate citations — that's `paper-refs`.
- It does not write paper content or invent results.
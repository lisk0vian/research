---
name: paper-new
description: >
  Start a new research paper in this repository with the standard folder
  structure. Use whenever the user wants to start a new paper, add a paper,
  begin a manuscript, or set up a paper directory — including when they already
  have a Word/PDF draft to migrate. Interviews the user for title, journal,
  authors and funding, then runs `scripts/paper_new.py`. Never builds the folder
  structure by hand: the script and templates/paper/ are the source of truth.
---

# paper-new

Scaffold `papers/<slug>/` with the repository's standard layout. The layout,
naming rules and manifest contract are defined in `AGENTS.md`; the mechanics
live in `scripts/paper_new.py`. **Do not create folders or seed files by hand.**

## Workflow

1. **Resolve the slug** (`papers/<slug>/`). Rule: institutional code lowercased
   (`C22-2026` → `c22-2026`), otherwise a short kebab-case topic+method slug.
   Never the full title. If `papers/<slug>/` exists, stop and ask for another.

2. **Ask how the manuscript starts**:
   - *Empty* — a blank `main.qmd` to write from scratch.
   - *Migrate* — an existing `.docx`. Scaffold with `--migrate` (leaves
     `paper/MIGRATION_PENDING.txt`), then run the migration step to produce
     `paper/main.qmd`.

3. **Interview for metadata**: title, internal code, institution (default
   `SENATI`), funding statement, journal, keywords.

4. **Journal** — list folders under `templates/journals/` and let the user pick,
   or choose "not decided yet" (omit `--journal`; the script falls back to a
   generic pdf/docx format).

5. **Authors** — read `authors/*.yaml`, let the user select who is on this paper
   and give each a `role` and `order`. New coauthors: create
   `authors/<id>.yaml` from `templates/paper/author.yaml.template` first.

6. **Run the script** (one command, reproducible):

   ```bash
   python scripts/paper_new.py --slug <slug> --title "<title>" \
       --internal-code <CODE> --institution SENATI --funding "<statement>" \
       --journal <journal-slug> \
       --author id:role:order --author id:role:order \
       --keyword "..." --keyword "..."
   ```

7. **Report pending items** at the end (title/funding left as TODO, no journal,
   empty `references.bib`, body not written, migration still pending). Never
   mark the paper "done".

## What this skill does NOT do

- It does not render PDF/Word — that is `paper-build`.
- It does not convert `.docx` — that is the migration step.
- It does not choose/validate citations — that is `paper-search`.
- It does not write paper content or invent results.

Reference detail: `references/naming.md`, `references/structure.md`.

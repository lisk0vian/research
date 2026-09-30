---
name: paper-journal
description: >
  Set or change the target journal for a paper and propagate the change
  everywhere it matters. Use whenever the user wants to choose a journal, change
  journals, re-target or resubmit a paper to a different venue, add a journal
  from its website link, or set up formatting for a specific journal. Runs
  `scripts/paper_journal.py`, which updates the manifest, rewrites the main.qmd
  format block from templates/journals/<slug>/type.yaml, and can add a new
  journal. Never invents journal metadata — it reads the catalog or asks.
---

# paper-journal

Point a paper at a journal (or move it) and keep every dependent file in sync.
Journal metadata lives ONLY in `templates/journals/<slug>/type.yaml`; the script
routes everything through it. Never hardcode journal values into a paper.

Changing journals touches three places, and the script does all three:

1. `papers/<slug>/paper/manifest.yaml` — the `journal` field.
2. `papers/<slug>/paper/main.qmd` — the `format:` block.
3. `papers/<slug>/paper/_extensions/` — the Quarto extension, via `quarto add`.

## Retarget a paper

```bash
python scripts/paper_journal.py --slug <paper-slug> --journal <journal-slug>
```

Then, if it prints an extension: `cd papers/<slug>/paper && quarto add <extension>`.

## Add a journal from a link

1. **You fetch the page** (the script is network-free). Extract `journal`,
   `publisher`, `issn`, `url`, optional `cite_style`, and `notes` (APC,
   highlights, graphical abstract, columns, reference style).
2. Derive a stable kebab-case slug (e.g. `machine-learning-with-applications`).
3. Write `meta.json` and run:

   ```bash
   python scripts/paper_journal.py --add-journal <journal-slug> --meta meta.json [--force]
   ```

   The script maps publisher → Quarto extension + `quarto_format` + default
   `cite_style` (the table in the script; detail in
   `references/publisher-extensions.md`). Springer/Frontiers/Wiley/T&F have no
   official extension → generic pdf/docx and a manual-template note.
4. Show the resulting `type.yaml` and confirm before retargeting the paper.

## What this skill does NOT do

- Render (`paper-build`).
- Rewrite paper content or re-number citations.
- Migrate a `.docx`.

# Paper folder structure

Every `papers/<slug>/` is created with exactly this tree. Empty directories get
a `.gitkeep` so Git tracks them.

```
papers/<slug>/
├── paper/
│   ├── main.qmd               # from assets/main.qmd.template (or migrated)
│   ├── manifest.yaml          # from assets/manifest.yaml.template
│   ├── references.bib         # from assets/references.bib.template (empty)
│   ├── references-source.bib  # raw export from the reference manager (biblatex)
│   ├── media/                 # figures from a migrated Word doc live here
│   └── _extensions/           # NOT created here; `quarto add` makes it (gitignored)
│
├── legacy/                    # original .docx/.pdf when migrating
│
├── data/
│   ├── raw/
│   └── processed/
│
├── experiments/               # figures for NEW papers are generated here
├── notebooks/
│
├── reviews/
│   └── round-1/
│       ├── comments.yaml      # from assets/comments.yaml.template
│       ├── responses.yaml     # from assets/responses.yaml.template
│       └── ai-review.yaml     # from assets/ai-review.yaml.template
│
└── build/                     # gitignored except the final PDF
```

## Figure origin rule

- **Migrated paper**: figures already rendered inside the Word doc go to
  `paper/media/`.
- **New paper**: figures are produced by code under `experiments/exp-XX/` and
  the `.qmd` references them from there. Do not force migrated figures into
  `experiments/`.

## Bib rule

- `references-source.bib` = raw export from Zotero/Mendeley (biblatex fields:
  `journaltitle`, `date`).
- `references.bib` = converted to classic BibTeX (`journal`, `year`) — this is
  what Quarto/elsarticle actually reads. The `paper-refs` / conversion script
  regenerates it from the source, so manual fixes are never lost on re-export.
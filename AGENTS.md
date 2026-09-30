# AGENTS.md — Research Repository

Single source of truth for how this repository is laid out and how a paper is
created, built and validated. Everything here is enforced by
`scripts/paper_validate.py` in CI (`.github/workflows/validate.yml`), so a pull
request that breaks a rule fails the check.

Language: English everywhere in the repository (docs, code, commit messages).

---

## 1. Repository layout

```
research/
├── papers/                 # active papers, one standardized folder each
├── authors/                # shared author records (one YAML per person)
├── templates/
│   ├── paper/              # seed files used by scripts/paper_new.py
│   └── journals/<slug>/    # editorial metadata (type.yaml) per journal
├── scripts/                # the reproducible automation (plain Python)
├── tests/                  # structure + script tests
├── AGENTS.md               # this file
├── README.md               # project index
└── <LEGACY PROJECTS>/      # pre-standardization work (see section 7)
```

## 2. Paper folder structure

Every paper lives in `papers/<slug>/` and is born with **exactly** this tree:

```
papers/<slug>/
├── paper/
│   ├── main.qmd            # single source of the manuscript
│   ├── manifest.yaml       # paper metadata: title, journal, authors, claims, figures
│   ├── references.bib      # classic BibTeX (what Quarto reads)
│   ├── media/              # figures (migrated PNGs or generated here)
│   └── _extensions/        # Quarto extension (regenerated; gitignored)
├── data/                   # raw + processed (large/sensitive files stay out of git)
├── experiments/            # pipeline code that produces numbers and figures
├── notebooks/              # exploratory notebooks
├── outputs/                # machine-readable results (CSV/JSON/PNG/PKL)
├── reviews/round-N/        # comments.yaml, responses.yaml, ai-review.yaml
├── build/                  # rendered output (only the final PDF is committed)
└── legacy/                 # original .docx/.pdf when migrating an existing paper
```

Rules:

- **`main.qmd` is the only manuscript source.** `.tex`, `.docx`, `.pdf` are
  derived; never edit a derivative and never write paper content in
  `experiments/`.
- **Numbers live in `outputs/` as CSV/JSON.** No `.xlsx`/`.xls` may be an
  artefact of record under `paper/`, `outputs/` or `experiments/`. Every figure
  or table in the manuscript must trace back to a file in `outputs/`.
- **Metadata is referenced, never duplicated.** Authors live in
  `authors/<id>.yaml`; the paper's `manifest.yaml` references them by `id` plus
  per-paper `role`/`order`. Journals live in `templates/journals/<slug>/type.yaml`.

### Folder naming

- Institutional code exists → lowercase it: `C15-2026` → `papers/c15-2026/`.
- No code → short kebab-case topic+method slug: `carrion-clustering`.
- Lowercase letters, digits and hyphens only. No spaces, underscores or accents.

## 3. Workflow and commands

The scripts are the reproducible implementation; the skills are thin wrappers
that know *when* to call them and interview you for the arguments.

| Step | Command |
|---|---|
| Create a paper | `python scripts/paper_new.py --slug <slug> --journal <journal> --author id:role:order ...` |
| Change journal | `python scripts/paper_journal.py --slug <slug> --journal <journal>` |
| Add a journal from a link | `python scripts/paper_journal.py --add-journal <slug> --meta meta.json` |
| Build PDF/DOCX | `python scripts/paper_build.py --slug <slug> --format all` |
| Check environment only | `python scripts/paper_build.py --slug <slug> --check-only` |
| Validate the repo | `python scripts/paper_validate.py` |
| Verify Claude skill links | `python scripts/link_skills.py --check` |
| Link skills for Claude | `python scripts/link_skills.py` |
| Run tests | `pytest -q` |

A new paper typically follows: `paper_new.py` → literature search
(`paper-search`) → pipeline in `experiments/` writing to `outputs/` →
`paper_build.py` → `reviews/round-N/`.

## 4. Manifest contract

`paper/manifest.yaml` must contain at least:

```yaml
paper: <slug>            # must equal the folder name
journal: <journal-slug>  # must exist in templates/journals/
authors:                 # at least one; id must exist in authors/
  - id: <author-id>
    role: <corresponding | author | advisor | ...>
    order: <int>
```

Optional but encouraged: `title`, `internal_code`, `institution`, `funding`,
`claims[]` (each number anchored to its `outputs/` source), `figures[]`.

## 5. Skills

Canonical skills live in `.agents/skills/` (committed). Agent paths:

- **OpenCode** reads `.agents/skills/` directly — no setup needed.
- **Claude Code** reads only `.claude/skills/`, so each skill there is a link to
  its `.agents/skills/` twin (a junction on Windows, a relative symlink
  elsewhere). `.claude/settings.json` carries a `SessionStart` hook that runs
  `scripts/link_skills.py`, so the links are created automatically on the first
  session. Verify or recreate them by hand if needed:

  ```bash
  python scripts/link_skills.py --check   # exit 1 if missing/stale
  python scripts/link_skills.py           # create/refresh
  ```

  The links are machine-local and gitignored. `paper_validate.py` warns when
  they are missing or stale (skipped on CI).

Registry:

| Skill | Purpose |
|---|---|
| `paper-new` | Scaffold a paper via `scripts/paper_new.py` |
| `paper-build` | Render PDF/DOCX via `scripts/paper_build.py` |
| `paper-journal` | Set/change the journal via `scripts/paper_journal.py` |
| `paper-validate` | Run `scripts/paper_validate.py` |
| `paper-search` | Literature search, citation verification, BibTeX |
| `paper-humanize` | Rewrite AI-drafted prose into natural academic writing |
| `util-docx` | Create/edit Word (`.docx`) files |
| `util-office-to-md` | Convert Office files to Markdown |
| `util-search` | Content search (prefer over `grep`/`rg`) |
| `grilling` | Relentless design interview before committing to a plan |

## 6. Pull request validation

`.github/workflows/validate.yml` runs `scripts/paper_validate.py` and `pytest`
on every PR that touches `papers/`, `authors/`, `templates/`, `scripts/`,
`tests/` or `.agents/skills/`. The validator checks:

- paper folder naming and required directories;
- presence and shape of `manifest.yaml`, `references.bib`, `main.qmd`;
- journal and author references resolve to the shared catalogs;
- no spreadsheet artefacts under `paper/`, `outputs/`, `experiments/`;
- no secrets/credentials tracked by git;
- every skill folder has a `SKILL.md` whose `name` matches the folder.

Run it locally before pushing: `python scripts/paper_validate.py`.

## 7. Legacy projects (pre-standardization)

These folders predate the `papers/` standard and are **frozen**: do not
restructure them, and do not treat them as the reference layout.

| Folder | Notes |
|---|---|
| `C20-202610-temperature/` | Notebook-only pipeline; data `data/EstacionEMA_2018_2025.csv`. |
| `C25-202620-violence/` | Early stage. |
| `C26-202609-missingpersons/` | Information Sciences submission; `src/reniped/`, `run_all.py`. |
| `C20-2026-Reproducible GeoAi/` | Early stage. |

New work always goes under `papers/` with the structure in section 2.

## 8. How to investigate an existing paper

1. Read `papers/<slug>/paper/manifest.yaml` (metadata + claims/figures).
2. Read `papers/<slug>/outputs/manifest_index.json` (the numbers's source).
3. Read `papers/<slug>/paper/main.qmd` for the narrative.
4. `papers/<slug>/reviews/round-N/` for reviewer comments and responses.

## 9. Licensing

- Code: MIT (`./LICENSE`).
- Research content: CC BY 4.0 (`./LICENSE-CONTENT`).

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
├── manifest.yaml           # paper metadata: title, journal, authors, claims, figures
├── paper/                  # sources only — no build artefacts ever live here
│   ├── main.qmd            # single source of the manuscript
│   ├── references.bib      # classic BibTeX (what Quarto reads)
│   └── media/              # figures (migrated PNGs or generated here)
├── data/                   # raw + processed (large/sensitive files stay out of git)
├── experiments/            # pipeline code that produces numbers and figures
├── notebooks/              # exploratory notebooks
├── outputs/                # machine-readable results (CSV/JSON/PNG/PKL)
├── tests/                  # optional: per-paper suite (see section 6)
├── reviews/round-N/        # comments.yaml, responses.yaml, ai-review.yaml
├── build/                  # <slug>.pdf/.docx/-latex.zip + render/ scratch (only the PDF committed)
└── legacy/                 # original .docx/.pdf when migrating an existing paper
```

Rules:

- **`main.qmd` is the only manuscript source.** `.tex`, `.docx`, `.pdf` are
  derived; never edit a derivative and never write paper content in
  `experiments/`.
- **`paper/` holds sources only.** Every build copies them into
  `build/render/` (extension sync, flattened format-resources, `.tex`/`.aux`),
  so the tracked folder never fills with artefacts.
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
| Build PDF, DOCX and LaTeX zip | `python scripts/paper_build.py --slug <slug> --format all` |
| Check environment only | `python scripts/paper_build.py --slug <slug> --check-only` |
| Measure DOCX/LaTeX-zip vs PDF parity | `python scripts/paper_parity.py --slug <slug>` (Word, else LibreOffice) |
| Validate the repo | `python scripts/paper_validate.py` |
| Sparse clone one paper (Colab) | `python scripts/paper_sparse_clone.py --slug <slug> --dest <dir>` |
| Sync a paper's Drive folder (in place) | `python scripts/paper_drive_sync.py --slug <slug>` |
| Check CAS sample fidelity | `python scripts/cas_fidelity.py` (add `--docx` for the Word suite) |
| Verify Claude skill links | `python scripts/link_skills.py --check` |
| Link skills for Claude | `python scripts/link_skills.py` |
| Generate `opencode.jsonc` (MCP) | `python scripts/setup_mcp.py` |
| Run tests | `pytest -q` |

A new paper typically follows: `paper_new.py` → literature search
(`paper-search`) → pipeline in `experiments/` writing to `outputs/` →
`paper_build.py` → `reviews/round-N/`.

### Drive sync for Colab notebooks — always in place

A paper whose code runs on Colab keeps its notebook and `experiments/` on Drive.
**Always update them with `fileId`, never recreate them with
`parentFolderId`.** A new Drive file gets a new id, which produces a new Colab
URL and a new runtime session, and accounts cap concurrent sessions. Two files
with the same name in `Drive/<folder>/code/` are worse: the notebook's
`copytree` then picks one arbitrarily, so the stub can silently shadow the
implementation.

`scripts/paper_drive_sync.py` enforces this. Drive file ids live in
`papers/<slug>/.drive_ids.json` (gitignored, see `.drive_ids.json.example`),
never hardcoded in code or committed. Resolve a new id once with the `gdrive`
MCP, record it with `--record`, and from then on every sync is in place.

## 4. Manifest contract

`papers/<slug>/manifest.yaml` must contain at least:

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

- **OpenCode** reads `.agents/skills/` directly — no setup needed. Its MCP
  servers do need one step, though: `opencode.jsonc` is **generated**, not
  committed, because it holds an absolute path to the MCP server. Run this once
  after cloning:

  ```bash
  python scripts/setup_mcp.py            # writes opencode.jsonc
  python scripts/setup_mcp.py --check    # exit 1 if missing/stale
  ```

  `opencode.jsonc.example` is the committed template; edit it to change which
  servers are configured, then re-run the script. MCP servers added by hand to
  `opencode.jsonc` are preserved across runs.

  Do **not** hand-write a relative `cwd` there. OpenCode resolves a relative MCP
  `cwd` against the *session* directory, not the config file or the git root,
  so it silently breaks whenever a session is rooted anywhere else
  (`papers/<slug>/`, a legacy folder, a subagent):

  ```
  NotFound: FileSystem.access (D:\...\papers\c20-2026\.agents\skills\...)
  ```

  The academic-search server needs no `cwd` at all — it imports `sources`/
  `utils` as top-level modules and loads `config.toml` through `Path(__file__)`,
  both independent of the working directory. Hence the generated absolute path.
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

A paper may also carry an optional `tests/` folder holding a synthetic-fixture
suite (tests never read `data/` or `outputs/` for real). `pytest` only collects
what `pytest.ini` lists in `testpaths`, so a new folder must be added there or
it is never collected at all. Two suites are marked `slow` and the gate runs
`pytest -m "not slow"`: the per-paper suites under `papers/` (`papers/conftest.py`)
and `tests/test_cas_fidelity.py`, which compiles LaTeX against a committed
reference (`tests/conftest.py`). Measured: the gate runs 51 tests in ~5 s,
plain `pytest -q` runs all 169 in ~66 s. Everything marked `slow` must still
pass locally and before a release. The suite must not import the paper's
`requirements-experiments.txt` environment: `pytest` runs the repository's own
dependencies only.

## 7. Legacy projects (pre-standardization)

These folders predate the `papers/` standard and are **frozen**: do not
restructure them, and do not treat them as the reference layout.

| Folder | Notes |
|---|---|
| `C20-202610-temperature/` | Notebook-only pipeline; data `data/EstacionEMA_2018_2025.csv`. |
| `C25-202620-violence/` | Early stage. |
| `C20-2026-Reproducible GeoAi/` | Early stage. |

New work always goes under `papers/` with the structure in section 2.

## 8. How to investigate an existing paper

1. Read `papers/<slug>/manifest.yaml` (metadata + claims/figures).
2. Read `papers/<slug>/outputs/manifest_index.json` (the numbers's source).
3. Read `papers/<slug>/paper/main.qmd` for the narrative.
4. `papers/<slug>/reviews/round-N/` for reviewer comments and responses.

## 9. Licensing

- Code: MIT (`./LICENSE`).
- Research content: CC BY 4.0 (`./LICENSE-CONTENT`).

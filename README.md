# Research

Repository for organizing and documenting ongoing and completed research
projects: source code, data, manuscripts and submission materials.

Each active paper lives under [`papers/`](./papers/) with a standardized layout
so the tooling, the build and the review process all find what they expect. The
rules are enforced in CI (see [`AGENTS.md`](./AGENTS.md)).

## Status

- `Planning` — proposed or being prepared.
- `In Progress` — currently being developed.
- `Revision` — being corrected after reviewer feedback.
- `Resubmitted` — revised and resubmitted, awaiting response.
- `Under Review` — submitted and under review.
- `Accepted` — accepted for publication.
- `Published` — officially published.
- `Completed` — finished (may be unpublished).

## Research projects

### Active papers

| Code | Title | Journal | Status | Folder |
|---|---|---|---|---|
| `C15-2026` | A Reproducible Methodological Framework for Prosecutorial Congestion Risk Prediction | Machine Learning with Applications | `Revision` | [`papers/c15-2026/`](./papers/c15-2026/) |
| `C21-2026` | Early Prediction of Low Birth Weight in a National Peruvian Cohort | Discover Artificial Intelligence | `Revision` | [`papers/c21-2026/`](./papers/c21-2026/) |

### Legacy projects (pre-standardization)

| Code | Title | Status | Folder |
|---|---|---|---|
| `C20-2026` | Subseasonal Temperature Forecasting in Andean Stations | `In Progress` | [`C20-202610-temperature/`](./C20-202610-temperature/) |
| `C25-2026` | Violence analysis | `In Progress` | [`C25-202620-violence/`](./C25-202620-violence/) |
| `C26-2026` | Explainable Spatiotemporal Analysis of National Missing Persons Records | `In Progress` | [`C26-202609-missingpersons/`](./C26-202609-missingpersons/) |
| `C20-GeoAI` | Reproducible GeoAI | `In Progress` | [`C20-2026-Reproducible GeoAi/`](./C20-2026-Reproducible%20GeoAi/) |

## Structure of an active paper

```
papers/<slug>/
├── paper/       main.qmd (source), manifest.yaml, references.bib, media/
├── data/        raw + processed data (large files stay out of git)
├── experiments/ pipeline code that produces the numbers
├── notebooks/   exploratory notebooks
├── outputs/     machine-readable results (CSV/JSON/PNG/PKL)
├── reviews/     round-N/ with comments, responses and ai-review
├── build/       rendered PDF (only the final PDF is committed)
└── legacy/      original .docx/.pdf when migrating
```

## Quick start

```bash
# Create a new paper ("paper-new" skill can guide you)
python scripts/paper_new.py --slug c22-2026 --title "My paper" \
    --journal machine-learning-with-applications \
    --author moises:corresponding:1 --author jeremi:author:2

# Build PDF and Word
python scripts/paper_build.py --slug c22-2026 --format all

# Validate the repository structure (also runs in CI on every PR)
python scripts/paper_validate.py

# Claude Code: link the shared skills into .claude/skills (OpenCode needs no
# setup: it reads .agents/skills directly). A SessionStart hook normally does
# this for you; run it once by hand if you prefer.
python scripts/link_skills.py
```

## Contributing

Opening a pull request that touches `papers/`, `authors/`, `templates/`,
`scripts/`, `tests/` or `.agents/skills/` runs the validation workflow. Make it
pass locally first:

```bash
pip install -r requirements-dev.txt
python scripts/paper_validate.py && pytest -q
```

## License

- **Code** — [MIT](./LICENSE).
- **Research content** — [CC BY 4.0](./LICENSE-CONTENT).
- Third-party datasets, libraries and publications keep their own licenses.

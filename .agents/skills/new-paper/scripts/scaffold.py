#!/usr/bin/env python3
"""
scaffold.py — create papers/<slug>/ from the new-paper skill's asset templates.

The agent gathers values (via the interview in SKILL.md) and passes them here as
a JSON file. This script does the MECHANICAL part only: make the folder tree,
copy each assets/*.template to its destination, and substitute {{PLACEHOLDER}}.
It does not decide anything — no author picking, no journal logic. That is the
agent's job before calling this.

Usage:
    python scaffold.py --repo-root /path/to/research-hub --values values.json

values.json shape (all strings unless noted):
{
  "slug": "c15-2026",
  "title": "A Reproducible Framework ...",
  "internal_code": "C15-2026",
  "institution": "SENATI",
  "funding": "This work was funded by SENATI, Peru (Project C15-2026).",
  "journal_slug": "machine-learning-with-applications",   # "" if undecided
  "journal_name": "Machine Learning with Applications",   # "" if undecided
  "quarto_format": "elsevier-pdf",                        # "pdf" if undecided
  "cite_style": "number",
  "abstract": "TODO",
  "keywords": ["machine learning", "prosecutorial analytics"],
  "authors_qmd_block": "  - name: \"...\"\n    orcid: \"...\"\n    ...",
  "authors_manifest_block": "  - id: moises\n    role: corresponding\n    order: 1",
  "round": "1",
  "migrate": false
}
"""

import argparse
import json
import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"

EMPTY_DIRS = [
    "legacy",
    "data/raw",
    "data/processed",
    "experiments",
    "notebooks",
    "build",
]


def render(template_name: str, values: dict) -> str:
    text = (ASSETS / template_name).read_text(encoding="utf-8")
    # Block placeholders (multi-line) first
    text = text.replace("{{AUTHORS_BLOCK}}", values.get("authors_qmd_block", ""))
    text = text.replace(
        "{{AUTHORS_MANIFEST_BLOCK}}", values.get("authors_manifest_block", "")
    )
    kw = values.get("keywords", [])
    kw_block = "\n".join(f"  - {k}" for k in kw) if kw else "  - TODO"
    text = text.replace("{{KEYWORDS_BLOCK}}", kw_block)
    # Scalar placeholders
    scalars = {
        "SLUG": values.get("slug", ""),
        "TITLE": values.get("title", "TODO"),
        "INTERNAL_CODE": values.get("internal_code", ""),
        "INSTITUTION": values.get("institution", ""),
        "FUNDING": values.get("funding", "TODO"),
        "JOURNAL_SLUG": values.get("journal_slug", ""),
        "JOURNAL_NAME": values.get("journal_name", ""),
        "QUARTO_FORMAT": values.get("quarto_format", "pdf"),
        "CITE_STYLE": values.get("cite_style", "number"),
        "ABSTRACT": values.get("abstract", "TODO"),
        "ROUND": str(values.get("round", "1")),
    }
    for key, val in scalars.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  created {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--values", required=True)
    args = ap.parse_args()

    values = json.loads(Path(args.values).read_text(encoding="utf-8"))
    slug = values["slug"]
    repo = Path(args.repo_root)
    paper_root = repo / "papers" / slug

    if paper_root.exists():
        sys.exit(f"ERROR: {paper_root} already exists. Choose a different slug.")

    print(f"Scaffolding {paper_root} ...")

    # 1. empty dirs with .gitkeep
    for d in EMPTY_DIRS:
        keep = paper_root / d / ".gitkeep"
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_text("", encoding="utf-8")

    # 2. seed files
    if not values.get("migrate", False):
        write(paper_root / "paper" / "main.qmd", render("main.qmd.template", values))
    else:
        # migration handled by paper-migrate skill; leave a marker
        write(
            paper_root / "paper" / "MIGRATION_PENDING.txt",
            "Run the paper-migrate skill to produce paper/main.qmd from legacy/.\n",
        )

    write(paper_root / "paper" / "manifest.yaml", render("manifest.yaml.template", values))
    write(paper_root / "paper" / "references.bib", render("references.bib.template", values))
    (paper_root / "paper" / "media").mkdir(parents=True, exist_ok=True)
    (paper_root / "paper" / "media" / ".gitkeep").write_text("", encoding="utf-8")

    round_dir = paper_root / "reviews" / f"round-{values.get('round', '1')}"
    for f in ("comments.yaml", "responses.yaml", "ai-review.yaml"):
        write(round_dir / f, render(f + ".template", values))

    print("Done.")


if __name__ == "__main__":
    main()

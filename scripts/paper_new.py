#!/usr/bin/env python3
"""paper_new.py — scaffold papers/<slug>/ from templates/paper/.

Mechanical only: create the folder tree and render the seed files. It makes no
decisions. The `paper-new` skill wrapper interviews the user and passes explicit
flags here, so the same command reproduces the same folder every time.

Usage:
    python scripts/paper_new.py --slug c22-2026 --title "My paper" \
        --internal-code C22-2026 --journal machine-learning-with-applications \
        --author moises:corresponding:1 --author jeremi:author:2

    # migrating an existing .docx (no main.qmd, marker left instead):
    python scripts/paper_new.py --slug c21-2026 --migrate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402
from _structure import (  # noqa: E402
    MIGRATION_MARKER,
    PAPER_DIRS,
    REVIEW_FILES,
    SLUG_PATTERN,
    format_block_from_type,
)

TEMPLATES_SUBDIR = Path("templates") / "paper"


def render(template: str, values: dict) -> str:
    text = template
    # Multi-line blocks first.
    text = text.replace("{{AUTHORS_BLOCK}}", values.get("authors_qmd_block", ""))
    text = text.replace("{{AUTHORS_MANIFEST_BLOCK}}", values.get("authors_manifest_block", ""))
    keywords = values.get("keywords") or []
    kw_block = "\n".join(f"  - {k}" for k in keywords) if keywords else "  - TODO"
    text = text.replace("{{KEYWORDS_BLOCK}}", kw_block)
    # Scalars.
    scalars = {
        "SLUG": values.get("slug", ""),
        "TITLE": values.get("title", "TODO"),
        "INTERNAL_CODE": values.get("internal_code", ""),
        "INSTITUTION": values.get("institution", ""),
        "FUNDING": values.get("funding", "TODO"),
        "JOURNAL_SLUG": values.get("journal_slug", ""),
        "JOURNAL_NAME": values.get("journal_name", ""),
        "FORMAT_BLOCK": values.get("format_block", "format:\n  pdf: default\n  docx: default\n"),
        "ABSTRACT": values.get("abstract", "TODO"),
        "ROUND": str(values.get("round", "1")),
    }
    for key, val in scalars.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  created {path}")


def build_author_blocks(repo: Path, specs: list[str]) -> tuple[str, str]:
    """Turn ['id:role:order', ...] into (qmd author block, manifest author block)."""
    qmd_lines, man_lines = [], []
    for spec in specs:
        parts = spec.split(":")
        if len(parts) != 3:
            raise SystemExit(f"ERROR: --author must be id:role:order, got '{spec}'")
        aid, role, order = (p.strip() for p in parts)
        record = repo / "authors" / f"{aid}.yaml"
        if not record.is_file():
            raise SystemExit(f"ERROR: no authors/{aid}.yaml — add the author first")
        data = load_yaml(record)
        qmd_lines.append(
            f'  - name: "{data.get("name", aid)}"\n'
            f'    affiliation: "{data.get("affiliation", "")}"\n'
            f'    email: "{data.get("email", "")}"\n'
            f'    orcid: "{data.get("orcid", "")}"'
        )
        man_lines.append(f"  - id: {aid}\n    role: {role}\n    order: {order}")
    return "\n".join(qmd_lines), "\n".join(man_lines)


def collect_values(repo: Path, args) -> dict:
    journal_slug = args.journal or ""
    journal_name, format_block = "", "format:\n  pdf: default\n  docx: default\n"
    if journal_slug:
        type_yaml = repo / "templates" / "journals" / journal_slug / "type.yaml"
        if not type_yaml.is_file():
            raise SystemExit(
                f"ERROR: journal '{journal_slug}' not in templates/journals/. "
                "Add it with scripts/paper_journal.py --add-journal, or omit --journal."
            )
        tj = load_yaml(type_yaml)
        journal_name = tj.get("journal", journal_slug)
        format_block = format_block_from_type(tj)

    qmd_block, man_block = build_author_blocks(repo, args.author or [])
    return {
        "slug": args.slug,
        "title": args.title or "TODO",
        "internal_code": args.internal_code or "",
        "institution": args.institution or "",
        "funding": args.funding or "TODO",
        "journal_slug": journal_slug,
        "journal_name": journal_name,
        "format_block": format_block,
        "authors_qmd_block": qmd_block,
        "authors_manifest_block": man_block or "  - id: TODO\n    role: TODO\n    order: 1",
        "keywords": args.keyword or [],
        "round": args.round,
        "migrate": args.migrate,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a new paper folder.")
    ap.add_argument("--slug", required=True, help="folder name under papers/ (e.g. c22-2026)")
    ap.add_argument("--title", default="")
    ap.add_argument("--internal-code", default="")
    ap.add_argument("--institution", default="SENATI")
    ap.add_argument("--funding", default="")
    ap.add_argument("--journal", default="", help="journal slug from templates/journals/")
    ap.add_argument("--author", action="append", default=[], help="id:role:order (repeatable)")
    ap.add_argument("--keyword", action="append", default=[], help="keyword (repeatable)")
    ap.add_argument("--abstract", default="TODO")
    ap.add_argument("--round", default="1")
    ap.add_argument("--migrate", action="store_true", help="no main.qmd; leave MIGRATION_PENDING.txt")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    import re

    if not re.match(SLUG_PATTERN, args.slug):
        raise SystemExit(f"ERROR: slug '{args.slug}' must be lowercase kebab/code (regex {SLUG_PATTERN})")

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    paper_root = repo / "papers" / args.slug
    if paper_root.exists():
        raise SystemExit(f"ERROR: papers/{args.slug} already exists — choose another slug")

    tmpl_dir = repo / TEMPLATES_SUBDIR
    if not tmpl_dir.is_dir():
        raise SystemExit(f"ERROR: missing templates at {tmpl_dir}")

    values = collect_values(repo, args)

    print(f"Scaffolding papers/{args.slug} ...")
    for d in PAPER_DIRS:
        keep = paper_root / d / ".gitkeep"
        keep.parent.mkdir(parents=True, exist_ok=True)
        if not any(keep.parent.iterdir()):
            keep.write_text("", encoding="utf-8")

    if args.migrate:
        _write(paper_root / MIGRATION_MARKER,
               "Run the paper-migrate step to produce paper/main.qmd from legacy/.\n")
    else:
        _write(paper_root / "paper" / "main.qmd",
               render((tmpl_dir / "main.qmd.template").read_text(encoding="utf-8"), values))

    for tpl, dest in [
        ("manifest.yaml.template", "paper/manifest.yaml"),
        ("references.bib.template", "paper/references.bib"),
    ]:
        _write(paper_root / dest,
               render((tmpl_dir / tpl).read_text(encoding="utf-8"), values))

    for fname in REVIEW_FILES:
        _write(paper_root / "reviews" / f"round-{args.round}" / fname,
               render((tmpl_dir / f"{fname}.template").read_text(encoding="utf-8"), values))

    print("\nPending (fill before submission):")
    pend = []
    if values["title"] == "TODO":
        pend.append("- title (manifest.yaml / main.qmd)")
    if not values["journal_slug"]:
        pend.append("- journal (none selected)")
    if args.migrate:
        pend.append("- run the paper-migrate step to produce paper/main.qmd")
    pend.append("- write the body of paper/main.qmd")
    pend.append("- populate paper/references.bib")
    for p in pend:
        print(p)
    print(f"\nScaffolded {paper_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

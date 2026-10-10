#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_title_page.py — check the data behind a paper's separate title page.

Under double-anonymized review Elsevier asks for the title page and the
anonymized manuscript "as separate files": the title page "will not be sent to
the reviewers" and carries the title, all authors' names and affiliations, a
complete address for the corresponding author with e-mail, acknowledgements
and the declaration of interest; funding moves there as well.

scripts/paper_build.py renders it (build/<slug>-title-page.docx/.pdf) from
main.qmd's front matter whenever journal.formatting ends in "blind". This
script verifies that front matter is true and complete before submission:

  - author names, e-mails and ORCIDs equal authors/<id>.yaml, in the order of
    manifest.yaml (names must match the submission system exactly);
  - exactly one corresponding author, the manifest's, with an e-mail;
  - every author has an affiliation and every affiliation a full postal
    address (organization, street address, city, country);
  - the title-page block declares competing interests and funding;
  - no TODO left on the author, affiliations or title-page blocks (a TODO
    marks a value nobody has verified yet);
  - the identifying data never appear in the manuscript body, nor in the
    built anonymized docx/pdf when they exist.

Usage:
    python scripts/paper_title_page.py --slug c15-2026
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402

TITLE_PAGE_BLOCKS = ("author", "affiliations", "title-page")
ADDRESS_FIELDS = ("name", "address", "city", "country")


def split_qmd(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return "", text
    _, head, body = text.split("---", 2)
    return head, body


def todos_by_block(head: str) -> dict[str, list[str]]:
    """TODO comments of the front matter, keyed by the top-level key they
    annotate (a column-0 comment belongs to the next key; an indented one to
    the current key)."""
    found: dict[str, list[str]] = {}
    current, pending = "", []
    for line in head.splitlines():
        key = re.match(r"^([A-Za-z][\w-]*):", line)
        if key:
            current = key.group(1)
            for note in pending:
                found.setdefault(current, []).append(note)
            pending = []
        elif "TODO" in line:
            note = line.strip().lstrip("#").strip()
            if line.startswith("#"):
                pending.append(note)
            else:
                found.setdefault(current, []).append(note)
    return found


def fold(text: str) -> str:
    """Case- and accent-insensitive form for leak searches."""
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def literal(name: object) -> str:
    return str(name.get("literal") if isinstance(name, dict) else name or "").strip()


def check(repo: Path, slug: str) -> int:
    import yaml

    paper = repo / "papers" / slug
    head, body = split_qmd(paper / "paper" / "main.qmd")
    front = yaml.safe_load(head) or {}
    manifest = load_yaml(paper / "manifest.yaml")
    errors: list[str] = []
    warnings: list[str] = []

    journal = front.get("journal") if isinstance(front.get("journal"), dict) else {}
    if not str(journal.get("formatting") or "").endswith("blind"):
        warnings.append("journal.formatting is not singleblind/doubleblind: paper_build makes no "
                        "separate title page and the manuscript keeps the authors")
    if not str(front.get("title") or "").strip():
        errors.append("main.qmd has no title")

    # authors: order, names, e-mails, ORCIDs against the shared records
    listed = sorted((a for a in manifest.get("authors") or [] if isinstance(a, dict)),
                    key=lambda a: a.get("order") or 0)
    qmd_authors = [a for a in front.get("author") or [] if isinstance(a, dict)]
    if len(listed) != len(qmd_authors):
        errors.append(f"manifest lists {len(listed)} author(s), main.qmd {len(qmd_authors)}")
    records = []
    for i, (entry, author) in enumerate(zip(listed, qmd_authors), start=1):
        record = load_yaml(repo / "authors" / f"{entry.get('id')}.yaml")
        records.append(record)
        for field, value in (("name", literal(author.get("name"))),
                             ("email", author.get("email")), ("orcid", author.get("orcid"))):
            truth = str(record.get(field) or "").strip()
            if truth and truth != "TODO" and str(value or "").strip() != truth:
                errors.append(f"author {i} {field} '{value}' differs from "
                              f"authors/{entry.get('id')}.yaml ('{truth}')")
        if not (author.get("affiliation") or author.get("affiliations")):
            errors.append(f"author {i} ({literal(author.get('name'))}) has no affiliation")

    # corresponding author
    marked = [i for i, a in enumerate(qmd_authors)
              if (a.get("cas") or {}).get("cormark") or a.get("corresponding")]
    wanted = [i for i, a in enumerate(listed) if a.get("role") == "corresponding"]
    if len(marked) != 1:
        errors.append(f"{len(marked)} corresponding author(s) marked in main.qmd (need exactly 1)")
    elif wanted and marked != wanted[:1]:
        errors.append("the corresponding author in main.qmd is not the manifest's")
    elif not qmd_authors[marked[0]].get("email"):
        errors.append("the corresponding author has no e-mail")

    # affiliations: complete postal address
    ids = set()
    for aff in front.get("affiliations") or []:
        if not isinstance(aff, dict):
            continue
        ids.add(str(aff.get("id")))
        missing = [f for f in ADDRESS_FIELDS if not str(aff.get(f) or "").strip()]
        if missing:
            errors.append(f"affiliation {aff.get('id')}: missing {', '.join(missing)} "
                          "(a full postal address and the country are required)")
    for i, author in enumerate(qmd_authors, start=1):
        for ref in author.get("affiliation") or author.get("affiliations") or []:
            ref = ref.get("ref") if isinstance(ref, dict) else ref
            if str(ref) not in ids:
                errors.append(f"author {i} points to unknown affiliation '{ref}'")

    # statements that leave the anonymized manuscript
    statements = front.get("title-page") if isinstance(front.get("title-page"), dict) else {}
    if not str(statements.get("competing-interests") or "").strip():
        errors.append("title-page.competing-interests is missing (declaration of interest)")
    if not str(statements.get("funding") or "").strip():
        errors.append("title-page.funding is missing (state the funder, or that the research "
                      "received no specific grant)")

    # values nobody has verified yet
    for block, notes in todos_by_block(head).items():
        if block in TITLE_PAGE_BLOCKS:
            for note in notes:
                errors.append(f"unverified ({block}): {note}")

    # the same data must not leak into the anonymized manuscript
    secrets = set()
    for author, record in zip(qmd_authors, records or [{}] * len(qmd_authors)):
        for value in (literal(author.get("name")), author.get("email"), author.get("orcid"),
                      record.get("name"), record.get("email")):
            if value and str(value) != "TODO":
                secrets.add(str(value))
    for aff in front.get("affiliations") or []:
        if isinstance(aff, dict):
            secrets.update(str(aff[k]) for k in ("name", "address") if aff.get(k))
            acronym = re.search(r"\(([A-Z]{3,})\)", str(aff.get("name") or ""))
            if acronym:
                secrets.add(acronym.group(1))
    if str(journal.get("formatting") or "").endswith("blind"):
        folded_body = fold(body)
        for value in sorted(secrets):
            if fold(value) in folded_body:
                errors.append(f"manuscript body names '{value}' (identifying)")
        docx = paper / "build" / f"{slug}.docx"
        if docx.is_file():
            with zipfile.ZipFile(docx) as z:
                xml = fold(" ".join(z.read(n).decode("utf-8", "ignore")
                                    for n in z.namelist() if n.endswith(".xml")))
            for value in sorted(secrets):
                if fold(value) in xml:
                    errors.append(f"build/{docx.name} contains '{value}' (rebuild after fixing)")
        else:
            warnings.append(f"build/{slug}.docx not built yet: run paper_build.py and re-check")

    for w in warnings:
        print(f"  [warn] {w}")
    for e in errors:
        print(f"  [FAIL] {e}")
    print(f"RESULT: {'FAIL' if errors else 'PASS'} ({len(qmd_authors)} author(s))")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Check a paper's title-page data.")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--root", default=None)
    args = ap.parse_args()
    repo = Path(args.root).resolve() if args.root else find_repo_root()
    if not (repo / "papers" / args.slug / "paper" / "main.qmd").is_file():
        raise SystemExit(f"ERROR: papers/{args.slug}/paper/main.qmd not found")
    return check(repo, args.slug)


if __name__ == "__main__":
    raise SystemExit(main())

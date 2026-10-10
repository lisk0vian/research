#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_cover_letter.py — scaffold and check a paper's cover letter.

The letter lives in papers/<slug>/paper/cover-letter.qmd and is rendered by
scripts/paper_build.py into build/<slug>-cover-letter.docx/.pdf. Its layout
follows Elsevier's "What to include in a cover letter" tutorial: sender,
editor + journal, date, salutation, then four short paragraphs (submission,
problem/method/finding/significance, fit with the journal's scope,
originality + conflicts of interest), thanks and signature.

Two operations, both deterministic:

  --init   write the skeleton: every field that comes from metadata (sender,
           affiliation, journal, date, title, signature) is filled from
           main.qmd, manifest.yaml and authors/<id>.yaml; the body paragraphs
           are left as [WRITE: ...] slots for the agent or the author.
  --check  lint an existing letter: no slot left, exact manuscript title,
           journal named, length, no content the tutorial says to leave out
           (funding, author declarations, suggested/opposed reviewers) unless
           --allow says the journal asks for it, and every number in the
           letter present in main.qmd.

Usage:
    python scripts/paper_cover_letter.py --slug c15-2026 --init [--force]
    python scripts/paper_cover_letter.py --slug c15-2026 --check [--allow funding]
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402

LETTER = "cover-letter.qmd"
# A letter longer than this is no longer "short and focused" (about one page
# of 11 pt text once the address block and signature are added).
MAX_BODY_WORDS = 450
SLOT = re.compile(r"\[WRITE:[^\]]*\]|\bTODO\b")

# Content the tutorial says a cover letter should NOT carry unless the
# journal's Guide for Authors asks for it. --allow <key> lifts one group.
EXCLUDED = {
    "funding": r"\b(fund(ed|ing)|grant(s|ed)?\b|financ(ed|ial support)|supported by|sponsor)",
    "declarations": r"\b(CRediT|author contributions?|data availability|generative AI|"
                    r"declaration of|ethic(s|al) approval)",
    "reviewers": r"\b(suggest(ed)?|propos(e|ed)|oppos(e|ed)|exclude[d]?)\s+(potential\s+)?reviewers?\b",
}

SKELETON = """---
# papers/{slug}/paper/cover-letter.qmd
# Cover letter for the submission to {journal}. Rendered by
#   python scripts/paper_build.py --slug {slug} --format all
# into build/{slug}-cover-letter.docx/.pdf. Checked by
#   python scripts/paper_cover_letter.py --slug {slug} --check
# Every number in the letter must also appear in main.qmd.
format:
  docx: default
  pdf:
    papersize: a4
    geometry: margin=2.5cm
    pagestyle: empty
    fontsize: 11pt
---

{name}\\
{affiliation}

{editor}\\
*{journal}*\\
{publisher}

{date}

Dear {salutation},

We wish to submit an original research paper entitled **"{title}"** for consideration for publication in *{journal}*.

[WRITE: problem paragraph. This paper addresses the problem of <main question>. Studies have shown that <brief background, cited in the manuscript>. However, it remains unclear whether <problem statement>. Using <method>, we show that <key findings, numbers copied from main.qmd>. Our findings are significant because <impact>.]

[WRITE: fit paragraph. Since our study deals with <how its focus matches the journal's aims and scope>, we believe it is a good fit for *{journal}*. We feel that its findings will be relevant to your readers because <contribution or practical implications>.]

The manuscript "{title}" has not been published elsewhere, is not under consideration by another journal, and reflects original research conducted by its authors. None of the authors have any conflicts of interest to disclose concerning this study.

Thank you for your valuable time.

Sincerely,

{name}\\
{position}{email}
"""


def front_matter(path: Path) -> tuple[dict, str]:
    """(YAML front matter, body) of a .qmd; ({}, text) when there is none."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    _, head, body = text.split("---", 2)
    import yaml

    data = yaml.safe_load(head) or {}
    return (data if isinstance(data, dict) else {}), body


def corresponding_author(repo: Path, paper: Path) -> dict:
    """authors/<id>.yaml of the manifest's corresponding author (else first)."""
    authors = [a for a in load_yaml(paper / "manifest.yaml").get("authors") or []
               if isinstance(a, dict) and a.get("id")]
    if not authors:
        raise SystemExit(f"ERROR: no authors in {paper / 'manifest.yaml'}")
    authors.sort(key=lambda a: a.get("order") or 0)
    chosen = next((a for a in authors if a.get("role") == "corresponding"), authors[0])
    return load_yaml(repo / "authors" / f"{chosen['id']}.yaml")


def init(repo: Path, slug: str, editor: str, date: str, force: bool) -> int:
    paper = repo / "papers" / slug
    out = paper / "paper" / LETTER
    if out.exists() and not force:
        raise SystemExit(f"ERROR: {out} exists (use --force to overwrite)")
    meta, _ = front_matter(paper / "paper" / "main.qmd")
    journal_slug = load_yaml(paper / "manifest.yaml").get("journal") or ""
    tj = load_yaml(repo / "templates" / "journals" / journal_slug / "type.yaml")
    person = corresponding_author(repo, paper)
    journal = tj.get("journal") or journal_slug
    out.write_text(SKELETON.format(
        slug=slug,
        journal=journal,
        publisher=tj.get("publisher") or "",
        title=meta.get("title") or "",
        name=person.get("name") or "",
        affiliation=person.get("affiliation") or "",
        editor=editor or "The Editor-in-Chief",
        salutation=editor or "Editor",
        date=date or dt.date.today().strftime("%B %d, %Y").replace(" 0", " "),
        position="[WRITE: position or academic title, or delete this line]\\\n",
        email=person.get("email") or "",
    ), encoding="utf-8")
    print(f"wrote {out.relative_to(repo)}: fill the [WRITE: ...] slots, then run --check")
    return 0


def numbers(text: str) -> set[str]:
    """Numbers worth checking: decimals, thousands, percentages, ranges' ends.

    Single small integers (1, 2, 4 ...) are ignored: they are counts or
    ordinals far too common to trace.
    """
    found = set()
    for m in re.finditer(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+(?=\s?%)|\b\d{3,}\b", text):
        found.add(m.group(0))
    return found


def check(repo: Path, slug: str, allow: set[str]) -> int:
    paper = repo / "papers" / slug
    letter = paper / "paper" / LETTER
    if not letter.is_file():
        raise SystemExit(f"ERROR: {letter} not found (run --init first)")
    _, body = front_matter(letter)
    meta, manuscript = front_matter(paper / "paper" / "main.qmd")
    manuscript_text = manuscript + "\n" + str(meta.get("abstract") or "")
    tj = load_yaml(repo / "templates" / "journals"
                   / (load_yaml(paper / "manifest.yaml").get("journal") or "") / "type.yaml")
    errors: list[str] = []
    warnings: list[str] = []

    slots = SLOT.findall(body)
    if slots:
        errors.append(f"{len(slots)} unfilled slot(s): {slots[0][:60]}")
    title = str(meta.get("title") or "")
    if title and title not in body:
        errors.append("the manuscript title is not quoted exactly as in main.qmd")
    journal = str(tj.get("journal") or "")
    if journal and journal not in body:
        errors.append(f"the journal is not named ('{journal}')")
    words = len(re.findall(r"[A-Za-z][\w'’-]*", body))
    if words > MAX_BODY_WORDS:
        warnings.append(f"{words} words: keep it short and focused (<= {MAX_BODY_WORDS})")
    for key, pattern in EXCLUDED.items():
        if key in allow:
            continue
        m = re.search(pattern, body, re.I)
        if m:
            errors.append(f"'{m.group(0)}': {key} belongs in the submission system, not the "
                          f"letter (use --allow {key} if the Guide for Authors asks for it)")
    if not re.search(r"conflicts? of interest|competing interests?", body, re.I):
        warnings.append("no conflict-of-interest sentence")
    if not re.search(r"not (been )?published|original", body, re.I):
        warnings.append("no originality / not-published-elsewhere sentence")
    # only the letter proper: the address block, date and signature (ORCID,
    # postcodes, submission year) are not claims about the study
    proper = re.search(r"Dear\b(.*?)(Sincerely|Yours|Kind regards|Best regards)", body, re.S)
    strays = sorted(n for n in numbers(proper.group(1) if proper else body)
                    if n not in manuscript_text)
    if strays:
        errors.append(f"number(s) not found in main.qmd: {', '.join(strays)}")

    for w in warnings:
        print(f"  [warn] {w}")
    for e in errors:
        print(f"  [FAIL] {e}")
    print(f"RESULT: {'FAIL' if errors else 'PASS'} ({words} words)")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold or check a cover letter.")
    ap.add_argument("--slug", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--init", action="store_true", help="write the skeleton")
    mode.add_argument("--check", action="store_true", help="lint the letter")
    ap.add_argument("--editor", default="", help="editor's name, if known (e.g. 'Dr. Jane Doe')")
    ap.add_argument("--date", default="", help="submission date as printed (default: today)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing letter")
    ap.add_argument("--allow", action="append", default=[], choices=sorted(EXCLUDED),
                    help="content the journal explicitly asks for in the letter")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()
    repo = Path(args.root).resolve() if args.root else find_repo_root()
    if not (repo / "papers" / args.slug).is_dir():
        raise SystemExit(f"ERROR: papers/{args.slug} not found")
    if args.init:
        return init(repo, args.slug, args.editor, args.date, args.force)
    return check(repo, args.slug, set(args.allow))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_journal.py — set/change a paper's target journal, or add a journal.

Two independent operations:

  retarget a paper (the common case):
      python scripts/paper_journal.py --slug c15-2026 --journal machine-learning-with-applications
    -> writes `journal:` in the paper's manifest.yaml and rewrites the `format:`
       block of main.qmd from templates/journals/<journal>/type.yaml.

  add/update a journal from scraped metadata (the agent fetches the page and
  hands the fields here, so this script stays network-free):
      python scripts/paper_journal.py --add-journal discover-ai --meta meta.json [--force]

Journal metadata lives ONLY in templates/journals/<slug>/type.yaml: the single
source. The publisher -> Quarto extension mapping below is the catalog-wide
source of truth for deducing an extension the journal site never publishes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402
from _structure import format_block_from_type  # noqa: E402

# publisher (lowercased) -> (extension, quarto_format, default_cite_style, format)
PUBLISHER_MAP = {
    "elsevier": ("quarto-journals/elsevier", "elsevier-pdf", "number", "latex"),
    "ieee": ("quarto-journals/ieee", "ieee-pdf", "number", "latex"),
    "mdpi": ("quarto-journals/mdpi", "mdpi-pdf", "numbername", "latex"),
    "acm": ("quarto-journals/acm", "acm-pdf", "number", "latex"),
    "acs": ("quarto-journals/acs", "acs-pdf", "number", "latex"),
    "plos": ("quarto-journals/plos", "plos-pdf", "number", "latex"),
    "agu": ("quarto-journals/agu", "agu-pdf", "authoryear", "latex"),
    "springer": ("", "pdf", "numbername", "latex"),
    "springer nature": ("", "pdf", "numbername", "latex"),
    "frontiers": ("", "pdf", "authoryear", "latex"),
    "taylor & francis": ("", "pdf", "authoryear", "latex"),
    "taylor and francis": ("", "pdf", "authoryear", "latex"),
    "wiley": ("", "pdf", "authoryear", "latex"),
}

DOMAIN_HINTS = {
    "sciencedirect.com": "elsevier",
    "elsevier.com": "elsevier",
    "ieee.org": "ieee",
    "mdpi.com": "mdpi",
    "acm.org": "acm",
    "acs.org": "acs",
    "plos.org": "plos",
    "springer.com": "springer",
    "springeropen.com": "springer",
    "frontiersin.org": "frontiers",
    "tandfonline.com": "taylor & francis",
    "wiley.com": "wiley",
}


def resolve_publisher(meta: dict) -> str:
    pub = (meta.get("publisher") or "").strip().lower()
    if pub in PUBLISHER_MAP:
        return pub
    for domain, key in DOMAIN_HINTS.items():
        if domain in (meta.get("url") or "").lower():
            return key
    return pub


def esc(text: str) -> str:
    return (text or "").replace('"', '\\"')


def add_journal(repo: Path, slug: str, meta_path: Path, force: bool) -> int:
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    jdir = repo / "templates" / "journals" / slug
    out = jdir / "type.yaml"
    if out.exists() and not force:
        print(f"EXISTS: {out} already exists. Re-run with --force to update.")
        return 1

    pub_key = resolve_publisher(meta)
    if pub_key in PUBLISHER_MAP:
        ext, qformat, default_cite, fmt = PUBLISHER_MAP[pub_key]
    else:
        ext, qformat, default_cite, fmt = ("", "pdf", "number", "latex")
        print(f"  WARN: unknown publisher '{meta.get('publisher')}' — generic pdf, empty extension")

    cite = meta.get("cite_style") or default_cite
    jdir.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f'journal: "{esc(meta.get("journal", ""))}"\n'
        f"publisher: {pub_key or 'unknown'}\n"
        f"format: {fmt}\n"
        f'extension: "{ext}"\n'
        f"quarto_format: {qformat}\n"
        f"cite_style: {cite}\n"
        f'issn: "{esc(meta.get("issn", ""))}"\n'
        f'url: "{esc(meta.get("url", ""))}"\n'
        "notes: >\n"
        f"  {esc(meta.get('notes', '')) or 'TODO'}\n",
        encoding="utf-8",
    )
    print(f"  {'updated' if force else 'created'} {out}")
    if ext:
        print(f"  extension: {ext}  (install: quarto add {ext})")
    else:
        print("  NOTE: no official Quarto extension — final PDF needs a manual template.")
    return 0


def update_manifest(repo: Path, slug: str, journal: str) -> None:
    mp = repo / "papers" / slug / "manifest.yaml"
    if not mp.is_file():
        raise SystemExit(f"ERROR: manifest not found: {mp}")
    text = mp.read_text(encoding="utf-8")
    new, n = re.subn(
        r"(?m)^(journal:\s*).*?(\s*#.*)?$",
        lambda m: f"journal: {journal}" + (m.group(2) or ""),
        text,
        count=1,
    )
    if n == 0:
        raise SystemExit("ERROR: no `journal:` line found in manifest.yaml")
    mp.write_text(new, encoding="utf-8")
    print(f"  manifest.yaml: journal -> {journal}")


def update_main_qmd(repo: Path, slug: str, type_meta: dict) -> None:
    qp = repo / "papers" / slug / "paper" / "main.qmd"
    if not qp.is_file():
        print(f"  WARN: main.qmd not found ({qp}); skipping front-matter (migration pending)")
        return
    text = qp.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        raise SystemExit("ERROR: main.qmd has no YAML front-matter block")
    fm, body = m.group(1), m.group(2)
    new_format = format_block_from_type(type_meta).rstrip("\n")

    lines = fm.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^format:\s*$", line) or re.match(r"^format:\s+\S", line):
            i += 1
            while i < len(lines) and (lines[i].startswith(" ") or lines[i].strip() == ""):
                if lines[i].strip() == "" and (
                    i + 1 >= len(lines) or not lines[i + 1].startswith(" ")
                ):
                    break
                i += 1
            continue
        out.append(line)
        i += 1

    final, inserted = [], False
    for line in out:
        final.append(line)
        if not inserted and re.match(r"^title:\s", line):
            final.append(new_format)
            inserted = True
    if not inserted:
        final.insert(0, new_format)
    joined = "\n".join(final)
    qp.write_text(f"---\n{joined}\n---\n{body}", encoding="utf-8")
    print(f"  main.qmd: format block -> {type_meta.get('quarto_format') or 'pdf/docx'}")


def retarget(repo: Path, slug: str, journal: str) -> int:
    type_yaml = repo / "templates" / "journals" / journal / "type.yaml"
    if not type_yaml.is_file():
        raise SystemExit(f"ERROR: journal not in catalog: {type_yaml}")
    tj = load_yaml(type_yaml)
    print(f"Retargeting papers/{slug} -> {journal}")
    update_manifest(repo, slug, journal)
    update_main_qmd(repo, slug, tj)
    ext = tj.get("extension") or tj.get("quarto_extension") or ""
    if ext:
        print(f"\nNext: cd papers/{slug}/paper && quarto add {ext}")
    else:
        print("\nNo Quarto extension for this journal — manual template needed for final PDF.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Set a paper's journal or add a journal to the catalog.")
    ap.add_argument("--root", default=None)
    ap.add_argument("--slug", help="paper slug to retarget")
    ap.add_argument("--journal", help="journal slug (retarget)")
    ap.add_argument("--add-journal", metavar="JOURNAL_SLUG", help="create templates/journals/<slug>/type.yaml")
    ap.add_argument("--meta", help="JSON file with scraped journal metadata (for --add-journal)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing type.yaml")
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()

    if args.add_journal:
        if not args.meta:
            raise SystemExit("ERROR: --add-journal requires --meta meta.json")
        return add_journal(repo, args.add_journal, Path(args.meta), args.force)

    if args.slug and args.journal:
        return retarget(repo, args.slug, args.journal)

    ap.error("provide either --slug/--journal (retarget) or --add-journal/--meta")


if __name__ == "__main__":
    raise SystemExit(main())

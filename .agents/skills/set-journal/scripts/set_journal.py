#!/usr/bin/env python3
"""
set_journal.py — retarget a paper to a journal.

Updates papers/<slug>/paper/manifest.yaml (journal field) and rewrites the
format: block of papers/<slug>/paper/main.qmd using the journal's type.yaml.
Does NOT run `quarto add` (the agent/command does that, or CI does).

Usage:
    python set_journal.py --repo-root . --slug c15-2026 \
        --journal machine-learning-with-applications

Reads templates/journals/<journal>/type.yaml for the values to write.
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")


def load_type_yaml(repo: Path, journal_slug: str) -> dict:
    p = repo / "templates" / "journals" / journal_slug / "type.yaml"
    if not p.exists():
        sys.exit(f"ERROR: journal not in catalog: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def update_manifest(repo: Path, slug: str, journal_slug: str):
    mp = repo / "papers" / slug / "paper" / "manifest.yaml"
    if not mp.exists():
        sys.exit(f"ERROR: manifest not found: {mp}")
    text = mp.read_text(encoding="utf-8")
    # Replace the `journal:` line, preserving any trailing comment.
    new, n = re.subn(
        r"(?m)^(journal:\s*).*?(\s*#.*)?$",
        lambda m: f"journal: {journal_slug}" + (m.group(2) or ""),
        text,
        count=1,
    )
    if n == 0:
        sys.exit("ERROR: no `journal:` line found in manifest.yaml")
    mp.write_text(new, encoding="utf-8")
    print(f"  manifest.yaml: journal -> {journal_slug}")


def build_format_block(tj: dict) -> str:
    qformat = tj.get("quarto_format") or "pdf"
    name = tj.get("journal", "")
    cite = tj.get("cite_style", "number")
    extension = tj.get("extension", "")

    if extension:
        return (
            "format:\n"
            f"  {qformat}:\n"
            "    keep-tex: true\n"
            "    journal:\n"
            f'      name: "{name}"\n'
            f"      cite-style: {cite}\n"
            "  docx: default\n"
        )
    # No official extension: generic pdf + docx, note the manual template step.
    return (
        "format:\n"
        "  pdf: default\n"
        "  docx: default\n"
        f"  # NOTE: {name} has no Quarto extension in the catalog. Use a\n"
        "  # reference-doc for docx and/or a raw LaTeX bundle for the final PDF.\n"
    )


def update_main_qmd(repo: Path, slug: str, tj: dict):
    qp = repo / "papers" / slug / "paper" / "main.qmd"
    if not qp.exists():
        print(f"  WARN: main.qmd not found ({qp}); skipping front-matter edit "
              "(likely migration still pending)")
        return
    text = qp.read_text(encoding="utf-8")

    # Split front-matter (between the first two --- lines) from the body.
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        sys.exit("ERROR: main.qmd has no YAML front-matter block")
    fm, body = m.group(1), m.group(2)

    new_format = build_format_block(tj).rstrip("\n")

    # Remove any existing top-level `format:` block from the front-matter,
    # then re-insert the new one after the title line (or at the top).
    lines = fm.split("\n")
    out, i, skipping = [], 0, False
    while i < len(lines):
        line = lines[i]
        if re.match(r"^format:\s*$", line) or re.match(r"^format:\s+\S", line):
            skipping = True
            i += 1
            # skip indented lines belonging to the format block
            while i < len(lines) and (lines[i].startswith(" ") or lines[i].strip() == ""):
                if lines[i].strip() == "" and (i + 1 >= len(lines) or not lines[i + 1].startswith(" ")):
                    break
                i += 1
            skipping = False
            continue
        out.append(line)
        i += 1

    # Insert new format block right after the title line if present.
    inserted = False
    final = []
    for line in out:
        final.append(line)
        if not inserted and re.match(r'^title:\s', line):
            final.append(new_format)
            inserted = True
    if not inserted:
        final.insert(0, new_format)

    new_fm = "\n".join(final)
    qp.write_text(f"---\n{new_fm}\n---\n{body}", encoding="utf-8")
    print(f"  main.qmd: format block -> {tj.get('quarto_format') or 'pdf/docx'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--journal", required=True)
    args = ap.parse_args()

    repo = Path(args.repo_root)
    tj = load_type_yaml(repo, args.journal)

    print(f"Retargeting papers/{args.slug} -> {args.journal}")
    update_manifest(repo, args.slug, args.journal)
    update_main_qmd(repo, args.slug, tj)

    ext = tj.get("extension", "")
    if ext:
        print(f"\nNext (local or CI): cd papers/{args.slug}/paper && quarto add {ext}")
    else:
        print("\nNo Quarto extension for this journal — manual template needed for final PDF.")


if __name__ == "__main__":
    main()

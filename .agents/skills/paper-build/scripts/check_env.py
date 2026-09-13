#!/usr/bin/env python3
"""
check_env.py — verify the build environment for a paper WITHOUT installing.

Checks quarto, a LaTeX engine (for PDF), the journal's Quarto extension, and the
bibliography. Prints a clear report and exits non-zero if a REQUIRED piece for
the requested format is missing, so the build skill can stop and tell the user
what to run.

Usage:
    python check_env.py --repo-root . --slug c15-2026 --format all
    # --format: pdf | docx | all
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return out.returncode, (out.stdout + out.stderr).strip()
    except Exception as e:
        return 1, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--format", default="all", choices=["pdf", "docx", "all"])
    args = ap.parse_args()

    repo = Path(args.repo_root)
    paper_dir = repo / "papers" / args.slug / "paper"
    need_pdf = args.format in ("pdf", "all")
    need_docx = args.format in ("docx", "all")

    problems = []   # required things missing -> stop
    warnings = []   # non-fatal
    ok = []

    # --- quarto ---
    if shutil.which("quarto"):
        rc, ver = run(["quarto", "--version"])
        ok.append(f"quarto {ver.splitlines()[0] if ver else '(version?)'}")
    else:
        problems.append("quarto not found on PATH. Install: https://quarto.org/docs/get-started/")

    # --- paper files ---
    qmd = paper_dir / "main.qmd"
    if qmd.exists():
        ok.append(f"main.qmd present ({qmd})")
    else:
        problems.append(f"main.qmd missing at {qmd} (run paper-migrate or new-paper first)")

    bib = paper_dir / "references.bib"
    if bib.exists() and bib.stat().st_size > 0 and any(
        l.strip().startswith("@") for l in bib.read_text(encoding="utf-8", errors="ignore").splitlines()
    ):
        ok.append("references.bib has entries")
    else:
        warnings.append("references.bib empty or has no @entries — bibliography will be blank")

    # --- journal / extension ---
    quarto_format = None
    extension = ""
    manifest = paper_dir / "manifest.yaml"
    if manifest.exists() and yaml:
        mf = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        journal_slug = mf.get("journal", "")
        if journal_slug:
            tj_path = repo / "templates" / "journals" / journal_slug / "type.yaml"
            if tj_path.exists():
                tj = yaml.safe_load(tj_path.read_text(encoding="utf-8")) or {}
                quarto_format = tj.get("quarto_format", "pdf")
                extension = tj.get("extension", "") or ""
                ok.append(f"journal: {journal_slug} (format {quarto_format})")
            else:
                warnings.append(f"journal '{journal_slug}' not in templates/journals/ — will fall back to plain pdf")
        else:
            warnings.append("no journal set in manifest — will render plain pdf/docx (run set-journal)")
    elif not yaml:
        warnings.append("PyYAML not installed here; cannot read journal from manifest (pip install pyyaml)")

    # extension installed?
    if need_pdf and extension:
        ext_dir = paper_dir / "_extensions"
        installed = ext_dir.exists() and any(ext_dir.rglob("_extension.yml"))
        if installed:
            ok.append(f"Quarto extension present for {extension}")
        else:
            problems.append(
                f"Quarto extension '{extension}' not installed. "
                f"Run: cd papers/{args.slug}/paper && quarto add {extension}"
            )

    # --- LaTeX engine for PDF ---
    if need_pdf:
        has_engine = any(shutil.which(e) for e in ("xelatex", "pdflatex", "lualatex"))
        rc, tinytex = run(["quarto", "list", "tools"]) if shutil.which("quarto") else (1, "")
        tinytex_ok = "tinytex" in tinytex.lower() and "installed" in tinytex.lower()
        if has_engine or tinytex_ok:
            ok.append("LaTeX engine available")
        else:
            problems.append(
                "No LaTeX engine found for PDF. Install: quarto install tinytex"
            )

    # --- report ---
    print("=== build environment check ===")
    print(f"paper: {args.slug}   format: {args.format}\n")
    for o in ok:
        print(f"  [ok]   {o}")
    for w in warnings:
        print(f"  [warn] {w}")
    for p in problems:
        print(f"  [MISS] {p}")

    print()
    if problems:
        print("RESULT: missing required components — fix the [MISS] items above, then rebuild.")
        sys.exit(1)
    print("RESULT: environment OK for the requested format.")
    if quarto_format:
        print(f"quarto_format={quarto_format}")
    print(f"extension={extension}")
    sys.exit(0)


if __name__ == "__main__":
    main()

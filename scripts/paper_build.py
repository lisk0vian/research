#!/usr/bin/env python3
"""paper_build.py — verify the environment and render paper/main.qmd.

Two phases, both explicit and re-runnable:

  1. check  — verify quarto, the LaTeX engine (for PDF), the journal's Quarto
              extension and the bibliography. Never installs anything; reports
              the exact command to run when something is missing.
  2. render — `quarto render` to PDF and/or DOCX into papers/<slug>/build/, then
              rename the output to <slug>.pdf / <slug>.docx.

Usage:
    python scripts/paper_build.py --slug c15-2026 --format all
    python scripts/paper_build.py --slug c15-2026 --check-only
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900)
        return out.returncode, (out.stdout + out.stderr).strip()
    except Exception as exc:  # pragma: no cover
        return 1, str(exc)


def resolve_format(repo: Path, slug: str, paper_dir: Path) -> tuple[str, str, list[str], list[str]]:
    """Return (quarto_format, extension, ok_lines, problems)."""
    ok: list[str] = []
    problems: list[str] = []
    extension = ""
    quarto_format = "pdf"

    manifest = paper_dir / "manifest.yaml"
    journal = ""
    if manifest.is_file():
        journal = str(load_yaml(manifest).get("journal") or "")
    if journal:
        type_yaml = repo / "templates" / "journals" / journal / "type.yaml"
        if type_yaml.is_file():
            tj = load_yaml(type_yaml)
            quarto_format = tj.get("quarto_format") or "pdf"
            extension = tj.get("extension") or tj.get("quarto_extension") or ""
            ok.append(f"journal: {journal} (quarto_format={quarto_format})")
        else:
            problems.append(f"journal '{journal}' not in templates/journals/")
    else:
        problems.append("no journal set in manifest.yaml (run scripts/paper_journal.py)")

    return quarto_format, extension, ok, problems


def check(repo: Path, slug: str, fmt: str, paper_dir: Path) -> tuple[list[str], list[str], list[str], str, str]:
    need_pdf = fmt in ("pdf", "all")
    ok: list[str] = []
    warnings: list[str] = []
    problems: list[str] = []

    if shutil.which("quarto"):
        rc, ver = run(["quarto", "--version"])
        ok.append(f"quarto {ver.splitlines()[0] if ver else '?'}")
    else:
        problems.append("quarto not on PATH — https://quarto.org/docs/get-started/")

    qmd = paper_dir / "main.qmd"
    if not qmd.is_file():
        problems.append(f"main.qmd missing at {qmd} (run paper-new / paper-migrate first)")
    else:
        ok.append("main.qmd present")

    bib = paper_dir / "references.bib"
    has_entries = bib.is_file() and any(
        line.strip().startswith("@") for line in bib.read_text(encoding="utf-8", errors="ignore").splitlines()
    )
    if has_entries:
        ok.append("references.bib has entries")
    else:
        warnings.append("references.bib empty or has no @entries — bibliography will be blank")

    quarto_format, extension, fok, fprob = resolve_format(repo, slug, paper_dir)
    ok += fok
    problems += fprob

    if need_pdf and extension:
        ext_dir = paper_dir / "_extensions"
        installed = ext_dir.is_dir() and any(ext_dir.rglob("_extension.yml"))
        if installed:
            ok.append(f"Quarto extension present ({extension})")
        else:
            problems.append(
                f"Quarto extension '{extension}' not installed. "
                f"Run: cd papers/{slug}/paper && quarto add {extension}"
            )

    if need_pdf:
        has_engine = any(shutil.which(e) for e in ("xelatex", "pdflatex", "lualatex"))
        tinytex_ok = False
        if shutil.which("quarto"):
            _, tools = run(["quarto", "list", "tools"])
            tinytex_ok = "tinytex" in tools.lower() and "installed" in tools.lower()
        if has_engine or tinytex_ok:
            ok.append("LaTeX engine available")
        else:
            problems.append("no LaTeX engine for PDF. Install: quarto install tinytex")

    return ok, warnings, problems, quarto_format, extension


def render(repo: Path, slug: str, fmt: str, quarto_format: str, extension: str) -> int:
    paper_dir = repo / "papers" / slug / "paper"
    build_dir = repo / "papers" / slug / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    wants = ["pdf", "docx"] if fmt == "all" else [fmt]
    rc_total = 0
    for kind in wants:
        target = quarto_format if kind == "pdf" else "docx"
        if kind == "pdf" and not extension:
            target = "pdf"
        rc, out = run(
            ["quarto", "render", "main.qmd", "--to", target, "--output-dir", "../build"],
            cwd=paper_dir,
        )
        produced = build_dir / f"main.{kind}"
        final = build_dir / f"{slug}.{kind}"
        if rc == 0 and produced.is_file():
            if final.exists():
                final.unlink()
            produced.rename(final)
            print(f"  rendered {final}")
        elif rc == 0 and final.is_file():
            print(f"  rendered {final} (already named)")
        else:
            rc_total = 1
            print(f"  FAILED {kind} (quarto render --to {target})")
            print("  " + "\n  ".join(out.splitlines()[-15:]))
    return rc_total


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify and render a paper.")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--format", default="all", choices=["pdf", "docx", "all"])
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    paper_dir = repo / "papers" / args.slug / "paper"
    if not paper_dir.is_dir():
        raise SystemExit(f"ERROR: papers/{args.slug}/paper not found")

    ok, warnings, problems, quarto_format, extension = check(repo, args.slug, args.format, paper_dir)

    print("=== build environment check ===")
    print(f"paper: {args.slug}   format: {args.format}\n")
    for line in ok:
        print(f"  [ok]   {line}")
    for line in warnings:
        print(f"  [warn] {line}")
    for line in problems:
        print(f"  [MISS] {line}")

    if problems:
        print("\nRESULT: missing required components — fix the [MISS] items above.")
        return 1

    if args.check_only:
        print("\nRESULT: environment OK.")
        return 0

    print("\nRendering ...")
    return render(repo, args.slug, args.format, quarto_format, extension)


if __name__ == "__main__":
    raise SystemExit(main())

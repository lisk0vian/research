#!/usr/bin/env python3
"""paper_validate.py — enforce the repository structure contract.

Runs standalone (`python scripts/paper_validate.py`) and is imported by the test
suite so the same rules gate every pull request in CI. Exit code 0 = valid,
1 = at least one error.

Usage:
    python scripts/paper_validate.py [--root .] [--json] [--quiet]
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402
from _structure import (  # noqa: E402
    ARTEFACT_SCOPE_DIRS,
    FORBIDDEN_ARTEFACT_EXTENSIONS,
    MIGRATION_MARKER,
    REQUIRED_DIRS,
    REQUIRED_PAPER_FILES,
    REVIEW_FILES,
    SECRET_PATTERNS,
    SKILL_REGISTRY,
    SLUG_PATTERN,
)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}" if where else msg)

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}" if where else msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def _front_matter(text: str) -> str | None:
    """Return the YAML front-matter block of a .qmd/.md file, or None."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.DOTALL)
    return m.group(1) if m else None


def _parse_simple_yaml(text: str) -> dict:
    """Parse a tiny YAML mapping without requiring PyYAML at import time."""
    try:
        import yaml

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        # Fallback: only top-level "key:" lines (enough for a front-matter gate).
        out = {}
        for line in text.splitlines():
            m = re.match(r"^([A-Za-z_][\w-]*):", line)
            if m:
                out[m.group(1)] = True
        return out


# --------------------------------------------------------------------------- #
# Repo-level catalogs
# --------------------------------------------------------------------------- #
def check_authors(repo: Path, rep: Report) -> None:
    authors_dir = repo / "authors"
    if not authors_dir.is_dir():
        rep.error("authors/", "missing (shared author catalog)")
        return
    for f in sorted(authors_dir.glob("*.yaml")):
        data = load_yaml(f)
        where = f"authors/{f.name}"
        if data.get("id") != f.stem:
            rep.error(where, f"id '{data.get('id')}' must equal filename '{f.stem}'")
        if not data.get("name"):
            rep.error(where, "missing 'name'")


def check_journals(repo: Path, rep: Report) -> None:
    journals_dir = repo / "templates" / "journals"
    if not journals_dir.is_dir():
        rep.error("templates/journals/", "missing (shared journal catalog)")
        return
    for d in sorted(p for p in journals_dir.iterdir() if p.is_dir()):
        type_yaml = d / "type.yaml"
        if not type_yaml.is_file():
            rep.error(f"templates/journals/{d.name}/", "missing type.yaml")
            continue
        data = load_yaml(type_yaml)
        if not data.get("journal"):
            rep.error(f"templates/journals/{d.name}/type.yaml", "missing 'journal' name")


def check_skills(repo: Path, rep: Report) -> None:
    skills_dir = repo / ".agents" / "skills"
    if not skills_dir.is_dir():
        rep.warn(".agents/skills/", "missing")
        return
    for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            rep.error(f".agents/skills/{d.name}/", "missing SKILL.md")
            continue
        fm = _front_matter(skill_md.read_text(encoding="utf-8")) or ""
        name = _parse_simple_yaml(fm).get("name")
        if name != d.name:
            rep.error(
                f".agents/skills/{d.name}/SKILL.md",
                f"front-matter name '{name}' must equal folder name '{d.name}'",
            )
        if d.name not in SKILL_REGISTRY:
            rep.warn(f".agents/skills/{d.name}/", "not in the documented skill registry")


def check_claude_links(repo: Path, rep: Report) -> None:
    """Claude Code reads `.claude/skills/`; OpenCode reads `.agents/skills/` directly.

    The canonical skills are `.agents/skills/`, and `scripts/link_skills.py`
    mirrors them into `.claude/skills/` (a SessionStart hook keeps them fresh).
    Warn when that mirror is missing or out of date. Skipped on CI, where the
    links are machine-local and intentionally absent.
    """
    canonical = repo / ".agents" / "skills"
    link_dir = repo / ".claude" / "skills"
    if not canonical.is_dir():
        return
    skills = sorted(p.name for p in canonical.iterdir() if p.is_dir())

    if not link_dir.exists():
        if not os.environ.get("CI"):
            rep.warn(
                ".claude/skills/",
                "not set up — Claude Code reads .claude/skills (OpenCode reads "
                ".agents/skills directly); run `python scripts/link_skills.py`",
            )
        return

    missing = [s for s in skills if not (link_dir / s / "SKILL.md").is_file()]
    if missing:
        rep.warn(
            ".claude/skills/",
            f"missing links for: {', '.join(missing)} — run `python scripts/link_skills.py`",
        )
    stale = sorted(p.name for p in link_dir.iterdir() if p.name not in skills and os.path.lexists(p))
    if stale:
        rep.warn(
            ".claude/skills/",
            f"stale links: {', '.join(stale)} — run `python scripts/link_skills.py`",
        )


def check_no_tracked_secrets(repo: Path, rep: Report) -> None:
    if not (repo / ".git").exists():
        return
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=repo, capture_output=True, text=True, timeout=30
        )
    except Exception as exc:  # pragma: no cover
        rep.warn("git", f"could not list tracked files: {exc}")
        return
    for line in out.stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        base = path.lower()
        if base.endswith(".env.example"):
            continue
        names = [path, Path(path).name]
        if any(fnmatch.fnmatch(n.lower(), pat) for pat in SECRET_PATTERNS for n in names):
            rep.error(path, "looks like a secret/credential and must not be tracked")
        if Path(path).name == ".env":
            rep.error(path, ".env must not be committed (use .env.example)")


# --------------------------------------------------------------------------- #
# Per-paper checks
# --------------------------------------------------------------------------- #
def check_paper(repo: Path, root: Path, rep: Report) -> None:
    slug = root.name
    where = f"papers/{slug}"

    if not re.match(SLUG_PATTERN, slug):
        rep.error(where, f"folder name '{slug}' must be lowercase kebab/code (regex {SLUG_PATTERN})")

    for d in REQUIRED_DIRS:
        if not (root / d).is_dir():
            rep.error(where, f"missing required directory '{d}/'")

    if not (root / "paper" / "media").is_dir():
        rep.warn(where, "missing 'paper/media/' (figures folder)")

    for f in REQUIRED_PAPER_FILES:
        if not (root / f).is_file():
            rep.error(where, f"missing required file '{f}'")

    has_qmd = (root / "paper" / "main.qmd").is_file()
    has_marker = (root / MIGRATION_MARKER).is_file()
    if not has_qmd and not has_marker:
        rep.error(where, "need paper/main.qmd (or MIGRATION_PENDING.txt while migrating)")

    check_manifest(repo, root, rep)
    if has_qmd:
        check_qmd(root, rep)
    check_artefacts(root, rep)
    check_reviews(root, rep)
    rep.checked.append(where)


def check_manifest(repo: Path, root: Path, rep: Report) -> None:
    slug = root.name
    where = f"papers/{slug}/manifest.yaml"
    mp = root / "manifest.yaml"
    if not mp.is_file():
        return
    try:
        data = load_yaml(mp)
    except Exception as exc:
        rep.error(where, f"unparseable YAML: {exc}")
        return

    if data.get("paper") != slug:
        rep.error(where, f"'paper' must be '{slug}', found '{data.get('paper')}'")

    journal = data.get("journal")
    if not journal:
        rep.error(where, "missing 'journal'")
    elif not (repo / "templates" / "journals" / str(journal) / "type.yaml").is_file():
        rep.error(where, f"journal '{journal}' not found in templates/journals/")

    authors = data.get("authors")
    if not isinstance(authors, list) or not authors:
        rep.error(where, "'authors' must be a non-empty list")
        return
    seen_orders = set()
    for i, a in enumerate(authors):
        tag = f"{where} authors[{i}]"
        if not isinstance(a, dict):
            rep.error(tag, "must be a mapping with id/role/order")
            continue
        for key in ("id", "role", "order"):
            if a.get(key) in (None, ""):
                rep.error(tag, f"missing '{key}'")
        aid = a.get("id")
        if aid and not (repo / "authors" / f"{aid}.yaml").is_file():
            rep.error(tag, f"author id '{aid}' has no authors/{aid}.yaml")
        order = a.get("order")
        if order in seen_orders:
            rep.error(tag, f"duplicate author order {order}")
        seen_orders.add(order)


def check_qmd(root: Path, rep: Report) -> None:
    slug = root.name
    qmd = root / "paper" / "main.qmd"
    where = f"papers/{slug}/paper/main.qmd"
    fm = _front_matter(qmd.read_text(encoding="utf-8"))
    if fm is None:
        rep.error(where, "missing YAML front-matter block (--- ... ---)")
        return
    data = _parse_simple_yaml(fm)
    if not data.get("title"):
        rep.error(where, "front-matter missing 'title'")
    if not data.get("format"):
        rep.error(where, "front-matter missing 'format'")


def check_artefacts(root: Path, rep: Report) -> None:
    slug = root.name
    for scope in ARTEFACT_SCOPE_DIRS:
        base = root / scope
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if f.is_file() and f.suffix.lower() in FORBIDDEN_ARTEFACT_EXTENSIONS:
                rep.error(
                    f"papers/{slug}/{f.relative_to(root).as_posix()}",
                    f"{f.suffix} is banned in {scope}/ "
                    "(numbers must live in CSV/JSON, not spreadsheets)",
                )


def check_reviews(root: Path, rep: Report) -> None:
    slug = root.name
    reviews = root / "reviews"
    if not reviews.is_dir():
        return
    for round_dir in sorted(p for p in reviews.iterdir() if p.is_dir()):
        for fname in REVIEW_FILES:
            f = round_dir / fname
            if not f.is_file():
                rep.warn(
                    f"papers/{slug}/reviews/{round_dir.name}/",
                    f"missing '{fname}'",
                )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def check_cas_fixture(repo: Path, rep: Report) -> None:
    """TeX-free checks for the CAS fidelity fixture and its canonical
    extension. The actual render comparison against cas-sc-sample needs
    quarto/pdflatex and lives in scripts/cas_fidelity.py +
    tests/test_cas_fidelity.py; here we only ensure the pieces exist.
    """
    journal = (
        repo / "templates" / "journals"
        / "engineering-applications-of-artificial-intelligence"
    )
    if not journal.is_dir():
        return
    specimen = journal / "tests" / "specimen"
    for rel in (
        "specimen.qmd",
        "cas-refs.bib",
        "reference/cas-sc-sample.tex",
        "reference/cas-sc-sample.pdf",
        "figs/cas-grabs.pdf",
        "figs/cas-munnar-2024.jpg",
        "figs/cas-pic1.pdf",
        "thumbnails/cas-email.jpeg",
        "thumbnails/cas-url.jpeg",
    ):
        if not (specimen / rel).is_file():
            rep.error(
                f"templates/journals/{journal.name}/tests/specimen/{rel}",
                "missing CAS fidelity fixture file",
            )
    ext = (
        journal / "quarto-extension" / "_extensions"
        / "quarto-journals" / "elsevier-cas"
    )
    for rel in (
        "_extension.yml",
        "cas.lua",
        "cas-pre-ast.lua",
        "cas-docx.lua",
        "nologo.tex",
        "elsevier-harvard.csl",
        "reference.docx",
        "partials/before-body.tex",
        "partials/after-body.tex",
        "partials/hypersetup.latex",
        "partials/fonts.latex",
        "partials/font-settings.latex",
    ):
        if not (ext / rel).is_file():
            rep.error(
                f"templates/journals/{journal.name}/quarto-extension/"
                f"_extensions/quarto-journals/elsevier-cas/{rel}",
                "missing canonical extension file",
            )
    tool = journal / "quarto-extension" / "tools" / "make_reference_docx.py"
    if not tool.is_file():
        rep.error(
            f"templates/journals/{journal.name}/quarto-extension/tools/"
            "make_reference_docx.py",
            "missing the docx reference-doc generator",
        )
    if not (repo / "scripts" / "cas_fidelity.py").is_file():
        rep.error("scripts/cas_fidelity.py", "missing the CAS fidelity harness")


def validate_repo(root: str | Path | None = None) -> Report:
    repo = Path(root).resolve() if root else find_repo_root()
    rep = Report()

    if not (repo / "papers").is_dir():
        rep.error("", "no papers/ directory at repository root")
        return rep
    if not (repo / "AGENTS.md").is_file():
        rep.error("", "missing AGENTS.md at repository root")

    check_authors(repo, rep)
    check_journals(repo, rep)
    check_cas_fixture(repo, rep)
    check_skills(repo, rep)
    check_claude_links(repo, rep)
    check_no_tracked_secrets(repo, rep)

    papers_dir = repo / "papers"
    for root_dir in sorted(p for p in papers_dir.iterdir() if p.is_dir()):
        check_paper(repo, root_dir, rep)

    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate the repository structure contract.")
    ap.add_argument("--root", default=None, help="repository root (default: auto-detect)")
    ap.add_argument("--json", action="store_true", help="emit a JSON report")
    ap.add_argument("--quiet", action="store_true", help="only print errors")
    args = ap.parse_args()

    rep = validate_repo(args.root)

    if args.json:
        print(
            json.dumps(
                {"ok": rep.ok, "errors": rep.errors, "warnings": rep.warnings, "checked": rep.checked},
                indent=2,
            )
        )
        return 0 if rep.ok else 1

    if not args.quiet:
        for c in rep.checked:
            print(f"  [ok]   {c}")
        for w in rep.warnings:
            print(f"  [warn] {w}")
    for e in rep.errors:
        print(f"  [ERROR] {e}")
    if not args.quiet:
        print()
    print(
        f"RESULT: {'PASS' if rep.ok else 'FAIL'} "
        f"({len(rep.checked)} paper(s) checked, {len(rep.errors)} error(s), "
        f"{len(rep.warnings)} warning(s))"
    )
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

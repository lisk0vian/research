"""The structure contract: the real repo passes, and the validator catches drift."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import paper_validate  # noqa: E402


def test_repository_is_valid():
    """CI gate: the committed repo must satisfy the structure contract."""
    report = paper_validate.validate_repo(REPO_ROOT)
    assert report.ok, "structure errors:\n" + "\n".join(report.errors)
    assert report.checked, "no papers were checked"


def _write_min_paper(repo: Path, slug: str = "c99-2026") -> Path:
    root = repo / "papers" / slug
    for d in ("paper/media", "data", "experiments", "notebooks", "build"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "manifest.yaml").write_text(
        f"paper: {slug}\njournal: test-journal\nauthors:\n"
        "  - id: moises\n    role: corresponding\n    order: 1\n",
        encoding="utf-8",
    )
    (root / "paper" / "references.bib").write_text("@article{x, title={x}}\n", encoding="utf-8")
    (root / "paper" / "main.qmd").write_text(
        '---\ntitle: "T"\nformat:\n  pdf: default\n---\n\n# Intro\n', encoding="utf-8"
    )
    return root


def test_valid_min_paper_passes(mini_repo: Path):
    _write_min_paper(mini_repo)
    report = paper_validate.validate_repo(mini_repo)
    assert report.ok, report.errors


def test_missing_required_dir_fails(mini_repo: Path):
    root = _write_min_paper(mini_repo)
    (root / "experiments").rmdir()
    report = paper_validate.validate_repo(mini_repo)
    assert any("experiments" in e for e in report.errors)


def test_bad_slug_fails(mini_repo: Path):
    _write_min_paper(mini_repo, slug="Bad_Slug")
    report = paper_validate.validate_repo(mini_repo)
    assert any("folder name" in e for e in report.errors)


def test_manifest_paper_field_must_match_folder(mini_repo: Path):
    root = _write_min_paper(mini_repo)
    (root / "manifest.yaml").write_text(
        "paper: wrong\njournal: test-journal\nauthors:\n  - id: moises\n    role: a\n    order: 1\n",
        encoding="utf-8",
    )
    report = paper_validate.validate_repo(mini_repo)
    assert any("'paper' must be" in e for e in report.errors)


def test_unknown_author_fails(mini_repo: Path):
    root = _write_min_paper(mini_repo)
    (root / "manifest.yaml").write_text(
        "paper: c99-2026\njournal: test-journal\nauthors:\n  - id: ghost\n    role: a\n    order: 1\n",
        encoding="utf-8",
    )
    report = paper_validate.validate_repo(mini_repo)
    assert any("ghost" in e for e in report.errors)


def test_xlsx_artefact_fails(mini_repo: Path):
    root = _write_min_paper(mini_repo)
    (root / "outputs").mkdir()
    (root / "outputs" / "Tabla_99.xlsx").write_bytes(b"x")
    report = paper_validate.validate_repo(mini_repo)
    assert any("banned" in e for e in report.errors)


def test_migration_marker_allows_missing_qmd(mini_repo: Path):
    root = _write_min_paper(mini_repo)
    (root / "paper" / "main.qmd").unlink()
    (root / "paper" / "MIGRATION_PENDING.txt").write_text("pending\n", encoding="utf-8")
    report = paper_validate.validate_repo(mini_repo)
    assert report.ok, report.errors


def test_skill_name_must_match_folder(mini_repo: Path):
    (mini_repo / ".agents" / "skills" / "paper-new" / "SKILL.md").write_text(
        "---\nname: something-else\ndescription: test\n---\n", encoding="utf-8"
    )
    report = paper_validate.validate_repo(mini_repo)
    assert any("must equal folder name" in e for e in report.errors)


def test_missing_claude_link_warns(mini_repo: Path):
    _write_min_paper(mini_repo)
    (mini_repo / ".claude" / "skills").mkdir(parents=True)
    report = paper_validate.validate_repo(mini_repo)
    assert any("missing links" in w for w in report.warnings), report.warnings


def test_absent_claude_dir_is_silent_on_ci(mini_repo: Path, monkeypatch):
    _write_min_paper(mini_repo)
    monkeypatch.setenv("CI", "true")
    report = paper_validate.validate_repo(mini_repo)
    assert not any(".claude/skills" in w for w in report.warnings), report.warnings


def test_stray_directory_under_papers_is_not_a_paper(mini_repo: Path):
    """A __pycache__ under papers/ must not be reported as a malformed paper.

    It appears the moment any module is imported from under papers/, which
    papers/conftest.py does on every test run, so this used to turn the
    structure gate red for a reason unrelated to any paper.
    """
    _write_min_paper(mini_repo)
    cache = mini_repo / "papers" / "__pycache__"
    cache.mkdir()
    (cache / "conftest.cpython-312.pyc").write_bytes(b"\x00")
    report = paper_validate.validate_repo(mini_repo)
    assert report.ok, report.errors
    assert "__pycache__" not in report.checked


def test_dot_directory_under_papers_is_not_a_paper(mini_repo: Path):
    _write_min_paper(mini_repo)
    (mini_repo / "papers" / ".scratch").mkdir()
    report = paper_validate.validate_repo(mini_repo)
    assert report.ok, report.errors
    assert ".scratch" not in report.checked

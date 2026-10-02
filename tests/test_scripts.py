"""Smoke tests for the scripts: scaffold, journal retarget, format block."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import paper_validate  # noqa: E402
from _structure import format_block_from_type  # noqa: E402
from paper_build import make_latex_zip  # noqa: E402


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=cwd or REPO_ROOT, capture_output=True, text=True
    )


def test_paper_new_scaffolds_valid_paper(mini_repo: Path):
    proc = _run(
        "scripts/paper_new.py",
        "--root", str(mini_repo),
        "--slug", "c99-2026",
        "--title", "A test paper",
        "--journal", "test-journal",
        "--author", "moises:corresponding:1",
    )
    assert proc.returncode == 0, proc.stderr
    assert (mini_repo / "papers" / "c99-2026" / "paper" / "main.qmd").is_file()
    assert (mini_repo / "papers" / "c99-2026" / "manifest.yaml").is_file()
    report = paper_validate.validate_repo(mini_repo)
    assert report.ok, report.errors


def test_paper_new_rejects_existing_slug(mini_repo: Path):
    args = ["scripts/paper_new.py", "--root", str(mini_repo), "--slug", "c99-2026", "--journal", "test-journal"]
    assert _run(*args).returncode == 0
    second = _run(*args)
    assert second.returncode != 0
    assert "already exists" in (second.stderr + second.stdout)


def test_paper_new_rejects_bad_slug(mini_repo: Path):
    proc = _run("scripts/paper_new.py", "--root", str(mini_repo), "--slug", "Bad_Slug")
    assert proc.returncode != 0


def test_paper_new_rejects_unknown_journal(mini_repo: Path):
    proc = _run(
        "scripts/paper_new.py", "--root", str(mini_repo),
        "--slug", "c99-2026", "--journal", "nope-journal",
    )
    assert proc.returncode != 0


def test_paper_journal_retarget_updates_manifest_and_qmd(mini_repo: Path):
    _run(
        "scripts/paper_new.py", "--root", str(mini_repo),
        "--slug", "c99-2026", "--title", "T", "--journal", "test-journal",
    )
    proc = _run(
        "scripts/paper_journal.py", "--root", str(mini_repo),
        "--slug", "c99-2026", "--journal", "test-journal",
    )
    assert proc.returncode == 0, proc.stderr
    manifest = (mini_repo / "papers" / "c99-2026" / "manifest.yaml").read_text(encoding="utf-8")
    assert "journal: test-journal" in manifest
    qmd = (mini_repo / "papers" / "c99-2026" / "paper" / "main.qmd").read_text(encoding="utf-8")
    assert "format:" in qmd


def test_format_block_with_extension():
    block = format_block_from_type(
        {"journal": "Test", "extension": "quarto-journals/elsevier",
         "quarto_format": "elsevier-pdf", "cite_style": "number"}
    )
    assert "elsevier-pdf:" in block
    assert "docx: default" in block
    assert "model:" not in block
    assert "formatting:" not in block


def test_format_block_passes_model_and_formatting():
    block = format_block_from_type(
        {"journal": "Information Sciences", "extension": "quarto-journals/elsevier",
         "quarto_format": "elsevier-pdf", "cite_style": "numbername",
         "model": "1p", "formatting": "review"}
    )
    assert "cite-style: numbername" in block
    assert "model: 1p" in block
    assert "formatting: review" in block


def test_format_block_without_extension():
    block = format_block_from_type({"journal": "Springer", "quarto_format": "pdf"})
    assert "pdf: default" in block
    assert "docx: default" in block


def test_link_check_reports_missing_links(mini_repo: Path):
    proc = _run("scripts/link_skills.py", "--root", str(mini_repo), "--check")
    assert proc.returncode == 1, proc.stdout
    assert "missing Claude links" in proc.stdout


def test_make_latex_zip_packages_submission_sources(tmp_path: Path):
    """The zip must hold everything needed to compile main.tex standalone."""
    render = tmp_path / "render"
    build = tmp_path / "build"
    (render / "media").mkdir(parents=True)
    (render / "thumbnails").mkdir()
    (render / "main.tex").write_text("\\documentclass{cas-sc}\n", encoding="utf-8")
    (render / "cas-sc.cls").write_text("cls\n", encoding="utf-8")
    (render / "references.bib").write_text("@article{x, title={x}}\n", encoding="utf-8")
    (render / "main.bbl").write_text("\\bibitem{x}\n", encoding="utf-8")
    (render / "main.aux").write_text("junk\n", encoding="utf-8")  # excluded
    (render / "media" / "fig.pdf").write_bytes(b"%PDF-1.4")
    (render / "thumbnails" / "cas-email.jpeg").write_bytes(b"icon")
    (render / "cas-email.jpeg").write_bytes(b"flattened duplicate")  # excluded
    build.mkdir()

    ok, msg = make_latex_zip(render, build, "c99-2026", ["A bullet"])
    assert ok, msg
    with zipfile.ZipFile(build / "c99-2026-latex.zip") as z:
        assert z.testzip() is None
        assert set(z.namelist()) == {
            "main.tex",
            "cas-sc.cls",
            "references.bib",
            "main.bbl",
            "media/fig.pdf",
            "thumbnails/cas-email.jpeg",
            "highlights.txt",
        }
        assert z.read("highlights.txt") == b"A bullet\n"

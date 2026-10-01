"""Tests for the CAS fidelity harness (scripts/cas_fidelity.py).

The fixture tests are TeX-free and run everywhere (including CI). The full
rendering test needs quarto + pdflatex + poppler and is skipped when any of
them is missing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPECIMEN = (
    REPO / "templates" / "journals"
    / "engineering-applications-of-artificial-intelligence" / "tests" / "specimen"
)
HARNESS = REPO / "scripts" / "cas_fidelity.py"

# Everything the specimen needs to reproduce cas-sc-sample.tex (Elsevier CAS
# bundle v2.4, LPPL) without touching the network or the machine's Downloads.
FIXTURE = [
    "specimen.qmd",
    "cas-refs.bib",
    "reference/cas-sc-sample.tex",
    "reference/cas-sc-sample.pdf",
    "figs/cas-grabs.pdf",
    "figs/cas-munnar-2024.jpg",
    "figs/cas-pic1.pdf",
    "thumbnails/cas-email.jpeg",
    "thumbnails/cas-url.jpeg",
]

# Canonical extension files (single source of truth, copied at build time).
EXTENSION = (
    REPO / "templates" / "journals"
    / "engineering-applications-of-artificial-intelligence" / "quarto-extension"
    / "_extensions" / "quarto-journals" / "elsevier-cas"
)
EXTENSION_FILES = [
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
]
# the docx pipeline also needs the reference-doc generator (per-paper running
# heads are patched by scripts/paper_build.py through it)
DOCX_TOOL = EXTENSION.parents[2] / "tools" / "make_reference_docx.py"

RENDER_TOOLS = ("quarto", "pdflatex", "pdftoppm", "pdffonts", "pdftotext")
HAVE_RENDER_TOOLS = all(shutil.which(tool) for tool in RENDER_TOOLS)
# the docx suite only needs quarto + pdftoppm (figure rasterization)
HAVE_DOCX_TOOLS = all(shutil.which(tool) for tool in ("quarto", "pdftoppm"))


def test_specimen_fixture_complete() -> None:
    missing = [rel for rel in FIXTURE if not (SPECIMEN / rel).is_file()]
    assert not missing, f"missing specimen fixture files: {missing}"


def test_canonical_extension_complete() -> None:
    missing = [rel for rel in EXTENSION_FILES if not (EXTENSION / rel).is_file()]
    assert not missing, f"missing canonical extension files: {missing}"
    assert DOCX_TOOL.is_file(), "missing the reference-doc generator (docx)"


def test_reference_docx_is_a_valid_zip() -> None:
    import zipfile

    ref = EXTENSION / "reference.docx"
    with zipfile.ZipFile(ref) as z:
        assert z.testzip() is None, "reference.docx corrupt"
        names = set(z.namelist())
        for part in ("word/styles.xml", "word/document.xml", "word/header1.xml",
                     "word/footer1.xml", "word/fontTable.xml"):
            assert part in names, f"reference.docx lacks {part}"
        styles = z.read("word/styles.xml").decode("utf-8", "replace")
        assert 'w:ascii="STIX"' in styles, "reference.docx does not use STIX"


def test_reference_is_the_seven_page_sample() -> None:
    """Guard against a corrupted/wrong reference fixture."""
    tex = (SPECIMEN / "reference" / "cas-sc-sample.tex").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "\\documentclass[a4paper,fleqn]{cas-sc}" in tex
    assert "\\maketitle" in tex
    assert "\\bibliography{cas-refs}" in tex


@pytest.mark.skipif(
    not HAVE_RENDER_TOOLS,
    reason="needs quarto + pdflatex + poppler (pdftoppm/pdffonts/pdftotext)",
)
def test_specimen_matches_reference() -> None:
    """Full harness: renders the specimen and verifies the result against the
    official cas-sc-sample.tex/.pdf (text, fonts, layout, pixels)."""
    proc = subprocess.run(
        [sys.executable, str(HARNESS)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=900,
        errors="replace",
    )
    report = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"cas_fidelity.py failed:\n{report}"
    assert "RESULT: OK" in report, report


@pytest.mark.skipif(
    not HAVE_DOCX_TOOLS,
    reason="needs quarto + pdftoppm (figure rasterization)",
)
def test_docx_styles() -> None:
    """DOCX style suite: a temporary mini-document must carry the CAS look
    (STIX fonts, geometry, running heads, front-matter styles, footnotes,
    rasterized figure, numbered captions, Elsevier-Harvard citations)."""
    proc = subprocess.run(
        [sys.executable, str(HARNESS), "--docx"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=900,
        errors="replace",
    )
    report = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"cas_fidelity.py --docx failed:\n{report}"
    assert "RESULT: OK" in report, report

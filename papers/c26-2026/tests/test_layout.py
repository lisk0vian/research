"""Layout regression test for the rendered manuscript.

Runs scripts/paper_layout_check.py against build/c26-2026.pdf: no content may
leave the journal column (the engine's Overfull boxes and the ink bounding box
prove it), the display equations must be centered, every figure/table caption
and highlight must reach the PDF, and the bibliography must stay readable
(few authors per entry, every entry cited, none rendered as a wall of text).

Slow by design (it rasterizes every page) and needs the built PDF, which is
committed; it skips when the PDF is absent (fresh sparse checkout).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PAPER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PAPER_ROOT.parents[1]


def test_rendered_pdf_respects_the_layout():
    pdf = PAPER_ROOT / "build" / "c26-2026.pdf"
    if not pdf.is_file():
        pytest.skip("build/c26-2026.pdf not present; render it with paper_build.py first")
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "paper_layout_check.py"),
         "--slug", "c26-2026", "--root", str(REPO_ROOT)],
        capture_output=True, text=True, timeout=900,
    )
    print(proc.stdout)
    assert proc.returncode == 0, proc.stdout + proc.stderr

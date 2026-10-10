# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""scripts/paper_cover_letter.py: scaffold from metadata, lint the letter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TITLE = "A test paper on congestion"
MAIN = f"""---
title: "{TITLE}"
abstract: |
  We report an F1-score of 0.469 on 9,593 records.
---

# Results

The model reached an F1-score of 0.469 and a ROC-AUC of 0.798.
"""


def _paper(repo: Path) -> Path:
    paper = repo / "papers" / "t1"
    (paper / "paper").mkdir(parents=True)
    (paper / "manifest.yaml").write_text(
        "paper: t1\njournal: test-journal\nauthors:\n"
        "  - id: moises\n    role: corresponding\n    order: 1\n", encoding="utf-8")
    (paper / "paper" / "main.qmd").write_text(MAIN, encoding="utf-8")
    return paper


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "paper_cover_letter.py"),
         "--root", str(repo), "--slug", "t1", *args],
        capture_output=True, text=True)


def _fill(letter: Path, problem: str) -> None:
    text = letter.read_text(encoding="utf-8").splitlines(keepends=True)
    out, slots = [], iter([problem, "It fits the journal's scope."])
    for line in text:
        if line.startswith("[WRITE: position"):
            continue
        out.append(next(slots) + "\n" if line.startswith("[WRITE:") else line)
    letter.write_text("".join(out), encoding="utf-8")


def test_init_fills_metadata_and_leaves_slots(mini_repo: Path):
    paper = _paper(mini_repo)
    assert _run(mini_repo, "--init", "--date", "October 1, 2026").returncode == 0
    text = (paper / "paper" / "cover-letter.qmd").read_text(encoding="utf-8")
    assert f'"{TITLE}"' in text and "*Test Journal*" in text
    assert "October 1, 2026" in text and "m@x" in text
    assert "[WRITE:" in text
    # unfilled slots fail the check
    assert _run(mini_repo, "--check").returncode == 1
    # an existing letter is never overwritten silently
    assert _run(mini_repo, "--init").returncode != 0


def test_check_passes_a_faithful_letter(mini_repo: Path):
    paper = _paper(mini_repo)
    _run(mini_repo, "--init")
    _fill(paper / "paper" / "cover-letter.qmd",
          "Using 9,593 records we reach an F1-score of 0.469 and a ROC-AUC of 0.798.")
    proc = _run(mini_repo, "--check")
    assert proc.returncode == 0, proc.stdout


def test_check_rejects_invented_numbers_and_funding(mini_repo: Path):
    paper = _paper(mini_repo)
    _run(mini_repo, "--init")
    _fill(paper / "paper" / "cover-letter.qmd",
          "We reach an F1-score of 0.512. This work was supported by a national grant.")
    proc = _run(mini_repo, "--check")
    assert proc.returncode == 1
    assert "0.512" in proc.stdout and "funding" in proc.stdout
    # the journal can ask for funding in the letter; the number stays wrong
    proc = _run(mini_repo, "--check", "--allow", "funding")
    assert "funding" not in proc.stdout and "0.512" in proc.stdout

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""scripts/paper_title_page.py: title-page data true, complete, not leaked."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FRONT = """---
title: "A test paper"
journal:
  formatting: doubleblind
author:
  - name: "M"
    email: "m@x"
    affiliation: [{ref: aff-1}]
    cas:
      cormark: 1
affiliations:
  - id: aff-1
    name: Test Institute (TINST)
    address: Main Street 1
    city: Lima
    country: Peru
title-page:
  funding: "This research did not receive any specific grant."
  competing-interests: "The authors declare no competing interests."
---
"""


def _paper(repo: Path, front: str = FRONT, body: str = "# Introduction\n\nText.\n") -> None:
    paper = repo / "papers" / "t1" / "paper"
    paper.mkdir(parents=True)
    (paper.parent / "manifest.yaml").write_text(
        "paper: t1\njournal: test-journal\nauthors:\n"
        "  - id: moises\n    role: corresponding\n    order: 1\n", encoding="utf-8")
    (paper / "main.qmd").write_text(front + "\n" + body, encoding="utf-8")


def _check(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "paper_title_page.py"),
         "--root", str(repo), "--slug", "t1"], capture_output=True, text=True)


def test_complete_verified_title_page_passes(mini_repo: Path):
    _paper(mini_repo)
    proc = _check(mini_repo)
    assert proc.returncode == 0, proc.stdout


def test_unverified_or_incomplete_data_fails(mini_repo: Path):
    front = (FRONT.replace("    address: Main Street 1\n",
                           "    # TODO: verify the street\n    address: Main Street 1\n")
                  .replace("    city: Lima\n", "")
                  .replace('email: "m@x"', 'email: "other@x"'))
    _paper(mini_repo, front=front)
    out = _check(mini_repo).stdout
    assert "unverified (affiliations)" in out
    assert "missing city" in out
    assert "email 'other@x' differs" in out


def test_identifying_data_in_the_body_fails(mini_repo: Path):
    _paper(mini_repo, body="# Acknowledgements\n\nWe thank the TINST staff.\n")
    proc = _check(mini_repo)
    assert proc.returncode == 1 and "TINST" in proc.stdout

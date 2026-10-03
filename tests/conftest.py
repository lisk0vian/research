# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Shared pytest fixtures for the repository structure tests."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_ROOT = REPO_ROOT
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A minimal but valid repo skeleton to exercise scaffold + validator."""
    repo = tmp_path / "repo"
    (repo / "papers").mkdir(parents=True)
    (repo / "authors").mkdir()
    (repo / "templates" / "journals" / "test-journal").mkdir(parents=True)
    (repo / ".agents" / "skills" / "paper-new").mkdir(parents=True)

    (repo / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (repo / "authors" / "moises.yaml").write_text(
        'id: moises\nname: "M"\naffiliation: "X"\nemail: "m@x"\norcid: "TODO"\n',
        encoding="utf-8",
    )
    (repo / "templates" / "journals" / "test-journal" / "type.yaml").write_text(
        'journal: "Test Journal"\npublisher: elsevier\nformat: latex\n'
        'extension: ""\nquarto_format: pdf\ncite_style: number\n',
        encoding="utf-8",
    )
    (repo / ".agents" / "skills" / "paper-new" / "SKILL.md").write_text(
        "---\nname: paper-new\ndescription: test\n---\n\n# paper-new\n",
        encoding="utf-8",
    )
    shutil.copytree(REPO_ROOT / "templates" / "paper", repo / "templates" / "paper")
    return repo


# The CAS fidelity suite compiles LaTeX and compares the output against the
# committed reference PDF. Measured on this machine the two tests in it take
# 29 of the 36 seconds the gate spent running tests, so it is the single
# heaviest thing in CI. The gate runs `pytest -m "not slow"`; the contract this
# suite protects - that a journal template still renders its specimen - stays
# checked locally and before a release.
_SLOW_FILES = {(_ROOT / "tests" / "test_cas_fidelity.py").resolve()}


def pytest_collection_modifyitems(items):
    """Tag the CAS fidelity file as slow.

    The hook is session-scoped and receives every collected item, not only the
    ones from this directory, so the path filter is what keeps the rest of the
    suite out of the deselection.
    """
    for item in items:
        path = (getattr(item, "path", None) or Path(str(item.fspath))).resolve()
        if path in _SLOW_FILES:
            item.add_marker(pytest.mark.slow)

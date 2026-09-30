"""Shared pytest fixtures for the repository structure tests."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
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

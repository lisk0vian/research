"""Tests for paper_sparse_clone.py: path building, URL parsing, verification.

No network access: the clone step is exercised through its pure helpers, and
`verify()` runs against a fake destination tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import paper_sparse_clone as psc  # noqa: E402


def test_sparse_paths_excludes_paper_dir():
    paths = psc.sparse_paths("c20-2026")
    assert paths == [
        "papers/c20-2026/experiments",
        "papers/c20-2026/notebooks",
    ]
    assert not any(p.endswith("/paper") for p in paths)


def test_clone_url_is_https_and_tokenless():
    url = psc.clone_url("lisk0vian/research")
    assert url == "https://github.com/lisk0vian/research.git"
    assert "@" not in url  # no embedded credentials


def test_verify_accepts_complete_checkout(tmp_path: Path):
    paper = tmp_path / "papers" / "c20-2026"
    (tmp_path / ".git").mkdir()
    (paper / "experiments").mkdir(parents=True)
    (paper / "notebooks").mkdir(parents=True)
    (paper / "experiments" / "config.yaml").write_text("project: X\n", encoding="utf-8")
    assert psc.verify(tmp_path, "c20-2026") == []


def test_verify_flags_missing_sentinel(tmp_path: Path):
    paper = tmp_path / "papers" / "c20-2026"
    (tmp_path / ".git").mkdir()
    (paper / "experiments").mkdir(parents=True)
    (paper / "notebooks").mkdir(parents=True)
    problems = psc.verify(tmp_path, "c20-2026")
    assert any("config.yaml" in p for p in problems)


def test_verify_flags_not_a_checkout(tmp_path: Path):
    problems = psc.verify(tmp_path, "c20-2026")
    assert problems == [f"{tmp_path} is not a git checkout"]


def test_verify_flags_missing_sparse_path(tmp_path: Path):
    paper = tmp_path / "papers" / "c20-2026"
    (tmp_path / ".git").mkdir()
    (paper / "experiments").mkdir(parents=True)
    (paper / "experiments" / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    problems = psc.verify(tmp_path, "c20-2026")
    assert any("notebooks" in p for p in problems)


def test_repo_slug_parses_ssh_remote():
    assert psc.repo_slug(REPO_ROOT) == "lisk0vian/research"


def test_cli_check_exit_codes(tmp_path: Path):
    import subprocess

    proc = subprocess.run(
        [sys.executable, "scripts/paper_sparse_clone.py",
         "--slug", "c20-2026", "--dest", str(tmp_path), "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "not a git checkout" in proc.stdout
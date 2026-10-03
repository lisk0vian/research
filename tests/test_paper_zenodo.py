# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for paper_zenodo.py: file collection, metadata, draft/publish states.

The invariant that matters: nothing becomes public by accident. A draft must
stay a draft (no DOI in the manifest, no BibTeX entry) until an explicit
publish step runs. Everything network-bound is left to manual runs against
sandbox/production; these tests cover the offline contract.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import paper_zenodo as zen  # noqa: E402
from _repo import load_yaml  # noqa: E402


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    """A minimal paper with experiments, a notebook and one author."""
    repo = tmp_path / "repo"
    p = repo / "papers" / "c99-2026"
    (p / "experiments" / "src").mkdir(parents=True)
    (p / "notebooks").mkdir(parents=True)
    (p / "paper").mkdir(parents=True)
    (p / "experiments" / "run_all.py").write_text("print('run')\n", encoding="utf-8")
    (p / "experiments" / "src" / "core.py").write_text("X = 1\n", encoding="utf-8")
    (p / "experiments" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (p / "experiments" / "model.pkl").write_bytes(b"\x00" * 16)
    (p / "experiments" / "__pycache__").mkdir()
    (p / "experiments" / "__pycache__" / "core.pyc").write_bytes(b"\x00")
    (p / "notebooks" / "experiments.ipynb").write_text('{"cells": []}\n', encoding="utf-8")
    (p / "paper" / "references.bib").write_text("", encoding="utf-8")
    (p / "manifest.yaml").write_text(
        'paper: c99-2026\ntitle: "Test paper"\njournal: test-journal\n'
        'authors:\n  - id: ana\n    role: corresponding\n    order: 1\n',
        encoding="utf-8",
    )
    (repo / "authors").mkdir(parents=True)
    (repo / "authors" / "ana.yaml").write_text(
        'id: ana\nname: "Ana Tester"\naffiliation: "SENATI, Perú"\n'
        'email: "a@x.pe"\norcid: "0000-0001-0002-0003"\n',
        encoding="utf-8",
    )
    (repo / "authors" / "ghost.yaml").write_text(
        'id: ghost\nname: "Ghost"\naffiliation: "X"\norcid: "TODO"\n',
        encoding="utf-8",
    )
    return p


def _repo_of(paper: Path) -> Path:
    return paper.parents[1]


def _run(*args: str, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/paper_zenodo.py", "--root", str(root), *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


# --- file collection ---------------------------------------------------------

def test_collect_includes_code_and_notebook(paper):
    names = {zen._zenodo_filename(f, paper, "experiments") for f in zen.collect_files(paper)}
    assert "run_all.py" in names
    assert "src/core.py" in names
    assert "experiments.ipynb" in names


def test_collect_excludes_secrets_caches_and_heavy_files(paper):
    names = {zen._zenodo_filename(f, paper, "experiments") for f in zen.collect_files(paper)}
    assert ".env" not in names
    assert "model.pkl" not in names
    assert not any("__pycache__" in n for n in names)


def test_collect_excludes_empty_files(paper):
    # Zenodo rejects empty files, so placeholders like .gitkeep never upload.
    (paper / "experiments" / ".gitkeep").write_text("", encoding="utf-8")
    names = {zen._zenodo_filename(f, paper, "experiments") for f in zen.collect_files(paper)}
    assert ".gitkeep" not in names


def test_collect_missing_source_dir_fails_clearly(paper):
    with pytest.raises(SystemExit, match="--source"):
        zen.collect_files(paper, "nope-dir")


def test_notebook_maps_to_flat_name(paper):
    nb = paper / "notebooks" / "experiments.ipynb"
    assert zen._zenodo_filename(nb, paper, "experiments") == "experiments.ipynb"
    code = paper / "experiments" / "src" / "core.py"
    assert zen._zenodo_filename(code, paper, "experiments") == "src/core.py"


# --- metadata ----------------------------------------------------------------

def test_build_metadata_resolves_authors(paper):
    manifest = load_yaml(paper / "manifest.yaml")
    meta = zen.build_metadata(_repo_of(paper), paper, manifest, version="1.0.0")
    assert meta["upload_type"] == "software"
    assert meta["creators"] == [
        {"name": "Ana Tester", "orcid": "0000-0001-0002-0003",
         "affiliation": "SENATI, Perú"}
    ]


def test_build_metadata_skips_todo_orcid(paper):
    manifest = load_yaml(paper / "manifest.yaml")
    manifest["authors"].append({"id": "ghost", "role": "author", "order": 2})
    meta = zen.build_metadata(_repo_of(paper), paper, manifest)
    ghost = next(c for c in meta["creators"] if c["name"] == "Ghost")
    assert "orcid" not in ghost


# --- manifest states -----------------------------------------------------------

def test_draft_state_keeps_doi_out_of_manifest(paper):
    zen.update_manifest_draft(
        paper, deposit_id=123, draft_url="https://zenodo.org/deposit/123",
        reserved_doi="10.5281/zenodo.123", version="1.0.0",
    )
    manifest = load_yaml(paper / "manifest.yaml")
    assert manifest["zenodo_status"] == "draft"
    assert manifest["zenodo_deposit_id"] == 123
    assert "zenodo_doi" not in manifest


def test_manifest_update_preserves_comments_and_formatting(paper):
    # The manifest is hand-maintained: comments and style must survive.
    (paper / "manifest.yaml").write_text(
        "# header comment\npaper: c99-2026  # trailing note\ntitle: T\n",
        encoding="utf-8",
    )
    zen.update_manifest_draft(
        paper, deposit_id=7, draft_url="https://x/7",
        reserved_doi="10.1/7", version="1.0.0",
    )
    content = (paper / "manifest.yaml").read_text(encoding="utf-8")
    assert "# header comment" in content
    assert "paper: c99-2026  # trailing note" in content
    assert "zenodo_status: draft" in content


def test_publish_state_replaces_draft_keys(paper):
    zen.update_manifest_draft(
        paper, deposit_id=123, draft_url="https://zenodo.org/deposit/123",
        reserved_doi="10.5281/zenodo.123", version="1.0.0",
    )
    zen.update_manifest_published(
        paper, doi="10.5281/zenodo.123", record_id=456,
        record_url="https://zenodo.org/records/456", version="1.0.0",
    )
    manifest = load_yaml(paper / "manifest.yaml")
    assert manifest["zenodo_status"] == "published"
    assert manifest["zenodo_doi"] == "10.5281/zenodo.123"
    assert "zenodo_draft_url" not in manifest
    assert "zenodo_reserved_doi" not in manifest


def test_bibtex_entry_is_idempotent(paper):
    manifest = load_yaml(paper / "manifest.yaml")
    repo = _repo_of(paper)
    zen.update_references_bib(paper, manifest, "10.5281/zenodo.123", repo)
    zen.update_references_bib(paper, manifest, "10.5281/zenodo.123", repo)
    content = (paper / "paper" / "references.bib").read_text(encoding="utf-8")
    assert content.count("@software{c99-2026-code,") == 1
    assert "Ana Tester" in content


# --- CLI guards (offline) ------------------------------------------------------

def test_draft_and_publish_are_mutually_exclusive(paper):
    proc = _run("--slug", "c99-2026", "--draft", "--publish", root=_repo_of(paper))
    assert proc.returncode != 0
    assert "mutually exclusive" in (proc.stderr + proc.stdout)


def test_delete_without_draft_fails_clearly(paper):
    proc = _run("--slug", "c99-2026", "--delete-draft", "--yes", root=_repo_of(paper))
    assert proc.returncode != 0
    assert "no draft deposit" in (proc.stderr + proc.stdout)


def test_delete_dry_run_keeps_everything(paper):
    zen.update_manifest_draft(
        paper, deposit_id=7, draft_url="https://x/7",
        reserved_doi="10.1/7", version="1.0.0",
    )
    proc = _run("--slug", "c99-2026", "--delete-draft", root=_repo_of(paper))
    assert proc.returncode == 0, proc.stderr
    assert "DRY RUN" in proc.stdout
    manifest = load_yaml(paper / "manifest.yaml")
    assert manifest["zenodo_deposit_id"] == 7


def test_publish_without_draft_fails_clearly(paper):
    proc = _run("--slug", "c99-2026", "--publish", root=_repo_of(paper))
    assert proc.returncode != 0
    assert "no draft deposit" in (proc.stderr + proc.stdout)


def test_dry_run_touches_nothing_but_zenodo_json(paper):
    proc = _run("--slug", "c99-2026", root=_repo_of(paper))
    assert proc.returncode == 0, proc.stderr
    assert "DRY RUN" in proc.stdout
    manifest = load_yaml(paper / "manifest.yaml")
    assert "zenodo_status" not in manifest
    assert "zenodo_doi" not in manifest
    record = json.loads((paper / "experiments" / "zenodo.json").read_text(encoding="utf-8"))
    assert record["metadata"]["creators"][0]["name"] == "Ana Tester"

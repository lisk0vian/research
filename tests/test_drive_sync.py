"""Tests for paper_drive_sync.py: target discovery, in-place uploads, clash refusal.

The invariant that matters: a target with a known Drive id must be uploaded with
`fileId`, never with `parentFolderId`. Recreating a file changes its id, which
changes the Colab url and burns one of the account's concurrent runtime sessions.
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

import paper_drive_sync as sync  # noqa: E402


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    p = tmp_path / "papers" / "c99-2026"
    (p / "experiments").mkdir(parents=True)
    (p / "notebooks").mkdir(parents=True)
    (p / "experiments" / "00_a.py").write_text("print('a')\n", encoding="utf-8")
    (p / "experiments" / "config.yaml").write_text("project: X\n", encoding="utf-8")
    (p / "notebooks" / "experiments.ipynb").write_text('{"cells": []}\n', encoding="utf-8")
    return p


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/paper_drive_sync.py", *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


# --- target discovery ------------------------------------------------------

def test_targets_include_notebook_and_code(paper):
    targets = {t["remote"] for t in sync.target_specs(paper)}
    assert "experiments.ipynb" in targets
    assert "code/00_a.py" in targets
    assert "code/config.yaml" in targets


def test_notebook_carries_the_ipynb_mime(paper):
    nb = next(t for t in sync.target_specs(paper) if t["is_notebook"])
    assert nb["mime_type"] == "application/x-ipynb+json"


def test_secrets_and_caches_are_never_uploaded(paper):
    (paper / "experiments" / ".env").write_text("TOKEN=1\n", encoding="utf-8")
    (paper / "experiments" / ".env.example").write_text("A=1\n", encoding="utf-8")
    (paper / "experiments" / "__pycache__").mkdir()
    (paper / "experiments" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    names = {t["remote"] for t in sync.target_specs(paper)}
    assert not any(".env" in n for n in names)
    assert not any("pycache" in n for n in names)


def test_non_source_suffixes_are_skipped(paper):
    (paper / "experiments" / "model.pkl").write_bytes(b"\x00")
    names = {t["remote"] for t in sync.target_specs(paper)}
    assert not any(n.endswith(".pkl") for n in names)


# --- the in-place guarantee ------------------------------------------------

def test_known_id_yields_fileid_not_parentfolder(paper, capsys):
    sync.save_ids(paper, {"experiments.ipynb": "FILEID1"})
    updates, clashes = sync.plan(paper)
    sync.print_calls(paper, updates, "FOLDER")
    out = capsys.readouterr().out
    call = next(json.loads(l) for l in out.splitlines() if l.startswith("{"))
    assert call["arguments"]["fileId"] == "FILEID1"
    assert "parentFolderId" not in call["arguments"]


def test_unknown_id_yields_parentfolder(paper, capsys):
    updates, clashes = sync.plan(paper)
    sync.print_calls(paper, updates, "FOLDER")
    out = capsys.readouterr().out
    call = next(json.loads(l) for l in out.splitlines() if l.startswith("{"))
    assert call["arguments"]["parentFolderId"] == "FOLDER"
    assert call["arguments"]["mimeType"] == "application/x-ipynb+json"


def test_every_in_place_target_keeps_its_id(paper):
    ids = {"experiments.ipynb": "A", "code/00_a.py": "B", "code/config.yaml": "C"}
    sync.save_ids(paper, ids)
    updates, _ = sync.plan(paper)
    assert {u["file_id"] for u in updates} == {"A", "B", "C"}
    assert all(u["file_id"] for u in updates)


# --- clash refusal --------------------------------------------------------

def test_clash_when_remote_exists_without_a_recorded_id(paper):
    updates, clashes = sync.plan(paper, remote_names={"experiments.ipynb": "LIVE"})
    assert "experiments.ipynb" in {c["remote"] for c in clashes}


def test_recorded_id_matching_drive_is_in_place(paper):
    sync.save_ids(paper, {"experiments.ipynb": "LIVE"})
    updates, clashes = sync.plan(paper, remote_names={"experiments.ipynb": "LIVE"})
    assert clashes == []
    nb = next(u for u in updates if u["remote"] == "experiments.ipynb")
    assert nb["file_id"] == "LIVE"


def test_stale_id_is_refused(paper):
    """The exact mistake that produced two copies of 05_features_local.py."""
    sync.save_ids(paper, {"experiments.ipynb": "OLD_ID"})
    _, clashes = sync.plan(paper, remote_names={"experiments.ipynb": "NEW_ID"})
    assert "experiments.ipynb" in {c["remote"] for c in clashes}
    entry = next(c for c in clashes if c["remote"] == "experiments.ipynb")
    assert entry["live_id"] == "NEW_ID"


def test_id_missing_from_drive_is_refused(paper):
    sync.save_ids(paper, {"experiments.ipynb": "GONE"})
    _, clashes = sync.plan(paper, remote_names={})
    assert "experiments.ipynb" in {c["remote"] for c in clashes}


def test_no_clash_when_remote_is_absent(paper):
    _, clashes = sync.plan(paper, remote_names={"code/other.py": "X"})
    assert clashes == []


def test_accepts_a_bare_name_list(paper):
    """listFolder output may be passed as names only; ids stay unknown."""
    _, clashes = sync.plan(paper, remote_names=["experiments.ipynb"])
    assert "experiments.ipynb" in {c["remote"] for c in clashes}


def test_clash_exits_nonzero_with_a_fix_hint(paper):
    proc = _run("--slug", "c99-2026", "--root", str(paper.parents[1]),
                "--remote-names", json.dumps({"experiments.ipynb": "LIVE"}))
    assert proc.returncode == 1
    assert "Refusing to proceed" in proc.stdout
    assert "--record" in proc.stdout


# --- manifest --------------------------------------------------------------

def test_record_writes_the_manifest(paper):
    _run("--slug", "c99-2026", "--root", str(paper.parents[1]),
         "--record", "code/00_a.py", "XYZ")
    assert sync.load_ids(paper)["code/00_a.py"] == "XYZ"


def test_manifest_roundtrips(paper):
    sync.save_ids(paper, {"a": "1", "b": "2"})
    assert json.loads(sync.ids_path(paper).read_text(encoding="utf-8")) == {"a": "1", "b": "2"}


def test_missing_manifest_is_not_an_error(paper):
    assert sync.load_ids(paper) == {}


def test_plan_reports_all_in_place_for_a_complete_manifest(paper):
    # A manifest is "complete" when every target has a real id; a null entry is
    # not an id and must still be treated as unrecorded.
    ids = {u["remote"]: f"ID-{i}" for i, u in enumerate(sync.target_specs(paper))}
    sync.save_ids(paper, ids)
    updates, clashes = sync.plan(paper)
    assert clashes == []
    assert {u["file_id"] for u in updates} == set(ids.values())


def test_null_id_is_treated_as_unrecorded(paper):
    sync.save_ids(paper, {"experiments.ipynb": None})
    updates, _ = sync.plan(paper)
    nb = next(u for u in updates if u["remote"] == "experiments.ipynb")
    assert nb["file_id"] is None


def test_unknown_slug_exits_nonzero():
    proc = _run("--slug", "does-not-exist")
    assert proc.returncode != 0
    assert "not found" in proc.stderr


# --- the real manifest -----------------------------------------------------

def test_real_paper_manifest_is_in_place():
    """The shipped c20-2026 manifest must upload everything in place."""
    paper = REPO_ROOT / "papers" / "c20-2026"
    if not sync.ids_path(paper).is_file():
        pytest.skip("machine-local manifest not present")
    updates, clashes = sync.plan(paper)
    assert clashes == []
    assert updates, "expected targets"
    assert all(u["file_id"] for u in updates), "every target must be in place"
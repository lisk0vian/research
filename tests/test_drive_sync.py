# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for paper_drive_sync.py: target discovery, in-place uploads, clash refusal.

The invariant that matters: a target with a known Drive id must be uploaded with
`fileId`, never with `parentFolderId`. Recreating a file changes its id, which
changes the Colab url and burns one of the account's concurrent runtime sessions.
"""

from __future__ import annotations

import json
import re
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

def test_outputs_and_logs_are_never_targets(paper):
    """Colab owns outputs/ on Drive; a local copy pushed over it erases the real run."""
    logs = paper / "outputs" / "logs"
    logs.mkdir(parents=True)
    (logs / "00_verify_source.log").write_text("log\n", encoding="utf-8")
    (logs / "errors.log").write_text("", encoding="utf-8")
    assert not [s for s in sync.target_specs(paper) if s["remote"].startswith("outputs/")]


def test_target_names_never_carry_a_timestamp(paper):
    """A timestamped filename would mint a new Drive id every run."""
    for s in sync.target_specs(paper):
        assert not re.search(r"\d{8}-\d{6}|\d{4}-\d{2}-\d{2}T", s["remote"]), s["remote"]


def _with_runtime(paper):
    scripts = paper.parents[1] / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "_colab_runtime.py").write_text("# runtime\n", encoding="utf-8")


def test_shared_runtime_is_a_target_of_a_colab_paper(paper):
    _with_runtime(paper)
    (paper / "experiments" / "colab.yaml").write_text("title: X\n", encoding="utf-8")
    spec = next(s for s in sync.target_specs(paper) if s["remote"] == "code/_colab_runtime.py")
    assert spec["local"] == paper.parents[1] / "scripts" / "_colab_runtime.py"


def test_shared_runtime_is_not_pushed_to_a_paper_without_colab_yaml(paper):
    _with_runtime(paper)
    assert "code/_colab_runtime.py" not in {s["remote"] for s in sync.target_specs(paper)}


def test_new_code_file_is_created_inside_the_code_folder(paper, capsys):
    """Without the code/ folder id a new file lands in the project root."""
    sync.save_ids(paper, {"code/": "CODEFOLDER", "experiments.ipynb": "NB"})
    updates, _ = sync.plan(paper)
    sync.print_calls(paper, [u for u in updates if u["remote"] == "code/00_a.py"], "ROOT")
    call = json.loads(capsys.readouterr().out.strip())
    assert call["arguments"]["parentFolderId"] == "CODEFOLDER"


def test_new_code_file_without_a_code_folder_id_is_refused(paper):
    sync.save_ids(paper, {"experiments.ipynb": "NB"})
    proc = _run("--slug", "c99-2026", "--root", str(paper.parents[1]),
                "--print-calls", "--folder-id", "ROOT")
    assert proc.returncode == 1
    assert "--record code/" in proc.stderr
    assert "uploadFile" not in proc.stdout


# --- content hashing: upload only what changed -----------------------------

def test_hashes_manifest_roundtrip(paper):
    sync.save_hashes(paper, {"code/a.py": "abc"})
    assert sync.load_hashes(paper) == {"code/a.py": "abc"}


def test_absent_hash_manifest_means_everything_changed(paper):
    """A lost manifest costs one full upload; a wrong one hides a missing file."""
    assert sync.load_hashes(paper) == {}


def test_corrupt_hash_manifest_is_treated_as_absent(paper):
    sync.hashes_path(paper).write_text("{not json", encoding="utf-8")
    assert sync.load_hashes(paper) == {}


def test_hash_manifest_non_string_values_are_dropped(paper):
    sync.hashes_path(paper).write_text('{"a": 1, "b": "x"}', encoding="utf-8")
    assert sync.load_hashes(paper) == {"b": "x"}


def _one_target(paper):
    exp = paper / "experiments"
    exp.mkdir(parents=True, exist_ok=True)
    f = exp / "00_a.py"
    f.write_text("def main():\n    pass\n", encoding="utf-8")
    return next(s for s in sync.target_specs(paper) if s["remote"] == "code/00_a.py")


def test_unchanged_file_with_a_drive_id_is_skipped(paper):
    spec = _one_target(paper)
    spec["file_id"] = "LIVE"
    changed, unchanged = sync.split_by_change(paper, [spec], {"code/00_a.py": sync.file_sha256(spec["local"])})
    assert [s["remote"] for s in unchanged] == ["code/00_a.py"] and changed == []


def test_changed_content_is_uploaded_even_with_a_matching_id(paper):
    spec = _one_target(paper)
    spec["file_id"] = "LIVE"
    changed, unchanged = sync.split_by_change(paper, [spec], {"code/00_a.py": "stale-hash"})
    assert [s["remote"] for s in changed] == ["code/00_a.py"] and unchanged == []


def test_matching_hash_without_a_drive_id_is_still_uploaded(paper):
    """The exact bug class that produced two copies of 05_features_local.py."""
    spec = _one_target(paper)
    spec["file_id"] = None
    changed, unchanged = sync.split_by_change(paper, [spec], {"code/00_a.py": sync.file_sha256(spec["local"])})
    assert [s["remote"] for s in changed] == ["code/00_a.py"] and unchanged == []


def test_mark_uploaded_rejects_a_path_that_is_not_a_target(paper):
    _one_target(paper)
    proc = _run("--slug", "c99-2026", "--root", str(paper.parents[1]),
                "--mark-uploaded", "code/nope.py")
    assert proc.returncode == 2
    assert "not a sync target" in proc.stderr


def test_missing_folder_id_refuses_instead_of_emitting_an_empty_one(paper):
    """parentFolderId:"" is a malformed call, and its natural fix duplicates files."""
    _one_target(paper)
    sync.save_ids(paper, {"code/": "CODEFOLDER"})  # only the root-level notebook is new
    proc = _run("--slug", "c99-2026", "--root", str(paper.parents[1]),
                "--print-calls", "--folder-id", "")
    assert proc.returncode == 1
    assert "would be created" in proc.stderr
    assert "uploadFile" not in proc.stdout

def test_a_second_notebook_is_a_target_at_the_folder_root(paper):
    (paper / "notebooks" / "figures.ipynb").write_text('{"cells": []}\n', encoding="utf-8")
    nbs = {t["remote"]: t for t in sync.target_specs(paper) if t["is_notebook"]}
    assert set(nbs) == {"experiments.ipynb", "figures.ipynb"}
    assert nbs["figures.ipynb"]["remote_dir"] == ""
    assert nbs["figures.ipynb"]["mime_type"] == "application/x-ipynb+json"

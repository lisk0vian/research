# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Atomic writes and the EXP_ENV check.

The failure these guard against is quiet: a Colab disconnect or a crash in the
middle of `to_csv` used to leave a truncated CSV on disk, and the next stage
reads that as a complete file. Nothing errors; the pipeline just produces wrong
numbers one step downstream.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

PAPER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAPER_ROOT / "experiments"))

import _common  # noqa: E402


def _temp_siblings(directory: Path) -> list[Path]:
    """Leftover temp files from an interrupted write."""
    return [p for p in directory.iterdir() if p.name.endswith(".tmp")]


def test_atomic_write_replaces_only_on_success(tmp_path: Path):
    target = tmp_path / "out.csv"
    _common.atomic_write_csv(pd.DataFrame({"a": [1]}), target)
    assert pd.read_csv(target)["a"].tolist() == [1]

    def explode(p: Path) -> None:
        p.write_text("garbage\nnot,a,valid\ncsv", encoding="utf-8")
        raise RuntimeError("died mid-write")

    with pytest.raises(RuntimeError, match="died mid-write"):
        _common._atomic_write(target, explode)

    # The previous file survived intact rather than being replaced by a partial.
    assert pd.read_csv(target)["a"].tolist() == [1]


def test_failed_write_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "out.json"
    with pytest.raises(ValueError):
        _common._atomic_write(target, lambda p: (_ for _ in ()).throw(ValueError()))
    assert _temp_siblings(tmp_path) == []


def test_successful_write_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "out.json"
    _common.atomic_write_json({"a": 1}, target)
    assert _temp_siblings(tmp_path) == []
    assert target.read_text(encoding="utf-8").strip().startswith("{")


def test_temp_file_is_a_sibling_so_replace_is_atomic(tmp_path: Path):
    """os.replace only guarantees atomicity within one filesystem."""
    seen: list[Path] = []

    def capture(p: Path) -> None:
        seen.append(p.parent)
        p.write_text("x", encoding="utf-8")

    _common._atomic_write(tmp_path / "deep" / "out.txt", capture)
    assert seen and seen[0] == tmp_path / "deep"


def test_write_table_is_atomic(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(_common, "TABLES", tmp_path / "tables")
    _common.write_table(pd.DataFrame({"x": [7]}), "T9.csv")
    assert pd.read_csv(tmp_path / "tables" / "T9.csv")["x"].tolist() == [7]
    assert _temp_siblings(tmp_path / "tables") == []


def test_write_manifest_keeps_previous_keys(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(_common, "OUTPUTS", tmp_path)
    _common.write_manifest({"climatology": {"D1": 1}})
    _common.write_manifest({"issuances": {"D1": 2}})
    data = __import__("json").loads((tmp_path / "manifest_index.json").read_text("utf-8"))
    assert data["climatology"] == {"D1": 1}
    assert data["issuances"] == {"D1": 2}
    assert _temp_siblings(tmp_path) == []


def test_inspect_write_lands_under_inspect_not_outputs(tmp_path: Path, monkeypatch):
    """The inspection cache must not be mistakable for a declared output."""
    monkeypatch.setattr(_common, "INSPECT", tmp_path / "_inspect")
    out = _common.inspect_write("panel", pd.DataFrame({"v": [1.5]}))
    assert out == tmp_path / "_inspect" / "panel.csv"
    assert pd.read_csv(out)["v"].tolist() == [1.5]


class TestExpEnvValidation:
    """EXP_ENV is a check, never a switch: it must fail, not silently route."""

    def test_unset_is_a_noop(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EXP_ENV", raising=False)
        monkeypatch.setattr(_common, "OUTPUTS", tmp_path)
        _common._validate_environment()  # must not raise

    def test_unknown_env_is_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EXP_ENV", "colabby")
        monkeypatch.setattr(_common, "OUTPUTS", tmp_path)
        with pytest.raises(SystemExit, match="is not one of"):
            _common._validate_environment()

    def test_colab_with_runtime_disk_paths_fails(self, monkeypatch, tmp_path):
        """The expensive silent bug: outputs to /content, lost on recycle."""
        monkeypatch.setenv("EXP_ENV", "colab")
        monkeypatch.setattr(_common, "OUTPUTS", Path("/content/c20-2026/outputs"))
        with pytest.raises(SystemExit, match="not on Drive"):
            _common._validate_environment()

    def test_local_pointing_at_drive_fails(self, monkeypatch):
        monkeypatch.setenv("EXP_ENV", "local")
        monkeypatch.setattr(
            _common, "OUTPUTS", Path("/content/drive/MyDrive/c20-2026/outputs")
        )
        with pytest.raises(SystemExit, match="is on Drive"):
            _common._validate_environment()

    def test_colab_pointing_at_drive_passes(self, monkeypatch):
        monkeypatch.setenv("EXP_ENV", "colab")
        monkeypatch.setattr(
            _common, "OUTPUTS", Path("/content/drive/MyDrive/c20-2026/outputs")
        )
        _common._validate_environment()


def test_exp_config_overrides_the_config_path(tmp_path, monkeypatch):
    """`--config` on run_all has to reach the stages it spawns."""
    other = tmp_path / "other.yaml"
    other.write_text("project: from-override\n", encoding="utf-8")
    monkeypatch.setenv("EXP_CONFIG", str(other))
    reloaded = importlib.reload(_common)
    try:
        assert reloaded.CONFIG_PATH == other
        assert reloaded.load_config()["project"] == "from-override"
    finally:
        monkeypatch.delenv("EXP_CONFIG", raising=False)
        importlib.reload(_common)
"""The report must survive a run that died before the tables could be rewritten.

A schema rename (COLAB.md §7, rule 12) leaves every table from the run before
it unreadable by name. That is what a stage's failure leaves on Drive, and the
report reading it is right to say so in a line instead of crashing on a KeyError
halfway through a table - that KeyError took the rest of the report with it.

Tables here are synthetic files in a tmp dir: the conftest audit hook forbids
touching the real `outputs/`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

report = importlib.import_module("report")

OLD_T10 = pd.DataFrame({"role": ["blind"], "check": ["daily"], "scope": ["days 1-7"],
                        "paths": [0.21], "observed": [0.9],
                        "metric": ["cov90 of daily anomaly (nominal 0.90)"]})
NEW_T10 = pd.DataFrame({"role": ["blind"], "check": ["daily"], "scope": ["days 1-7"],
                        "value": [0.21], "reference": [0.9],
                        "metric": ["cov90 of daily anomaly (nominal 0.90)"]})


def run_only(monkeypatch, tmp_path, frame, name, section):
    """Write `frame` and run `main()` over that one section against it."""
    monkeypatch.setattr(report, "TABLES", tmp_path)
    monkeypatch.setattr(report, "SECTIONS", [(name, section)])
    if frame is not None:
        frame.to_csv(tmp_path / "T10_chronos_diagnostic.csv", index=False)
    return report.main()


def test_a_renamed_table_is_a_note_naming_the_stage_that_refreshes_it(
        monkeypatch, tmp_path, capsys):
    assert run_only(monkeypatch, tmp_path, OLD_T10, "T10", report._t10) == 0
    out = capsys.readouterr().out
    assert "[stale]" in out
    assert "T10_chronos_diagnostic.csv: older schema (missing value, reference)" in out
    assert "re-run 09c_chronos_diagnostic to refresh it" in out
    assert "Traceback" not in out


def test_the_current_schema_still_prints(monkeypatch, tmp_path, capsys):
    assert run_only(monkeypatch, tmp_path, NEW_T10, "T10", report._t10) == 0
    out = capsys.readouterr().out
    assert "[stale]" not in out and "Traceback" not in out
    assert "cov90 of daily anomaly" in out


def test_a_missing_table_is_still_a_note(monkeypatch, tmp_path, capsys):
    assert run_only(monkeypatch, tmp_path, None, "T10", report._t10) == 0
    out = capsys.readouterr().out
    assert "[missing]" in out and "T10_chronos_diagnostic.csv: not produced yet" in out


def test_anything_else_is_still_a_failure(monkeypatch, tmp_path):
    def boom():
        raise ValueError("a real bug is not a stale artefact")

    monkeypatch.setattr(report, "SECTIONS", [("T10", boom)])
    assert report.main() == 1


def test_require_columns_names_the_missing_ones_and_the_stage():
    with pytest.raises(report.StaleTable) as exc:
        report.require_columns(OLD_T10, ["role", "value", "reference"], "T10.csv", "09c")
    assert exc.value.want == ["value", "reference"]
    assert exc.value.stage == "09c" and exc.value.filename == "T10.csv"


def test_require_columns_passes_a_frame_that_has_it_all():
    assert report.require_columns(NEW_T10, ["role", "value", "reference"], "T10.csv",
                                  "09c") is NEW_T10

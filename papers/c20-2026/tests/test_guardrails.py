# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for the test guard rails themselves.

These meta-tests keep the invariants in conftest.py honest: that a test cannot
silently depend on the real dataset, and that the guard actually fires.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

TESTS = Path(__file__).resolve().parent
PAPER_ROOT = TESTS.parents[0]
sys.path.insert(0, str(TESTS))

import conftest  # noqa: E402  (installs the audit hook on import)


def test_guard_blocks_reading_the_real_dataset():
    with pytest.raises(AssertionError, match="real pipeline data"):
        pd.read_csv(PAPER_ROOT / "data" / "raw" / "dataset.csv", nrows=1)


def test_guard_blocks_writing_into_real_outputs():
    with pytest.raises(AssertionError, match="real pipeline data"):
        (PAPER_ROOT / "outputs" / "should_not_exist.csv").write_text("x", encoding="utf-8")


def test_guard_allows_synthetic_paths(tmp_path):
    # A normal write inside tmp_path must keep working.
    f = tmp_path / "ok.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    assert pd.read_csv(f).shape == (1, 2)


def test_guard_allows_importing_experiment_modules():
    # Importing the code is fine; only real data access is blocked.
    assert conftest.PAPER_ROOT == PAPER_ROOT
    assert conftest.REAL_DATA_DIR == PAPER_ROOT / "data"


def test_real_dataset_exists_but_is_unreadable_from_tests():
    # Documents the intent: the file is on disk and gitignored, never a test input.
    raw = PAPER_ROOT / "data" / "raw" / "dataset.csv"
    assert raw.is_file()
    assert raw.suffix == ".csv"
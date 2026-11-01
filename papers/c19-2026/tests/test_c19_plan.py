# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""The frozen analysis plan may only change together with a version bump."""

import pathlib
import sys

EXP = pathlib.Path(__file__).resolve().parents[1] / "experiments"
sys.path.insert(0, str(EXP))

from _paths import plan_record  # noqa: E402

PLAN = "version: 2\nfrozen: '2026-10-31'\n"


def test_first_run_is_accepted():
    record, error = plan_record(PLAN, None)
    assert error is None
    assert record["version"] == 2


def test_same_version_with_new_content_fails():
    previous, _ = plan_record(PLAN, None)
    _, error = plan_record(PLAN + "extra: 1\n", previous)
    assert error and "version bump" in error


def test_new_version_is_accepted():
    previous, _ = plan_record(PLAN, None)
    record, error = plan_record("version: 3\nfrozen: '2026-11-01'\n", previous)
    assert error is None
    assert record["version"] == 3

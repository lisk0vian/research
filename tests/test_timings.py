# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for the timing record: outputs/timings.json and outputs/timings.md.

The contract (COLAB.md, `_colab_runtime.Timings`): how long each process takes
is recorded as it happens, an expected duration is the median of the *fresh*
measurements or else the a-priori estimate - never a blend of the two - and a
measurement stops counting the moment the stage's key or code changes, which
puts the estimate back in charge until something re-measures. That is what
makes "this is taking too long" and "that finished suspiciously fast" readable
from the file, before and after the first run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _colab_runtime as rt  # noqa: E402
import paper_timings as pt  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(rt.TIMINGS_ENV, raising=False)
    monkeypatch.delenv("EXP_FAST", raising=False)
    monkeypatch.delenv("EXP_PAPER", raising=False)
    rt.Timings._instances.clear()


@pytest.fixture
def outputs(tmp_path: Path) -> Path:
    out = tmp_path / "paper-slug" / "outputs"
    out.mkdir(parents=True)
    return out


def timings(outputs: Path, mode: str = "full") -> rt.Timings:
    return rt.Timings(outputs, code_dir=outputs.parent / "experiments", mode=mode)


def write_estimates(outputs: Path, stages: dict[str, dict],
                    session: dict[str, dict] | None = None) -> None:
    exp = outputs.parent / "experiments"
    exp.mkdir(parents=True, exist_ok=True)
    lines = ["session:"]
    for name, est in (session or {}).items():
        lines.append(f"  {name}: {{{', '.join(f'{k}: {v}' for k, v in est.items())}}}")
    lines.append("stages:")
    for name, est in stages.items():
        lines.append(f"  {name}: {{{', '.join(f'{k}: {v}' for k, v in est.items())}}}")
    (exp / rt.ESTIMATES_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


EST = {"min_s": 10, "typical_s": 100, "max_s": 200}


# --- the two sources of an expectation ------------------------------------------

def test_a_paper_that_never_ran_shows_the_estimate(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    data = tim.preview()
    block = data["modes"]["full"]["07_models"]
    assert block["expected_s"] == 100.0
    assert block["expected_source"] == "estimate"
    assert "07_models" in tim.render()


def test_a_measurement_takes_over_the_expectation(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    tim.record_stage("07_models", 300.0, "ok", key="k1", code_sha="s1")
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["expected_s"] == 300.0
    assert block["expected_source"] == "measured"


def test_the_estimate_is_never_blended_with_the_measurement(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    # Three runs under the same fingerprint: three comparable measurements.
    for secs in (240.0, 300.0, 360.0):
        tim.record_stage("07_models", secs, "ok", key="k1", code_sha="s1")
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["expected_s"] == 300.0            # the median, not an average with 100
    assert block["stats"]["p90_s"] == 360.0
    assert block["stats"]["n"] == 3
    # Runs under a different key are not comparable: only the last one counts.
    tim.record_stage("07_models", 420.0, "ok", key="k2", code_sha="s1")
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["stats"]["n"] == 1
    assert block["expected_s"] == 420.0


def test_a_code_change_puts_the_estimate_back_in_charge(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    tim.record_stage("07_models", 300.0, "ok", key="k1", code_sha="s1")
    assert tim.preview()["modes"]["full"]["07_models"]["expected_source"] == "measured"
    # Same key, different code: the measurement stays in the history but stops
    # counting (Q15 rule: key OR code_sha).
    tim.sync_fingerprints({"07_models": ("k1", "s2")})
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["expected_source"] == "estimate"
    assert block["stale_n"] == 1
    assert block["history"][0]["fresh"] is False


def test_a_config_change_also_invalidates_the_measurement(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    tim.record_stage("07_models", 300.0, "ok", key="k1", code_sha="s1")
    tim.sync_fingerprints({"07_models": ("k2", "s1")})
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["expected_source"] == "estimate"
    assert block["expected_s"] == 100.0


def test_a_unchanged_fingerprint_keeps_the_measurement_fresh(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    tim.record_stage("07_models", 300.0, "ok", key="k1", code_sha="s1")
    tim.sync_fingerprints({"07_models": ("k1", "s1")})
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["expected_source"] == "measured"
    assert block["stale_n"] == 0


# --- history, modes and deviations ----------------------------------------------

def test_history_keeps_ten_runs_and_never_mixes_modes(outputs):
    tim = timings(outputs, mode="full")
    for i in range(12):
        tim.record_stage("07_models", 100.0 + i, "ok", key=f"k{i}", code_sha="s")
    smoke = rt.Timings(outputs, code_dir=outputs.parent / "experiments", mode="smoke")
    smoke.record_stage("07_models", 5.0, "ok", key="k0", code_sha="s")
    data = tim.preview()["modes"]
    assert len(data["full"]["07_models"]["history"]) == 10
    assert data["full"]["07_models"]["history"][0]["elapsed_s"] == 102.0  # oldest dropped
    assert data["smoke"]["07_models"]["history"][0]["elapsed_s"] == 5.0


def test_a_run_outside_the_estimate_is_flagged_and_visible(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    tim.record_stage("07_models", 900.0, "ok", key="k1", code_sha="s1")
    entry = tim.preview()["modes"]["full"]["07_models"]["history"][0]
    assert entry["outside_estimate"] is True
    assert "⚠" in tim.render()
    tim.record_stage("07_models", 3.0, "ok", key="k1", code_sha="s1")
    entry = tim.preview()["modes"]["full"]["07_models"]["history"][-1]
    assert entry["outside_estimate"] is True       # suspiciously fast counts too


def test_a_failed_run_is_kept_but_never_averaged_in(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    tim.record_stage("07_models", 300.0, "ok", key="k1", code_sha="s1")
    tim.record_stage("07_models", 12.0, "failed", key="k1", code_sha="s1")
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["expected_s"] == 300.0
    assert block["stats"]["n"] == 1
    assert block["history"][-1]["status"] == "failed"


# --- units and the run in progress ----------------------------------------------

def test_units_survive_the_checkpoints_they_come_from(outputs, monkeypatch):
    write_estimates(outputs, {"07_models": {"min_s": 1, "typical_s": 50, "max_s": 100,
                                            "unit": "fold", "unit_typical_s": 10}})
    monkeypatch.setenv(rt.TIMINGS_ENV, "1")
    tim = timings(outputs)
    tim.begin_run(["07_models"])
    tim.begin_stage("07_models")
    ck = rt.Checkpoints("07_models", root=outputs / rt.CHECKPOINT_DIR, key="k1")
    ck.save("B1", {"preds": [1]}, elapsed_s=12.5)
    ck.save("B2", {"preds": [2]}, elapsed_s=8.0)
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["units_last"] == {"B1": 12.5, "B2": 8.0}
    tim.record_stage("07_models", 20.5, "ok", key="k1", code_sha="s1")
    entry = tim.preview()["modes"]["full"]["07_models"]["history"][-1]
    assert entry["n_units"] == 2
    assert entry["unit_median_s"] == 10.25
    ck.clear()                                      # checkpoints die ...
    assert "B1" in tim.preview()["modes"]["full"]["07_models"]["history"][-1]["units"]


def test_recording_is_silent_without_the_env(outputs):
    tim = timings(outputs)
    tim.unit_done("07_models", "B1", 12.5)
    assert not tim.path.exists()


def test_the_run_flags_a_stage_past_its_maximum(outputs, monkeypatch):
    write_estimates(outputs, {"07_models": dict(EST)})
    monkeypatch.setenv(rt.TIMINGS_ENV, "1")
    tim = timings(outputs)
    tim.begin_run(["07_models", "10_tables"])
    tim.begin_stage("07_models")
    tim._t0["07_models"] -= 500.0                   # pretend it has been running 500s
    tim.unit_done("07_models", "B1", 1.0)
    run = tim.preview()["current_run"]
    assert run["over_estimate"] is True
    assert run["eta_remaining_s"] is not None
    tim.record_stage("07_models", 500.0, "ok", key="k1", code_sha="s1")
    run = tim.preview()["current_run"]
    assert run["stage"] is None
    assert run["pending"] == ["10_tables"]


def test_the_eta_falls_back_to_the_estimate_when_nothing_is_measured(outputs):
    write_estimates(outputs, {"a": {"typical_s": 100}, "b": {"typical_s": 300}})
    tim = timings(outputs)
    tim.begin_run(["a", "b"])
    tim.record_stage("a", 120.0, "ok", key="k", code_sha="s")
    run = tim.preview()["current_run"]
    assert run["eta_remaining_s"] == 300.0
    assert run["eta_source"] == "estimate"


# --- seeding --------------------------------------------------------------------

def test_seeded_measurements_never_claim_freshness_on_their_own(outputs):
    write_estimates(outputs, {"07_models": dict(EST)})
    tim = timings(outputs)
    tim.seed_stage("07_models", 250.0, "ok", key="k1", code_sha="s1", source="state")
    block = tim.preview()["modes"]["full"]["07_models"]
    assert block["expected_source"] == "estimate"   # seeded is history, not proof
    assert block["history"][0]["seeded"] is True
    tim.sync_fingerprints({"07_models": ("k1", "s1")})   # ... until it is proven
    assert tim.preview()["modes"]["full"]["07_models"]["expected_source"] == "measured"


def test_units_from_a_file_feed_a_stage_that_times_itself(outputs):
    write_estimates(outputs, {"pipeline": {"typical_s": 1800}})
    exp = outputs.parent / "experiments"
    (exp / rt.ESTIMATES_NAME).write_text(
        (exp / rt.ESTIMATES_NAME).read_text(encoding="utf-8").replace(
            "pipeline: {typical_s: 1800}",
            'pipeline: {typical_s: 1800, unit: etapa, '
            'units_from: {file: outputs/results.json, json_key: tiempos}}'),
        encoding="utf-8")
    (outputs / "results.json").write_text(
        json.dumps({"tiempos": {"1_datos": 2.0, "8_multiverso": 1500.0}}), encoding="utf-8")
    tim = timings(outputs)
    tim.record_stage("pipeline", 1502.0, "ok", key="k1", code_sha="s1")
    entry = tim.preview()["modes"]["full"]["pipeline"]["history"][-1]
    assert entry["units"] == {"1_datos": 2.0, "8_multiverso": 1500.0}
    assert entry["unit_median_s"] == 751.0


# --- the cross-paper view ---------------------------------------------------------

def test_the_seeder_finds_durations_in_state_logs_and_the_run_meta(outputs):
    state = outputs / rt.STATE_DIR
    state.mkdir(parents=True)
    (state / "07_models.json").write_text(
        json.dumps({"stage": "07_models", "key": "k1", "code_sha": "s1",
                    "elapsed_s": 300.0, "finished": "2026-10-03T19:00:00+00:00"}),
        encoding="utf-8")
    logs = outputs / "logs"
    logs.mkdir()
    (logs / "07_models.log").write_text(
        "# STAGE-EXIT 07_models exit_code=0 elapsed_s=300.00\n", encoding="utf-8")
    (logs / "10_tables.log").write_text(
        "# STAGE-EXIT 10_tables exit_code=1 elapsed_s=4.50\n", encoding="utf-8")
    (outputs / "run_meta.json").write_text(
        json.dumps({"results": {"09_inference": {"exit_code": 0, "elapsed_s": 120.0}}}),
        encoding="utf-8")

    found = pt._entries_from(outputs)
    assert {s: [e["elapsed_s"] for e in b] for s, b in found.items()} == {
        "07_models": [300.0],            # seen twice, recorded once
        "10_tables": [4.5],
        "09_inference": [120.0],
    }
    assert found["07_models"][0]["key"] == "k1"     # the state file carries the proof
    assert found["10_tables"][0]["status"] == "failed"


def test_the_aggregate_view_answers_before_anything_runs(outputs, capsys):
    write_estimates(outputs, {"a": {"typical_s": 100}}, session={"deps": {"typical_s": 300}})
    text = timings(outputs).render()
    assert "a" in text and "100" in text
    assert "session overhead" in text
    assert "no run recorded yet" in text


def test_the_json_and_the_markdown_are_written_side_by_side(outputs):
    tim = timings(outputs)
    tim.record_stage("07_models", 42.0, "ok", key="k1", code_sha="s1")
    data = json.loads(tim.path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["paper"] == "paper-slug"
    assert data["modes"]["full"]["07_models"]["history"][0]["elapsed_s"] == 42.0
    md = tim.md_path.read_text(encoding="utf-8")
    assert "07_models" in md and "42.0" in md

"""Tests for the multi-station boundary in stages 01 and 02.

Every bug here is the same shape: with one station the code was correct, and
adding a second station made it wrong without raising. A daily frame keyed on
date alone averages two observatories into one plausible-looking row. A spike
test that never fires on the last hour of a station reports clean data. A
manifest that shallow-merges keeps one station where there should be five.

These are cheap to write and they are the reason the refactor can be trusted,
so they are written against synthetic frames and never the real dataset.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments"
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))

qc = importlib.import_module("01_qc_hourly")
daily = importlib.import_module("02_aggregate_daily")
verify = importlib.import_module("00_verify_source")


def _hours(station: str, day: str, values: list[float]) -> pd.DataFrame:
    """One station's worth of hourly rows for a single calendar day."""
    base = pd.Timestamp(day)
    return pd.DataFrame({
        "UBIGEO": station,
        "timestamp": base + pd.to_timedelta(np.arange(len(values)), unit="h"),
        "TT": values,
        "HR": [50.0] * len(values),
        "PP": [700.0] * len(values),
        "FF": [2.0] * len(values),
        "DD": [180.0] * len(values),
        "RR": [0.0] * len(values),
    })


CFG = {"qc_hourly": {"step_TT_max_degC": 8, "stuck_run_hours": 6},
       "daily_aggregation": {"min_hours": 20, "require_each_6h_block": True,
                             "rr_min_hours": 24}}


# --- 02: the collapse ------------------------------------------------------

def test_two_stations_on_one_date_do_not_collapse_into_one_row():
    """The bug this whole refactor exists to catch. Keyed on date alone the
    group covers both stations, the mean blends them, and the row looks
    ordinary. 877 m of elevation disappears with no warning."""
    a = _hours("040122", "2020-01-15", [12.0] * 24)     # Huancayo, cool
    b = _hours("040514", "2020-01-15", [24.0] * 24)     # Matucana, warm
    out = daily.aggregate(pd.concat([a, b], ignore_index=True), CFG)

    assert len(out) == 2, "one row per (station, date), not one per date"
    assert set(out["station"]) == {"040122", "040514"}
    row_a = out[out["station"] == "040122"].iloc[0]
    row_b = out[out["station"] == "040514"].iloc[0]
    assert row_a["TT_mean"] == pytest.approx(12.0)
    assert row_b["TT_mean"] == pytest.approx(24.0)
    assert row_a["TT_mean"] != pytest.approx(row_b["TT_mean"])


def test_a_blended_mean_would_have_been_the_old_behaviour():
    """Guards the test above against passing for the wrong reason: if the two
    means came out equal, the collapse is still happening."""
    a = _hours("040122", "2020-01-15", [12.0] * 24)
    b = _hours("040514", "2020-01-15", [24.0] * 24)
    out = daily.aggregate(pd.concat([a, b], ignore_index=True), CFG)
    assert 18.0 not in out["TT_mean"].to_numpy(), "the two stations were averaged"


def test_station_and_date_are_the_composite_key():
    a = _hours("040122", "2020-01-15", [12.0] * 24)
    b = _hours("040514", "2020-01-15", [24.0] * 24)
    out = daily.aggregate(pd.concat([a, b], ignore_index=True), CFG)
    assert not out.duplicated(subset=["station", "date"]).any()


def test_each_station_keeps_its_own_hour_count():
    """If the counts are pooled, a station with 12 hours looks as complete as
    one with 24, and min_hours stops meaning anything."""
    a = _hours("040122", "2020-01-15", [12.0] * 24)
    b = _hours("040514", "2020-01-15", [np.nan] * 12 + [24.0] * 12)
    out = daily.aggregate(pd.concat([a, b], ignore_index=True), CFG)
    counts = dict(zip(out["station"], out["n_hours"]))
    assert counts["040122"] == 24
    assert counts["040514"] == 12
    assert bool(out[out["station"] == "040514"].iloc[0]["valid"]) is False


def test_five_stations_produce_five_rows():
    blocks = [_hours(f"04051{i}", "2020-01-15", [10.0 + i] * 24) for i in range(5)]
    out = daily.aggregate(pd.concat(blocks, ignore_index=True), CFG)
    assert len(out) == 5
    assert out["station"].nunique() == 5


def test_a_single_station_frame_still_works_without_a_station_column():
    """Pre-migration data has no UBIGEO column at all; it must still run."""
    frame = _hours("040122", "2020-01-15", [12.0] * 24).drop(columns=["UBIGEO"])
    out = daily.aggregate(frame, CFG)
    assert len(out) == 1
    assert "station" in out.columns


def test_the_output_carries_the_station_column():
    a = _hours("040122", "2020-01-15", [12.0] * 24)
    out = daily.aggregate(a, CFG)
    assert "station" in daily.DAILY_COLUMNS
    assert out["station"].iloc[0] == "040122"


# --- 01: flags must not cross a station boundary --------------------------

def test_a_spike_in_the_last_hour_of_a_station_is_still_flagged():
    """Sorting on timestamp alone interleaves stations, so timestamp.diff() is
    zero between two sensors, contiguous goes false, and the spike test never
    fires on the hour that matters most."""
    values = [12.0] * 23 + [40.0]
    frame = qc.apply_qc_flags(_hours("040122", "2020-01-15", values), CFG)
    assert (frame["TT_qc"] == "spike").any(), "the final-hour spike was missed"


def test_a_spike_at_a_station_boundary_is_not_invented():
    """Two stations, wildly different temperatures, same hour. Not a spike:
    they are different sensors, and a step between them measures nothing."""
    a = _hours("040122", "2020-01-15", [12.0] * 24)
    b = _hours("040514", "2020-01-15", [24.0] * 24)
    frame = qc.apply_qc_flags(pd.concat([a, b], ignore_index=True).sort_values("timestamp"),
                              CFG)
    assert (frame["TT_qc"] == "spike").sum() == 0


def test_a_stuck_run_is_not_formed_across_two_stations():
    """Each station holds five identical hours, under the six-hour threshold.
    Interleaved by timestamp they are ten consecutive, so a whole-frame pass
    calls it an instrument freeze that never happened."""
    values = [12.0] * 5 + [13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]
    a = _hours("040122", "2020-01-15", values)
    b = _hours("040514", "2020-01-15", values)
    frame = qc.apply_qc_flags(pd.concat([a, b], ignore_index=True).sort_values("timestamp"),
                              CFG)
    assert (frame["TT_qc"] == "stuck").sum() == 0


def test_a_run_long_enough_inside_one_station_is_still_flagged():
    """A genuine freeze must survive the per-station grouping."""
    values = [12.0] * 4 + [7.0] * 10 + [13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0]
    frame = qc.apply_qc_flags(_hours("040122", "2020-01-15", values), CFG)
    assert (frame["TT_qc"] == "stuck").sum() == 10


def test_two_constant_stations_are_each_a_genuine_run():
    """Twenty-four identical hours inside one station is a real freeze, so
    grouping per station must not make it disappear."""
    a = _hours("040122", "2020-01-15", [12.0] * 24)
    b = _hours("040514", "2020-01-15", [24.0] * 24)
    frame = qc.apply_qc_flags(pd.concat([a, b], ignore_index=True).sort_values("timestamp"),
                              CFG)
    assert (frame["TT_qc"] == "stuck").sum() == 48
    assert set(frame.loc[frame["TT_qc"] == "stuck", "UBIGEO"]) == {"040122", "040514"}


def test_flags_are_applied_per_station_not_globally():
    """A spike in station A must not change station B's flags."""
    a = _hours("040122", "2020-01-15", [12.0] * 23 + [40.0])
    b = _hours("040514", "2020-01-15", [24.0] * 24)
    frame = qc.apply_qc_flags(pd.concat([a, b], ignore_index=True).sort_values("timestamp"),
                              CFG)
    assert (frame.loc[frame["UBIGEO"] == "040514", "TT_qc"] == "spike").sum() == 0
    assert (frame.loc[frame["UBIGEO"] == "040122", "TT_qc"] == "spike").sum() == 1


def test_a_frame_without_a_station_column_still_gets_flagged():
    frame = _hours("040122", "2020-01-15", [12.0] * 23 + [40.0]).drop(columns=["UBIGEO"])
    out = qc.apply_qc_flags(frame, CFG)
    assert (out["TT_qc"] == "spike").any()


# --- 00: the station set and the duplicates -------------------------------

def _raw(stations: list[str], per_station: int = 3) -> pd.DataFrame:
    rows = []
    base = pd.Timestamp("2020-01-01")
    for i, code in enumerate(stations):
        for h in range(per_station):
            rows.append({"UBIGEO": code,
                         "timestamp": base + pd.Timedelta(hours=h),
                         "TT": 12.0 + i, "HR": 50.0, "PP": 700.0,
                         "FF": 2.0, "DD": 180.0, "RR": 0.0})
    return pd.DataFrame(rows)


CFG5 = {"stations": [{"ubigeo": "040114"}, {"ubigeo": "040122"},
                     {"ubigeo": "040506"}, {"ubigeo": "040513"},
                     {"ubigeo": "040514"}]}


def test_the_declared_and_present_sets_agree():
    res = verify.check_v5_ubigeo(_raw([s["ubigeo"] for s in CFG5["stations"]]), CFG5)
    assert res["verdict"] == "ok"
    assert res["value"] == "n_present=5"


def test_a_declared_station_with_no_rows_is_reported():
    """An entire elevation level silently missing is the failure that would
    quietly narrow the gradient the paper is built on."""
    res = verify.check_v5_ubigeo(_raw(["040114", "040122"]), CFG5)
    assert res["verdict"] == "REVIEW_station_mismatch"
    assert "040514" in res["detail"]
    assert "missing" in res["detail"]


def test_a_station_the_config_does_not_declare_is_reported():
    res = verify.check_v5_ubigeo(_raw(["040114", "040122", "040506", "040513",
                                       "040514", "099999"]), CFG5)
    assert res["verdict"] == "REVIEW_station_mismatch"
    assert "undeclared" in res["detail"]


def test_the_single_station_contract_still_evaluates():
    """Pre-migration config declares nothing, so one station is still correct."""
    res = verify.check_v5_ubigeo(_raw(["040122"]), {})
    assert res["verdict"] == "ok"


def test_two_stations_against_an_undeclared_config_is_flagged():
    res = verify.check_v5_ubigeo(_raw(["040122", "040514"]), {})
    assert res["verdict"] == "REVIEW_multi_station_undeclared"


def test_repeated_timestamps_across_stations_are_not_duplicates():
    """Five stations, one hour, five rows. Counting duplicates over the whole
    frame reports four false ones per hour and buries the real ones."""
    res = verify.check_v6_duplicates(_raw(["040114", "040122", "040506",
                                           "040513", "040514"], per_station=3))
    assert res["verdict"] == "ok"
    assert res["value"] == "duplicates=0"


def test_a_repeated_timestamp_within_one_station_is_a_duplicate():
    frame = _raw(["040122"], per_station=3)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    res = verify.check_v6_duplicates(frame)
    assert res["verdict"] == "REVIEW_deduplicate_first_occurrence"
    assert res["value"] == "duplicates=1"


def test_duplicates_are_counted_without_a_station_column():
    frame = _raw(["040122"], per_station=3).drop(columns=["UBIGEO"])
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    assert verify.check_v6_duplicates(frame)["value"] == "duplicates=1"

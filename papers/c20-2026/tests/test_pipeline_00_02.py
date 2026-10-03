# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for the c20-2026 early pipeline (00 verify, 01 QC, 02 aggregate).

The real dataset is gitignored, so these tests build a synthetic hourly frame
that reproduces the properties verified against the real file: a local-civil
diurnal cycle, row-wise provider gaps, a wind sector, and enough days to
exercise the completeness rules.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments"
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))

import _common  # noqa: E402
import importlib  # noqa: E402

qc_mod = importlib.import_module("01_qc_hourly")
agg_mod = importlib.import_module("02_aggregate_daily")
verify_mod = importlib.import_module("00_verify_source")

VARS = ["TT", "HR", "RR", "PP", "FF", "DD"]


@pytest.fixture
def hourly() -> pd.DataFrame:
    """96 days of hourly local-civil data with a diurnal TT cycle."""
    idx = pd.date_range("2023-01-01", periods=96 * 24, freq="h")
    hour = idx.hour.to_numpy()
    # Peak at 17:00, trough at 05:00: a local-civil cycle like the real station,
    # where 00/V1 reads a midday trough as UTC and asks for a shift.
    tt = 10.0 + 6.0 * np.sin((hour - 11) / 24 * 2 * np.pi)
    df = pd.DataFrame({
        "timestamp": idx,
        "year": idx.year, "month": idx.month, "day": idx.day, "hour": idx.hour,
        "UBIGEO": "120904",
        "TT": tt,
        "HR": 70.0 + 10.0 * np.cos((hour - 8) / 24 * 2 * np.pi),
        "RR": np.where(hour == 15, 1.5, 0.0),
        "PP": 688.0,
        "FF": 3.0,
        "DD": 180.0,
    })
    # One full provider gap, exactly like the real file: all vars empty together.
    df.loc[10 * 24: 10 * 24 + 23, VARS] = np.nan
    return df


@pytest.fixture
def cfg() -> dict:
    return {
        "data": {"coverage_declared": [2023]},
        "station": {"n_stations": 1},
        "qc_hourly": {
            "range": {"TT": [-15, 35], "HR": [0, 100], "PP": [640, 720],
                      "RR": [0, 60], "FF": [0, 40], "DD": [0, 360]},
            "hr_clip_upper": 103, "step_TT_max_degC": 8, "stuck_run_hours": 6,
        },
        "daily_aggregation": {
            "min_hours": 20, "require_each_6h_block": True,
            "rr_min_hours": 24, "wind": "vector_components",
        },
        "validation": {"folds": [{"id": "B1", "test": 2023, "role": "blind"}]},
    }


# --- 00 verify -------------------------------------------------------------

def test_v1_detects_local_civil_cycle(hourly):
    out = verify_mod.check_v1_timezone(hourly)
    assert out["verdict"] == "local_civil"
    assert "min 0" in out["detail"] or "min 1" in out["detail"]


def test_v1_flags_shift_when_trough_is_midday(hourly):
    # Same data five hours later: the trough lands at 10:00, which is what a
    # UTC-labelled series looks like once it has NOT been shifted to local time.
    shifted = hourly.copy()
    shifted["timestamp"] = shifted["timestamp"] + pd.Timedelta(hours=10)
    new_hour = shifted["timestamp"].dt.hour.to_numpy()
    # Trough at 10:00, peak at 22:00: the signature of UTC-labelled rows that
    # were never shifted to local time.
    shifted["TT"] = 10.0 + 6.0 * np.sin((new_hour - 16) / 24 * 2 * np.pi)
    shifted["hour"] = new_hour
    out = verify_mod.check_v1_timezone(shifted)
    assert out["verdict"] == "REVIEW_shift_required"
    assert "min 10:00" in out["detail"]


def test_v3_confirms_rowwise_gaps(hourly, cfg):
    out = verify_mod.check_v3_missing(hourly, cfg)
    assert "row-wise pattern: True" in out["detail"]
    assert out["verdict"] == "ok"


def test_v5_flags_multistation_against_an_undeclared_config(hourly):
    """Verdict string changed with the check, not by accident.

    V5 used to assert UBIGEO was constant and returned
    REVIEW_multi_station, meaning "several stations is wrong". It now compares
    the file's station set against the declared one, so with nothing declared
    the useful failure is that the config is not describing this file. The
    intent of the test is unchanged: several stations with a single-station
    contract must not pass silently.
    """
    multi = hourly.copy()
    multi.loc[0, "UBIGEO"] = "150901"
    out = verify_mod.check_v5_ubigeo(multi, {"station": {"n_stations": 1}})
    assert out["verdict"] == "REVIEW_multi_station_undeclared"


def test_v5_is_ok_when_the_config_declares_no_station_and_one_is_present(hourly):
    """The pre-migration contract: nothing declared, one station in the file."""
    assert verify_mod.check_v5_ubigeo(hourly, {})["verdict"] == "ok"


def test_v6_counts_duplicates(hourly):
    duped = pd.concat([hourly, hourly.tail(1)], ignore_index=True)
    out = verify_mod.check_v6_duplicates(duped)
    assert out["value"] == "duplicates=1"


def test_v4_flags_incomplete_blind_year(hourly, cfg):
    # The fixture covers only part of 2023, so the blind year is not complete.
    out = verify_mod.check_v4_coverage(hourly, cfg)
    assert out["verdict"] == "REVIEW_coverage_gaps"


def test_v4_ok_when_blind_year_fully_covered(hourly, cfg):
    # A full 12-month span with no short days satisfies the blind-year rule.
    idx = pd.date_range("2023-01-01", periods=365 * 24, freq="h")
    hour = idx.hour.to_numpy()
    full = pd.DataFrame({
        "timestamp": idx,
        "year": idx.year, "month": idx.month, "day": idx.day, "hour": idx.hour,
        "UBIGEO": "120904",
        "TT": 10.0 + 6.0 * np.sin((hour - 11) / 24 * 2 * np.pi),
        "HR": 70.0, "RR": 0.0, "PP": 688.0, "FF": 3.0, "DD": 180.0,
    })
    out = verify_mod.check_v4_coverage(full, cfg)
    assert out["verdict"] == "ok"
    assert "incomplete_days=0" in out["detail"].replace("<24h", "incomplete_days")


# --- 01 QC -----------------------------------------------------------------

def _qc(df, cfg):
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = qc_mod.flag_missing_source(df)
    df = qc_mod.flag_out_of_range(df, cfg)
    df = qc_mod.flag_tt_spikes(df, cfg)
    return qc_mod.flag_stuck_runs(df, cfg)


def test_missing_source_flagged_on_all_vars(hourly, cfg):
    out = _qc(hourly.copy(), cfg)
    gap = out.loc[out["timestamp"].dt.day == 11, "TT_qc"]
    assert (gap == "missing_source").all()


def test_out_of_range_becomes_nan(hourly, cfg):
    dirty = hourly.copy()
    dirty.loc[5, "TT"] = 99.0  # far above the [-15, 35] range
    out = _qc(dirty, cfg)
    assert out.loc[5, "TT_qc"] == "out_of_range"
    assert np.isnan(out.loc[5, "TT"])


def test_spike_flagged_when_no_precip(hourly, cfg):
    # A 20 degC jump with dry, steady air is a real discontinuity.
    dry = hourly.copy()
    dry.loc[50, "TT"] = dry.loc[50, "TT"] + 20
    dry.loc[50, "RR"] = 0.0
    dry.loc[49, "RR"] = 0.0
    out = _qc(dry, cfg)
    assert out.loc[50, "TT_qc"] == "spike"
    assert np.isnan(out.loc[50, "TT"])


def test_convective_event_kept_not_flagged(hourly, cfg):
    # The real-data pattern: TT drops ~9 degC as RR rises and HR jumps, i.e. an
    # afternoon storm. The value must survive QC.
    storm = hourly.copy()
    storm.loc[50, "TT"] = storm.loc[50, "TT"] - 9.0
    storm.loc[50, "RR"] = 15.0
    storm.loc[49, "HR"] = 55.0  # humidity climbs with the rain, as in the real events
    storm.loc[50, "HR"] = 95.0
    out = _qc(storm, cfg)
    assert out.loc[50, "TT_qc"] == "precip_event"
    assert not np.isnan(out.loc[50, "TT"])


def test_spike_not_raised_across_a_gap(hourly, cfg):
    # A 20 degC jump across a 5 h hole is unmeasurable, so it must not be flagged.
    gapped = hourly.drop(index=range(200, 205)).reset_index(drop=True)
    out = _qc(gapped, cfg)
    assert (out["TT_qc"] == "spike").sum() == 0


def test_stuck_run_flagged(hourly, cfg):
    stuck = hourly.copy()
    stuck.loc[100:107, "TT"] = 12.5  # 8 identical hours >= stuck_run_hours
    out = _qc(stuck, cfg)
    assert (out.loc[100:107, "TT_qc"] == "stuck").all()


def test_short_constant_run_not_flagged(hourly, cfg):
    short = hourly.copy()
    short.loc[100:103, "TT"] = 12.5  # 4 hours < stuck_run_hours
    out = _qc(short, cfg)
    assert (out.loc[100:103, "TT_qc"] == "stuck").sum() == 0


def test_qc_never_imputes_the_target(hourly, cfg):
    out = _qc(hourly.copy(), cfg)
    gap_rows = out["TT"].isna()
    assert gap_rows.sum() == 24  # only the original provider gap, nothing filled


# --- 02 aggregate ----------------------------------------------------------

def _daily(df, cfg):
    return agg_mod.aggregate(df.copy(), cfg)


def test_daily_shape_and_columns(hourly, cfg):
    daily = _daily(_qc(hourly.copy(), cfg), cfg)
    assert list(daily.columns) == agg_mod.DAILY_COLUMNS
    assert len(daily) == 96


def test_full_day_rejected_when_n_hours_below_min(hourly, cfg):
    daily = _daily(_qc(hourly.copy(), cfg), cfg)
    # The fixture's provider gap covers all 24 h of 2023-01-11.
    gap_day = daily[daily["date"] == pd.Timestamp("2023-01-11")].iloc[0]
    assert gap_day["n_hours"] == 0
    assert gap_day["valid"] == False  # noqa: E712
    assert gap_day["TT_mean"] != gap_day["TT_mean"]  # NaN, never imputed


def test_daily_stats_match_hourly_truth(hourly, cfg):
    clean = hourly.dropna(subset=VARS).copy()
    out = _qc(clean, cfg)
    daily = _daily(out, cfg)
    day = daily[daily["date"] == pd.Timestamp("2023-01-02")].iloc[0]
    expected = clean[(clean["date" if False else "timestamp"].dt.day == 2)]["TT"]
    assert day["TT_mean"] == pytest.approx(expected.mean())
    assert day["TT_max"] == pytest.approx(expected.max())
    assert day["DTR"] == pytest.approx(expected.max() - expected.min())


def test_dtr_is_max_minus_min(hourly, cfg):
    daily = _daily(_qc(hourly.copy(), cfg), cfg)
    valid = daily[daily["n_hours"] > 0]
    assert (valid["DTR"] - (valid["TT_max"] - valid["TT_min"])).abs().max() < 1e-9


def test_wind_is_vector_mean_not_degree_mean(hourly, cfg):
    # Meteorological convention: u = -FF sin(DD), v = -FF cos(DD), so a wind
    # FROM 180 deg (south) at 3 m/s is pure +v (blowing north).
    daily = _daily(_qc(hourly.copy(), cfg), cfg)
    row = daily.iloc[0]
    assert row["u_mean"] == pytest.approx(0.0, abs=1e-9)
    assert row["v_mean"] == pytest.approx(3.0, abs=1e-9)
    assert row["DD_mean"] == pytest.approx(180.0, abs=1e-6)


def test_calm_winds_contribute_zero_components(hourly, cfg):
    calm = hourly.copy()
    calm.loc[0:12, "FF"] = 0.0  # 13 calm hours dilute the vector mean
    daily = _daily(_qc(calm, cfg), cfg)
    row = daily.iloc[0]
    assert row["u_mean"] == pytest.approx(0.0, abs=1e-9)
    # 11 blown hours at 3 m/s over 24 h: 3 * 11/24, not the full 3 m/s.
    assert row["v_mean"] == pytest.approx(3.0 * 11 / 24, abs=1e-9)
    assert row["FF_mean"] == pytest.approx(3.0 * 11 / 24, abs=1e-9)


def test_rr_sum_nan_when_few_hours(hourly, cfg):
    # Drop RR for the first 30 hours: day 1 keeps 24 h but day 2 loses 6.
    partial = hourly.copy()
    partial.loc[0:29, "RR"] = np.nan
    daily = _daily(_qc(partial, cfg), cfg)
    assert np.isnan(daily.iloc[0]["RR_sum"])
    # Day 2 now has 18 RR hours < rr_min_hours=24, so its sum must be withheld.
    assert daily.iloc[1]["RR_n_hours"] == 18
    assert np.isnan(daily.iloc[1]["RR_sum"])
    # Day 3 is untouched: one 1.5 mm hour.
    assert daily.iloc[2]["RR_n_hours"] == 24
    assert daily.iloc[2]["RR_sum"] == pytest.approx(1.5)


def test_each_6h_block_required(hourly, cfg):
    # 6 valid hours, all inside the 00-06 block: enough for min_hours=1 but
    # the remaining three blocks are empty, so the day must be rejected.
    cfg_block = {**cfg, "daily_aggregation": {**cfg["daily_aggregation"],
                                             "min_hours": 1}}
    df = hourly.copy()
    day1 = pd.Timestamp("2023-01-01")
    keep_mask = (df["timestamp"].dt.normalize() == day1) & (df["hour"] < 6)
    trimmed = df[keep_mask].copy()
    daily = _daily(_qc(trimmed, cfg_block), cfg_block)
    row = daily[daily["date"] == day1].iloc[0]
    assert row["n_hours"] == 6
    assert row["valid"] == False  # noqa: E712


def test_day_spanning_all_blocks_is_valid(hourly, cfg):
    # The complement of the test above: 6 h in the 18-24 block also passes when
    # min_hours is relaxed, proving the block rule counts blocks, not hours.
    cfg_block = {**cfg, "daily_aggregation": {**cfg["daily_aggregation"],
                                             "min_hours": 1}}
    df = hourly.copy()
    day1 = pd.Timestamp("2023-01-01")
    keep_mask = (df["timestamp"].dt.normalize() == day1) & (df["hour"] >= 18)
    trimmed = df[keep_mask].copy()
    daily = _daily(_qc(trimmed, cfg_block), cfg_block)
    row = daily[daily["date"] == day1].iloc[0]
    assert row["valid"] == False  # noqa: E712  (only one block present too)


# --- Drive routing ---------------------------------------------------------

def test_paths_default_to_local_relative(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    import importlib as il

    mod = il.reload(_common)
    try:
        assert mod.DATA_DIR == mod.BASE / "data"
        assert mod.OUTPUTS == mod.BASE / "outputs"
        assert "[local]" in mod.paths_report()
    finally:
        monkeypatch.undo()
        il.reload(_common)


def test_paths_follow_env_when_set(monkeypatch, tmp_path):
    import importlib as il

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ddata"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "oout"))
    mod = il.reload(_common)
    try:
        assert mod.DATA_DIR == tmp_path / "ddata"
        assert mod.OUTPUTS == tmp_path / "oout"
        # The filename comes from config.source.file, not from a constant.
        # This test used to assert `dataset.csv`; asserting the configured name
        # instead is the point, because the failure it prevents is the stages
        # reading a different file than fetch_source.py just downloaded.
        assert mod.RAW_CSV == tmp_path / "ddata" / "raw" / mod._declared_raw_name()
        assert mod.RAW_CSV.name == "senamhi.csv"
        assert mod.TABLES == tmp_path / "oout" / "tables"
        assert "[drive]" in mod.paths_report()
    finally:
        monkeypatch.undo()
        il.reload(_common)


def test_ensure_dirs_creates_the_contract_tree(monkeypatch, tmp_path):
    import importlib as il

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ddata"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "oout"))
    mod = il.reload(_common)
    try:
        mod.ensure_dirs()
        # data/ tree
        assert (tmp_path / "ddata" / "raw").is_dir()
        assert (tmp_path / "ddata" / "processed").is_dir()
        # outputs/ contract tree
        for rel in ["tables", "figures", "logs", "models"]:
            assert (tmp_path / "oout" / rel).is_dir()
    finally:
        monkeypatch.undo()
        il.reload(_common)


def test_write_table_lands_in_env_output_dir(monkeypatch, tmp_path):
    import importlib as il

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "ddata"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "oout"))
    mod = il.reload(_common)
    try:
        path = mod.write_table(pd.DataFrame({"a": [1]}), "unit_test.csv")
        assert path == tmp_path / "oout" / "tables" / "unit_test.csv"
        assert path.is_file()
        manifest = mod.write_manifest({"probe": True})
        assert manifest == tmp_path / "oout" / "manifest_index.json"
        assert json.loads(manifest.read_text(encoding="utf-8"))["probe"] is True
    finally:
        monkeypatch.undo()
        il.reload(_common)


# --- shared helpers --------------------------------------------------------

def test_read_hourly_builds_timestamp_and_drops_cutoff(hourly, tmp_path, monkeypatch):
    csv = tmp_path / "dataset.csv"
    frame = hourly.assign(FECHA_CORTE="20260526")
    frame.to_csv(csv, index=False)
    monkeypatch.setattr(_common, "RAW_CSV", csv)
    out = _common.read_hourly(csv)
    assert out["timestamp"].is_monotonic_increasing
    assert out["timestamp"].iloc[0] == pd.Timestamp("2023-01-01 00:00")
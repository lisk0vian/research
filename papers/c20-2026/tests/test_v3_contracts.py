# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Design v3 contracts that would otherwise only fail on Colab.

Cheap by construction: tiny in-memory frames, no stage subprocesses. Each test
pins one thing that, if broken, silently corrupts a real run (the `PP`
precipitation column nulled by a pressure range, a timestamp built from the
wrong columns, a fold whose training window reaches into its test window).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PAPER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAPER_ROOT / "experiments"))

import _common  # noqa: E402
import _sample_data  # noqa: E402

qc = importlib.import_module("01_qc_hourly")
agg = importlib.import_module("02_aggregate_daily")


@pytest.fixture
def cfg() -> dict:
    return _common.load_config()


@pytest.fixture(scope="module")
def _senamhi_month() -> pd.DataFrame:
    # Built once: a month is enough to exercise every contract below.
    df = _sample_data.build("senamhi", years=1, seed=3, start_year=2023,
                            end_date="2023-01-31")
    return df


@pytest.fixture
def senamhi_csv(tmp_path, _senamhi_month) -> Path:
    path = tmp_path / "senamhi.csv"
    _senamhi_month.to_csv(path, index=False)
    return path


# --- variable layer ----------------------------------------------------------

def test_numeric_vars_follow_the_variable_map(cfg):
    assert _common.numeric_vars(cfg) == ("TT", "HR", "RR")
    assert "PP" not in _common.NUMERIC_VARS


def test_read_hourly_builds_timestamp_from_fecha_hora(senamhi_csv, cfg):
    df = _common.read_hourly(senamhi_csv, cfg=cfg)
    assert df["timestamp"].notna().all()
    first = df[df["UBIGEO"] == "150701"]["timestamp"].sort_values().iloc[:2].tolist()
    assert first == [pd.Timestamp("2023-01-01 00:00"), pd.Timestamp("2023-01-01 01:00")]
    assert {"TT", "HR", "RR"} <= set(df.columns)
    assert not {"TEMP", "PP"} & set(df.columns)


def test_ubigeo_keeps_its_leading_zero(senamhi_csv, cfg):
    raw = pd.read_csv(senamhi_csv)
    raw["UBIGEO"] = raw["UBIGEO"].astype(float)  # as the portal serves it
    raw.to_csv(senamhi_csv, index=False)
    codes = set(_common.read_hourly(senamhi_csv, cfg=cfg)["UBIGEO"])
    assert codes == set(_common.station_codes(cfg))


def test_precipitation_survives_qc(senamhi_csv, cfg):
    """The v2 regression: PP read as pressure, range [640, 720], all nulled."""
    df = _common.read_hourly(senamhi_csv, cfg=cfg)
    rain_before = int((df["RR"] > 0).sum())
    assert rain_before > 0
    df = qc.flag_missing_source(df.sort_values(["UBIGEO", "timestamp"]).reset_index(drop=True))
    df = qc.apply_qc_flags(df, cfg)
    assert int((df["RR"] > 0).sum()) == rain_before


def test_cold_station_values_are_in_range(cfg):
    lo, hi = cfg["qc_hourly"]["range"]["TT"]
    assert lo <= -16.7 and hi >= 26.3  # observed extremes of the real file


def test_daily_aggregation_without_wind_or_pressure(senamhi_csv, cfg):
    df = _common.read_hourly(senamhi_csv, cfg=cfg)
    daily = agg.aggregate(df, cfg)
    assert list(daily.columns) == agg.DAILY_COLUMNS
    assert daily["TT_mean"].notna().all()
    assert daily["RR_sum"].notna().any()
    assert daily[["PP_mean", "u_mean", "FF_mean"]].isna().all().all()
    assert daily["station"].nunique() == 5


# --- folds -------------------------------------------------------------------

def test_v3_folds_train_strictly_before_test(cfg):
    folds = cfg["validation"]["folds"]
    previous_end = None
    for fold in folds:
        tr0, tr1, te0, te1 = _common.fold_windows(fold, cfg)
        assert tr0 == pd.Timestamp(cfg["validation"]["train_start"])
        assert tr1 < te0 <= te1
        assert (te1 - te0).days in (364, 365)
        if previous_end is not None:
            assert te0 == previous_end + pd.Timedelta(days=1)  # contiguous, no overlap
        previous_end = te1
    assert previous_end <= pd.Timestamp(cfg["data"]["coverage_declared"][1])


def test_blind_folds_come_last(cfg):
    roles = [f["role"] for f in cfg["validation"]["folds"]]
    assert roles == sorted(roles, key=lambda r: r == "blind")


def test_legacy_fold_form_still_resolves():
    tr0, tr1, te0, te1 = _common.fold_windows({"train": [2018, 2020], "test": 2021})
    assert (tr0, tr1, te0, te1) == (pd.Timestamp("2018-01-01"), pd.Timestamp("2020-12-31"),
                                    pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31"))


def test_quantile_grid_is_symmetric_and_sorted(cfg):
    q = np.asarray(cfg["models"]["quantiles"])
    assert len(q) == 19 and np.all(np.diff(q) > 0)
    assert np.allclose(q + q[::-1], 1.0)


# --- fetch against the real portal's quirks ------------------------------------

def test_fetch_sends_a_browser_agent_and_reads_a_dkan_list(monkeypatch):
    import io
    import json as _json

    fetch = importlib.import_module("fetch_source")
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        body = {"success": True, "result": [{"resources": [
            {"url": "https://x/senamhi.csv", "format": "csv", "name": "data"}]}]}
        return Resp(_json.dumps(body).encode())

    monkeypatch.setattr(fetch.urllib.request, "urlopen", fake)
    out = fetch.resolve_resource({"source": {"dataset_id": "abc", "api": "https://x/api"}}, 5)
    assert out["resource"]["url"].endswith("senamhi.csv")
    assert seen["ua"].startswith("Mozilla/")

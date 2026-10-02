"""The synthetic data generator and the coverage check it exercises.

The generator exists so the pipeline can be run locally without the real
dataset. Two properties matter more than the values it produces:

- the column contract has to match what `_common.read_hourly` and the stages
  expect, or the local check fails for a reason that has nothing to do with the
  code under test;
- the synthetic series has to survive stage 00's checks, or it teaches the wrong
  lesson (a synthetic series without a diurnal cycle would fail V1, and V1's
  verdict would say nothing useful about the real data).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

PAPER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAPER_ROOT / "experiments"))

import _sample_data  # noqa: E402
import _common  # noqa: E402


class TestSchemas:
    def test_default_schema_comes_from_config(self):
        cfg = _common.load_config()
        assert cfg["sample_data"]["schema"] in _sample_data.BUILDERS

    def test_huancayo_matches_the_contract_read_hourly_needs(self):
        df = _sample_data.build("huancayo", years=1, seed=1)
        assert list(df.columns) == _sample_data.HUANCAYO_COLUMNS
        for required in ("year", "month", "day", "hour"):
            assert required in df.columns, "timestamp source column missing"

    def test_senamhi_matches_the_contract_of_record(self):
        df = _sample_data.build("senamhi", years=1, seed=1)
        assert list(df.columns) == _sample_data.SENAMHI_COLUMNS

    def test_unknown_schema_is_refused(self):
        with pytest.raises(SystemExit, match="unknown schema"):
            _sample_data.build("nope", years=1, seed=1)

    def test_config_change_is_the_only_edit_needed_to_switch(self):
        """The multi-station migration must not require rewriting this module."""
        assert set(_sample_data.BUILDERS) == {"huancayo", "senamhi"}


class TestValues:
    def test_is_deterministic_for_a_seed(self):
        a = _sample_data.build("huancayo", years=1, seed=7)
        b = _sample_data.build("huancayo", years=1, seed=7)
        pd.testing.assert_frame_equal(a, b)

    def test_a_different_seed_gives_different_values(self):
        a = _sample_data.build("huancayo", years=1, seed=7)
        b = _sample_data.build("huancayo", years=1, seed=8)
        assert not a["TT"].equals(b["TT"])

    def test_diurnal_trough_lands_in_the_window_v1_checks(self):
        """V1 tests exactly this (3 <= trough <= 8). A synthetic file that missed
        it would fail stage 00 for a reason unrelated to the code under test."""
        df = _sample_data.build("huancayo", years=1, seed=3)
        by_hour = df.groupby("hour")["TT"].mean()
        assert 3 <= by_hour.idxmin() <= 8, by_hour.idxmin()

    def test_the_diurnal_cycle_is_large_enough_to_see(self):
        df = _sample_data.build("huancayo", years=1, seed=3)
        by_hour = df.groupby("hour")["TT"].mean()
        assert by_hour.max() - by_hour.min() > 1.5

    def test_precipitation_is_a_burst_process_not_a_normal(self):
        """Features read rain sums and rain tendency, so a Gaussian would make
        them look meaningful when they are not."""
        df = _sample_data.build("huancayo", years=2, seed=5)
        wet = (df["RR"] > 0).mean()
        assert 0.01 < wet < 0.20, f"wet fraction {wet:.3f} out of range"
        assert df["RR"].max() > df["RR"].mean() * 5

    def test_humidity_stays_inside_its_physical_range(self):
        df = _sample_data.build("huancayo", years=1, seed=11)
        assert df["HR"].between(0, 100).all()

    def test_temperature_is_plausible_for_the_station(self):
        df = _sample_data.build("huancayo", years=1, seed=2)
        assert -30 < df["TT"].min() < 10
        assert 10 < df["TT"].max() < 40

    def test_senamhi_keeps_the_altitude_ordering_in_the_temperature(self):
        """The whole point of the study design is that higher is colder."""
        df = _sample_data.build("senamhi", years=1, seed=4)
        means = df.groupby(["ESTACION", "ALTITUD"])["TEMP"].mean().reset_index()
        means = means.sort_values("ALTITUD")
        assert means["TEMP"].is_monotonic_decreasing, means.to_dict("records")

    def test_senamhi_ubigeo_keeps_its_leading_zero(self):
        """The real file ships 40514 for IMATA; a float cast drops the zero and
        merges two stations. The generator must not reproduce that hazard."""
        df = _sample_data.build("senamhi", years=1, seed=6)
        ubis = set(df["UBIGEO"].astype(str))
        assert "040114" in ubis and "040514" in ubis
        assert all(len(u) == 6 for u in ubis), ubis

    def test_years_argument_sets_the_span(self):
        one = _sample_data.build("huancayo", years=1, seed=1)
        assert one["year"].nunique() == 1
        two = _sample_data.build("huancayo", years=2, seed=1)
        assert two["year"].nunique() == 2


class TestCoverageCheckOnShortData:
    """V4 must report an absent blind year, not raise a bare KeyError.

    The real dataset covers both blind years; a two-year synthetic one does not,
    and every station in the multi-station design carries its own window. That
    case has to produce a verdict naming the year, not a traceback.
    """

    def _v4(self, years):
        mod = importlib.import_module("00_verify_source")
        df = _sample_data.build("huancayo", years=years, seed=1)
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(
                dict(year=df.year, month=df.month, day=df.day, hour=df.hour)
            ),
        })
        return mod.check_v4_coverage(frame, _common.load_config())

    def test_short_series_reports_the_absent_blind_years(self):
        out = self._v4(2)
        assert out["verdict"] == "REVIEW_coverage_gaps"
        assert "absent from the data" in out["detail"]
        for y in (2024, 2025):
            assert str(y) in out["detail"]

    def test_it_does_not_raise(self):
        """The regression: this used to be KeyError('2024')."""
        assert self._v4(1)["check"] == "V4_coverage"
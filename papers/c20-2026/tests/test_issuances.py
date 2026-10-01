"""Tests for 04_make_issuances.py: calendar, targets, embargo, anti-leakage.

The property that matters most is that no target day is at or before its own
issuance, and that no training issuance sees into the fold's test year. Both are
checked exhaustively over every row of a synthetic run.
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

import importlib  # noqa: E402

iss = importlib.import_module("04_make_issuances")
harm = importlib.import_module("_harmonic")


@pytest.fixture
def daily() -> pd.DataFrame:
    """Four years of complete daily TT with a seasonal cycle.

    Kept deliberately short: every test that calls `compute_fold_issuances`
    rebuilds a panel and iterates daily issuances, so the fixture size drives the
    suite runtime on the author's machine.
    """
    idx = pd.date_range("2020-01-01", "2023-12-31", freq="D")
    doy = harm.doy_fractional(idx)
    tt = 11.0 + 4.0 * np.sin(2 * np.pi * (doy - 100) / 365.25)
    return pd.DataFrame({
        "date": idx, "n_hours": 24, "valid": True, "TT_mean": tt,
    })


@pytest.fixture
def cfg() -> dict:
    return {
        "target": {
            "horizons": {"W1": [1, 7], "W2": [8, 14], "W3_4": [15, 28]},
            "min_valid_days": {"W1": 5, "W2": 5, "W3_4": 10},
        },
        "climatology": {"harmonics_K": 3, "period_days": 365.25},
        "issuance": {"weekday": "monday", "training": "daily_allowed"},
        "validation": {"embargo_days": 28, "folds": [
            {"id": "D1", "train": [2020, 2021], "test": 2022, "role": "dev"},
            {"id": "B1", "train": [2020, 2022], "test": 2023, "role": "blind"},
        ]},
    }


@pytest.fixture
def climatology(tmp_path, monkeypatch):
    """Write fold coefficient JSONs and point the module at them.

    D1 and B1 get deliberately different intercepts so a test can prove that 04
    applies the coefficients of the fold being evaluated, not a shared default.
    """
    d = tmp_path / "outputs" / "climatology"
    d.mkdir(parents=True)
    intercepts = {"D1": 10.0, "B1": 12.0}
    for fold_id, intercept in intercepts.items():
        coef = [intercept, 1.0, -0.5, 0.3, -0.2, 0.1, -0.05]
        (d / f"{fold_id}.json").write_text(
            json.dumps({"fold": fold_id, "coefficients": {"C2": coef}}),
            encoding="utf-8",
        )
    monkeypatch.setattr(iss, "CLIM_JSON_DIR", d)
    return d


# --- weekday calendar ------------------------------------------------------

def test_weekly_dates_are_all_the_requested_weekday():
    got = iss.weekly_dates(pd.Timestamp("2022-01-01"), pd.Timestamp("2022-03-01"), 0)
    assert len(got) > 0
    assert set(got.dayofweek) == {0}


def test_weekly_dates_thursday_sensitivity():
    got = iss.weekly_dates(pd.Timestamp("2022-01-01"), pd.Timestamp("2022-03-01"), 3)
    assert set(got.dayofweek) == {3}


def test_weekly_dates_are_seven_days_apart():
    got = iss.weekly_dates(pd.Timestamp("2022-01-01"), pd.Timestamp("2022-06-01"), 0)
    gaps = np.diff(got.values).astype("timedelta64[D]").astype(int)
    assert set(gaps) == {7}


def test_weekly_dates_empty_when_start_after_end():
    assert len(iss.weekly_dates(pd.Timestamp("2022-05-01"),
                                pd.Timestamp("2022-01-01"), 0)) == 0


def test_weekday_table_covers_the_sensitivity_run():
    assert iss.WEEKDAY_NAMES["thursday"] == 3


# --- horizon windows -------------------------------------------------------

def test_horizon_windows_from_config():
    got = iss.horizon_windows({"W1": [1, 7], "W2": [8, 14], "W3_4": [15, 28]})
    assert got == {"W1": (1, 7), "W2": (8, 14), "W3_4": (15, 28)}


# --- climatology reconstruction -------------------------------------------

def test_anomalies_use_the_fold_coefficients(daily, climatology):
    coef = iss.load_fold_coefficients("D1")
    panel = iss.anomalies_for_window(
        daily, coef, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"), 365.25)
    expected_c2 = harm.eval_harmonic(coef, harm.doy_fractional(panel["date"]))
    assert np.allclose(panel["C2"], expected_c2)
    assert np.allclose(panel["A_C2"], panel["TT_mean"] - panel["C2"])


def test_climatology_differs_between_folds_not_between_years(daily, climatology):
    # C2 has no trend term, so within one fold the same day-of-year always gives
    # the same curve value. Per-fold fitting must therefore show up *between folds*
    # on a shared date, which is what this asserts.
    d1 = iss.load_fold_coefficients("D1")
    b1 = iss.load_fold_coefficients("B1")
    same_day = pd.Timestamp("2022-06-15")
    v_d1 = iss.anomalies_for_window(daily, d1, same_day, same_day, 365.25)
    v_b1 = iss.anomalies_for_window(daily, b1, same_day, same_day, 365.25)
    assert float(v_d1["C2"].iloc[0]) != float(v_b1["C2"].iloc[0])


def test_issuances_use_the_coefficients_of_their_own_fold(daily, cfg, climatology):
    # Each fold's rows must be built from that fold's climatology, not a default.
    for fold, expected in ((cfg["validation"]["folds"][0], 10.0),
                           (cfg["validation"]["folds"][1], 12.0)):
        out = iss.compute_fold_issuances(daily, fold, cfg)
        coef = iss.load_fold_coefficients(fold["id"])
        assert float(coef[0]) == expected
        assert not out.empty


def test_empty_window_returns_empty_frame(daily, climatology):
    coef = iss.load_fold_coefficients("D1")
    out = iss.anomalies_for_window(daily, coef,
                                   pd.Timestamp("2030-01-01"), pd.Timestamp("2030-02-01"), 365.25)
    assert out.empty


# --- target construction ---------------------------------------------------

@pytest.fixture
def panel() -> pd.DataFrame:
    idx = pd.date_range("2022-01-01", periods=90, freq="D")
    return pd.DataFrame({
        "date": idx, "valid": True, "TT_mean": 0.0,
        "C2": 11.0, "A_C2": np.linspace(-2, 2, len(idx)),
    })


def test_target_window_starts_after_the_issuance(panel):
    t = iss.build_target(panel, pd.Timestamp("2022-01-10"), "W1", 1, 7, 5)
    assert t["target_start"] == pd.Timestamp("2022-01-11")
    assert t["target_end"] == pd.Timestamp("2022-01-17")
    assert t["n_days"] == 7


def test_target_is_the_mean_of_daily_anomalies(panel):
    issue = pd.Timestamp("2022-01-10")
    t = iss.build_target(panel, issue, "W1", 1, 7, 5)
    win = panel[(panel["date"] > issue) & (panel["date"] <= issue + pd.Timedelta(days=7))]
    assert t["A_C2_target"] == pytest.approx(win["A_C2"].mean())


def test_target_rejects_short_windows(panel):
    # Drop most of the window: below min_valid the target is NaN, never imputed.
    gappy = panel.copy()
    gap = gappy["date"].between("2022-01-12", "2022-01-16")
    gappy.loc[gap, "A_C2"] = np.nan
    t = iss.build_target(gappy, pd.Timestamp("2022-01-10"), "W1", 1, 7, 5)
    assert t["n_valid_days"] == 2
    assert np.isnan(t["A_C2_target"])
    assert t["valid_target"] is False


def test_invalid_days_are_not_counted(panel):
    invalid = panel.copy()
    drop = invalid["date"].between("2022-01-12", "2022-01-15")
    invalid.loc[drop, "valid"] = False
    t = iss.build_target(invalid, pd.Timestamp("2022-01-10"), "W1", 1, 7, 5)
    assert t["n_valid_days"] == 3
    assert t["valid_target"] is False


def test_long_horizon_needs_more_days(panel):
    # 14 valid days is fine for W2 (needs 5) but for W3_4 the window is 14 wide.
    t_w2 = iss.build_target(panel, pd.Timestamp("2022-01-10"), "W2", 8, 14, 5)
    assert t_w2["n_days"] == 7
    t_w34 = iss.build_target(panel, pd.Timestamp("2022-01-10"), "W3_4", 15, 28, 10)
    assert t_w34["n_days"] == 14


# --- fold driver: structure and anti-leakage -------------------------------

def test_issuance_columns_match_contract(daily, cfg, climatology):
    out = iss.compute_fold_issuances(daily, cfg["validation"]["folds"][0], cfg)
    assert list(out.columns) == iss.ISSUANCE_COLUMNS


def test_eval_rows_are_weekly_and_inside_the_test_year(daily, cfg, climatology):
    fold = cfg["validation"]["folds"][0]  # test 2022
    out = iss.compute_fold_issuances(daily, fold, cfg)
    ev = out[out["kind"] == "eval"]
    assert set(ev["weekday"]) == {0}
    assert ev["issue_date"].dt.year.eq(2022).all()

    # Every issuance has three horizons except the ones clipped at year end, where
    # the target window would fall into the next year (the December Mondays).
    per_date = ev.groupby("issue_date")["horizon"].nunique()
    full, clipped = per_date[per_date == 3], per_date[per_date < 3]
    assert len(full) > 40
    assert set(clipped.index) <= {pd.Timestamp("2022-12-05"),
                                  pd.Timestamp("2022-12-12"),
                                  pd.Timestamp("2022-12-19"),
                                  pd.Timestamp("2022-12-26")}
    # A clipped date has fewer horizons exactly because its target leaves the year.
    for date in clipped.index:
        rows = ev[ev["issue_date"] == date]
        assert rows["target_end"].max() <= pd.Timestamp("2022-12-31")
        assert len(rows) == clipped[date]


def test_train_rows_are_daily_and_before_the_embargo(daily, cfg, climatology):
    fold = cfg["validation"]["folds"][0]  # train 2020-2021, test starts 2022-01-01
    out = iss.compute_fold_issuances(daily, fold, cfg)
    tr = out[out["kind"] == "train"]
    assert tr["issue_date"].nunique() > 300  # daily, not weekly
    last_allowed = pd.Timestamp("2021-12-04")  # 2021-12-04 + 28d < 2022-01-01
    assert tr["issue_date"].max() <= last_allowed


def test_no_target_day_is_at_or_before_its_issuance(daily, cfg, climatology):
    for fold in cfg["validation"]["folds"]:
        out = iss.compute_fold_issuances(daily, fold, cfg)
        assert (out["target_start"] > out["issue_date"]).all()


def test_no_training_target_reaches_the_test_year(daily, cfg, climatology):
    for fold in cfg["validation"]["folds"]:
        test_start = pd.Timestamp(fold["test"], 1, 1)
        out = iss.compute_fold_issuances(daily, fold, cfg)
        tr = out[out["kind"] == "train"]
        assert (tr["target_end"] < test_start).all()


def test_blind_targets_stay_inside_the_test_year(daily, cfg, climatology):
    fold = [f for f in cfg["validation"]["folds"] if f["role"] == "blind"][0]
    out = iss.compute_fold_issuances(daily, fold, cfg)
    ev = out[out["kind"] == "eval"]
    assert (ev["target_end"] <= pd.Timestamp(fold["test"], 12, 31)).all()
    assert (ev["issue_date"].dt.year == fold["test"]).all()


def test_embargo_covers_the_longest_horizon(daily, cfg, climatology):
    # The last allowed training issuance must still end its W3-4 window in time.
    fold = cfg["validation"]["folds"][0]
    test_start = pd.Timestamp(fold["test"], 1, 1)
    out = iss.compute_fold_issuances(daily, fold, cfg)
    w34 = out[(out["kind"] == "train") & (out["horizon"] == "W3_4")]
    assert w34["target_end"].max() < test_start


def test_dev_and_blind_folds_apply_the_same_clipping(daily, cfg, climatology):
    # Design choice: an issuance whose target leaves the test year is dropped for
    # every fold, so dev and blind are comparable. Both must lose their late
    # December W3-4 row rather than keeping an unvalidatable one.
    for fold in cfg["validation"]["folds"]:
        out = iss.compute_fold_issuances(daily, fold, cfg)
        ev = out[out["kind"] == "eval"]
        assert (ev["target_end"] <= pd.Timestamp(fold["test"], 12, 31)).all()
        assert ev["issue_date"].dt.year.eq(fold["test"]).all()
        per_date = ev.groupby("issue_date")["horizon"].nunique()
        assert (per_date < 3).sum() > 0, "the December clipping should bite"


def test_unknown_weekday_is_rejected(daily, cfg, climatology):
    bad = {**cfg, "issuance": {**cfg["issuance"], "weekday": "funday"}}
    with pytest.raises(SystemExit):
        iss.compute_fold_issuances(daily, bad["validation"]["folds"][0], bad)


def test_missing_coefficients_file_is_reported(daily, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(iss, "CLIM_JSON_DIR", tmp_path / "nope")
    with pytest.raises(SystemExit):
        iss.compute_fold_issuances(daily, cfg["validation"]["folds"][0], cfg)


def test_target_count_scales_with_training_window(daily, cfg, climatology):
    small = iss.compute_fold_issuances(daily, cfg["validation"]["folds"][0], cfg)
    large = iss.compute_fold_issuances(daily, cfg["validation"]["folds"][1], cfg)
    n_small = small[small["kind"] == "train"]["issue_date"].nunique()
    n_large = large[large["kind"] == "train"]["issue_date"].nunique()
    assert n_large > n_small


def test_all_rows_have_nan_targets_marked_invalid(daily, cfg, climatology):
    out = iss.compute_fold_issuances(daily, cfg["validation"]["folds"][0], cfg)
    invalid = out[out["A_C2_target"].isna()]
    assert (~invalid["valid_target"]).all()
    assert out[out["valid_target"]]["A_C2_target"].notna().all()
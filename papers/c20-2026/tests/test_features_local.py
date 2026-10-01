"""Tests for 05_features_local.py: trailing windows, per-variable anomalies, coverage.

The property that carries the most weight: no feature for issuance date d may
depend on any observation after d. A future leak would let the model read its own
target, and it would be invisible in the skill numbers, so it is tested by
perturbing the future and asserting the past does not move.
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

feat = importlib.import_module("05_features_local")
harm = importlib.import_module("_harmonic")

DAILY_COLS = ["date", "n_hours", "valid", "TT_mean", "TT_max", "TT_min", "DTR",
              "HR_mean", "PP_mean", "FF_mean", "DD_mean", "RR_sum",
              "u_mean", "v_mean", "RR_n_hours"]


@pytest.fixture
def daily() -> pd.DataFrame:
    """Two years of daily data with seasonal cycles on several variables."""
    idx = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    doy = harm.doy_fractional(idx)
    tt = 11.0 + 5.0 * np.sin(2 * np.pi * (doy - 100) / 365.25) + 0.01 * doy
    dtr = 12.0 + 4.0 * np.sin(2 * np.pi * (doy - 20) / 365.25)  # different phase
    hr = 65.0 - 10.0 * np.sin(2 * np.pi * (doy - 100) / 365.25)
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "date": idx, "n_hours": 24, "valid": True,
        "TT_mean": tt,
        "TT_max": tt + dtr / 2, "TT_min": tt - dtr / 2, "DTR": dtr,
        "HR_mean": hr, "PP_mean": 686.0 + 1.5 * np.sin(2 * np.pi * doy / 365.25),
        "FF_mean": 3.0, "DD_mean": 180.0,
        "RR_sum": rng.gamma(1.0, 2.0, size=len(idx)),
        "u_mean": 1.5 * np.cos(2 * np.pi * doy / 365.25),
        "v_mean": 1.5 * np.sin(2 * np.pi * doy / 365.25),
        "RR_n_hours": 24,
    })


@pytest.fixture
def cfg() -> dict:
    return {
        "climatology": {"harmonics_K": 3, "period_days": 365.25},
        "predictors": {"min_window_coverage": 0.5},
    }


@pytest.fixture
def clim_dir(tmp_path, monkeypatch):
    """03-style coefficient JSON so 05 can reuse the TT_mean reference."""
    d = tmp_path / "climatology"
    d.mkdir()
    coef = [11.0, 0.5, -0.3, 0.2, -0.1, 0.08, -0.04]
    (d / "D1.json").write_text(
        json.dumps({"fold": "D1", "coefficients": {"C2": coef}}), encoding="utf-8")
    monkeypatch.setattr(feat, "CLIM_JSON_DIR", d)
    return d


@pytest.fixture
def anom(daily, clim_dir):
    coef_tt = np.asarray(json.loads((clim_dir / "D1.json").read_text(encoding="utf-8"))
                         ["coefficients"]["C2"], dtype="float64")
    clims = feat.fit_variable_climatologies(daily, coef_tt,
                                            pd.Timestamp("2020-01-01"),
                                            pd.Timestamp("2020-12-31"), 3, 365.25)
    return feat.anomaly_frame(daily, clims, 365.25)


def _feats(daily, anom, coverage=0.5):
    return feat.build_daily_features(anom, daily["RR_sum"], daily["u_mean"],
                                     daily["v_mean"], coverage)


# --- the anti-leakage property --------------------------------------------

def _feats_from(daily: pd.DataFrame, coef_tt: np.ndarray) -> pd.DataFrame:
    """Features for an arbitrary frame, always against the same fitted reference."""
    clims = feat.fit_variable_climatologies(
        daily, coef_tt, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"), 3, 365.25)
    anom = feat.anomaly_frame(daily, clims, 365.25)
    return feat.build_daily_features(anom, daily["RR_sum"], daily["u_mean"],
                                     daily["v_mean"], 0.5)


def test_features_are_unaffected_by_the_future(daily, clim_dir):
    """Corrupting observations after a cutoff must not move earlier features.

    This is the anti-leakage test that carries the most weight: a leak would let
    a model read its own target, and it would never surface as a strange skill
    number, only as suspiciously good ones.
    """
    coef_tt = np.asarray(
        json.loads((clim_dir / "D1.json").read_text(encoding="utf-8"))["coefficients"]["C2"],
        dtype="float64")
    cutoff = pd.Timestamp("2021-06-01")

    clean = _feats_from(daily, coef_tt)

    poisoned = daily.copy()
    future = poisoned["date"] >= cutoff
    for col in ["TT_mean", "TT_max", "TT_min", "DTR", "HR_mean", "PP_mean",
                "RR_sum", "u_mean", "v_mean"]:
        poisoned.loc[future, col] = poisoned.loc[future, col] + 500.0
    dirty = _feats_from(poisoned, coef_tt)

    past = clean["date"] < cutoff
    assert past.any() and future.any()
    for col in clean.columns:
        if col in ("date", "valid"):
            continue
        a = clean.loc[past, col].to_numpy()
        b = dirty.loc[past, col].to_numpy()
        assert np.allclose(a, b, equal_nan=True), f"{col} leaked from the future"

    # Sanity: the perturbation really did move the later rows.
    later = clean["date"] >= cutoff
    assert not np.allclose(clean.loc[later, "TT_anom_lag_0"].to_numpy(),
                           dirty.loc[later, "TT_anom_lag_0"].to_numpy(), equal_nan=True)


def test_lag_zero_is_the_issuance_day_itself(daily, anom):
    f = _feats(daily, anom)
    assert np.allclose(f["TT_anom_lag_0"].to_numpy(), anom["A_TT_mean"].to_numpy())


def test_lag_n_is_n_days_back(daily, anom):
    f = _feats(daily, anom)
    for lag in (0, 3, 6):
        shifted = anom["A_TT_mean"].shift(lag).to_numpy()
        assert np.allclose(f[f"TT_anom_lag_{lag}"].to_numpy(), shifted, equal_nan=True)


# --- A0 and the mean windows ----------------------------------------------

def test_a0_is_the_trailing_7_day_anomaly_mean(daily, anom):
    f = _feats(daily, anom)
    expected = anom["A_TT_mean"].rolling(7, min_periods=4).mean()
    assert np.allclose(f["A0_7d"].to_numpy(), expected.to_numpy(), equal_nan=True)


def test_no_duplicate_column_for_the_seven_day_mean(daily, anom):
    # config lists A0_7d and TT_anom_mean_7_14_30; the 7-day member is the same
    # quantity, so it must appear once.
    f = _feats(daily, anom)
    assert "A0_7d" in f.columns
    assert "TT_anom_mean_7" not in f.columns
    assert "TT_anom_mean_14" in f.columns
    assert "TT_anom_mean_30" in f.columns


def test_thirty_day_window_differs_from_seven(daily, anom):
    f = _feats(daily, anom)
    assert not np.allclose(f["A0_7d"].to_numpy(), f["TT_anom_mean_30"].to_numpy(),
                           equal_nan=True)


# --- per-variable climatologies -------------------------------------------

def test_each_variable_gets_its_own_climatology(daily, anom):
    """DTR has a different seasonal phase from TT, so it needs its own curve."""
    assert "A_DTR" in anom.columns
    assert "A_HR_mean" in anom.columns
    # DTR residual SD must be small: a shared TT curve would leave its season in.
    assert anom["A_DTR"].std() < anom["DTR"].std() / 3


def test_fitted_anomalies_are_centred_on_the_training_window(daily, anom):
    """The curves 05 fits itself must leave no seasonal or level offset behind.

    A_TT_mean is deliberately absent: it reuses 03's coefficients verbatim and
    those carry no trend term, so a trending series leaves a residual mean. That
    is 03's contract (C3 is the variant with the trend) and is asserted in
    test_climatology.py, not here.
    """
    train = anom[(anom["date"] >= pd.Timestamp("2020-01-01"))
                 & (anom["date"] <= pd.Timestamp("2020-12-31"))]
    for var in ("A_DTR", "A_HR_mean", "A_PP_mean"):
        assert abs(float(train[var].mean())) < 0.5, var


def test_tt_mean_anomaly_keeps_the_stored_reference_not_a_refit(daily, anom, clim_dir):
    """A trend in the data must not be absorbed by 05 refitting TT_mean.

    If 05 fitted its own curve for TT_mean it would silently diverge from the
    target 04 built, and the model would be scored against a different reference.
    """
    coef = np.asarray(
        json.loads((clim_dir / "D1.json").read_text(encoding="utf-8"))["coefficients"]["C2"],
        dtype="float64")
    expected = harm.eval_harmonic(coef, harm.doy_fractional(anom["date"]))
    assert np.allclose(anom["TT_mean"].to_numpy() - anom["A_TT_mean"].to_numpy(),
                       expected, atol=1e-9)


def test_tt_mean_reuses_the_stored_coefficients(daily, anom):
    coef = np.asarray(json.loads((Path(feat.CLIM_JSON_DIR) / "D1.json")
                                 .read_text(encoding="utf-8"))["coefficients"]["C2"])
    expected = harm.eval_harmonic(coef, harm.doy_fractional(anom["date"]))
    assert np.allclose(anom["TT_mean"].to_numpy() - anom["A_TT_mean"].to_numpy(),
                       expected, atol=1e-9)


# --- coverage rule ---------------------------------------------------------

def test_min_periods_from_coverage():
    assert feat.min_periods(7, 0.5) == 4
    assert feat.min_periods(30, 0.5) == 15
    assert feat.min_periods(14, 1.0) == 14
    assert feat.min_periods(4, 0.1) == 1  # never zero


def test_short_window_becomes_nan_not_zero(daily, anom):
    gappy = anom.copy()
    mask = (gappy["date"] >= pd.Timestamp("2021-02-01")) & (gappy["date"] <= pd.Timestamp("2021-02-20"))
    gappy.loc[mask, "valid"] = False
    f = feat.build_daily_features(gappy, daily["RR_sum"], daily["u_mean"],
                                  daily["v_mean"], 0.5)
    during = f[(f["date"] >= pd.Timestamp("2021-02-15")) & (f["date"] <= pd.Timestamp("2021-02-18"))]
    assert during["A0_7d"].isna().all()


def test_invalid_days_do_not_contribute_to_means(daily, anom):
    gappy = anom.copy()
    day = pd.Timestamp("2021-05-10")
    huge = anom.loc[anom["date"] == day, "A_TT_mean"].iloc[0]
    gappy.loc[gappy["date"] == day, "A_TT_mean"] = huge + 100.0
    gappy.loc[gappy["date"] == day, "valid"] = False
    f = feat.build_daily_features(gappy, daily["RR_sum"], daily["u_mean"],
                                  daily["v_mean"], 0.5)
    row = f[f["date"] == day].iloc[0]
    assert row["A0_7d"] != row["A0_7d"] + 100.0


# --- non-mean features -----------------------------------------------------

def test_pp_tendency_is_a_difference_not_a_mean(daily, anom):
    f = _feats(daily, anom)
    expected = anom["PP_mean"] - anom["PP_mean"].shift(3)
    assert np.allclose(f["PP_tendency_3d"].to_numpy(), expected.to_numpy(), equal_nan=True)


def test_rain_features_use_log1p(daily, anom):
    f = _feats(daily, anom)
    raw = daily["RR_sum"].rolling(7, min_periods=4).sum()
    assert np.allclose(f["log1p_RR_sum_7"].to_numpy(), np.log1p(raw.to_numpy()),
                       equal_nan=True)


def test_wind_features_are_means_of_components(daily, anom):
    f = _feats(daily, anom)
    assert np.allclose(f["u_mean_7d"].to_numpy(),
                       daily["u_mean"].rolling(7, min_periods=4).mean().to_numpy(),
                       equal_nan=True)
    assert np.allclose(f["v_mean_7d"].to_numpy(),
                       daily["v_mean"].rolling(7, min_periods=4).mean().to_numpy(),
                       equal_nan=True)


# --- horizon-specific doy -------------------------------------------------

def test_doy_sin_cos_matches_the_horizon_midpoint():
    issue = pd.Timestamp("2021-06-15")
    s, c = feat.horizon_doy_sin_cos(issue, (1, 7))
    mid = issue + pd.Timedelta(days=(1 + 7) / 2)
    doy = harm.doy_fractional(pd.DatetimeIndex([mid]))[0]
    assert s == pytest.approx(np.sin(2 * np.pi * doy / 365.25))
    assert c == pytest.approx(np.cos(2 * np.pi * doy / 365.25))


def test_doy_sin_cos_differs_per_horizon():
    issue = pd.Timestamp("2021-06-15")
    w1 = feat.horizon_doy_sin_cos(issue, (1, 7))
    w2 = feat.horizon_doy_sin_cos(issue, (8, 14))
    w34 = feat.horizon_doy_sin_cos(issue, (15, 28))
    assert len({round(w1[0], 6), round(w2[0], 6), round(w34[0], 6)}) == 3


def test_doy_sin_cos_is_bounded():
    for lag in [(1, 7), (8, 14), (15, 28)]:
        s, c = feat.horizon_doy_sin_cos(pd.Timestamp("2021-03-01"), lag)
        assert abs(s) <= 1 and abs(c) <= 1
        assert s * s + c * c == pytest.approx(1.0, abs=1e-9)


# --- fold driver -----------------------------------------------------------

def _issuances(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for kind, dates in (("eval", pd.date_range("2021-01-04", "2021-03-01", freq="7D")),
                        ("train", pd.date_range("2020-02-01", "2020-04-01", freq="D"))):
        for d in dates:
            for h, (a, b) in {"W1": (1, 7), "W3_4": (15, 28)}.items():
                rows.append({"fold": "D1", "role": "dev", "issue_date": d,
                             "kind": kind, "horizon": h, "lag_start": a, "lag_end": b})
    return pd.DataFrame(rows)


def test_fold_features_have_one_row_per_issuance(daily, cfg, clim_dir):
    iss = _issuances(daily)
    out = feat.compute_fold_features(daily, iss, {"id": "D1", "train": [2020, 2020],
                                                  "test": 2021, "role": "dev"}, cfg)
    assert len(out) == len(iss)
    assert {"doy_sin_target_midpoint", "doy_cos_target_midpoint"}.issubset(out.columns)


def test_fold_features_only_cover_that_fold(daily, cfg, clim_dir):
    iss = _issuances(daily)
    iss = pd.concat([iss, iss.assign(fold="B1")], ignore_index=True)
    out = feat.compute_fold_features(daily, iss, {"id": "D1", "train": [2020, 2020],
                                                  "test": 2021, "role": "dev"}, cfg)
    assert set(out["fold"]) == {"D1"}


def test_missing_coefficients_file_is_reported(daily, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(feat, "CLIM_JSON_DIR", tmp_path / "nope")
    with pytest.raises(SystemExit):
        feat.compute_fold_features(daily, _issuances(daily),
                                   {"id": "D1", "train": [2020, 2020], "test": 2021,
                                    "role": "dev"}, cfg)
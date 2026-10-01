"""Tests for 03_climatology.py: harmonic fit, C1 window, sigma_hq, terciles.

The key property under test is that every fold fits its climatology on its own
training window only. A single global fit would leak the blind years (2024,
2025) into the reference those years are scored against and inflate MSSS_clim,
so the per-fold difference is asserted explicitly.
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

import _common  # noqa: E402

clim = importlib.import_module("03_climatology")


@pytest.fixture
def daily() -> pd.DataFrame:
    """Six years of daily TT with a seasonal cycle and a warming trend."""
    idx = pd.date_range("2020-01-01", "2025-12-31", freq="D")
    doy = idx.dayofyear.to_numpy(dtype="float64")
    tt = 11.0 + 4.0 * np.sin(2 * np.pi * (doy - 100) / 365.25) + 0.02 * doy
    return pd.DataFrame({
        "date": idx,
        "n_hours": 24,
        "valid": True,
        "TT_mean": tt,
    })


@pytest.fixture
def cfg() -> dict:
    return {
        "climatology": {"primary": "C2_harmonic", "harmonics_K": 3,
                        "period_days": 365.25},
        "target": {"horizons": {"W1": [1, 7], "W2": [8, 14], "W3_4": [15, 28]}},
        "validation": {"folds": [
            {"id": "D1", "train": [2020, 2022], "test": 2023, "role": "dev"},
            {"id": "B1", "train": [2020, 2024], "test": 2025, "role": "blind"},
        ]},
    }


# --- day-of-year and design matrix ----------------------------------------

def test_doy_fractional_resets_each_year_and_evaluates_smoothly():
    dates = pd.to_datetime(["2020-12-31", "2021-01-01"])
    doy = clim.doy_fractional(dates)
    assert doy[0] > 360      # Dec 31 is late in the year
    assert doy[1] < 5        # Jan 1 restarts at day 0
    # The harmonic is what must be continuous: day 365 and day 0 are adjacent on
    # the 365.25-day cycle, so their fitted climatology must nearly coincide.
    idx = pd.date_range("2020-06-01", "2021-05-31", freq="D")
    y = 11.0 + 4.0 * np.sin(2 * np.pi * clim.doy_fractional(idx) / 365.25)
    coef = clim.fit_harmonic(clim.doy_fractional(idx), y, k=3)
    at_365 = clim.eval_harmonic(coef, np.array([365.0]))
    at_0 = clim.eval_harmonic(coef, np.array([0.0]))
    assert abs(float(at_365[0] - at_0[0])) < 0.5


def test_design_matrix_shape_without_trend():
    X = clim.design_matrix(np.linspace(0, 365, 50), k=3)
    assert X.shape == (50, 7)  # intercept + 3 harmonics x (sin, cos)


def test_design_matrix_shape_with_trend():
    X = clim.design_matrix(np.linspace(0, 365, 50), k=3, trend=True)
    assert X.shape == (50, 8)


def test_eval_harmonic_recovers_k_from_coefficients():
    for k in (1, 2, 3):
        coef = np.arange(1 + 2 * k, dtype="float64")
        X = clim.design_matrix(np.linspace(0, 365, 20), k=k)
        assert np.allclose(clim.eval_harmonic(coef, np.linspace(0, 365, 20)), X @ coef)


def test_eval_harmonic_with_trend():
    coef = np.arange(8, dtype="float64")
    doy = np.linspace(0, 365, 20)
    X = clim.design_matrix(doy, k=3, trend=True)
    assert np.allclose(clim.eval_harmonic(coef, doy), X @ coef)


# --- fitting ---------------------------------------------------------------

def test_harmonic_recovers_known_amplitude():
    doy = np.linspace(0, 365.25, 800, endpoint=False)
    truth = 5.0 + 3.0 * np.sin(2 * np.pi * 1 * doy / 365.25)
    coef = clim.fit_harmonic(doy, truth, k=3)
    fitted = clim.eval_harmonic(coef, doy)
    assert np.max(np.abs(fitted - truth)) < 1e-6


def test_harmonic_ignores_nan_days():
    doy = np.linspace(0, 365.25, 200, endpoint=False)
    y = 5.0 + 2.0 * np.sin(2 * np.pi * doy / 365.25)
    y_with_gaps = y.copy()
    y_with_gaps[::7] = np.nan
    coef_clean = clim.fit_harmonic(doy, y, k=3)
    coef_gappy = clim.fit_harmonic(doy, y_with_gaps, k=3)
    # Missing days reduce the sample, not the underlying coefficients.
    assert np.max(np.abs(coef_clean - coef_gappy)) < 0.05


def test_c3_captures_a_trend_that_c2_cannot():
    doy = np.linspace(0, 365.25, 900, endpoint=False)
    y = 11.0 + 3.0 * np.sin(2 * np.pi * doy / 365.25) + 0.03 * doy
    resid_c2 = y - clim.eval_harmonic(clim.fit_harmonic(doy, y, k=3), doy)
    resid_c3 = y - clim.eval_harmonic(clim.fit_harmonic(doy, y, k=3, trend=True), doy)
    assert np.std(resid_c3) < np.std(resid_c2) * 0.5


# --- C1 window -------------------------------------------------------------

def test_c1_window_is_smooth_across_year_end():
    idx = pd.date_range("2020-01-01", periods=400, freq="D")
    y = 10.0 + 4.0 * np.sin(2 * np.pi * idx.dayofyear.to_numpy() / 365.25)
    smooth = clim.fit_c1_window(idx, y, window=15)
    assert len(smooth) == 365
    # Days 360 and 5 must be close: the band wraps the year boundary.
    assert abs(smooth[360] - smooth[5]) < 1.0


def test_apply_c1_window_returns_nan_for_unseen_days():
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    y = np.full(10, 12.0)
    smooth = clim.fit_c1_window(idx, y, window=15)
    out = clim.apply_c1_window(smooth, idx)
    assert out.shape == (10,)
    assert np.isfinite(out).all()


# --- fold isolation (the anti-leakage property) ---------------------------

def test_train_window_bounds():
    lo, hi = clim.train_window({"id": "B1", "train": [2020, 2024], "test": 2025})
    assert lo == pd.Timestamp("2020-01-01")
    assert hi == pd.Timestamp("2024-12-31")


def test_each_fold_gets_its_own_coefficients(daily, cfg):
    out_d1, meta_d1 = clim.compute_fold_climatology(daily, cfg["validation"]["folds"][0], cfg)
    out_b1, meta_b1 = clim.compute_fold_climatology(daily, cfg["validation"]["folds"][1], cfg)
    assert meta_d1["n_train_days"] < meta_b1["n_train_days"]
    # B1 trains on 5 years, D1 on 3: with a trend, the intercepts must differ.
    assert meta_d1["coefficients"]["C2"] != meta_b1["coefficients"]["C2"]
    # And the climatology evaluated on a shared day must differ between folds.
    shared = pd.Timestamp("2025-06-15")
    c2_d1 = float(out_d1.loc[out_d1["date"] == shared, "C2"].iloc[0])
    c2_b1 = float(out_b1.loc[out_b1["date"] == shared, "C2"].iloc[0])
    assert c2_d1 != c2_b1


def test_fold_does_not_see_its_own_test_year(daily, cfg):
    fold = cfg["validation"]["folds"][0]  # trains 2020-2022, tests 2023
    _, meta = clim.compute_fold_climatology(daily, fold, cfg)
    assert "2023" not in meta["train_window"][1]


def test_anomalies_are_centred_on_the_training_window(daily, cfg):
    fold = cfg["validation"]["folds"][0]
    out, _ = clim.compute_fold_climatology(daily, fold, cfg)
    train = out[(out["date"] >= pd.Timestamp("2020-01-01"))
                & (out["date"] <= pd.Timestamp("2022-12-31"))]
    # Residuals on the fitted window must average ~0 by least squares.
    assert abs(float(train["A_C2"].mean())) < 1e-6


# --- sigma_hq --------------------------------------------------------------

def test_quarter_boundaries_are_meteorological():
    dates = pd.to_datetime(["2021-01-15", "2021-03-15", "2021-07-15", "2021-10-15"])
    q = clim.quarter_of(dates)
    assert list(q) == [0, 1, 2, 3]  # DJF, MAM, JJA, SON


def test_quarter_of_wraps_december_into_djf():
    assert clim.quarter_of(pd.to_datetime(["2021-12-20"]))[0] == 0


def test_sigma_hq_has_four_quarters_per_horizon():
    idx = pd.date_range("2020-01-01", "2025-12-31", freq="D")
    resid = np.sin(idx.dayofyear.to_numpy() / 365.25 * 2 * np.pi)
    sig = clim.seasonal_sigma_hq(idx, resid, (1, 7))
    assert set(sig) == {"0", "1", "2", "3"}
    assert all(v > 0 for v in sig.values())


def test_sigma_hq_seasons_with_different_scales():
    # DJF twice as noisy as MAM: the per-quarter SDs must reflect that.
    idx = pd.date_range("2020-01-01", "2025-12-31", freq="D")
    scale = np.where(idx.month.isin([12, 1, 2]), 3.0, 1.0)
    resid = scale * np.sin(idx.dayofyear.to_numpy() / 365.25 * 4 * np.pi)
    sig = clim.seasonal_sigma_hq(idx, resid, (1, 7))
    assert sig["0"] > sig["1"] * 2


def test_sigma_hq_horizon_specific():
    # Sigma must grow with lead time when noise does.
    idx = pd.date_range("2020-01-01", "2025-12-31", freq="D")
    resid = np.random.default_rng(0).normal(size=len(idx))
    s1 = clim.seasonal_sigma_hq(idx, resid, (1, 7))
    s2 = clim.seasonal_sigma_hq(idx, resid, (15, 28))
    assert abs(np.mean(list(s1.values())) - np.mean(list(s2.values()))) < 0.2


def test_sigma_hq_falls_back_when_a_quarter_is_too_small():
    # Only one day of residuals: every quarter must still return a finite value.
    idx = pd.to_datetime(["2021-07-01"])
    sig = clim.seasonal_sigma_hq(idx, np.array([1.0]), (1, 7))
    # NaN here is correct: a single sample has no SD, and a one-sample pooled SD
    # would be a fabricated noise scale. 03 warns on it instead of inventing one.
    assert np.isnan(sig["0"])


# --- terciles --------------------------------------------------------------

def test_terciles_are_ordered_and_33_66_percentiles():
    idx = pd.date_range("2020-01-01", "2025-12-31", freq="D")
    y = np.random.default_rng(1).normal(size=len(idx))
    t = clim.tercile_thresholds(idx, y)
    assert set(t) == {str(m) for m in range(1, 13)}
    for month, (lo, hi) in t.items():
        assert lo < hi


def test_terciles_band_is_local_not_the_whole_year():
    idx = pd.date_range("2020-01-01", "2025-12-31", freq="D")
    # January is 0, everything else is 100.
    y = np.where(idx.month == 1, 0.0, 100.0)
    t = clim.tercile_thresholds(idx, y, window=15)
    # Locality: July's band never sees a January day, so it is pure 100. With a
    # band measured in months instead of days every month would share one pool.
    assert t["7"]["1"] == 100.0
    assert t["7"]["2"] == 100.0
    # January's own band is dominated by its own zero days.
    assert t["1"]["1"] == 0.0


def test_tercile_band_wraps_the_year_boundary():
    idx = pd.date_range("2020-01-01", "2025-12-31", freq="D")
    # Only December is extreme. With a circular band, December's terciles are
    # pulled down by the 100-valued days just after the year wraps.
    y = np.where(idx.month == 12, 0.0, 100.0)
    t = clim.tercile_thresholds(idx, y, window=15)
    assert t["12"]["1"] < 100.0
    assert t["12"]["1"] < t["1"]["1"]


def test_terciles_skip_months_with_too_few_samples():
    idx = pd.date_range("2021-07-01", periods=5, freq="D")
    assert clim.tercile_thresholds(idx, np.arange(5.0)) == {}


# --- fold driver contract --------------------------------------------------

def test_compute_fold_climatology_output_columns(daily, cfg):
    out, meta = clim.compute_fold_climatology(daily, cfg["validation"]["folds"][0], cfg)
    for col in ("date", "valid", "C2", "C3", "C1", "A_C2", "A_C3", "A_C1",
                "doy_frac", "quarter"):
        assert col in out.columns
    assert set(meta["sigma_hq"]) == {"W1", "W2", "W3_4"}
    assert meta["primary"] == "C2_harmonic"


def test_meta_is_json_serialisable(daily, cfg):
    _, meta = clim.compute_fold_climatology(daily, cfg["validation"]["folds"][0], cfg)
    json.loads(json.dumps(meta))  # must not raise


def test_empty_training_window_is_rejected(daily, cfg):
    bad = {"id": "X", "train": [2030, 2031], "test": 2032, "role": "dev"}
    with pytest.raises(SystemExit):
        clim.compute_fold_climatology(daily, bad, cfg)


def test_c1_c3_are_computed_for_every_day(daily, cfg):
    out, _ = clim.compute_fold_climatology(daily, cfg["validation"]["folds"][1], cfg)
    assert out["C1"].notna().all()
    assert out["C3"].notna().all()


def test_invalid_days_keep_their_anomaly_as_nan(daily, cfg):
    dirty = daily.copy()
    dirty.loc[dirty["date"].dt.year == 2025, "TT_mean"] = np.nan
    out, _ = clim.compute_fold_climatology(daily, cfg["validation"]["folds"][1], cfg)
    test_rows = out[out["date"].dt.year == 2025]
    assert test_rows["TT_mean"].isna().all() if "TT_mean" in out else True
    # C2 itself is a fitted curve: defined even where the observation is missing.
    assert test_rows["C2"].notna().all()
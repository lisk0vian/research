"""09c (amendment A2): the diagnostics must tell persistent paths from independent ones.

Synthetic paths only; no torch, no model download.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

d09c = importlib.import_module("09c_chronos_diagnostic")


def ar1(rng, shape, phi: float) -> np.ndarray:
    """AR(1) along the last axis, unit marginal variance."""
    x = np.empty(shape)
    x[..., 0] = rng.normal(size=shape[:-1])
    for t in range(1, shape[-1]):
        x[..., t] = phi * x[..., t - 1] + np.sqrt(1 - phi ** 2) * rng.normal(size=shape[:-1])
    return x


def test_lag1_recovers_the_ar_coefficient():
    rng = np.random.default_rng(0)
    assert d09c.lag1(ar1(rng, (400, 28), 0.7)) == pytest.approx(0.7, abs=0.03)
    assert d09c.lag1(rng.normal(size=(400, 28))) == pytest.approx(0.0, abs=0.03)


def test_independent_paths_shrink_like_one_over_sqrt_n():
    rng = np.random.default_rng(1)
    paths = rng.normal(size=(50, 200, 28))
    assert d09c.path_shrink(paths, 15, 28) == pytest.approx(1 / np.sqrt(14), rel=0.05)


def test_persistent_errors_shrink_much_less():
    rng = np.random.default_rng(2)
    err = ar1(rng, (3000, 28), 0.8)
    shrink = d09c.error_shrink(err, 15, 28)
    assert shrink > 2 * (1 / np.sqrt(14))


def test_calibrated_paths_cover_ninety_percent_daily():
    rng = np.random.default_rng(3)
    paths = rng.normal(size=(300, 200, 28))
    obs = rng.normal(size=(300, 28))
    d = d09c.daily_metrics(paths, obs)
    assert d["cov90"].mean() == pytest.approx(0.90, abs=0.02)
    assert d["spread"].mean() == pytest.approx(d["rmse_median"].mean(), rel=0.05)


def test_summary_flags_the_hypothesised_failure():
    """Daily-calibrated but independent paths vs persistent truth: the A2 cause."""
    rng = np.random.default_rng(4)
    n, s, lead = 400, 100, 28
    paths = rng.normal(size=(n, s, lead))              # right daily spread, no persistence
    obs = ar1(rng, (n, lead), 0.8)                     # real anomalies persist
    rows = {(r["check"], r["scope"], r["metric"][:6]): r
            for r in d09c.summarise(paths, obs, {"W3_4": (15, 28)}, "blind")}
    daily = rows[("daily", "days 15-28", "cov90 ")]
    agg = rows[("aggregation", "W3_4", "SD(win")]
    pers = rows[("persistence", "days 1-28", "lag-1 ")]
    assert daily["paths"] == pytest.approx(0.90, abs=0.03)
    assert pers["paths"] < 0.1 < 0.6 < pers["observed"]
    assert agg["paths"] < 0.5 * agg["observed"]


# --- 09d sensitivity: window coverage on the same anomaly scale -----------------------

def test_window_coverage_is_nominal_for_calibrated_paths():
    d09d = importlib.import_module("09d_chronos_sensitivity")
    rng = np.random.default_rng(5)
    n, s, lead = 400, 200, 28
    truth_paths = rng.normal(size=(n, s, lead))
    obs = rng.normal(size=(n, lead))
    cov, rmse = d09d.window_coverage(truth_paths, obs, 1, 7)
    assert cov == pytest.approx(0.90, abs=0.04)
    assert rmse == pytest.approx(1 / np.sqrt(7), rel=0.1)


def test_window_coverage_ignores_contexts_with_a_missing_day():
    d09d = importlib.import_module("09d_chronos_sensitivity")
    rng = np.random.default_rng(6)
    paths = rng.normal(size=(10, 50, 28))
    obs = rng.normal(size=(10, 28))
    obs[:, 3] = np.nan                       # every W1 window broken
    assert np.isnan(d09d.window_coverage(paths, obs, 1, 7)[0])
    assert np.isfinite(d09d.window_coverage(paths, obs, 8, 14)[0])

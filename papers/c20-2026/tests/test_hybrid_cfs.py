# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""09f (amendment A5): the CFSv2 hybrid, on synthetic data only.

What must hold: the CFS anomaly is fitted on training rows only and removes
the model's bias and seasonal cycle; a hybrid and its control always share
their training rows; the blend is a proper quantile average; the alignment
keeps only rows every system forecasts; H6 favours the better system and
corrects over horizons within each test; and the whole fit runs end to end
with a CFS signal the hybrid can use and the control cannot.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

h09 = importlib.import_module("09f_hybrid_cfs")
i09 = importlib.import_module("09_inference")
LEVELS = [round(0.05 * i, 2) for i in range(1, 20)]
COLS = [f"q{int(round(t * 100)):02d}" for t in LEVELS]
Z = np.array([NormalDist().inv_cdf(t) for t in LEVELS])


def mondays(start: str, n: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="W-MON")


def seasonal_frame(dates, bias, amp, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    doy = dates.dayofyear.to_numpy(float)
    f = bias + amp * np.sin(2 * np.pi * doy / 365.25) + noise * rng.normal(size=len(dates))
    return pd.DataFrame({"target_mid": dates, "F_mean": f})


# --- the CFS predictor -------------------------------------------------------------------------

def test_cfs_anomaly_removes_bias_and_seasonal_cycle():
    tr = seasonal_frame(mondays("2019-01-07", 160), bias=4.0, amp=3.0)
    ev = seasonal_frame(mondays("2022-07-04", 52), bias=4.0, amp=3.0)
    f_tr, f_ev = h09.cfs_anomaly(tr, ev, k=2, period=365.25, min_train=40)
    assert np.abs(f_tr).max() < 1e-6 and np.abs(f_ev).max() < 1e-6


def test_cfs_anomaly_is_fitted_on_training_rows_only():
    """A shift that exists only in the eval rows must survive as an anomaly."""
    tr = seasonal_frame(mondays("2019-01-07", 160), bias=4.0, amp=3.0)
    ev = seasonal_frame(mondays("2022-07-04", 52), bias=6.0, amp=3.0)
    _, f_ev = h09.cfs_anomaly(tr, ev, k=2, period=365.25, min_train=40)
    assert f_ev == pytest.approx(np.full(len(ev), 2.0), abs=1e-6)


def test_cfs_anomaly_refuses_a_thin_training_sample():
    tr = seasonal_frame(mondays("2019-01-07", 10), bias=0.0, amp=1.0)
    ev = seasonal_frame(mondays("2022-07-04", 5), bias=0.0, amp=1.0)
    assert h09.cfs_anomaly(tr, ev, k=2, period=365.25, min_train=40) is None


def test_add_cfs_anom_drops_thin_cells_and_keeps_rows_aligned():
    def cell(st, n_tr, n_ev):
        tr = seasonal_frame(mondays("2019-01-07", n_tr), 1.0, 2.0).assign(station=st, horizon="W1")
        ev = seasonal_frame(mondays("2022-07-04", n_ev), 1.0, 2.0).assign(station=st, horizon="W1")
        return tr, ev
    (tr_a, ev_a), (tr_b, ev_b) = cell("A", 120, 20), cell("B", 15, 20)
    train, evals = h09.add_cfs_anom(pd.concat([tr_a, tr_b]), pd.concat([ev_a, ev_b]),
                                    k=2, period=365.25, min_train=40)
    assert set(train["station"]) == {"A"} and set(evals["station"]) == {"A"}
    assert len(train) == 120 and len(evals) == 20
    assert train["cfs_anom"].notna().all() and evals["cfs_anom"].notna().all()


# --- combination, alignment and tests -------------------------------------------------------------

def test_blend_of_identical_forecasts_is_that_forecast():
    q = np.tile(Z, (4, 1))
    assert np.allclose(h09.vincent_blend(q, q), q)


def test_blend_sits_between_its_members_and_stays_monotone():
    a, b = np.tile(Z - 1.0, (3, 1)), np.tile(2.0 * Z + 1.0, (3, 1))
    q = h09.vincent_blend(a, b)
    assert np.all(np.diff(q, axis=1) >= 0)
    assert np.allclose(q, 0.5 * a + 0.5 * b)


def preds_frame(keys: pd.DataFrame, mu: float, sd: float = 1.0) -> pd.DataFrame:
    out = keys.copy()
    out["mean"] = mu
    for c, z in zip(COLS, Z):
        out[c] = mu + sd * z
    return out


def test_align_keeps_only_rows_every_system_forecasts():
    keys = pd.DataFrame({"station": "A", "fold": "B1",
                         "issue_date": mondays("2022-07-04", 6), "horizon": "W1"})
    index = keys.assign(obs=0.0)
    full = preds_frame(keys, 0.0)
    gappy = preds_frame(keys.iloc[:4], 0.5)
    gappy.loc[1, "q50"] = np.nan                       # an incomplete forecast is no forecast
    data = h09.align(index, {"X": full, "Y": gappy}, COLS)
    assert len(data["rows"]) == 3
    assert data["Q"]["Y"].shape == (3, len(LEVELS))
    assert np.allclose(data["MU"]["X"], 0.0) and np.allclose(data["MU"]["Y"], 0.5)


def test_h6_pairs_test_controls_only_for_trained_hybrids():
    present = {"Ridge_LG@CFS", "Ridge_LG@cfsrows", "GBM_LG@CFS", h09.BLEND, h09.CFS, "Ensemble"}
    pairs = h09.h6_pairs("Ensemble", present)
    labels = {(s, t) for s, _, t in pairs}
    assert ("Ridge_LG@CFS", "c_vs_control") in labels
    assert ("GBM_LG@CFS", "c_vs_control") not in labels   # its control is missing
    assert (h09.BLEND, "c_vs_control") not in labels      # the blend has no control
    assert len(pairs) == 3 * 2 + 1


def test_h6_favours_the_better_system_and_holm_runs_per_test():
    rng = np.random.default_rng(3)
    dates = mondays("2022-07-04", 60)
    rows = pd.concat([pd.DataFrame({"station": st, "fold": "B1", "issue_date": dates,
                                    "horizon": h}) for st in ("A", "B") for h in ("W1", "W2")],
                     ignore_index=True)
    obs = rng.normal(0.0, 1.0, len(rows))
    good = obs[:, None] + 0.2 * Z[None, :]             # sharp and centred on the truth
    poor = np.tile(1.5 + 1.0 * Z, (len(rows), 1))      # biased
    data = {"rows": rows, "obs": obs, "horizon": rows["horizon"].to_numpy(),
            "Q": {"H": good, "R": poor}}
    t = h09.h6_tests(data, [("H", "R", "a_vs_ref")], LEVELS, block=8, B=200, seed=0, m09=i09)
    assert list(t["horizon"]) == ["W1", "W2"]
    assert (t["dCRPS_ref_minus_system"] > 0).all() and (t["p_value"] < 0.05).all()
    assert (t["p_holm"] >= t["p_value"]).all()


def test_skill_table_reports_one_row_per_system_and_horizon():
    rng = np.random.default_rng(4)
    dates = mondays("2022-07-04", 30)
    rows = pd.concat([pd.DataFrame({"station": "A", "fold": "B1", "issue_date": dates,
                                    "horizon": h}) for h in ("W1", "W3_4")], ignore_index=True)
    obs = rng.normal(0.0, 1.0, len(rows))
    q = {"S": obs[:, None] + 0.3 * Z, "Clim": np.tile(1.0 * Z, (len(rows), 1)),
         "Damp": np.tile(0.9 * Z, (len(rows), 1))}
    data = {"rows": rows, "obs": obs, "horizon": rows["horizon"].to_numpy(), "Q": q}
    t = h09.skill_table(data, ["S"], {"clim": "Clim", "damp": "Damp"}, LEVELS, 4, 50, 0, i09)
    assert len(t) == 2 and set(t["horizon"]) == {"W1", "W3_4"}
    assert (t["CRPSS_clim"] > 0).all()
    assert (t["CRPSS_clim_low"] <= t["CRPSS_clim"]).all()
    assert t["cov90"].between(0, 1).all()


# --- end to end on a tiny panel -----------------------------------------------------------------

def tiny_panel_and_windows(seed: int = 7):
    """Two stations, one horizon, one blind fold; the target is mostly CFS signal."""
    rng = np.random.default_rng(seed)
    parts, wins = [], []
    for st, elev in (("000001", 3000.0), ("000002", 4000.0)):
        for kind, dates in (("train", mondays("2019-01-07", 170)),
                            ("eval", mondays("2022-07-04", 40))):
            signal = rng.normal(0.0, 1.0, len(dates))
            parts.append(pd.DataFrame({
                "station": st, "fold": "B1", "role": "blind", "kind": kind,
                "issue_date": dates, "horizon": "W1", "target_mid": dates + pd.Timedelta(days=4),
                "quarter": ((dates.month % 12) // 3).astype(int),
                "A0_7d": rng.normal(0.0, 1.0, len(dates)),
                "nino34_anom": rng.normal(0.0, 1.0, len(dates)),
                "A_C2_target": 0.9 * signal + 0.3 * rng.normal(size=len(dates)),
                "valid_target": True, "elev_m": elev, "lat": -12.0, "lon": -75.0,
            }))
            doy = (dates + pd.Timedelta(days=4)).dayofyear.to_numpy(float)
            wins.append(pd.DataFrame({
                "station": st, "issue_date": dates, "horizon": "W1",
                "F_mean": 10.0 + 2.0 * np.sin(2 * np.pi * doy / 365.25) + signal}))
    return pd.concat(parts, ignore_index=True), pd.concat(wins, ignore_index=True)


@pytest.fixture
def tiny_cfg():
    return {
        "models": {"quantiles": LEVELS, "ridge": {"alphas": [0.1, 1.0, 10.0]},
                   "gbm": {"n_estimators": 20, "learning_rate": 0.1, "num_leaves": 7,
                           "min_child_samples": 10},
                   "fast": {"gbm_n_estimators": 10, "bootstrap_B": 50}},
        "validation": {"embargo_days": 28},
        "seeds": {"gbm_largescale": 202},
    }


def test_fit_hybrids_end_to_end_uses_the_cfs_signal(tiny_cfg, monkeypatch):
    pytest.importorskip("lightgbm", reason="c20-2026 tests require lightgbm (paper environment)")
    monkeypatch.setenv("EXP_FAST", "1")
    panel, windows = tiny_panel_and_windows()
    out = h09.fit_hybrids(panel, windows, tiny_cfg, ["B1"], k=2, period=365.25, min_train=40)
    assert set(out) == {name for name, _, _ in h09.TRAINED}
    n = {name: len(f) for name, f in out.items()}
    assert len(set(n.values())) == 1 and n["Ridge_LG@CFS"] == 80      # same rows for all four
    obs = (panel[panel["kind"] == "eval"].sort_values(["station", "issue_date"])
           ["A_C2_target"].to_numpy())

    def crps(name):
        f = out[name].sort_values(["station", "issue_date"])
        return i09_crps(obs, f[COLS].to_numpy(float))
    assert crps("Ridge_LG@CFS") < 0.7 * crps("Ridge_LG@cfsrows")
    assert crps("GBM_LG@CFS") < crps("GBM_LG@cfsrows")


def i09_crps(obs, q):
    import _scores
    return float(_scores.crps_quantile(obs, q, LEVELS).mean())

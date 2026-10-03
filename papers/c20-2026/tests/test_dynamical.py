"""CFSv2 reference (stages 06b, 07d, H4): planning, aggregation, calibration.

Light by construction: the GRIB decoder (eccodes, absent locally) is never called;
the byte-range plan, the interpolation, the daily/window maths, the calibration
and the test statistic are pure numpy/pandas. The decode itself is exercised by
`06b_dynamical.py --probe` in the Colab notebook, on the first run.
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

d06 = importlib.import_module("06b_dynamical")
b07 = importlib.import_module("07d_cfs_benchmark")
i09 = importlib.import_module("09_inference")
r_all = importlib.import_module("run_all")


@pytest.fixture
def cfg() -> dict:
    return _common.load_config()


# --- planning -------------------------------------------------------------------

def test_issue_dates_are_mondays_from_the_archive_start():
    dates = d06.issue_dates("2018-10-31", "2018-12-31", weekday=0)
    assert dates[0] == pd.Timestamp("2018-11-05") and all(d.dayofweek == 0 for d in dates)


def test_file_url_matches_the_bucket_layout():
    url = d06.file_url("https://b", pd.Timestamp("2023-01-02"), "00", 3, "tmp2m")
    assert url == "https://b/cfs.20230102/00/time_grib_03/tmp2m.03.2023010200.daily.grb2"


IDX = "\n".join(f"{i + 1}:{i * 1000}:d=2023010200:TMP:2 m above ground:{6 * (i + 1)} hour fcst:"
                for i in range(130))


def test_idx_parsing_and_one_contiguous_range_for_28_days():
    idx = d06.parse_idx(IDX)
    assert idx[0] == (6, 0) and len(idx) == 130
    hours = d06.needed_hours(28)
    assert hours[0] == 24 and hours[-1] == 24 * 28 + 18 and len(hours) == 112
    start, end, msgs = d06.plan_range(idx, hours)
    assert start == 3 * 1000                      # hour 24 is the 4th message
    assert end == 115 * 1000 - 1                  # up to the byte before hour 696 (message 115)
    assert len(msgs) == 112 and msgs[0][1:] == (0, 1000)
    assert msgs[-1][2] == end + 1 - start         # the slices tile the range exactly


def test_plan_refuses_a_truncated_index():
    short = d06.parse_idx("\n".join(IDX.splitlines()[:115]))  # ends at hour 690
    with pytest.raises(ValueError):
        d06.plan_range(short, d06.needed_hours(28))
    with pytest.raises(ValueError):
        d06.plan_range(d06.parse_idx("\n".join(IDX.splitlines()[:20])), d06.needed_hours(28))


# --- interpolation and aggregation ------------------------------------------------

def test_bilinear_is_exact_on_a_plane_and_wraps_the_seam():
    lats = np.arange(90, -91, -1.0)            # north to south, as NOAA grids are stored
    lons = np.arange(0, 360, 1.0)
    plane = 0.5 * lats[:, None] + 0.1 * lons[None, :]
    got = d06.bilinear(plane, lats, lons, -11.8391, 283.62)
    assert got == pytest.approx(0.5 * -11.8391 + 0.1 * 283.62, abs=1e-9)
    assert d06.bilinear(plane, lats, lons, -11.8391, -76.378) == pytest.approx(got + 0.1 * (-76.378 + 360 - 283.62), abs=1e-9)
    seam = np.tile(np.sin(np.deg2rad(lats))[:, None], (1, 360))
    assert d06.bilinear(seam, lats, lons, 10.0, 359.5) == pytest.approx(np.sin(np.deg2rad(10.0)), abs=2e-3)


def test_daily_means_and_horizon_windows():
    steps = np.repeat(np.arange(28.0), 4) + np.tile([0.0, 0.2, 0.4, 0.6], 28)
    daily = d06.daily_from_steps(steps, 28)
    assert daily[0] == pytest.approx(0.3) and daily[27] == pytest.approx(27.3)
    frame = pd.DataFrame({"station": "A", "member": 1, "lead_day": np.arange(1, 29), "T_c": daily})
    w = d06.window_means(frame, {"W1": (1, 7), "W3_4": (15, 28)}).set_index("horizon")
    assert w.loc["W1", "F"] == pytest.approx(np.mean(daily[:7])) and w.loc["W1", "n_days"] == 7
    assert w.loc["W3_4", "F"] == pytest.approx(np.mean(daily[14:28]))


def test_ensemble_collapse_counts_members_and_spread():
    pm = pd.DataFrame({"station": "A", "horizon": "W1", "member": [1, 2, 3, 4],
                       "F": [10.0, 12.0, 14.0, 16.0], "n_days": 7})
    out = d06.ensemble_windows(pm, pd.Timestamp("2023-01-02")).iloc[0]
    assert out["F_mean"] == 13.0 and out["n_members"] == 4 and out["F_sd"] == pytest.approx(2.5819889)


class FakeGaussianCodes:
    """What eccodes reports for a CFSv2 `regular_gg` message, on a toy grid.

    Uneven latitudes, north to south, and no `jDirectionIncrementInDegrees`:
    the real T126 grid has none, which is what broke the first Colab run. The
    value of row i is i degC, so a station's result says which row it read.
    """
    LATS = np.array([80.0, 50.0, 10.0, -12.5, -40.0, -75.0])
    LONS = np.arange(0.0, 360.0, 45.0)

    def __init__(self, values_c=None):
        self.values_c = values_c

    def codes_new_from_message(self, b): return 1

    def codes_get(self, gid, key):
        keys = {"Ni": len(self.LONS), "Nj": len(self.LATS), "gridType": "regular_gg"}
        if key not in keys:
            raise KeyError(f"Key/value not found: {key}")
        return keys[key]

    def codes_get_array(self, gid, key):
        lat2d, lon2d = np.meshgrid(self.LATS, self.LONS, indexing="ij")
        return {"latitudes": lat2d.ravel(), "longitudes": lon2d.ravel()}[key]

    def codes_get_values(self, gid):
        if self.values_c is not None:
            return np.full(self.LATS.size * self.LONS.size, self.values_c + d06.KELVIN)
        rows = np.repeat(np.arange(self.LATS.size, dtype=float), self.LONS.size)
        return rows + d06.KELVIN

    def codes_release(self, gid): pass


def test_decoder_reads_a_gaussian_grid(monkeypatch):
    monkeypatch.setattr(d06, "_eccodes", lambda: FakeGaussianCodes())
    out = d06.decode_stations(b"x" * 10, [(24, 0, 10)],
                              [{"code": "A", "lat": -12.5, "lon": -45.0},   # row 3 exactly
                               {"code": "B", "lat": 30.0, "lon": 90.0}],    # halfway rows 1-2
                              (-45.0, 45.0))
    assert out[0, 0] == pytest.approx(3.0)
    assert out[0, 1] == pytest.approx(1.5)


def test_decoder_rejects_values_that_are_not_celsius(monkeypatch):
    """K -> degC is the one unit assumption; a wrong one must fail loudly."""
    monkeypatch.setattr(d06, "_eccodes", lambda: FakeGaussianCodes(values_c=5.0 - d06.KELVIN))
    with pytest.raises(RuntimeError, match="outside"):
        d06.decode_stations(b"x" * 10, [(24, 0, 10)], [{"code": "A", "lat": -12.0, "lon": -76.0}],
                            (-45.0, 45.0))


def test_new_stages_are_discovered_in_run_order():
    stages = r_all.discover_stages()
    assert stages.index("06_features_largescale") < stages.index("06b_dynamical") < stages.index("07_models")
    assert stages.index("07c_ensemble") < stages.index("07d_cfs_benchmark") < stages.index("08_metrics")


# --- calibration (07d) -------------------------------------------------------------

def _cells(n: int, slope: float, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2019-01-07", periods=n, freq="7D")
    mid = dates + pd.Timedelta(days=4)
    season = 6 * np.sin(2 * np.pi * (mid.dayofyear - 80) / 365.25)
    anomaly = rng.normal(0, 1, n)
    return pd.DataFrame({
        "target_mid": mid, "quarter": ((dates.month % 12) // 3).astype(int),
        # a biased CFS with its own seasonal cycle, carrying `slope` of the true anomaly
        "F_mean": 4.0 + 2.0 * season + slope * anomaly + rng.normal(0, 0.3, n),
        "A_C2_target": anomaly})


def test_calibration_removes_bias_and_seasonality_and_finds_the_signal():
    tr, ev = _cells(220, slope=1.5, seed=1), _cells(40, slope=1.5, seed=2)
    mu, sd, diag = b07.calibrate(tr, ev, k=2, period=365.25, min_train=40)
    assert diag["corr_train"] > 0.9 and diag["slope"] == pytest.approx(1 / 1.5, rel=0.2)
    assert np.corrcoef(mu, ev["A_C2_target"])[0, 1] > 0.9
    assert abs(mu.mean()) < 0.5 and np.all(sd > 0)    # no leftover offset of ~4 degC


def test_calibration_of_pure_noise_has_no_skill_and_too_thin_is_skipped():
    rng = np.random.default_rng(5)
    tr, ev = _cells(220, slope=0.0, seed=3), _cells(60, slope=0.0, seed=4)
    tr["F_mean"] = tr["F_mean"] + rng.normal(0, 1, len(tr))
    mu, _, diag = b07.calibrate(tr, ev, k=2, period=365.25, min_train=40)
    assert abs(diag["slope"]) < 0.4
    assert b07.calibrate(_cells(10, 1.0), ev, k=2, period=365.25, min_train=40) is None


def test_cfs_bc_is_neither_a_candidate_nor_an_ensemble_member(cfg):
    assert "CFS_BC" not in cfg["models"]["ensemble"]["members"]
    assert "CFS_BC" not in cfg["models"]["primary_model_selection"]["among"]
    assert "CFS_BC" not in cfg["models"]["candidates"]
    assert cfg["dynamical"]["folds"] == ["B1", "B2"] and "H4" in cfg["inference"]["multiplicity"]["families"]


# --- H4 ----------------------------------------------------------------------------

def _scored(n: int, crps_m: float, crps_cfs: float, indep: float = 0.0) -> pd.DataFrame:
    """Both models share the day's difficulty (as real CRPS series do); `indep` adds
    model-specific noise. With indep=0 and equal means the paired difference is
    exactly zero, so the 'no difference' case does not depend on a random draw."""
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        d = pd.Timestamp("2022-07-04") + pd.Timedelta(weeks=i)
        for st in ("A", "B"):
            shared = rng.normal(0, 0.1)
            for model, c in (("M", crps_m), ("CFS_BC", crps_cfs)):
                rows.append({"model": model, "station": st, "issue_date": d, "horizon": "W1",
                             "crps": c + shared + rng.normal(0, indep)})
    return pd.DataFrame(rows)


def test_h4_detects_a_better_observation_model_and_stays_quiet_otherwise():
    better = i09.h4_rows(_scored(60, 0.5, 0.8, indep=0.02), "M", {"W1": (1, 7)}, block=8, B=100, seed=1)[0]
    assert better["statistic"] > 0.4 and better["p_value"] < 0.05 and better["n_dates"] == 60
    same = i09.h4_rows(_scored(60, 0.6, 0.6), "M", {"W1": (1, 7)}, block=8, B=100, seed=1)[0]
    assert same["p_value"] > 0.05
    assert i09.h4_rows(_scored(60, 0.5, 0.8).query("model == 'M'"), "M", {"W1": (1, 7)}, 8, 50, 1) == []


# --- 07d end to end on synthetic inputs ---------------------------------------------

def test_07d_main_joins_windows_to_the_panel_and_writes_the_prediction_contract(
        tmp_path, monkeypatch, cfg):
    import _panel

    st = "150701"
    rng = np.random.default_rng(7)
    train_dates = pd.date_range("2019-01-07", periods=150, freq="7D")
    eval_dates = pd.date_range("2022-07-04", periods=20, freq="7D")

    def rows(dates, kind):
        mid = dates + pd.Timedelta(days=4)
        season = 6 * np.sin(2 * np.pi * (mid.dayofyear - 80) / 365.25)
        a = rng.normal(0, 1, len(dates))
        return pd.DataFrame({
            "station": st, "fold": "B1", "role": "blind" if kind == "eval" else "train",
            "kind": kind, "issue_date": dates, "horizon": "W1", "lag_start": 1, "lag_end": 7,
            "target_mid": mid.normalize(), "quarter": ((dates.month % 12) // 3).astype(int),
            "A_C2_target": a, "valid_target": True}), 3.0 + 1.5 * season + 1.2 * a

    (tr, f_tr), (ev, f_ev) = rows(train_dates, "train"), rows(eval_dates, "eval")
    panel = pd.concat([tr, ev], ignore_index=True)
    windows = pd.DataFrame({
        "station": st, "horizon": "W1", "issue_date": list(train_dates) + list(eval_dates),
        "F_mean": np.concatenate([f_tr, f_ev]), "F_sd": 0.5, "n_members": 4})
    wpath = tmp_path / "cfs_windows.csv"
    windows.to_csv(wpath, index=False)

    captured = {}
    monkeypatch.setattr(b07, "WINDOWS_CSV", wpath)
    monkeypatch.setattr(b07, "TABLES", tmp_path)
    monkeypatch.setattr(b07, "load_panel", lambda c: panel)
    monkeypatch.setattr(b07, "ensure_dirs", lambda: None)
    monkeypatch.setattr(b07, "write_manifest", lambda *a, **k: None)
    monkeypatch.setattr(b07, "write_preds",
                        lambda frames, exp, model: captured.update(frames=frames, exp=exp, model=model) or "ok")
    monkeypatch.setattr(b07, "load_config", lambda: {**cfg, "dynamical": {**cfg["dynamical"], "folds": ["B1"]}})
    b07.main()

    assert captured["exp"] == "temporal" and captured["model"] == "CFS_BC"
    out = pd.concat(captured["frames"], ignore_index=True)
    levels = [round(0.05 * k, 2) for k in range(1, 20)]
    from _scores import quantile_columns
    expected = ["experiment", "target", "station", "fold", "role", "issue_date", "horizon",
                "model", "mean", *quantile_columns(levels)]
    assert list(out.columns) == expected
    assert len(out) == len(eval_dates) and set(out["fold"]) == {"B1"} and set(out["role"]) == {"blind"}
    q = out[_panel.qcols({"models": {"quantiles": levels}})].to_numpy()
    assert np.isfinite(q).all() and np.all(np.diff(q, axis=1) >= 0)
    assert np.corrcoef(out["mean"], ev["A_C2_target"].to_numpy())[0, 1] > 0.8   # the signal survives
    diag = pd.read_csv(tmp_path / "T8_cfs_calibration.csv")
    assert diag.loc[0, "corr_train"] > 0.8 and diag.loc[0, "n_eval"] == len(eval_dates)

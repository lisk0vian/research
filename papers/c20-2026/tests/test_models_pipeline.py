"""Stages 06-10 on tiny in-memory data: contracts, not numbers.

Budget: the whole file runs in a few seconds on CPU. GBM uses a handful of
trees, the bootstrap 50 replicates, nothing is downloaded, and torch/Chronos
are only touched through their pure-numpy adapters (the network itself is
exercised on Colab). What is pinned here is what would otherwise fail an hour
into a Colab run: column contracts, key alignment between models, the latency
of the large-scale join, the scoring maths and the test statistics.
"""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PAPER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAPER_ROOT / "experiments"))

import _common  # noqa: E402
import _panel  # noqa: E402
import _scores  # noqa: E402

g06 = importlib.import_module("06_features_largescale")
m07 = importlib.import_module("07_models")
d07 = importlib.import_module("07b_deep")
e07 = importlib.import_module("07c_ensemble")
s08 = importlib.import_module("08_metrics")
i09 = importlib.import_module("09_inference")
f10 = importlib.import_module("10_tables_figures")

LEVELS = [round(0.05 * k, 2) for k in range(1, 20)]


@pytest.fixture
def cfg() -> dict:
    c = _common.load_config()
    c["models"]["gbm"]["n_estimators"] = 5
    return c


@pytest.fixture
def panel() -> pd.DataFrame:
    """Two stations, a dev and a blind fold, two horizons; y = 0.6 * A0 + noise."""
    rng = np.random.default_rng(0)
    rows = []
    for st, elev in (("150701", 2421.0), ("040514", 4475.0)):
        for fold, role, t0 in (("D1", "dev", "2019-07-01"), ("B1", "blind", "2022-07-01")):
            for kind, dates in (("train", pd.date_range("2016-01-01", periods=300, freq="D")),
                                ("eval", pd.date_range(t0, periods=30, freq="7D"))):
                for h, (a, b) in (("W1", (1, 7)), ("W3_4", (15, 28))):
                    a0 = rng.normal(0, 1, len(dates))
                    nino = rng.normal(0, 1, len(dates))
                    y = 0.6 * a0 + 0.3 * nino + rng.normal(0, 0.5, len(dates))
                    rows.append(pd.DataFrame({
                        "station": st, "fold": fold, "role": role if kind == "eval" else "train",
                        "kind": kind, "issue_date": dates, "horizon": h, "lag_start": a,
                        "lag_end": b, "A0_7d": a0, "TT_anom_lag_0": a0 + rng.normal(0, .3, len(dates)),
                        "nino34_anom": nino, "elev_m": elev, "lat": -12.0, "lon": -76.0,
                        "A_C2_target": y, "valid_target": True, "C2_target": 2.0,
                        "A_C2_target_TT_min": y - 1, "valid_target_TT_min": True,
                        "C2_target_TT_min": 0.5,
                    }))
    p = pd.concat(rows, ignore_index=True)
    mid = p["issue_date"] + pd.to_timedelta((p["lag_start"] + p["lag_end"]) / 2, unit="D")
    p["target_mid"] = mid.dt.normalize()
    p["quarter"] = ((p["issue_date"].dt.month % 12) // 3).astype(int)
    return p


# --- 06 large scale -----------------------------------------------------------

CPC_SAMPLE = """ Weekly SST data starts week centered on 2Sept1981

                Nino1+2      Nino3        Nino34        Nino4
 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 03JAN2024     24.1 1.5     27.0 1.9     28.2 2.0     29.3 1.0
 10JAN2024     24.0-0.3     26.9 1.7     28.0-1.8     29.1 0.9
"""


def test_cpc_parser_handles_glued_negative_values():
    df = g06.parse_cpc_weekly(CPC_SAMPLE)
    assert len(df) == 2
    assert df.loc[1, "nino12_anom"] == pytest.approx(-0.3)
    assert df.loc[1, "nino34_anom"] == pytest.approx(-1.8)
    assert df.loc[0, "week_centre"] == pd.Timestamp("2024-01-03")


def test_romi_parser_reads_components():
    df = g06.parse_romi("2024  1  2  0     0.5    -0.25     0.56\nheader line\n")
    assert df.loc[0, ["romi1", "romi2"]].tolist() == [0.5, -0.25]


def test_as_of_join_respects_latency():
    nino = g06.parse_cpc_weekly(CPC_SAMPLE)
    romi = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=30),
                         "romi1": np.arange(30.0), "romi2": 0.0, "romi_amp": 1.0})
    days = pd.date_range("2024-01-09", "2024-01-20")
    out = g06.as_of_daily(days, nino, romi, nino_lag=7, romi_lag=1).set_index("date")
    # On Jan 16 (d-7 = Jan 9) the Jan 10 week is not yet known: Jan 3 is used.
    assert out.loc["2024-01-16", "nino_week"] == pd.Timestamp("2024-01-03")
    assert out.loc["2024-01-17", "nino_week"] == pd.Timestamp("2024-01-10")
    # Before any week is centred on or before d-7 there is no value at all.
    assert np.isnan(out.loc["2024-01-09", "nino34_anom"])
    # ROMI of d-1 exactly.
    assert out.loc["2024-01-10", "romi1"] == 8.0  # Jan 9 is index 8


# --- scores ---------------------------------------------------------------------

def test_crps_on_grid_matches_gaussian_closed_form():
    mu, sd, y = 0.0, 1.0, 0.7
    q = _scores.gaussian_quantiles([mu], [sd], LEVELS)
    approx = _scores.crps_quantile([y], q, LEVELS)[0]
    z = (y - mu) / sd
    pdf, cdf = math.exp(-z * z / 2) / math.sqrt(2 * math.pi), 0.5 * (1 + math.erf(z / math.sqrt(2)))
    exact = sd * (z * (2 * cdf - 1) + 2 * pdf - 1 / math.sqrt(math.pi))
    # A 19-point quadrature of the quantile-score integral: within a few percent,
    # and the same rule for every model, so skill ratios are unaffected.
    assert approx == pytest.approx(exact, rel=0.08)


def test_rearrangement_removes_crossings():
    q = np.array([[0.0, 0.5, 0.3, 1.0]])
    assert np.all(np.diff(_scores.rearrange(q), axis=1) >= 0)


def test_pit_and_tercile_probabilities_are_coherent():
    q = _scores.gaussian_quantiles([0.0], [1.0], LEVELS)
    assert _scores.cdf_from_quantiles([0.0], q, LEVELS)[0] == pytest.approx(0.5, abs=1e-6)
    p = _scores.tercile_probs([-0.43], [0.43], q, LEVELS)[0]
    assert p.sum() == pytest.approx(1.0)
    assert p == pytest.approx([1 / 3, 1 / 3, 1 / 3], abs=0.02)


def test_murphy_terms_add_up():
    rng = np.random.default_rng(1)
    o = rng.normal(0, 1, 200)
    f = 0.5 * o + 0.2 + rng.normal(0, 0.5, 200)
    m = _scores.murphy(f, o)
    msss = 1 - np.mean((f - o) ** 2) / np.var(o)
    assert m["msss_sample"] == pytest.approx(msss, abs=1e-9)


# --- 07 models ------------------------------------------------------------------

def test_reference_models_shapes(panel, cfg):
    block = panel[panel["fold"] == "B1"]
    train = _panel.target_rows(block, "TT_mean", "train")
    evals = _panel.target_rows(block, "TT_mean", "eval").reset_index(drop=True)
    for q, mu in (m07.predict_clim(train, evals, "TT_mean", LEVELS),
                  m07.predict_damp(train, evals, "TT_mean", LEVELS),
                  m07.predict_pers(evals, LEVELS)):
        assert q.shape == (len(evals), 19) and len(mu) == len(evals)
        assert np.all(np.diff(q, axis=1) >= -1e-12)


def test_damp_recovers_the_persistence_slope(panel):
    block = panel[panel["fold"] == "B1"]
    train = _panel.target_rows(block, "TT_mean", "train")
    evals = _panel.target_rows(block, "TT_mean", "eval").reset_index(drop=True)
    _, mu = m07.predict_damp(train, evals, "TT_mean", LEVELS)
    slope = np.polyfit(evals["A0_7d"], mu, 1)[0]
    assert slope == pytest.approx(0.6, abs=0.15)


def test_ridge_lg_uses_the_large_scale_signal(panel, cfg):
    block = panel[panel["fold"] == "B1"]
    train = _panel.target_rows(block, "TT_mean", "train")
    evals = _panel.target_rows(block, "TT_mean", "eval").reset_index(drop=True)
    y = evals["A_C2_target"].to_numpy()
    mse = {}
    for name, cols in (("L", ["A0_7d", "TT_anom_lag_0"]),
                       ("LG", ["A0_7d", "TT_anom_lag_0", "nino34_anom"])):
        q, mu, chosen = m07.predict_ridge(train, evals, cols, "TT_mean", LEVELS,
                                          [0.1, 10.0], embargo=28)
        assert chosen and np.isfinite(q).all()
        mse[name] = np.mean((y - mu) ** 2)
    assert mse["LG"] < mse["L"]


def test_gbm_quantiles_do_not_cross(panel, cfg):
    block = panel[panel["fold"] == "B1"]
    train = _panel.target_rows(block, "TT_mean", "train")
    evals = _panel.target_rows(block, "TT_mean", "eval").reset_index(drop=True)
    params = {"n_estimators": 5, "learning_rate": 0.1, "num_leaves": 4,
              "min_child_samples": 10, "verbose": -1, "random_state": 0, "n_jobs": 1}
    q, mu = m07.predict_gbm(train, evals, ["A0_7d", "elev_m"], "TT_mean", LEVELS[::6] + [0.95], params)
    assert np.all(np.diff(q, axis=1) >= 0) and np.isfinite(mu).all()


def test_eval_index_holds_one_truth_per_key(panel):
    idx = _panel.build_eval_index(panel, "temporal", "TT_mean")
    assert not idx.duplicated(["station", "fold", "issue_date", "horizon"]).any()
    assert set(idx["role"]) == {"dev", "blind"}
    assert (idx["t1"] < idx["t2"]).all()


def test_loso_training_excludes_the_held_out_station(panel, monkeypatch, cfg):
    seen = []

    def fake_gbm(train, evals, cols, target, levels, params):
        seen.append((set(train["station"]), set(evals["station"])))
        n = len(evals)
        return np.zeros((n, len(levels))), np.zeros(n)

    monkeypatch.setattr(m07, "predict_gbm", fake_gbm)
    monkeypatch.setattr(m07, "atomic_write_csv", lambda *a, **k: None)
    monkeypatch.setattr(m07, "write_preds", lambda *a, **k: None)
    cfg["validation"]["loso"] = {"folds": ["B1"]}
    m07.run_loso(panel, cfg)
    assert seen
    for train_st, eval_st in seen:
        assert eval_st and not (train_st & eval_st)


# --- 07b adapters (no torch, no download) ---------------------------------------

def test_window_mean_is_taken_per_path_before_quantiles():
    rng = np.random.default_rng(0)
    paths = rng.normal(0, 1, (3, 400, 28))  # independent daily noise
    out = d07.window_quantiles(paths, {"W1": (1, 7), "W3_4": (15, 28)}, LEVELS)
    q, mu = out["W1"]
    assert q.shape == (3, 19) and mu.shape == (3,)
    # Mean of 7 iid N(0,1): sd 1/sqrt(7). Averaging daily quantiles would give sd 1.
    spread = (q[:, -1] - q[:, 0]).mean() / (2 * 1.645)
    assert spread == pytest.approx(1 / math.sqrt(7), rel=0.2)


def test_sequences_end_at_the_issue_date_and_never_after():
    idx = pd.date_range("2020-01-01", periods=100, freq="D")
    frame = pd.DataFrame({v: np.arange(100.0) for v in d07.SEQ_VARS}, index=idx)
    rows = pd.DataFrame({"station": ["X"], "issue_date": [pd.Timestamp("2020-02-10")]})
    seq = d07.build_sequences({"X": frame}, rows, seq_len=5)
    assert seq[0, -1, 0] == idx.get_loc(pd.Timestamp("2020-02-10"))  # last step is day d
    assert seq.shape == (1, 5, len(d07.SEQ_VARS))


def test_explode_aligns_quantiles_with_the_eval_index():
    ev = pd.DataFrame({"station": ["A", "B"], "issue_date": pd.to_datetime(["2023-01-02"] * 2),
                       "fold": "B1", "role": "blind"})
    q = np.arange(2 * 2 * 3, dtype=float).reshape(2, 2, 3)
    mu = q.mean(axis=-1)
    index = pd.DataFrame({"station": ["B", "A"], "fold": "B1",
                          "issue_date": pd.to_datetime(["2023-01-02"] * 2),
                          "horizon": ["W2", "W1"]})
    rows, Q, M = d07.explode(ev, q, mu, ["W1", "W2"], index)
    got = {(r.station, r.horizon): Q[i].tolist() for i, r in enumerate(rows.itertuples())}
    assert got == {("A", "W1"): q[0, 0].tolist(), ("B", "W2"): q[1, 1].tolist()}


# --- 07c, 08, 09 on predictions ---------------------------------------------------

@pytest.fixture
def preds_and_index(panel, cfg):
    cfg["models"]["quantiles"] = LEVELS
    idx = _panel.build_eval_index(panel, "temporal", "TT_mean")
    frames = []
    for fold in ("D1", "B1"):
        block = panel[panel["fold"] == fold]
        train = _panel.target_rows(block, "TT_mean", "train")
        evals = _panel.target_rows(block, "TT_mean", "eval").reset_index(drop=True)
        for model, (q, mu) in {
            "Clim": m07.predict_clim(train, evals, "TT_mean", LEVELS),
            "Damp": m07.predict_damp(train, evals, "TT_mean", LEVELS),
            "Pers": m07.predict_pers(evals, LEVELS),
        }.items():
            frames.append(_panel.pred_frame(evals, "temporal", "TT_mean", model, q, mu, cfg))
        for model, cols in (("Ridge_L", ["A0_7d"]), ("Ridge_LG", ["A0_7d", "nino34_anom"])):
            q, mu, _ = m07.predict_ridge(train, evals, cols, "TT_mean", LEVELS, [1.0], 28)
            frames.append(_panel.pred_frame(evals, "temporal", "TT_mean", model, q, mu, cfg))
    return pd.concat(frames, ignore_index=True), idx


def test_ensemble_weights_favour_the_better_member(preds_and_index):
    preds, idx = preds_and_index
    scores = e07.dev_crps(preds, idx, LEVELS)
    w = e07.inverse_crps_weights(scores, ["Clim", "Ridge_LG"])
    for h, wh in w.items():
        assert sum(wh.values()) == pytest.approx(1.0)
        assert wh["Ridge_LG"] > wh["Clim"]
    rows, q, mu = e07.combine(preds, w, _panel.qcols({"models": {"quantiles": LEVELS}}))
    assert len(rows) == len(idx) and np.all(np.diff(q, axis=1) >= 0)


def test_scoring_and_skill_tables(preds_and_index, cfg):
    preds, idx = preds_and_index
    scored = s08.score_rows(preds, idx, cfg)
    assert scored.loc[scored["model"] == "Pers", "crps"].isna().all()
    assert scored.loc[scored["model"] != "Pers", "crps"].notna().all()
    assert scored["pit"].dropna().between(0, 1).all()
    table = s08.aggregate(scored)
    pooled = table[(table["scope"] == "pooled") & (table["role"] == "blind")]
    damp = pooled[pooled["model"] == "Damp"]
    assert np.allclose(damp["CRPSS_damp"], 0.0)
    ridge = pooled[pooled["model"] == "Ridge_LG"]
    assert (ridge["CRPSS_clim"] > 0).all()
    frost = scored[scored["target"] == "TT_mean"]["p_frost"]
    assert frost.isna().all()  # frost index is defined on TT_min only


def test_bootstrap_and_hac_primitives():
    rng = np.random.default_rng(3)
    n = 104
    idx = i09.moving_block_indices(n, 8, rng)
    assert len(idx) == n and idx.max() < n
    num, den = rng.uniform(0.5, 1.0, n), np.full(n, 1.0)
    point, reps = i09.bootstrap_ratio(num, den, 8, 50, seed=1)
    assert point == pytest.approx(1 - num.sum() / den.sum())
    assert len(reps) == 50
    assert i09.one_sided_p(reps, point) < 0.05  # clearly positive skill
    assert i09.newey_west_se(rng.normal(0, 1, n), 4) > 0
    assert i09.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_clark_west_favours_a_correct_larger_model():
    rng = np.random.default_rng(4)
    x = rng.normal(0, 1, 500)
    y = 0.5 * x + rng.normal(0, 1, 500)
    cw = i09.clark_west(y, np.zeros(500), 0.5 * x)
    z = cw.mean() / i09.newey_west_se(cw, 3)
    assert i09.norm_sf(z) < 0.01


def test_figures_render_from_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(f10, "FIGURES", tmp_path)
    plt = f10._plt()

    def cheap_save(fig, name):  # the contract is "a file appears", not print quality
        path = tmp_path / f"{name}.png"
        fig.savefig(path, dpi=30)
        plt.close(fig)
        return f"figures/{name}.png"
    monkeypatch.setattr(f10, "_save", cheap_save)
    t2 = pd.DataFrame([{"model": m, "horizon": h, "metric": metric, "value": 0.1,
                        "ci_low": 0.0, "ci_high": 0.2}
                       for m in ("Ridge_L", "Ridge_LG", "GBM_L", "GBM_LG")
                       for h in ("W1", "W2") for metric in ("CRPSS_clim", "CRPSS_damp")])
    gaps = pd.DataFrame([{"model": "GBM_LG", "station": s, "elev_m": e, "horizon": h,
                          "dCRPS_loso_minus_temporal": 0.01, "ci_low": 0.0, "ci_high": 0.02}
                         for s, e in (("A", 2421), ("B", 4475)) for h in ("W1", "W2")])
    for path in (f10.fig_skill_by_horizon(t2, ["W1", "W2"]), f10.fig_budget(t2, ["W1", "W2"]),
                 f10.fig_loso(gaps, ["W1", "W2"])):
        assert (tmp_path / Path(path).name).stat().st_size > 1000

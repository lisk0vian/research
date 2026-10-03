"""09e (amendment A3.3): the pieces M*2 is built and selected from.

Synthetic data only. What must hold: the linear pool is a real mixture, the
calibrations reach their coverage on the data they are fitted to, EMOS
recovers a known normal, the selection follows A3's rule, and the cross-fit
never lets a fold calibrate itself.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pytest

scipy = pytest.importorskip("scipy", reason="c20-2026 tests require scipy (paper environment)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

m09e = importlib.import_module("09e_mstar2")
LEVELS = [round(0.05 * i, 2) for i in range(1, 20)]
Z = np.array([NormalDist().inv_cdf(t) for t in LEVELS])


def normal_q(mu, sd, n):
    return np.tile(mu + sd * Z, (n, 1))


def test_extended_tails_reach_zero_and_one_linearly():
    q, lv = m09e.extend_tails(normal_q(0.0, 1.0, 1), LEVELS)
    assert lv[0] == 0.0 and lv[-1] == 1.0 and q.shape == (1, 21)
    assert q[0, 0] < q[0, 1] and q[0, -1] > q[0, -2]


def test_pool_of_identical_members_is_that_member():
    q = normal_q(0.0, 1.0, 3)
    out = m09e.linear_pool([q, q], np.full((3, 2), 0.5), LEVELS)
    assert np.allclose(out, q, atol=0.02)


def test_pool_of_separated_members_is_wider_than_their_average():
    """The point of A3's second combination: disagreement widens the mixture."""
    a, b = normal_q(-2.0, 1.0, 1), normal_q(2.0, 1.0, 1)
    pool = m09e.linear_pool([a, b], np.array([[0.5, 0.5]]), LEVELS)
    vinc = 0.5 * a + 0.5 * b
    width = lambda q: q[0, -1] - q[0, 0]  # noqa: E731
    assert width(pool) > 1.5 * width(vinc)
    assert pool[0, LEVELS.index(0.5)] == pytest.approx(0.0, abs=0.05)


def test_conformal_reaches_its_coverage_on_the_fit_data():
    rng = np.random.default_rng(0)
    obs = rng.normal(0, 2.0, 4000)                      # forecasts say sd 1
    q = normal_q(0.0, 1.0, len(obs))
    p = m09e.fit_conformal(obs, q, LEVELS)
    qc, _ = m09e.apply_conformal(p, q, np.zeros(len(obs)), np.zeros(len(obs)), LEVELS)
    cov = np.mean((obs >= qc[:, 0]) & (obs <= qc[:, -1]))
    assert cov == pytest.approx(0.90, abs=0.01)
    assert qc[0, LEVELS.index(0.5)] == pytest.approx(0.0)  # median unchanged


def test_emos_recovers_a_known_normal():
    rng = np.random.default_rng(1)
    mu = rng.normal(0, 1, 5000)
    s2 = rng.uniform(0.0, 1.0, 5000)
    obs = 0.5 + 0.8 * mu + np.sqrt(0.3 + 2.0 * s2) * rng.normal(size=5000)
    p = m09e.fit_emos(obs, None, mu, s2)
    assert p["a"] == pytest.approx(0.5, abs=0.05) and p["b"] == pytest.approx(0.8, abs=0.05)
    assert p["c"] == pytest.approx(0.3, abs=0.1) and p["d"] == pytest.approx(2.0, abs=0.3)


def test_selection_prefers_in_range_then_lowest_crps():
    r = [{"dev_crps": 0.40, "dev_cov90": {"W1": 0.70, "W2": 0.72}},
         {"dev_crps": 0.45, "dev_cov90": {"W1": 0.88, "W2": 0.91}},
         {"dev_crps": 0.44, "dev_cov90": {"W1": 0.90, "W2": 0.86}}]
    assert m09e.select(r) is r[2]                       # lowest CRPS among in-range


def test_selection_falls_back_to_the_closest_coverage():
    r = [{"dev_crps": 0.40, "dev_cov90": {"W1": 0.70, "W2": 0.72}},
         {"dev_crps": 0.45, "dev_cov90": {"W1": 0.80, "W2": 0.83}}]
    assert m09e.select(r) is r[1]


def _data(rng, n_per_fold=400):
    """Two members, three dev folds and a 'blind' one, outcomes wider than both."""
    folds = np.repeat(["D1", "D2", "D3", "B1"], n_per_fold)
    n = len(folds)
    horizon = np.tile(np.array(["W1", "W2"]), n // 2)
    truth = rng.normal(0, 1, n)
    obs = truth + rng.normal(0, 1.5, n)
    Q = {"A": truth[:, None] + 0.8 * Z[None, :], "B": truth[:, None] + 0.2 + 0.6 * Z[None, :]}
    MU = {"A": truth, "B": truth + 0.2}
    return {"obs": obs, "horizon": horizon, "fold": folds, "Q": Q, "MU": MU}


@pytest.mark.parametrize("combo", ["vincent", "linpool"])
@pytest.mark.parametrize("calib", ["none", "k", "conformal", "emos"])
def test_every_configuration_runs_and_calibration_helps(combo, calib):
    data = _data(np.random.default_rng(2))
    dev = np.isin(data["fold"], ["D1", "D2", "D3"])
    q, mu, params = m09e.run_config(data, ["A", "B"], combo, calib, dev, ~dev, LEVELS)
    assert q.shape == ((~dev).sum(), len(LEVELS)) and np.isfinite(q).all()
    assert set(params["weights"]) == {"W1", "W2"}
    s = m09e.score(data["obs"][~dev], q, LEVELS, data["horizon"][~dev])
    if calib != "none":
        assert all(0.83 <= c <= 0.97 for c in s["cov90"].values())


def test_cross_fit_never_calibrates_a_fold_on_itself():
    """A fold whose outcomes are far wider must not set its own k."""
    rng = np.random.default_rng(3)
    data = _data(rng)
    wild = data["fold"] == "D3"
    data["obs"] = np.where(wild, data["obs"] * 4, data["obs"])
    dev = np.isin(data["fold"], ["D1", "D2", "D3"])
    q, _, _ = m09e.run_config(data, ["A", "B"], "vincent", "k", dev & ~wild, wild, LEVELS)
    s = m09e.score(data["obs"][wild], q, LEVELS, data["horizon"][wild])
    assert all(c < 0.8 for c in s["cov90"].values())   # k from D1-D2 cannot cover D3

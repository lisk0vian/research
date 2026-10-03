"""09b_calibration (amendment A2): the spread factor and its cross-fitting.

The property that matters: k is fitted on the dev folds only. Blind rows get k
from all dev folds; each dev row gets k from the *other* dev folds, so the
reported dev coverage is out of sample too.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

c09b = importlib.import_module("09b_calibration")

LEVELS = [round(0.05 * i, 2) for i in range(1, 20)]
COLS = [f"q{int(round(q * 100)):02d}" for q in LEVELS]


def _normal_quantiles(n: int, sd: float) -> np.ndarray:
    from statistics import NormalDist
    z = np.array([NormalDist().inv_cdf(q) for q in LEVELS])
    return np.tile(z * sd, (n, 1))


def test_exceedance_is_one_at_the_interval_edges():
    q = _normal_quantiles(2, 1.0)
    i05, i50, i95 = (c09b.level_index(LEVELS, x) for x in (0.05, 0.5, 0.95))
    obs = np.array([q[0, i95], q[1, i05]])
    assert np.allclose(c09b.exceedance(obs, q, i05, i50, i95), 1.0)


def test_fit_k_recovers_the_true_spread_ratio():
    """Forecasts with sd 1 for outcomes with sd 1.5 need k close to 1.5."""
    rng = np.random.default_rng(0)
    obs = rng.normal(0, 1.5, 20000)
    k = c09b.fit_k(obs, _normal_quantiles(len(obs), 1.0), LEVELS)
    assert k == pytest.approx(1.5, rel=0.05)


def test_stretch_keeps_the_median_and_scales_the_rest():
    q = _normal_quantiles(1, 1.0)
    s = c09b.stretch(q, 2.0, LEVELS)
    i50 = c09b.level_index(LEVELS, 0.5)
    assert s[0, i50] == pytest.approx(q[0, i50])
    assert np.allclose(s - s[:, [i50]], 2.0 * (q - q[:, [i50]]))


def _frame(rng, folds: dict[str, float]) -> pd.DataFrame:
    """Rows per fold whose outcomes have the given sd; forecasts all say sd 1."""
    parts = []
    for fold, sd in folds.items():
        n = 4000
        f = pd.DataFrame({"fold": fold, "horizon": "W1", "obs": rng.normal(0, sd, n)})
        f[COLS] = _normal_quantiles(n, 1.0)
        parts.append(f)
    return pd.concat(parts, ignore_index=True)


def test_blind_rows_get_k_from_dev_only():
    """A blind fold twice as variable must not pull its own k up."""
    rng = np.random.default_rng(1)
    frame = _frame(rng, {"D1": 1.5, "D2": 1.5, "D3": 1.5, "B1": 3.0})
    _, ks = c09b.recalibrated(frame, COLS, LEVELS, ["D1", "D2", "D3"])
    blind_k = ks[(frame["fold"] == "B1").to_numpy()]
    assert np.allclose(blind_k, blind_k[0]) and blind_k[0] == pytest.approx(1.5, rel=0.05)


def test_each_dev_fold_is_scored_with_k_from_the_other_dev_folds():
    rng = np.random.default_rng(2)
    frame = _frame(rng, {"D1": 1.0, "D2": 2.0, "D3": 2.0})
    _, ks = c09b.recalibrated(frame, COLS, LEVELS, ["D1", "D2", "D3"])
    k_d1 = ks[(frame["fold"] == "D1").to_numpy()][0]
    k_d2 = ks[(frame["fold"] == "D2").to_numpy()][0]
    assert k_d1 == pytest.approx(2.0, rel=0.05)   # fitted on D2 + D3 only
    assert k_d2 == pytest.approx(1.5, rel=0.15)   # fitted on D1 + D3

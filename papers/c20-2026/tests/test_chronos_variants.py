"""07e (amendment A3.1): Chronos-Bolt at the target's own resolution.

The parts that decide what Bolt sees and what it is scored on, tested without
torch: which block and step give each window, that a block follows the
target's validity rule and never reaches past the issue date, and how Bolt's
nine levels become the nineteen-level grid.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

m07e = importlib.import_module("07e_chronos_variants")
LEVELS = [round(0.05 * i, 2) for i in range(1, 20)]


def test_each_window_maps_to_a_block_and_a_step():
    assert m07e.block_step(1, 7) == (7, 1)      # W1: next 7-day block
    assert m07e.block_step(8, 14) == (7, 2)     # W2: the one after
    assert m07e.block_step(15, 28) == (14, 2)   # W3_4: second 14-day block
    with pytest.raises(ValueError):
        m07e.block_step(3, 9)                   # not on a block boundary


def test_blocks_end_on_the_issue_date_and_never_after():
    days = pd.date_range("2020-01-01", periods=60, freq="D")
    s = pd.Series(np.arange(60.0), index=days)
    means = m07e.block_means(s, 7, 5)
    issue = pd.Timestamp("2020-02-14")          # day index 44
    out = m07e.block_series(means, issue, 7, 3)
    assert out[-1] == pytest.approx(np.mean(np.arange(38, 45)))   # days 38..44
    assert out[-2] == pytest.approx(np.mean(np.arange(31, 38)))
    assert out[0] == pytest.approx(np.mean(np.arange(24, 31)))


def test_a_block_with_too_few_valid_days_is_missing():
    days = pd.date_range("2020-01-01", periods=21, freq="D")
    vals = np.arange(21.0)
    vals[14:17] = np.nan                         # last block keeps 4 of 7 days
    means = m07e.block_means(pd.Series(vals, index=days), 7, 5)
    out = m07e.block_series(means, days[-1], 7, 2)
    assert np.isnan(out[-1]) and np.isfinite(out[0])


def test_validity_rule_matches_the_target():
    assert m07e.min_valid_days(7, {}) == 5 and m07e.min_valid_days(14, {}) == 10


def test_bolt_levels_expand_to_the_grid():
    from statistics import NormalDist
    z = [NormalDist().inv_cdf(t) for t in m07e.BOLT_LEVELS]
    q = np.array([z, [2 * v + 1 for v in z]])   # N(0,1) and N(1,2)
    out = m07e.expand_levels(q, LEVELS)
    assert out.shape == (2, 19)
    assert np.all(np.diff(out, axis=1) > 0)
    i10, i50, i05, i95 = LEVELS.index(0.1), LEVELS.index(0.5), LEVELS.index(0.05), LEVELS.index(0.95)
    assert out[0, i10] == pytest.approx(z[0]) and out[1, i50] == pytest.approx(1.0)
    # Normal tails: exact for a normal forecast.
    assert out[0, i05] == pytest.approx(NormalDist().inv_cdf(0.05), abs=1e-6)
    assert out[1, i95] == pytest.approx(1 + 2 * NormalDist().inv_cdf(0.95), abs=1e-6)


# --- 07f (A3.2): seed summaries --------------------------------------------------

def _scored(rng):
    rows = []
    for model, shift in (("GBM_L", 0.0), ("GBM_LG", -0.1)):
        for k in range(5):
            for i in range(50):
                c = 1.0 + shift + rng.normal(0, 0.01)
                rows.append({"model": model, "seed": 100 + k, "seed_index": k, "role": "blind",
                             "horizon": "W1", "crps": c, "crps_clim": 1.2, "crps_damp": 1.1})
    return pd.DataFrame(rows)


def test_seed_summary_reports_mean_sd_and_range():
    m07f = importlib.import_module("07f_seed_variability")
    scored = _scored(np.random.default_rng(0))
    skill = m07f.skill_by_seed(scored).merge(
        scored[["model", "seed", "seed_index"]].drop_duplicates(), on=["model", "seed"])
    t12 = m07f.summarise_seeds(skill).set_index("model")
    assert t12.loc["GBM_LG", "n_seeds"] == 5
    assert t12.loc["GBM_LG", "CRPSS_clim_mean"] == pytest.approx(1 - 0.9 / 1.2, abs=0.01)
    assert t12.loc["GBM_LG", "CRPSS_clim_min"] <= t12.loc["GBM_LG", "CRPSS_clim_mean"] \
        <= t12.loc["GBM_LG", "CRPSS_clim_max"]
    assert t12.loc["GBM_LG", "CRPSS_clim_sd"] < 0.01


def test_pair_wins_counts_seeds_where_a_beats_b():
    m07f = importlib.import_module("07f_seed_variability")
    scored = _scored(np.random.default_rng(1))
    skill = m07f.skill_by_seed(scored).merge(
        scored[["model", "seed", "seed_index"]].drop_duplicates(), on=["model", "seed"])
    pairs = m07f.pair_wins(skill, ["GBM_L", "GBM_LG"]).iloc[0]
    assert pairs["n_seeds"] == 5 and pairs["a_better"] == 0   # GBM_L never beats GBM_LG

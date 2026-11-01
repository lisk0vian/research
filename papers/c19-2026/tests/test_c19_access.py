# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Synthetic tests for the access engine and the known-truth simulation (G1)."""

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

EXP = pathlib.Path(__file__).resolve().parents[1] / "experiments"
sys.path.insert(0, str(EXP))

from _access import (  # noqa: E402
    accumulated_cost, allocate_population, bootstrap_spearman, district_summary,
    stability,
)
from _simulate import empirical_or, simulate_outcomes  # noqa: E402

MIN_PER_KM = 1.0 / 1000.0  # 1 minute per kilometre, in minutes per metre


def test_uniform_row_is_exact():
    cost = np.full((1, 11), MIN_PER_KM)
    times = accumulated_cost(cost, [0], pixel_m=1000.0)
    np.testing.assert_allclose(times.ravel(), np.arange(11), atol=1e-12)


def test_source_pixel_is_zero():
    cost = np.full((5, 5), MIN_PER_KM)
    times = accumulated_cost(cost, [12], pixel_m=1000.0)
    assert times[2, 2] == 0.0


def test_diagonal_costs_sqrt2():
    cost = np.full((2, 2), MIN_PER_KM)
    times = accumulated_cost(cost, [0], pixel_m=1000.0)
    np.testing.assert_allclose(times[1, 1], np.sqrt(2.0), atol=1e-12)


def test_impassable_cell_forces_detour():
    cost = np.full((3, 3), MIN_PER_KM)
    cost[1, 1] = np.inf
    times = accumulated_cost(cost, [0], pixel_m=1000.0)
    np.testing.assert_allclose(times[2, 2], 2.0 + np.sqrt(2.0), atol=1e-12)


def test_time_ge_euclidean_distance_times_min_cost():
    rng = np.random.default_rng(3)
    cost = rng.uniform(1e-3, 5e-3, size=(15, 15))
    times = accumulated_cost(cost, [0], pixel_m=1000.0)
    rr, cc = np.indices(cost.shape)
    straight = np.hypot(rr, cc) * 1000.0 * cost.min()
    assert np.all(times + 1e-9 >= straight)


def test_population_keeps_the_census_total():
    rng = np.random.default_rng(4)
    grid = rng.uniform(0, 5, size=(10, 10))
    districts = np.zeros((10, 10), dtype=int)
    districts[:, 5:] = 1
    allocated, report = allocate_population(grid, districts, {0: 1000.0, 1: 50.0})
    assert allocated[districts == 0].sum() == pytest.approx(1000.0)
    assert allocated[districts == 1].sum() == pytest.approx(50.0)
    assert report[0]["status"] == "ok" and report[1]["status"] == "ok"


def test_population_without_cells_is_reported_not_invented():
    grid = np.zeros((4, 4))
    districts = np.ones((4, 4), dtype=int)
    allocated, report = allocate_population(grid, districts, {1: 100.0})
    assert allocated.sum() == 0.0
    assert report[1]["status"] == "no_population"


def test_district_summary_is_person_weighted():
    times = np.array([0.0, 61.0, 0.0, 120.0])
    pop = np.array([9.0, 1.0, 100.0, 0.0])
    districts = np.array([1, 1, 2, 2])
    frame = district_summary(times, pop, districts, ids=[1, 2])
    d1 = frame.loc[frame["district"] == 1].iloc[0]
    assert d1["mean_min"] == pytest.approx(6.1)
    assert d1["share_over_60"] == pytest.approx(0.1)
    d2 = frame.loc[frame["district"] == 2].iloc[0]
    assert d2["mean_min"] == pytest.approx(0.0)
    assert d2["share_unreachable"] == pytest.approx(0.0)


def test_stability_identity_and_reversal():
    rng = np.random.default_rng(5)
    a = rng.normal(size=60)
    same = stability(a, a)
    assert same["spearman"] == pytest.approx(1.0)
    assert same["jaccard_top"] == pytest.approx(1.0)
    reversed_ = stability(a, -a)
    assert reversed_["spearman"] == pytest.approx(-1.0)


def test_stability_compares_the_worst_districts():
    # Best set of a = 0..9, of b = 10..19; the worst sets are swapped.
    a = np.r_[np.arange(10), np.arange(100, 110)]
    b = np.r_[np.arange(100, 110), np.arange(10, 20)]
    assert stability(a, b, k=10)["jaccard_top"] == 0.0


def test_kappa_of_a_km_variant_is_quantile_matched():
    # Same order, different unit: matched classes agree perfectly at 60 and 120.
    minutes = np.linspace(5, 300, 40)
    km = minutes / 3.0                       # never above 60 "km" for most districts
    s = stability(minutes, km, b_minutes=False)
    assert s["kappa_60"] == pytest.approx(1.0)
    assert s["kappa_120"] == pytest.approx(1.0)
    assert s["flagged_variant_60"] == s["flagged_main_60"]
    # The pre-v3 rule (km > 60) would have flagged a different count.
    assert int((km > 60).sum()) != s["flagged_main_60"]


def test_constant_variant_gives_zero_kappa_and_reports_counts():
    minutes = np.linspace(5, 300, 40)
    s = stability(minutes, np.zeros(40), b_minutes=False)
    assert s["kappa_60"] == pytest.approx(0.0)
    assert s["flagged_variant_60"] == 40     # every tie at the cut is flagged, and reported


def test_top_k_overlap_is_undefined_when_ties_straddle_the_cut():
    a = np.arange(30, dtype=float)
    b = np.r_[np.zeros(15), np.arange(15, dtype=float)]   # 15 tied at the bottom
    assert stability(a, -b, k=10)["jaccard_top"] is None  # negated: ties become the "worst"
    assert stability(a, b, k=10)["jaccard_top"] is not None


def test_weighted_by_district_is_person_weighted():
    from _access import weighted_by_district
    values = np.array([[1.0, 3.0], [10.0, np.nan]])
    pop = np.array([[1.0, 3.0], [5.0, 2.0]])
    districts = np.array([[1, 1], [2, 2]])
    out = weighted_by_district(values, pop, districts, ids=[1, 2, 3])
    assert out[0] == pytest.approx((1 * 1 + 3 * 3) / 4)
    assert out[1] == pytest.approx(10.0)      # the NaN cell is ignored
    assert np.isnan(out[2])                    # a district without people stays NaN


def test_unreachable_counts_as_deficient():
    times = np.array([0.0, np.inf, 30.0, np.inf])
    pop = np.ones(4)
    districts = np.ones(4, dtype=int)
    row = district_summary(times, pop, districts, ids=[1]).iloc[0]
    assert row["share_over_60"] == pytest.approx(0.5)
    assert row["share_over_120"] == pytest.approx(0.5)
    assert row["share_unreachable"] == pytest.approx(0.5)
    assert row["mean_min"] == pytest.approx(15.0)


def test_east_west_width_follows_latitude():
    cost = np.full((1, 11), MIN_PER_KM)
    times = accumulated_cost(cost, [0], pixel_m=927.0, lats=np.array([-18.0]))
    dx = 927.0 * np.cos(np.radians(-18.0))
    np.testing.assert_allclose(times.ravel(), np.arange(11) * dx / 1000.0, atol=1e-9)


def test_bootstrap_ci_brackets_the_estimate():
    rng = np.random.default_rng(6)
    a = rng.normal(size=80)
    b = a + rng.normal(0, 0.5, size=80)
    lo, hi = bootstrap_spearman(a, b, n_boot=200, seed=1)
    assert lo < 1.0 and hi > lo


def test_planted_or_is_recovered():
    times = np.array([0.0] * 40 + [60.0] * 40)
    deaths = np.full(80, 10_000)
    cases = simulate_outcomes(times, deaths, or_per_60=1.5,
                              baseline_odds=0.2, seed=7)
    assert empirical_or(times, deaths, cases) == pytest.approx(1.5, rel=0.15)


def test_null_or_is_near_one():
    times = np.array([0.0] * 40 + [60.0] * 40)
    deaths = np.full(80, 10_000)
    cases = simulate_outcomes(times, deaths, or_per_60=1.0,
                              baseline_odds=0.2, seed=8)
    assert empirical_or(times, deaths, cases) == pytest.approx(1.0, rel=0.15)

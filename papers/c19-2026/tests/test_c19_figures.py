# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Synthetic tests for stage 10 (figures and tables): pure helpers and one drawing."""

import importlib
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

EXP = pathlib.Path(__file__).resolve().parents[1] / "experiments"
sys.path.insert(0, str(EXP))
ft = importlib.import_module("10_figures_tables")


def test_altitude_bands_follow_the_plan_cuts():
    bands = ft.altitude_band([10, 499.9, 500, 2499, 2500, 3500, 4800]).astype(str).tolist()
    assert bands == ["<500 m", "<500 m", "500–2,500 m", "500–2,500 m", "2,500–3,500 m",
                     "≥3,500 m", "≥3,500 m"]


def test_equity_table_is_person_weighted():
    access = pd.DataFrame({"ubigeo": ["a", "b", "c"], "population": [100.0, 300.0, 0.0],
                           "mean_min": [10.0, 50.0, 999.0], "share_over_60": [0.0, 0.5, 1.0],
                           "share_over_120": [0.0, 0.1, 1.0]})
    regions = pd.DataFrame({"ubigeo": ["a", "b", "c"], "mean_altitude": [100.0, 120.0, 4000.0],
                            "amazon": [False, False, True]})
    t = ft.equity_table(access, regions)
    peru = t[t["basin"] == "Peru"].iloc[0]
    assert peru["districts"] == 2                        # the district without people is left out
    assert peru["mean_min"] == pytest.approx((100 * 10 + 300 * 50) / 400)
    assert peru["pct_over_60"] == pytest.approx(100 * 150 / 400)


def test_agreement_classes_match_the_count_of_deficient_districts():
    minutes = np.array([10, 20, 70, 80, 130, 200], dtype=float)
    km = np.array([1, 50, 2, 60, 70, 80], dtype=float)
    cls, cut = ft.agreement_classes(minutes, km)
    assert (cls != "neither").sum() >= 4
    assert int(((cls == "both") | (cls == "distance_only")).sum()) == 4   # 4 flagged by km too
    assert cut == 50.0
    assert cls[1] == "distance_only" and cls[2] == "time_only"


def test_weighted_cdf_is_the_population_share_within_t():
    cdf = ft.weighted_cdf([10, 30, 90], [1, 1, 2], np.array([0, 10, 60, 120]))
    np.testing.assert_allclose(cdf, [0.0, 25.0, 50.0, 100.0])


def test_markdown_tables_are_latex_safe_and_mark_missing_values():
    df = pd.DataFrame({"κ at 60 min": [0.5, np.nan], "band": ["≥3,500 m", "x"]})
    text = ft.latex_safe(ft.to_markdown(df, {"κ at 60 min": ".2f"}))
    assert "$\\kappa$" in text and "$\\geq$" in text
    assert "| 0.50 |" in text and "—" in text


def _summary():
    row = {"n": 100, "or_per_60": 1.01, "ci_low": 0.98, "ci_high": 1.04}
    groups = ["amenable_acute", "amenable_chronic", "cancer", "external", "other", "unknown"]
    return {"main": row, "sensitivity_gee": row, "completeness_sensitivity": row,
            "exclude_otro": row, "period_2020_2021": row, "exploratory_all_causes": row,
            "h3b": {"by_cause": [{"cause_group": g, **row} for g in groups]},
            "simulation": {"planted": [{"or_planted": 1.1, "power": 0.99}]}}


def test_forest_rows_keep_the_plotting_order():
    rows = ft.forest_rows(_summary())
    assert rows["label"].iloc[0].startswith("H3a")
    assert rows["label"].iloc[-1].startswith("All causes")
    assert len(rows) == 12


def test_forest_plot_draws_at_page_size():
    import _figqa as qa
    import _figstyle as st
    plt = st.setup()
    f = ft.fig5_rq3(plt, {"s8": _summary()})
    try:
        assert qa.check_size(f.fig, st.DOUBLE_MM, st.MAX_HEIGHT_MM["chart"]) == []
        assert qa.check_text(f.fig) == []
    finally:
        plt.close(f.fig)

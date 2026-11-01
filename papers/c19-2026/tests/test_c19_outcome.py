# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Synthetic tests for the SINADEF outcome pipeline (no real data)."""

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("statsmodels", reason="c19-2026 tests require the paper environment")

EXP = pathlib.Path(__file__).resolve().parents[1] / "experiments"
sys.path.insert(0, str(EXP))

import _outcome as oc  # noqa: E402
from _simulate import death_level_outcome  # noqa: E402


def raw_frame():
    return pd.DataFrame({
        "COD# UBIGEO DOMICILIO": ["92-33-14-01-32-000", "92-33-14-01-32-000",
                                  "92-33-04-01-14-000", "92-33-14-01-01-000",
                                  "92-33-14-01-32-000", "92-33-14-01-32-000"],
        "AÑO": ["2023"] * 6,
        "TIPO LUGAR": ["EESS", "DOMICILIO", "VIA PUBLICA", "OTRO", "", "SIN REGISTRO"],
        "SEXO": ["MASCULINO", "FEMENINO", "MASCULINO", "FEMENINO", "MASCULINO", "FEMENINO"],
        "EDAD": ["10", "70", "40", "85", "2", "50"],
        "TIEMPO EDAD": ["AÑOS", "AÑOS", "AÑOS", "AÑOS", "MESES", "AÑOS"],
        "CAUSA A (CIE-X)": ["I219", "E119", "V091", "C509", "J189", "SIN REGISTRO"],
        **{f"CAUSA {k} (CIE-X)": [None] * 6 for k in "BCDEF"},
        "DEPARTAMENTO DOMICILIO": ["LIMA"] * 6,
        "PROVINCIA DOMICILIO": ["LIMA"] * 6,
        "DISTRITO DOMICILIO": ["VILLA MARIA DEL TRIUNFO"] * 6,
    })


def test_cause_group_prefixes():
    assert oc.cause_group("I219") == "amenable_acute"
    assert oc.cause_group("E119") == "amenable_chronic"
    assert oc.cause_group("V091") == "external"
    assert oc.cause_group("C509") == "cancer"
    assert oc.cause_group("J189") == "other"
    assert oc.cause_group("SIN REGISTRO") == "unknown"
    assert oc.cause_group("") == "unknown"


def test_parse_place_ubigeo_and_age():
    parsed, counts = oc.parse_deaths(raw_frame())
    assert parsed.loc[0, "ubigeo"] == "140132"
    assert list(parsed["outside"]) == [False, True, True, True, True, True]
    assert list(parsed["place_excluded"]) == [False, False, False, False, True, True]
    assert parsed.loc[0, "age_group"] == "0-14"
    assert parsed.loc[1, "age_group"] == "60-74"
    assert parsed.loc[4, "age_group"] == "0-14"   # 2 months
    assert parsed.loc[0, "sex"] == "M"
    assert counts["excluded_place"] == 2


def test_cause_falls_back_to_next_code():
    raw = raw_frame()
    raw.loc[0, "CAUSA A (CIE-X)"] = None
    raw.loc[0, "CAUSA B (CIE-X)"] = "I219"
    parsed, _ = oc.parse_deaths(raw)
    assert parsed.loc[0, "cause_group"] == "amenable_acute"


def test_completeness_flag():
    census = pd.DataFrame({
        "ubigeo": ["000001", "000002", "000003"],
        "department": ["D", "D", "D"],
        "population_total": [1000, 1000, 1000],
    })
    deaths = pd.DataFrame({"ubigeo": ["000001"] * 100 + ["000002"] * 1 + ["000003"] * 10})
    frame = oc.completeness(deaths, census).set_index("ubigeo")
    assert frame.loc["000001", "deaths_per_1000"] == pytest.approx(100.0)
    assert frame.loc["000002", "deaths_per_1000"] == pytest.approx(1.0)
    assert bool(frame.loc["000002", "low_completeness"]) is True


def test_reniec_code_maps_to_inei_by_name():
    census = pd.DataFrame({
        "ubigeo": ["150132", "070101"],
        "department": ["Lima Metropolitana", "Prov. Const. del Callao"],
        "province": ["Lima", "Prov. Const. del Callao"],
        "district": ["Villa María del Triunfo", "Callao"],
    })
    deaths = pd.DataFrame({
        "ubigeo": ["140132", "240101"],
        "department_raw": ["LIMA", "CALLAO"],
        "province_raw": ["LIMA", "CALLAO"],
        "district_raw": ["VILLA MARIA DEL TRIUNFO", "CALLAO"],
    })
    resolved, by_name, stats = oc.resolve_ubigeo(deaths, census)
    assert resolved.tolist() == ["150132", "070101"]
    assert by_name.tolist() == [True, True]
    assert stats["resolved_by_name"] == 2


def test_model_frame_drops_excluded_places():
    deaths = pd.DataFrame({
        "ubigeo": ["010101", "010101"],
        "place_excluded": [True, False],
        "outside": [True, False],
        "year": [2023, 2023],
    })
    access = pd.DataFrame({"ubigeo": ["010101"], "mean_min": [10.0]})
    census = pd.DataFrame({"ubigeo": ["010101"], "department": ["D"]})
    frame = oc.model_frame(deaths, access, census)
    assert len(frame) == 1
    assert bool(frame.iloc[0]["outside"]) is False


def test_fit_cell_design_matches_the_row_level_fit():
    df = _simulated_deaths(or_per_60=1.5, n=30_000)
    row = oc.fit_logit(df)
    cells = oc.aggregate_cells(df)
    X, _, groups = oc.design_matrix(cells.assign(outside=cells["cases"] / cells["deaths"]))
    cell = oc.fit_cell_design(X, cells["cases"], cells["deaths"], groups)
    assert cell["or_per_60"] == pytest.approx(row["or_per_60"], rel=0.02)
    assert cell["ci_low"] == pytest.approx(row["ci_low"], rel=0.02)
    assert cell["ci_high"] == pytest.approx(row["ci_high"], rel=0.02)


def test_fit_by_cause_keeps_the_sign_with_boolean_outcome():
    df = _simulated_deaths(or_per_60=1.5, n=30_000)
    df["outside"] = df["outside"].astype(bool)
    table = oc.fit_by_cause(df)
    acute = table.loc[table["cause_group"] == "amenable_acute", "or_per_60"].iloc[0]
    assert acute > 1.1


def _simulated_deaths(or_per_60=1.5, n=30_000, seed=7):
    rng = np.random.default_rng(seed)
    districts = [f"{i:06d}" for i in range(1, 51)]
    times = np.linspace(0, 180, len(districts))
    idx = rng.integers(0, len(districts), n)
    outside = death_level_outcome(times[idx], or_per_60=or_per_60,
                                  baseline_odds=0.2, seed=seed)
    return pd.DataFrame({
        "ubigeo": np.array(districts)[idx],
        "mean_min": times[idx],
        "outside": outside,
        "age_group": rng.choice(["0-14", "15-44", "45-59", "60-74", "75+"], n),
        "sex": rng.choice(["M", "F"], n),
        "cause_group": rng.choice(["amenable_acute", "amenable_chronic", "external",
                                   "cancer", "other"], n),
        "department": np.array([f"D{i // 10}" for i in range(len(districts))])[idx],
    })


def test_fit_logit_recovers_the_planted_effect():
    result = oc.fit_logit(_simulated_deaths(or_per_60=1.5))
    assert 1.25 < result["or_per_60"] < 1.8
    assert result["ci_low"] > 1.0


def test_fit_logit_null_covers_one():
    result = oc.fit_logit(_simulated_deaths(or_per_60=1.0, seed=11))
    assert result["ci_low"] <= 1.0 <= result["ci_high"]


def test_fit_gee_recovers_the_sign():
    result = oc.fit_gee(_simulated_deaths(or_per_60=1.5, n=30_000, seed=7))
    assert result["or_per_60"] > 1.15

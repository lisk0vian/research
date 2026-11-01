# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""SINADEF outcome (O1): reading, cleaning, cause groups, completeness, model.

Reads only the columns the plan uses. The cause groups and the excluded place
values come from `analysis_plan.yaml`, so the frozen plan stays the single
source of truth. The estimator is a logistic GLM with department fixed effects
and district-cluster robust standard errors (population-averaged OR); the
random-intercept alternative is not used because the 500-replication simulation
must fit the same estimator in a Colab session.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
import yaml

HERE = Path(__file__).resolve().parent
PLAN = yaml.safe_load((HERE / "analysis_plan.yaml").read_text(encoding="utf-8"))
GROUPS = PLAN["outcome"]["cause_groups"]
FACILITY = set(PLAN["outcome"]["place_mapping"]["facility"])
OUTSIDE = set(PLAN["outcome"]["place_mapping"]["outside"])
EXCLUDED = {v.upper() for v in PLAN["outcome"]["place_mapping"]["excluded"]}

USECOLS = (["COD# UBIGEO DOMICILIO", "AÑO", "TIPO LUGAR", "SEXO", "EDAD",
            "TIEMPO EDAD", "DEPARTAMENTO DOMICILIO", "PROVINCIA DOMICILIO",
            "DISTRITO DOMICILIO"] + [f"CAUSA {k} (CIE-X)" for k in "ABCDEF"])
AGE_BINS = [(0, 14, "0-14"), (15, 44, "15-44"), (45, 59, "45-59"),
            (60, 74, "60-74"), (75, 200, "75+")]


def cause_group(code) -> str:
    """ICD-10 prefix -> plan group; `other` when nothing matches."""
    if not isinstance(code, str) or not code.strip():
        return "unknown"
    c = re.sub(r"[^A-Z0-9]", "", code.upper())
    if not re.match(r"^[A-Z]\d{2}", c):
        return "unknown"
    for name in ("amenable_acute", "amenable_chronic", "external", "cancer"):
        for prefix in GROUPS.get(name, []):
            if prefix and c.startswith(str(prefix)):
                return name
    return "other"


def _age_years(edad, tiempo) -> float:
    value = pd.to_numeric(edad, errors="coerce")
    unit = str(tiempo or "").strip().upper()
    factor = {"AÑOS": 1.0, "ANOS": 1.0, "MESES": 1 / 12, "DIAS": 1 / 365, "DÍAS": 1 / 365,
              "HORAS": 1 / 8760}.get(unit, np.nan)
    return float(value) * factor if pd.notna(value) else np.nan


def age_group(years: float) -> str:
    if not np.isfinite(years):
        return "unknown"
    for low, high, label in AGE_BINS:
        if low <= years <= high:
            return label
    return "unknown"


def parse_deaths(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Raw SINADEF columns -> one compact row per death."""
    out = pd.DataFrame(index=raw.index)
    codes = raw["COD# UBIGEO DOMICILIO"].fillna("").str.strip()
    ubigeo = codes.str.split("-").str[2:5].str.join("")
    out["ubigeo"] = ubigeo.where(ubigeo.str.fullmatch(r"\d{6}"))
    place = raw["TIPO LUGAR"].fillna("").str.strip().str.upper()
    out["place_excluded"] = place.isin(EXCLUDED) | (place == "")
    out["outside"] = ~place.isin(FACILITY)
    out["place_otro"] = place.eq("OTRO")
    out["year"] = pd.to_numeric(raw["AÑO"], errors="coerce").astype("Int64")
    sex = raw["SEXO"].fillna("").str.strip().str.upper()
    out["sex"] = np.select([sex.eq("MASCULINO"), sex.eq("FEMENINO")], ["M", "F"], "unknown")
    years = [_age_years(e, t) for e, t in zip(raw["EDAD"], raw["TIEMPO EDAD"])]
    out["age_group"] = [age_group(y) for y in years]
    cause = raw[[f"CAUSA {k} (CIE-X)" for k in "ABCDEF"]].bfill(axis=1).iloc[:, 0]
    valid = cause.fillna("").str.strip().str.upper().str.match(r"^[A-Z]\d{2}")
    cause = cause.where(valid)
    out["cause_group"] = cause.map(cause_group)
    out["department_raw"] = raw["DEPARTAMENTO DOMICILIO"]
    out["province_raw"] = raw["PROVINCIA DOMICILIO"]
    out["district_raw"] = raw["DISTRITO DOMICILIO"]
    counts = {
        "rows": int(len(out)),
        "missing_ubigeo": int(out["ubigeo"].isna().sum()),
        "excluded_place": int(out["place_excluded"].sum()),
        "outside": int(out["outside"].sum()),
        "unknown_cause": int((out["cause_group"] == "unknown").sum()),
    }
    return out, counts


def read_deaths(path, years=(2022, 2025), chunksize: int = 200_000,
                total_rows: int | None = None, progress=None) -> tuple[pd.DataFrame, dict]:
    """Read only the needed columns in chunks, filter the period, parse.

    `progress(n, total)` is called after each chunk so the notebook can draw a
    live bar over the 504 MB file.
    """
    parts = []
    n = 0
    missing = 0
    reader = pd.read_csv(path, sep=";", encoding="utf-8-sig", usecols=USECOLS,
                         dtype=str, on_bad_lines="skip", chunksize=chunksize)
    for chunk in reader:
        parsed, _ = parse_deaths(chunk)
        missing += int(parsed["ubigeo"].isna().sum())
        parts.append(parsed.loc[parsed["year"].between(*years)])
        n += len(chunk)
        if progress:
            progress(n, total_rows)
    out = pd.concat(parts, ignore_index=True)
    counts = {
        "rows": int(n),
        "missing_ubigeo": int(missing),
        "excluded_place": int(out["place_excluded"].sum()),
        "outside": int(out["outside"].sum()),
        "unknown_cause": int((out["cause_group"] == "unknown").sum()),
        "rows_in_period": int(len(out)),
    }
    return out, counts


def completeness(deaths: pd.DataFrame, census: pd.DataFrame) -> pd.DataFrame:
    """Deaths per 1,000 and the low-completeness flag (plan: 0.5 x dept median)."""
    counts = (deaths.dropna(subset=["ubigeo"]).groupby("ubigeo").size()
              .rename("deaths").reset_index())
    frame = census[["ubigeo", "department", "population_total"]].merge(
        counts, on="ubigeo", how="left").fillna({"deaths": 0})
    frame["deaths_per_1000"] = 1000.0 * frame["deaths"] / frame["population_total"].replace(0, np.nan)
    median = frame.groupby("department")["deaths_per_1000"].transform("median")
    frame["low_completeness"] = frame["deaths_per_1000"] < 0.5 * median
    return frame


def normalize_name(value) -> str:
    text = str(value).strip().upper()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.split())


def _normalize_department(value) -> str:
    text = normalize_name(value)
    if text in {"LIMA METROPOLITANA", "REGION LIMA"}:
        return "LIMA"
    if text.startswith("PROV. CONST. DEL CALLAO") or text == "CALLAO":
        return "CALLAO"
    return text


def _normalize_province(value) -> str:
    text = normalize_name(value)
    if text.startswith("PROV. CONST. DEL CALLAO") or text == "CALLAO":
        return "CALLAO"
    return text


def name_crosswalk(census: pd.DataFrame) -> pd.Series:
    """(department, province, district) names -> INEI UBIGEO, Lima/Callao merged."""
    key = census[["ubigeo", "department", "province", "district"]].copy()
    key["department"] = key["department"].map(_normalize_department)
    key["province"] = key["province"].map(_normalize_province)
    key["district"] = key["district"].map(normalize_name)
    key = key.drop_duplicates(subset=["department", "province", "district"])
    return key.set_index(["department", "province", "district"])["ubigeo"]


def resolve_ubigeo(deaths: pd.DataFrame, census: pd.DataFrame) -> tuple[pd.Series, pd.Series, dict]:
    """RENIEC code -> INEI UBIGEO by name; the parsed code is the fallback.

    The SINADEF `COD# UBIGEO DOMICILIO` uses the RENIEC coding (Lima = 14,
    Callao = 24), which does not match the INEI census codes (Lima = 15,
    Callao = 07; INEI 24 is Tumbes, so the fallback must never feed the main
    model). Returns (resolved, resolved_by_name, stats).
    """
    key = name_crosswalk(census)
    idx = pd.MultiIndex.from_arrays([
        deaths["department_raw"].map(_normalize_department),
        deaths["province_raw"].map(_normalize_province),
        deaths["district_raw"].map(normalize_name),
    ])
    mapped = pd.Series(key.reindex(idx).to_numpy(), index=deaths.index)
    resolved = mapped.fillna(deaths["ubigeo"])
    by_name = mapped.notna()
    stats = {
        "resolved_by_name": int(by_name.sum()),
        "unmatched_names": int((~by_name).sum()),
        "final_missing_ubigeo": int(resolved.isna().sum()),
    }
    return resolved, by_name, stats


def model_frame(deaths: pd.DataFrame, access: pd.DataFrame,
                census: pd.DataFrame) -> pd.DataFrame:
    """Death-level frame with the district exposure and the department.

    Excluded places (empty, SIN REGISTRO, IGNORADO) never enter the model; the
    `resolved_by_name` flag lets the main model drop code-only assignments.
    """
    d = deaths.loc[~deaths["place_excluded"]].dropna(subset=["ubigeo"]).copy()
    d["ubigeo"] = d["ubigeo"].astype(str)
    acc = access[["ubigeo", "mean_min"]].copy()
    acc["ubigeo"] = acc["ubigeo"].astype(str)
    d = d.merge(acc, on="ubigeo", how="inner")
    d = d.merge(census[["ubigeo", "department"]].assign(
        ubigeo=lambda x: x["ubigeo"].astype(str)), on="ubigeo", how="left")
    return d[d["mean_min"].notna()].reset_index(drop=True)


def design_matrix(df: pd.DataFrame, exposure: str = "mean_min",
                  include_cause: bool = True):
    """Prebuilt design for repeated fits (placebo, simulation)."""
    import patsy
    terms = f"{exposure} + C(age_group) + C(sex)"
    if include_cause:
        terms += " + C(cause_group)"
    if "mean_altitude" in df.columns:
        terms += " + mean_altitude"
    X = patsy.dmatrix(terms + " + C(department)", df, return_type="dataframe")
    return X, df["outside"].to_numpy(dtype=float), df["ubigeo"].to_numpy()


def fit_design(X, y, groups, exposure: str = "mean_min") -> dict:
    model = sm.GLM(y, X, family=sm.families.Binomial())
    result = model.fit(cov_type="cluster", cov_kwds={"groups": groups})
    beta = float(result.params[exposure])
    se = float(result.bse[exposure])
    return {
        "n": int(len(y)),
        "beta_per_min": beta,
        "or_per_60": float(np.exp(60 * beta)),
        "ci_low": float(np.exp(60 * (beta - 1.96 * se))),
        "ci_high": float(np.exp(60 * (beta + 1.96 * se))),
        "p_value": float(result.pvalues[exposure]),
    }


def fit_logit(df: pd.DataFrame, cluster: str = "ubigeo",
              exposure: str = "mean_min", include_cause: bool = True) -> dict:
    """Logistic GLM: department fixed effects, district-cluster robust SEs."""
    X, y, groups = design_matrix(df, exposure=exposure, include_cause=include_cause)
    return fit_design(X, y, groups, exposure=exposure)


def fit_gee(df: pd.DataFrame, sample: int | None = None, seed: int = 42) -> dict:
    """GEE exchangeable by district (sensitivity for the main estimator)."""
    d = df.sample(sample, random_state=seed) if sample and len(df) > sample else df
    X, y, groups = design_matrix(d)
    model = sm.GEE(y, X, groups=groups, family=sm.families.Binomial(),
                   cov_struct=sm.cov_struct.Exchangeable())
    result = model.fit()
    beta = float(result.params["mean_min"])
    se = float(result.bse["mean_min"])
    return {
        "n": int(len(d)),
        "beta_per_min": beta,
        "or_per_60": float(np.exp(60 * beta)),
        "ci_low": float(np.exp(60 * (beta - 1.96 * se))),
        "ci_high": float(np.exp(60 * (beta + 1.96 * se))),
        "p_value": float(result.pvalues["mean_min"]),
    }


def collinearity_note(df: pd.DataFrame) -> dict:
    """VIF for altitude and the Amazon flag once the DEM/basin exist."""
    cols = [c for c in ("mean_altitude", "amazon") if c in df.columns]
    if not cols:
        return {"status": "not_available",
                "reason": "DEM and HydroBASINS flag are built in the region stage"}
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    data = sm.add_constant(df[cols].astype(float).dropna())
    vif = {c: float(variance_inflation_factor(data.values, i + 1))
           for i, c in enumerate(cols)}
    return {"status": "ok", "vif": vif, "flag_above_10": any(v > 10 for v in vif.values())}


def fit_interaction(df: pd.DataFrame, cluster: str = "ubigeo") -> tuple[pd.DataFrame, dict]:
    """OR per +60 min by cause group, with the time x group interaction test."""
    df = df.assign(outside=df["outside"].astype(float))  # bool would invert the link
    terms = ("outside ~ mean_min * C(cause_group) + C(age_group) + C(sex) "
             "+ C(department)")
    if "mean_altitude" in df.columns:
        terms += " + mean_altitude"  # plan v12: same RQ3 covariate set as the main model
    model = smf.glm(terms, data=df, family=sm.families.Binomial())
    result = model.fit(cov_type="cluster", cov_kwds={"groups": df[cluster]})
    groups = sorted(df["cause_group"].dropna().unique())
    rows = []
    for group in groups:
        name = f"mean_min:C(cause_group)[T.{group}]"
        beta = float(result.params["mean_min"] + result.params.get(name, 0.0))
        # covariance of the sum, not the sum of variances
        cov = result.cov_params()
        var = (cov.loc["mean_min", "mean_min"]
               + (cov.loc[name, name] if name in cov.index else 0.0)
               + 2 * (cov.loc["mean_min", name] if name in cov.index else 0.0))
        se = float(np.sqrt(max(var, 0.0)))
        rows.append({"cause_group": group,
                     "or_per_60": float(np.exp(60 * beta)),
                     "ci_low": float(np.exp(60 * (beta - 1.96 * se))),
                     "ci_high": float(np.exp(60 * (beta + 1.96 * se)))})
    interactions = {k: float(v) for k, v in result.pvalues.items()
                    if k.startswith("mean_min:C(cause_group)")}
    return pd.DataFrame(rows), {"interaction_p": interactions, "n": int(len(df))}


def fit_by_cause(df: pd.DataFrame) -> pd.DataFrame:
    """OR per +60 min estimated separately inside each cause group."""
    rows = []
    for group in sorted(df["cause_group"].dropna().unique()):
        sub = df[df["cause_group"] == group]
        if len(sub) < 100 or sub["outside"].nunique() < 2:
            continue
        result = fit_logit(sub, include_cause=False)
        rows.append({"cause_group": group, **result})
    return pd.DataFrame(rows)


def aggregate_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse deaths to district x age x sex x cause cells (same fit)."""
    keys = ["ubigeo", "department", "age_group", "sex", "cause_group", "mean_min"]
    for extra in ("mean_altitude", "amazon"):
        if extra in df.columns:
            keys.append(extra)
    return (df.groupby(keys, dropna=False)
            .agg(deaths=("outside", "size"), cases=("outside", "sum"))
            .reset_index())


def fit_cell_design(X, cases, deaths, groups, exposure: str = "mean_min") -> dict:
    """Binomial GLM on aggregated cells; coefficients match the row-level fit."""
    deaths = np.asarray(deaths, dtype=float)
    y = np.asarray(cases, dtype=float) / deaths
    model = sm.GLM(y, X, family=sm.families.Binomial(), freq_weights=deaths)
    result = model.fit(cov_type="cluster", cov_kwds={"groups": groups})
    beta = float(result.params[exposure])
    se = float(result.bse[exposure])
    return {
        "n_cells": int(len(y)),
        "deaths": int(deaths.sum()),
        "beta_per_min": beta,
        "or_per_60": float(np.exp(60 * beta)),
        "ci_low": float(np.exp(60 * (beta - 1.96 * se))),
        "ci_high": float(np.exp(60 * (beta + 1.96 * se))),
        "p_value": float(result.pvalues[exposure]),
    }


def district_sd(df: pd.DataFrame, min_deaths: int = 30) -> float:
    """Between-district SD of the logit outcome, net of binomial noise.

    Districts with p near 0 or 1 are excluded: their sampling variance explodes
    and would dominate the average, forcing the SD to 0.
    """
    g = df.groupby("ubigeo").agg(n=("outside", "size"), p=("outside", "mean"))
    g = g[(g["n"] >= min_deaths) & (g["p"] > 0.05) & (g["p"] < 0.95)]
    if len(g) < 10:
        return 0.0
    p = g["p"].clip(1e-6, 1 - 1e-6)
    logit = np.log(p / (1 - p))
    var_total = float(logit.var(ddof=1))
    var_binom = float((1.0 / (g["n"] * p * (1 - p))).mean())
    return float(np.sqrt(max(var_total - var_binom, 0.0)))


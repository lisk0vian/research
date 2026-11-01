# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 08: RQ3 models, placebo, controls and cell-level simulation.

Main (plan v9): H3a is evaluated on **amenable causes** (acute + chronic) and
on deaths whose district was resolved by name. Other causes are exploratory.
Estimator: logistic GLM, department fixed effects, district-cluster robust SEs
(population-averaged OR).

H3b: OR per +60 min estimated separately inside each cause group, plus the
time x group interaction. Negative control: cancer. Completeness and excluded
`OTRO` are sensitivities; 2020-2021 is the period sensitivity. The simulation
uses aggregated cells (district x age x sex x cause), the real baseline odds
and a district random intercept, at full size.
"""

from __future__ import annotations

import gc
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _outcome import (aggregate_cells, collinearity_note, design_matrix,  # noqa: E402
                      district_sd, fit_by_cause, fit_design, fit_gee,
                      fit_interaction, fit_logit, model_frame)
from _paths import OUTPUTS, RUTA_CENSO  # noqa: E402
from _simulate import run_cell_validation  # noqa: E402

RESULTS_VERSION = 9  # v9: unknown-cause table by place and travel-time band; Monte Carlo SEs
IN = OUTPUTS / "07_outcome_sinadef"
IN3 = OUTPUTS / "03_access_travel_time"
OUT = OUTPUTS / "08_validation_models"
PLACEBO_REPS = 200
SIM_REPS = 500
SIM_PLANTED_REPS = 200
SIM_SAMPLE = 50_000


def prog(level: str, n: int, total, desc: str) -> None:
    print("#PROG " + json.dumps({"level": level, "n": n, "total": total,
                                 "desc": desc}), flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()

    frame = pd.read_parquet(IN / "model_frame.parquet")
    frame["ubigeo"] = frame["ubigeo"].astype(str)
    regions_path = OUTPUTS / "02_regions" / "districts_regions.csv"
    regions_missing = 0
    if regions_path.exists():
        regions = pd.read_csv(regions_path, dtype={"ubigeo": str})
        frame = frame.merge(regions[["ubigeo", "mean_altitude", "amazon"]],
                            on="ubigeo", how="left")
        regions_missing = int(frame["mean_altitude"].isna().sum())
        frame["mean_altitude"] = frame["mean_altitude"].fillna(
            frame["mean_altitude"].median())
        frame["amazon"] = frame["amazon"].fillna(False).astype(bool)
    altitude_included = "mean_altitude" in frame.columns
    named = frame[frame["resolved_by_name"]].copy()
    amenable = named[named["cause_group"].isin(["amenable_acute", "amenable_chronic"])].copy()

    # --- unknown cause by place of death and travel-time band (descriptive) ------
    # If causes are recorded worse outside facilities, restricting H3a to amenable
    # causes selects on the outcome; this table shows how large that risk is.
    band = pd.cut(named["mean_min"], [-np.inf, 30, 60, 120, np.inf],
                  labels=["<=30", "30-60", "60-120", ">120"]).astype(str)
    unknown = (named.assign(band=band, unknown=named["cause_group"].eq("unknown"))
               .groupby(["band", "outside"])["unknown"].agg(["mean", "size"]).reset_index()
               .rename(columns={"mean": "share_unknown", "size": "deaths"}))
    unknown.to_csv(OUT / "unknown_cause_by_place_time.csv", index=False)

    prog("models", 0, 6, "H3a causas amenables")
    main_model = fit_logit(amenable)
    (OUT / "main.json").write_text(json.dumps(main_model, indent=2), encoding="utf-8")
    prog("models", 1, 6, "exploratorio todas las causas")
    exploratory = fit_logit(named)
    (OUT / "exploratory.json").write_text(json.dumps(exploratory, indent=2), encoding="utf-8")

    prog("models", 2, 6, "H3b por causa")
    by_cause = fit_by_cause(named)
    by_cause.to_csv(OUT / "h3b_cause_groups.csv", index=False)
    _, h3b_meta = fit_interaction(named)
    prog("models", 3, 6, "sensibilidad GEE")
    gee = fit_gee(amenable, sample=SIM_SAMPLE, seed=42)
    (OUT / "gee.json").write_text(json.dumps(gee, indent=2), encoding="utf-8")

    cancer = named[named["cause_group"] == "cancer"]
    controls = {"negative_control_cancer": fit_logit(cancer, include_cause=False)}
    comp = pd.read_csv(IN / "completeness.csv", dtype={"ubigeo": str})
    low = set(comp.loc[comp["low_completeness"], "ubigeo"])
    controls["completeness_sensitivity"] = fit_logit(amenable[~amenable["ubigeo"].isin(low)])
    controls["exclude_otro"] = fit_logit(amenable[~amenable["place_otro"]])
    controls["collinearity"] = collinearity_note(frame)

    # --- completeness bias flag: |r| of deaths/1000 vs travel time (plan) -------
    access_districts = pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str})
    rcomp = comp.merge(access_districts[["ubigeo", "mean_min"]], on="ubigeo",
                       how="inner").dropna()
    r_bias = float(rcomp["deaths_per_1000"].corr(rcomp["mean_min"]))
    controls["completeness_bias"] = {"r_deaths_per_1000_with_mean_min": r_bias,
                                     "flag_abs_r_gt_030": abs(r_bias) > 0.30}

    # --- code-only assignments: declared H3a sensitivity (plan v12) --------------
    code_only = frame[~frame["resolved_by_name"] & frame["cause_group"].isin(
        ["amenable_acute", "amenable_chronic"])]
    controls["code_only_assignment"] = (fit_logit(code_only)
                                        if len(code_only) > 1000 else {"n": len(code_only)})


    # --- period sensitivity: 2020-2021 -----------------------------------------
    deaths_all = pd.read_parquet(IN / "deaths_all.parquet")
    access = pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str})
    census = pd.read_csv(RUTA_CENSO, dtype={"ubigeo": str})
    early_deaths = deaths_all[deaths_all["year"] <= 2021].copy()
    early = model_frame(early_deaths, access, census)
    early_amenable = early[early["cause_group"].isin(["amenable_acute", "amenable_chronic"])]
    controls["period_2020_2021"] = (fit_logit(early_amenable)
                                    if len(early_amenable) > 1000 else {"n": len(early_amenable)})
    (OUT / "controls.json").write_text(json.dumps(controls, indent=2), encoding="utf-8")
    prog("models", 4, 6, "controles y sensibilidades")

    # --- placebo: permute district times within department ---------------------
    sample = amenable.sample(min(SIM_SAMPLE, len(amenable)), random_state=42)
    Xp, yp, gp = design_matrix(sample)
    districts = amenable[["ubigeo", "department", "mean_min"]].drop_duplicates("ubigeo")
    observed = abs(main_model["or_per_60"] - 1.0)
    rng = np.random.default_rng(42)
    placebo_rows = []
    base_exposure = Xp["mean_min"].to_numpy().copy()
    for rep in range(PLACEBO_REPS):
        perm = districts.copy()
        perm["mean_min_perm"] = perm.groupby("department")["mean_min"].transform(
            lambda s: rng.permutation(s.to_numpy()))
        values = sample[["ubigeo"]].merge(perm[["ubigeo", "mean_min_perm"]],
                                          on="ubigeo", how="left")["mean_min_perm"]
        Xp["mean_min"] = values.to_numpy()
        placebo_rows.append({"rep": rep, "or_per_60": fit_design(Xp, yp, gp)["or_per_60"]})
        if rep % 25 == 0:
            gc.collect()
            prog("placebo", rep, PLACEBO_REPS, "permutación intra-departamento")
    Xp["mean_min"] = base_exposure
    placebo = pd.DataFrame(placebo_rows)
    placebo.to_csv(OUT / "placebo.csv", index=False)
    placebo_p = float((placebo["or_per_60"].sub(1).abs() >= observed).mean())
    (OUT / "placebo_summary.json").write_text(json.dumps(
        {"p": placebo_p, "reps": PLACEBO_REPS, "sample": int(len(sample))}, indent=2),
        encoding="utf-8")
    prog("placebo", PLACEBO_REPS, PLACEBO_REPS, "permutación intra-departamento")
    del frame, Xp, yp, gp
    gc.collect()

    # --- known-truth simulation on cells, full size ----------------------------
    cells = aggregate_cells(amenable)
    sd = district_sd(amenable)
    Xs, _, gs = design_matrix(cells.assign(outside=cells["cases"] / cells["deaths"]))
    sim = run_cell_validation(
        cells, Xs, gs, reps={1.0: SIM_REPS, 1.1: SIM_PLANTED_REPS,
                             1.2: SIM_PLANTED_REPS, 1.5: SIM_PLANTED_REPS},
        district_sd=sd, baseline_odds=None, seed=42,
        progress=lambda n, t: prog("simulation", n, t, "réplicas de verdad conocida"))
    sim.to_csv(OUT / "simulation.csv", index=False)
    null = sim[sim["or_planted"] == 1.0]
    false_positive = float(((null["ci_low"] > 1) | (null["ci_high"] < 1)).mean())
    planted_rows = []
    coverage_passes = {}
    for value, group in sim[sim["or_planted"] > 1.0].groupby("or_planted"):
        coverage = float(((group["ci_low"] <= value) & (group["ci_high"] >= value)).mean())
        coverage_passes[str(float(value))] = bool(0.92 <= coverage <= 0.97)
        planted_rows.append({
            "or_planted": float(value),
            "reps": int(len(group)),
            "mean_or": float(group["or_per_60"].mean()),
            "bias": float(group["or_per_60"].mean() / value - 1.0),
            "coverage": coverage,
            "coverage_mcse": float(np.sqrt(coverage * (1 - coverage) / len(group))),
            "power": float((group["ci_low"] > 1).mean()),
        })
    planted = pd.DataFrame(planted_rows)
    planted.to_csv(OUT / "simulation_summary.csv", index=False)

    summary = {
        "estimator": "logistic GLM, department fixed effects, district-cluster robust SEs",
        "estimand": "population_averaged_or",
        "rq3_covariates": ["age_group", "sex", "cause_group", "mean_altitude",
                           "department (fixed effects)"],
        "altitude_included": altitude_included,
        "h3a_population": "amenable causes (acute + chronic), name-resolved districts",
        "regions_missing": regions_missing,
        "main": main_model,
        "exploratory_all_causes": exploratory,
        "h3b": {"by_cause": by_cause.to_dict(orient="records"), **h3b_meta},
        "sensitivity_gee": gee,
        "sensitivity_criterion": "same sign and overlapping 95 % CI",
        **controls,
        "placebo_p": placebo_p,
        "placebo_reps": PLACEBO_REPS,
        "unknown_cause_by_place_time": unknown.to_dict(orient="records"),
        "simulation": {
            "design": "cells district x age x sex x cause; district random intercept",
            "district_sd": sd,
            "cells": int(len(cells)),
            "deaths": int(cells["deaths"].sum()),
            "reps_null": SIM_REPS,
            "reps_planted": SIM_PLANTED_REPS,
            "false_positive_rate": false_positive,
            # Monte Carlo SE of a proportion over the null replications (Morris et al. 2019)
            "false_positive_mcse": float(np.sqrt(false_positive * (1 - false_positive) / len(null))),
            "false_positive_max": 0.07,
            "fp_gate_passes": bool(false_positive <= 0.07),
            "coverage_passes": coverage_passes,
            "planted": planted.to_dict(orient="records"),
            "bias_max": 0.10,
            "coverage_target": [0.92, 0.97],
        },
        "gee_criterion_passes": bool(
            (main_model["or_per_60"] - 1) * (gee["or_per_60"] - 1) > 0
            and min(main_model["ci_high"], gee["ci_high"])
            >= max(main_model["ci_low"], gee["ci_low"])),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    prog("models", 5, 6, "listo")
    print(json.dumps({"main_or": main_model["or_per_60"],
                      "main_ci": [main_model["ci_low"], main_model["ci_high"]],
                      "placebo_p": placebo_p, "false_positive": false_positive}, indent=2))
    print("Stage 08 done.")
    return 0


def synthetic() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    print("smoke: synthetic models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

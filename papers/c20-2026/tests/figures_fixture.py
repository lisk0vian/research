# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Synthetic outputs/ and data/processed/ for stage 11 (paper figures).

Every file stage 11 reads, with the real schema and made-up numbers. Tables
that two stages compute independently (T2 and T16, T9 and T16, T15 and the
PIT of M*) are built consistently, as the pipeline does, so the QA's
cross-checks pass on a correct fixture and fail on a broken one.

Usage outside pytest, for a local look at the figures:
    python tests/figures_fixture.py <root>
    OUTPUT_DIR=<root>/outputs DATA_DIR=<root>/data python experiments/11_paper_figures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

PAPER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAPER / "experiments"))

LEVELS = [round(0.05 * i, 2) for i in range(1, 20)]
COLS = [f"q{int(round(t * 100)):02d}" for t in LEVELS]
Z = np.array([NormalDist().inv_cdf(t) for t in LEVELS])
HORIZONS = ["W1", "W2", "W3_4"]
STATIONS = ["150701", "040114", "151007", "040514", "120607"]
ELEV = [2421, 3269, 3840, 4475, 3300]
SKILL = {  # CRPSS_clim by horizon, roughly the shape of the real result
    "Damp": (0.13, 0.11, 0.15), "Chronos": (0.13, 0.09, 0.10), "Chronos@abs": (0.27, 0.26, 0.32),
    "ChronosBolt": (0.21, 0.22, 0.18), "GBM_L": (0.22, 0.16, 0.17), "GBM_LG": (0.24, 0.24, 0.29),
    "LSTM_LG": (0.27, 0.31, 0.38), "Ridge_L": (0.24, 0.22, 0.25), "Ridge_LG": (0.30, 0.32, 0.39),
    "CFS_BC": (0.41, 0.30, 0.22), "Ensemble": (0.29, 0.30, 0.35),
}


COV = {"Chronos": 0.27, "Chronos@abs": 0.81, "ChronosBolt": 0.93, "Ensemble": 0.69}
WIDTH = {"Chronos": 0.55, "Chronos@abs": 2.2, "ChronosBolt": 3.3, "Ensemble": 1.5}


def _ci(v, w=0.09):
    return v - w, v + w


def write(root: Path, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    out, data = root / "outputs", root / "data"
    tables, models, processed = out / "tables", out / "models", data / "processed"
    for p in (tables, models / "hybrid", processed):
        p.mkdir(parents=True, exist_ok=True)

    # T2: every model, CRPSS vs Clim and vs Damp.
    t2 = []
    for m, vals in SKILL.items():
        for h, v in zip(HORIZONS, vals):
            pairs = (("CRPSS_clim", v),) if m == "Damp" else (("CRPSS_clim", v), ("CRPSS_damp", v - 0.11))
            for metric, val in pairs:  # as 09: Damp has no CRPSS vs itself
                lo, hi = _ci(val)
                t2.append({"model": m, "horizon": h, "metric": metric, "value": val,
                           "ci_low": lo, "ci_high": hi, "n_dates": 100})
    pd.DataFrame(t2).to_csv(tables / "T2_blind_skill.csv", index=False)

    # Blind eval rows and forecasts: obs ~ N(0, 1); each system centred near it.
    dates = pd.date_range("2022-07-04", "2024-06-24", freq="W-MON")
    rows = []
    for s in STATIONS:
        for h, (a, b) in zip(HORIZONS, ((1, 7), (8, 14), (15, 28))):
            for d in dates:
                rows.append({"experiment": "temporal", "target": "TT_mean", "station": s,
                             "fold": "B1" if d < pd.Timestamp("2023-07-01") else "B2",
                             "role": "blind", "issue_date": d, "horizon": h, "lag_start": a,
                             "lag_end": b, "quarter": ((d.month % 12) // 3),
                             "nino34_anom": 0.0, "romi_amp": 0.5,
                             "obs": float(rng.normal()), "clim": 10.0, "t1": -0.4, "t2": 0.4})
    index = pd.DataFrame(rows)
    index.to_csv(models / "eval_index_temporal.csv", index=False)
    keys = ["experiment", "target", "station", "fold", "role", "issue_date", "horizon"]

    def preds(model, sd, noise):
        mu = index["obs"].to_numpy() + rng.normal(0, noise, len(index))
        p = index[keys].assign(model=model, mean=mu)
        for c, z in zip(COLS, Z):
            p[c] = mu + sd * z
        return p

    ens = preds("Ensemble", 0.5, 0.8)
    ens.to_csv(models / "preds_temporal_Ensemble.csv", index=False)
    preds("CFS_BC", 0.7, 0.6).to_csv(models / "preds_temporal_CFS_BC.csv", index=False)
    preds(f"Ridge_LG@CFS", 0.75, 0.6).to_csv(models / "hybrid" / "preds_temporal_Ridge_LG@CFS.csv",
                                             index=False)
    m2 = preds("Mstar2", 0.85, 0.7).drop(columns=["experiment", "target"])
    m2.insert(5, "obs", index["obs"])
    m2.to_csv(models / "mstar2_preds.csv", index=False)
    (models / "primary_model.json").write_text(json.dumps({"primary_model": "Ensemble"}))

    # T15 from the same PIT the figure recomputes (as 08 + 10 do).
    from _scores import cdf_from_quantiles
    t15 = []
    for h in HORIZONS:
        sel = (ens["horizon"] == h).to_numpy()
        pit = cdf_from_quantiles(index["obs"].to_numpy()[sel], ens[COLS].to_numpy()[sel], LEVELS)
        counts, _ = np.histogram(pit, bins=10, range=(0, 1))
        for b in range(10):
            t15.append({"role": "blind", "horizon": h, "series": "pit_hist", "bin_low": b / 10,
                        "bin_high": (b + 1) / 10, "value": counts[b] / counts.sum(),
                        "reference": 0.1, "n": int(sel.sum())})
    pd.DataFrame(t15).to_csv(tables / "T15_pit_reliability.csv", index=False)

    cov_m = {"W1": 0.75, "W2": 0.69, "W3_4": 0.63}
    t9 = []
    for h in HORIZONS:
        t9.append({"variant": "Ensemble", "role": "blind", "horizon": h, "n": 500, "cov50": 0.36,
                   "cov90": cov_m[h], "width90": 1.5, "crps": 0.45, "crpss_clim": 0.3, "k": np.nan})
        t9.append({"variant": "Ensemble+k", "role": "blind", "horizon": h, "n": 500, "cov50": 0.5,
                   "cov90": 0.89, "width90": 2.4, "crps": 0.43, "crpss_clim": 0.32, "k": 1.5})
    pd.DataFrame(t9).to_csv(tables / "T9_calibration.csv", index=False)

    t14 = [{"horizon": h, "n_dates": 100, "crps_mstar": 0.45, "crps_mstar2": 0.42,
            "dCRPS_mstar_minus_mstar2": 0.1, "ci_low": 0.04, "ci_high": 0.16, "p_value": 0.001,
            "CRPSS_clim": v, "CRPSS_clim_low": v - 0.09, "CRPSS_clim_high": v + 0.09,
            "CRPSS_damp": v - 0.1, "CRPSS_damp_low": v - 0.18, "CRPSS_damp_high": v - 0.02,
            "p_holm": 0.002, "cov90_mstar2": c, "cov90_in_range": True}
           for h, v, c in zip(HORIZONS, (0.32, 0.35, 0.43), (0.90, 0.89, 0.87))]
    pd.DataFrame(t14).to_csv(tables / "T14_mstar2_blind.csv", index=False)

    t16 = []
    for system, vals, cov in (("Ridge_LG@CFS", (0.42, 0.38, 0.41), (0.84, 0.84, 0.81)),
                              ("CFS_BC", SKILL["CFS_BC"], (0.85, 0.80, 0.73)),
                              ("Ensemble", SKILL["Ensemble"], tuple(cov_m.values())),
                              ("Ridge_LG", SKILL["Ridge_LG"], (0.81, 0.79, 0.72)),
                              ("GBM_LG", SKILL["GBM_LG"], (0.77, 0.66, 0.57))):
        for h, v, c in zip(HORIZONS, vals, cov):
            t16.append({"system": system, "horizon": h, "n_dates": 100, "n_rows": 500,
                        "crps": 0.4, "cov90": c, "CRPSS_clim": v, "CRPSS_clim_low": v - 0.09,
                        "CRPSS_clim_high": v + 0.09, "CRPSS_damp": v - 0.11,
                        "CRPSS_damp_low": v - 0.19, "CRPSS_damp_high": v - 0.03})
    pd.DataFrame(t16).to_csv(tables / "T16_hybrid_cfs.csv", index=False)

    t16b = []
    for system, test, ref, base in (("Ridge_LG@CFS", "a_vs_CFS_BC", "CFS_BC", 0.03),
                                    ("Ridge_LG@CFS", "b_vs_Mstar", "Ensemble", 0.3),
                                    ("Ridge_LG@CFS", "c_vs_control", "Ridge_LG@cfsrows", 0.25),
                                    ("GBM_LG@CFS", "a_vs_CFS_BC", "CFS_BC", -0.2),
                                    ("Blend_CFS_Mstar", "a_vs_CFS_BC", "CFS_BC", 0.1),
                                    ("Blend_CFS_Mstar", "b_vs_Mstar", "Ensemble", 0.1)):
        for k, h in enumerate(HORIZONS):
            v = base + 0.1 * k
            t16b.append({"system": system, "reference": ref, "test": test, "horizon": h,
                         "n_dates": 100, "dCRPS_ref_minus_system": v, "ci_low": v - 0.15,
                         "ci_high": v + 0.15, "p_value": 0.01 if v > 0.15 else 0.3,
                         "p_holm": 0.03 if v > 0.15 else 0.6})
    pd.DataFrame(t16b).to_csv(tables / "T16b_hybrid_tests.csv", index=False)

    t10 = []
    for role in ("blind", "dev"):
        for scope, cov, sd, rmse in (("days 1-7", 0.21, 0.20, 1.14), ("days 8-14", 0.21, 0.23, 1.29),
                                     ("days 15-28", 0.22, 0.24, 1.32)):
            t10.append({"role": role, "check": "daily", "scope": scope, "value": cov,
                        "reference": 0.9, "metric": "cov90 of daily anomaly (nominal 0.90)"})
            t10.append({"role": role, "check": "daily", "scope": scope, "value": sd,
                        "reference": rmse, "metric": "path SD vs RMSE of the median (degC)"})
    pd.DataFrame(t10).to_csv(tables / "T10_chronos_diagnostic.csv", index=False)

    t7 = []
    for h, base in zip(HORIZONS, (0.29, 0.30, 0.35)):
        for split, conds in (("enso", ["La Niña", "neutral", "El Niño"]),
                             ("season", ["DJF", "MAM", "JJA", "SON"]),
                             ("mjo", ["MJO inactive", "MJO active"])):
            for i, c in enumerate(conds):
                t7.append({"model": "Ensemble", "horizon": h, "split": split, "condition": c,
                           "n": 120 + 10 * i, "CRPSS_clim": base + 0.05 * (i - 1)})
    pd.DataFrame(t7).to_csv(tables / "T7_conditional_skill.csv", index=False)

    t5 = []
    for m in ("Ensemble", "LSTM_LG", "GBM_LG", "GBM_LG@elev"):
        for s, e in zip(STATIONS, ELEV):
            for h in HORIZONS:
                v = 0.01 * (e - 3300) / 1000
                t5.append({"model": m, "base_model": m.split("@")[0],
                           "static_variant": "elev" if "@" in m else "all", "station": s,
                           "elev_m": e, "horizon": h, "crpss_clim_temporal": 0.3,
                           "crpss_clim_loso": 0.28, "dCRPS_loso_minus_temporal": v,
                           "ci_low": v - 0.02, "ci_high": v + 0.02, "n_dates": 100})
    pd.DataFrame(t5).to_csv(tables / "T5_loso_gap.csv", index=False)

    t12 = []
    for m, vals in (("GBM_L", (0.22, 0.16, 0.18)), ("GBM_LG", (0.24, 0.24, 0.29)),
                    ("LSTM_LG", (0.26, 0.30, 0.36))):
        for h, v in zip(HORIZONS, vals):
            t12.append({"model": m, "role": "blind", "horizon": h, "n_seeds": 5,
                        "CRPSS_clim_mean": v, "CRPSS_clim_sd": 0.01, "CRPSS_clim_min": v - 0.02,
                        "CRPSS_clim_max": v + 0.02, "CRPSS_damp_mean": v - 0.1,
                        "CRPSS_damp_sd": 0.01, "CRPSS_damp_min": v - 0.12,
                        "CRPSS_damp_max": v - 0.08})
    pd.DataFrame(t12).to_csv(tables / "T12_seed_variability.csv", index=False)

    ml = []
    for m, vals in SKILL.items():
        for h, v in zip(HORIZONS, vals):
            for role, val in (("dev", v * 0.45), ("blind", v)):
                ml.append({"experiment": "temporal", "target": "TT_mean", "horizon": h,
                           "role": role, "scope": "pooled", "model": m, "CRPSS_clim": val,
                           "cov90": COV.get(m, 0.8), "width90": WIDTH.get(m, 1.8)})
    pd.DataFrame(ml).to_csv(tables / "metrics_long.csv", index=False)

    # Processed inputs: one year of C2 per station (fold B2), daily Niño 3.4.
    days = pd.date_range("2023-07-01", "2024-06-30", freq="D")
    clim = []
    for s, e in zip(STATIONS, ELEV):
        base = 22 - 0.0055 * e
        c2 = base + 1.5 * np.cos(2 * np.pi * (days.dayofyear - 30) / 365.25)
        clim.append(pd.DataFrame({"date": days, "valid": True, "C2": c2, "C3": c2, "C1": c2,
                                  "A_C2": 0.0, "A_C3": 0.0, "A_C1": 0.0,
                                  "doy_frac": days.dayofyear, "quarter": 0, "station": s}))
    pd.concat(clim).to_csv(processed / "daily_clim.csv", index=False)
    all_days = pd.date_range("2015-01-01", "2024-06-30", freq="D")
    t = np.arange(len(all_days))
    nino = 1.3 * np.sin(2 * np.pi * t / (365.25 * 3.2) + 0.5)
    pd.DataFrame({"date": all_days, "nino34_anom": nino}).to_csv(
        processed / "largescale_daily.csv", index=False)
    return root


if __name__ == "__main__":
    print(write(Path(sys.argv[1])))

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""CFS_BC: the calibrated NOAA CFSv2 reference for the blind folds (amendment A1).

The raw CFSv2 2 m temperature of a 1 degree cell is not a forecast of a station
2421-4475 m high: it carries a large, station-specific bias and a seasonal cycle
that is not the station's. Scoring it raw would compare the models with a straw
man; this is the standard remedy (Monhart et al. 2018; Mouatadid et al. 2023),
kept deliberately simple and fitted on the fold's training rows only.

Per fold (B1, B2), station and horizon, on training Mondays:
  1. fit the CFS window-mean climatology: a harmonic in the day-of-year of the
     target midpoint (K = `dynamical.clim_harmonics_K`), on the CFS forecasts
     themselves, which removes the mean bias and the model's own seasonal cycle;
  2. regress the observed anomaly (the 04 target) on the CFS anomaly;
  3. Gaussian predictive distribution with the training-residual SD by quarter,
     the same construction as Damp, so CRPS differences come from the mean.

Evaluation rows are the fold's weekly Monday issuances. The result is written as
`preds_temporal_CFS_BC.csv` in the shared prediction contract, so 08-10 score it
like any other model. It is never a candidate for M* and never an ensemble member.

Also writes `T8_cfs_calibration.csv` (slope, residual SD and the correlation of the
CFS anomaly with the observation, in training and in evaluation, per cell), so a
reader can see whether CFSv2 carries any signal before looking at a skill score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from _common import (
    PROCESSED,
    TABLES,
    atomic_write_csv,
    ensure_dirs,
    load_config,
    paths_report,
    primary_target,
    read_station_keyed,
    rel_path,
    write_manifest,
)
from _harmonic import doy_fractional, eval_harmonic, fit_harmonic
from _panel import fast_mode, load_panel, pred_frame, quantile_levels, target_rows, write_preds
from _scores import gaussian_quantiles

WINDOWS_CSV = PROCESSED / "cfs_windows.csv"
TARGET = primary_target()
MODEL = "CFS_BC"
MIN_CELL = 20  # rows below which a quarter falls back to the pooled residual SD


def calibrate(tr: pd.DataFrame, ev: pd.DataFrame, k: int, period: float, min_train: int
              ) -> tuple[np.ndarray, np.ndarray, dict] | None:
    """Fit on `tr`, predict `ev`: returns (mu, sd, diagnostics) or None if too thin.

    `tr` and `ev` need target_mid, quarter, F_mean; `tr` also A_C2_target.
    """
    tr = tr[tr["F_mean"].notna()]
    if len(tr) < min_train:
        return None
    doy_tr = doy_fractional(tr["target_mid"])
    coef = fit_harmonic(doy_tr, tr["F_mean"].to_numpy(float), k, period)
    f_tr = tr["F_mean"].to_numpy(float) - eval_harmonic(coef, doy_tr, period)
    f_ev = ev["F_mean"].to_numpy(float) - eval_harmonic(coef, doy_fractional(ev["target_mid"]), period)
    y = tr["A_C2_target"].to_numpy(float)
    X = np.column_stack([np.ones_like(f_tr), f_tr])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    pooled = float(np.std(resid, ddof=2))
    qtr_tr = tr["quarter"].to_numpy()
    sd = np.empty(len(ev))
    for i, q in enumerate(ev["quarter"].to_numpy()):
        r = resid[qtr_tr == q]
        sd[i] = float(np.std(r, ddof=2)) if len(r) >= MIN_CELL else pooled
    mu = beta[0] + beta[1] * f_ev
    corr = lambda a, b: float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and np.std(a) > 0 and np.std(b) > 0 else np.nan
    diag = {"n_train": int(len(tr)), "intercept": float(beta[0]), "slope": float(beta[1]),
            "resid_sd": pooled, "corr_train": corr(f_tr, y)}
    if "A_C2_target" in ev.columns:
        diag["corr_eval"] = corr(f_ev, ev["A_C2_target"].to_numpy(float))
    return mu, sd, diag


def main() -> None:
    cfg = load_config()
    dyn = cfg.get("dynamical") or {}
    if not dyn.get("enabled", False):
        print("dynamical.enabled is false; nothing to do")
        return
    ensure_dirs()
    print(paths_report())
    if not WINDOWS_CSV.is_file():
        raise SystemExit(f"ERROR: {WINDOWS_CSV} not found — run 06b_dynamical.py first")

    levels = quantile_levels(cfg)
    k = int(dyn.get("clim_harmonics_K", 2))
    # Declared in config (dynamical.min_train), not hardcoded: the training
    # cutoff of the CFS calibration is an operating parameter a methods section
    # has to source from somewhere.
    min_train = int(dyn.get("min_train", 40))
    if fast_mode():
        fast = dyn.get("fast") or {}
        k = int(fast.get("clim_harmonics_K", 1))
        min_train = int(fast.get("min_train", 8))
        print(f"FAST MODE: K={k}, min_train={min_train}; numbers are not citable")
    period = float(cfg["climatology"].get("period_days", 365.25))
    folds = [str(f) for f in dyn.get("folds", ["B1", "B2"])]

    windows = read_station_keyed(WINDOWS_CSV, parse_dates=["issue_date"])
    windows = windows.rename(columns={"station": "station"})[
        ["station", "issue_date", "horizon", "F_mean", "F_sd", "n_members"]]
    panel = load_panel(cfg)

    frames, diag_rows = [], []
    for fold in folds:
        block = panel[panel["fold"] == fold]
        if block.empty:
            print(f"[{fold}] not in the panel; skipped")
            continue
        keys = ["station", "issue_date", "horizon"]
        train = target_rows(block, TARGET, "train").merge(windows, on=keys, how="inner")
        evals = target_rows(block, TARGET, "eval").merge(windows, on=keys, how="inner")
        for (st, h), ev in evals.groupby(["station", "horizon"]):
            tr = train[(train["station"] == st) & (train["horizon"] == h)]
            res = calibrate(tr, ev, k, period, min_train)
            if res is None:
                print(f"[{fold}/{st}/{h}] {len(tr)} training Mondays (< {min_train}); skipped")
                continue
            mu, sd, diag = res
            ev = ev.reset_index(drop=True)
            frames.append(pred_frame(ev, "temporal", TARGET, MODEL,
                                     gaussian_quantiles(mu, sd, levels), mu, cfg))
            diag_rows.append({"fold": fold, "station": st, "horizon": h, "n_eval": int(len(ev)),
                              **diag})
        print(f"[{fold}] train Mondays with a CFS window: {len(train)} | eval: {len(evals)}")

    diag = pd.DataFrame(diag_rows)
    atomic_write_csv(diag, TABLES / "T8_cfs_calibration.csv")
    path = write_preds(frames, "temporal", MODEL)
    if path is None:
        print("WARNING: no CFS_BC predictions (no fold had enough training Mondays); "
              "H4 and the CFS rows of T2 will be empty")
    else:
        pooled = diag.groupby("horizon")[["corr_train", "corr_eval", "slope"]].mean().round(3)
        print("\nCFS anomaly vs observed anomaly, mean over stations and folds:")
        print(pooled.to_string())
        print(f"wrote {path}")
    write_manifest({"tables": {"T8_cfs_calibration": "tables/T8_cfs_calibration.csv"},
                    "cfs_benchmark": {
        "model": MODEL, "folds": folds, "clim_harmonics_K": k, "min_train": min_train,
        "cells": int(len(diag)), "table": rel_path(TABLES / "T8_cfs_calibration.csv"),
        "fast_mode": fast_mode()}}, replace=("cfs_benchmark",))


if __name__ == "__main__":
    main()

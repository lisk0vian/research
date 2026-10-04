# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Amendment A2 (post hoc): why Chronos' window intervals are so narrow.

Chronos' 90 % intervals for 7-28-day window means covered only 22-31 % of the
outcomes. A2 put forward a cause without testing it: 07b averages each daily
sample path over the window, and if a path's days vary more independently than
real anomalies do, that average shrinks the spread far more than the real
errors shrink. This stage tests it on the daily paths, which 07b does not keep.

For every temporal evaluation context (same contexts, model and sample count as
07b), on the 28 daily leads:

1. **Daily calibration.** Coverage of the observed daily anomaly by the daily
   5-95 % quantiles of the paths, and the mean path spread against the RMSE of
   the path median.
2. **Persistence.** Lag-1 autocorrelation of the paths' deviations from their
   ensemble mean, against that of the real errors (observed minus median).
3. **Aggregation.** How much the spread shrinks from daily values to the
   window mean: SD(window mean) / mean daily SD, for the paths and for the real
   errors, next to 1/sqrt(n days), the value for independent days.

Daily calibration near nominal with lower persistence and stronger shrinkage
in the paths confirms the cause; poor daily calibration would point at the
daily distribution itself instead.

Writes `outputs/tables/T10_chronos_diagnostic.csv`.
"""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd

from _common import (
    TABLES,
    atomic_write_csv,
    checkpoints,
    ensure_dirs,
    load_config,
    paths_report,
    primary_target,
    read_station_keyed,
    write_manifest,
)
from _panel import fast_mode, read_eval_index

TARGET = primary_target()
# Declared with the `value`/`reference` schema of T10 (the columns used to be
# `paths`/`observed`); a stale T10 from an earlier run would not match what
# report.py and the paper read. Declaring it also re-runs the stage when the
# schema moves again (COLAB.md §7, rule 12).
RESULTS_VERSION = 1


# --- metrics (pure, tested without torch) ----------------------------------------

def daily_metrics(paths: np.ndarray, obs: np.ndarray) -> pd.DataFrame:
    """paths (n, S, L), obs (n, L) -> per lead: 90 % coverage, spread, RMSE of the median."""
    q05, q50, q95 = (np.quantile(paths, p, axis=1) for p in (0.05, 0.5, 0.95))
    ok = np.isfinite(obs)
    rows = []
    for lead in range(paths.shape[2]):
        m = ok[:, lead]
        o = obs[m, lead]
        rows.append({
            "lead_day": lead + 1, "n": int(m.sum()),
            "cov90": float(np.mean((o >= q05[m, lead]) & (o <= q95[m, lead]))) if m.any() else np.nan,
            "spread": float(np.mean(paths[m, :, lead].std(axis=1))) if m.any() else np.nan,
            "rmse_median": float(np.sqrt(np.mean((o - q50[m, lead]) ** 2))) if m.any() else np.nan,
        })
    return pd.DataFrame(rows)


def lag1(x: np.ndarray) -> float:
    """Lag-1 correlation along the last axis, pooled over everything else, NaN-safe."""
    a, b = x[..., :-1].ravel(), x[..., 1:].ravel()
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def path_shrink(paths: np.ndarray, a: int, b: int) -> float:
    """SD across samples of the window mean / mean daily SD across samples."""
    win = paths[:, :, a - 1:b]
    daily_var = win.var(axis=1).mean()
    window_var = win.mean(axis=2).var(axis=1).mean()
    return float(np.sqrt(window_var / daily_var)) if daily_var > 0 else float("nan")


def error_shrink(err: np.ndarray, a: int, b: int) -> float:
    """SD across contexts of the window-mean error / mean daily SD of the error."""
    win = err[:, a - 1:b]
    rows = np.isfinite(win).all(axis=1)
    if rows.sum() < 3:
        return float("nan")
    win = win[rows]
    daily_var = win.var(axis=0).mean()
    window_var = win.mean(axis=1).var()
    return float(np.sqrt(window_var / daily_var)) if daily_var > 0 else float("nan")


def summarise(paths: np.ndarray, obs: np.ndarray, windows: dict[str, tuple[int, int]],
              role: str) -> list[dict]:
    """Rows of T10 for one set of contexts.

    Column names say what they hold: `value` is the model's achieved quantity
    (its coverage, its spread, its persistence) and `reference` is what it is
    compared against (the nominal level, the RMSE, the real errors). They used
    to be `paths` and `observed`, which read as if the second were the data.
    """
    med = np.quantile(paths, 0.5, axis=1)
    err = obs - med
    dev = paths - paths.mean(axis=1, keepdims=True)
    rows = []
    d = daily_metrics(paths, obs)
    for (lo, hi), name in (((1, 7), "days 1-7"), ((8, 14), "days 8-14"), ((15, 28), "days 15-28")):
        part = d[(d["lead_day"] >= lo) & (d["lead_day"] <= hi)]
        rows.append({"role": role, "check": "daily", "scope": name,
                     "value": float(part["cov90"].mean()), "reference": 0.90,
                     "metric": "cov90 of daily anomaly (nominal 0.90)"})
        rows.append({"role": role, "check": "daily", "scope": name,
                     "value": float(part["spread"].mean()),
                     "reference": float(part["rmse_median"].mean()),
                     "metric": "path SD vs RMSE of the median (degC)"})
    rows.append({"role": role, "check": "persistence", "scope": "days 1-28",
                 "value": lag1(dev), "reference": lag1(err),
                 "metric": "lag-1 autocorrelation (path deviations vs real errors)"})
    for h, (a, b) in windows.items():
        rows.append({"role": role, "check": "aggregation", "scope": h,
                     "value": path_shrink(paths, a, b), "reference": error_shrink(err, a, b),
                     "metric": f"SD(window mean)/daily SD; independent days: "
                               f"{1 / np.sqrt(b - a + 1):.3f}"})
    return rows


# --- driver ------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    ccfg = cfg["models"]["chronos"]
    if not ccfg.get("enabled", True) or (fast_mode() and not cfg["models"]["fast"].get(
            "chronos_enabled", False)):
        print("Chronos disabled (config or fast mode): nothing to diagnose")
        return
    m07b = importlib.import_module("07b_deep")
    windows = {h: (int(v[0]), int(v[1])) for h, v in cfg["target"]["horizons"].items()}
    horizon_len = max(b for _, b in windows.values())
    folds = {f["id"]: f for f in cfg["validation"]["folds"]}

    daily = read_station_keyed(m07b.DAILY_CSV, parse_dates=["date"])
    index = read_eval_index("temporal")
    index = index[index["target"] == TARGET]
    evals = index.drop_duplicates(["station", "fold", "issue_date"])
    pipe = m07b.chronos_pipeline(ccfg["model_id"])
    bs = int(ccfg.get("batch_size", 64))
    ck = checkpoints("09c_chronos_diagnostic")

    by_role: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for fid, block in evals.groupby("fold"):
        unit = f"paths__{fid}"
        if ck.has(unit):
            paths, obs = ck.load(unit)
            print(f"[{fid}] loaded from checkpoint")
        else:
            seqs = {st: m07b.station_daily_anomalies(daily[daily["station"] == st],
                                                     m07b.load_fold_meta(st, fid), folds[fid], cfg)
                    ["A_TT_mean"] for st in block["station"].unique()}
            ctx, obs = [], []
            import torch
            for st, d in zip(block["station"], block["issue_date"]):
                s = seqs[st]
                ctx.append(torch.tensor(s[s.index <= d].iloc[-int(ccfg["context_days"]):]
                                        .to_numpy("float32")))
                lead = pd.date_range(d + pd.Timedelta(days=1), periods=horizon_len, freq="D")
                obs.append(s.reindex(lead).to_numpy(float))
            paths, bs = m07b.predict_paths(pipe, ctx, horizon_len, int(ccfg["num_samples"]), bs)
            obs = np.vstack(obs)
            ck.save(unit, (paths.astype("float32"), obs))
            print(f"[{fid}] {len(ctx)} contexts, batch size {bs}")
        role = str(block["role"].iloc[0])
        by_role.setdefault(role, []).append((paths, obs))

    rows = []
    for role, parts in sorted(by_role.items()):
        paths = np.concatenate([p for p, _ in parts]).astype(float)
        obs = np.concatenate([o for _, o in parts])
        rows += summarise(paths, obs, windows, role)
    table = pd.DataFrame(rows)
    path = atomic_write_csv(table.round(4), TABLES / "T10_chronos_diagnostic.csv")
    print(table.round(3).to_string(index=False))
    write_manifest({"tables": {"T10_chronos_diagnostic": "tables/T10_chronos_diagnostic.csv"},
                    "chronos_diagnostic_09c": {
        "amendment": "A2, post hoc", "table": "outputs/tables/T10_chronos_diagnostic.csv",
        "contexts": int(sum(len(p) for parts in by_role.values() for p, _ in parts)),
        "model_id": ccfg["model_id"], "num_samples": int(ccfg["num_samples"]),
    }}, replace=("chronos_diagnostic_09c",))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

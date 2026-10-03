"""Climatologies + seasonal dispersion (design §7.1). Train-only per fold.

C2 harmonic (K=3) is the primary reference fixed a priori; C1/C3 are sensitivity
runs. Fits on daily training data, then aggregates to horizons. Also estimates
sigma_h,q and empirical tercile thresholds (+/-15-day window).

Per-fold fitting is not optional. `experiments/README.md` §12 requires that every
fold fits its own climatology on its own training window: a climatology built on
the whole record would let the blind folds (2024, 2025) inform the reference
they are scored against, inflating MSSS_clim. Each fold therefore gets its own
harmonic coefficients, its own C1 window, its own C3 trend and its own
sigma_h,q.

Outputs
-------
`data/processed/climatology_<fold>.json`   coefficients + sigma_h,q + terciles
`data/processed/daily_clim.csv`            per-day climatology and anomalies

`daily.csv` is left untouched: downstream stages read the climatology from
`daily_clim.csv`, keeping the observed series and the reference separable.

Why one row per day and not one row per (day, fold)
----------------------------------------------------
A day belongs to a fold only when it is that fold's *test* year, so the union of
test years gives exactly one climatology per day with no ambiguity. Training
years need no row here: they are reconstructed on demand by `04` and `07` from
the fold's coefficients in `outputs/climatology/<fold>.json`, applied to the
observed series in `daily.csv`. That keeps this table small and unambiguous while
still letting every fold fit its features train-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from _common import (
    OUTPUTS,
    PROCESSED,
    atomic_write_csv,
    atomic_write_json,
    ensure_dirs,
    load_config,
    paths_report,
    progress,
    read_station_keyed,
    rel_path,
    write_manifest,
)
from _harmonic import (
    PERIOD_DAYS,
    design_matrix,
    doy_fractional,
    eval_harmonic,
    fit_harmonic,
    infer_k_and_trend,
)

DAILY_CSV = PROCESSED / "daily.csv"
CLIM_CSV = PROCESSED / "daily_clim.csv"
TARGET = "TT_mean"
# Window (days) used by C1 and by the tercile thresholds (config +/-15d).
WINDOW_DAYS = 15


# --- C1: window climatology ------------------------------------------------

def fit_c1_window(dates, values: np.ndarray, window: int = WINDOW_DAYS) -> dict[int, float]:
    """Mean per day-of-year over a +/-window band of observed days."""
    idx = pd.DatetimeIndex(dates)
    doy = np.round(doy_fractional(idx)).astype(int) % int(PERIOD_DAYS)
    table: dict[int, list[float]] = {}
    for d, v in zip(doy, values):
        if np.isfinite(v):
            table.setdefault(int(d), []).append(float(v))
    smooth: dict[int, float] = {}
    for day in range(int(PERIOD_DAYS)):
        acc: list[float] = []
        for off in range(-window, window + 1):
            acc.extend(table.get((day + off) % int(PERIOD_DAYS), []))
        if acc:
            smooth[day] = float(np.mean(acc))
    return smooth


def apply_c1_window(smooth: dict[int, float], dates) -> np.ndarray:
    idx = pd.DatetimeIndex(dates)
    doy = np.round(doy_fractional(idx)).astype(int) % int(PERIOD_DAYS)
    return np.array([smooth.get(int(d), np.nan) for d in doy], dtype="float64")


# --- sigma_h,q and terciles ------------------------------------------------

def quarter_of(dates) -> np.ndarray:
    """DJF=0, MAM=1, JJA=2, SON=3 (meteorological convention, METHODOLOGY §2)."""
    idx = pd.DatetimeIndex(dates)
    return ((idx.month % 12) // 3).to_numpy()


def horizon_windows(horizons: dict) -> dict[str, tuple[int, int]]:
    """{'W1': [1, 7]} -> {'W1': (1, 7)}; the first value is the lag."""
    return {h: (int(v[0]), int(v[1])) for h, v in horizons.items()}


def seasonal_sigma_hq(resid_dates, residuals: np.ndarray, horizon: tuple[int, int],
                      train_start: pd.Timestamp, train_end: pd.Timestamp,
                      quarters=range(4)) -> dict[str, float]:
    """Residual SD per quarter, using only residuals from that horizon's window.

    A residual at day `t` belongs to horizon (lag0, lag1) only when the whole
    issuance window [t-lag1, t-lag0] sits inside the training window and `t`
    itself is a training day. Edge days whose window sticks out are dropped, so
    longer horizons keep fewer days — that difference between horizons is the
    point, not a side effect. Quarters with too few samples fall back to the
    pooled in-window SD.
    """
    idx = pd.DatetimeIndex(resid_dates)
    lag0, lag1 = horizon
    start = pd.Timestamp(train_start)
    end = pd.Timestamp(train_end)
    in_window = (
        (idx - pd.Timedelta(days=lag1) >= start)
        & (idx - pd.Timedelta(days=lag0) <= end)
        & (idx >= start)
        & (idx <= end)
    )

    qu = quarter_of(idx)
    out: dict[str, float] = {}
    pooled = residuals[in_window & np.isfinite(residuals)]
    fallback = float(np.std(pooled, ddof=1)) if pooled.size > 1 else np.nan
    for q in quarters:
        sel = in_window & (qu == q) & np.isfinite(residuals)
        out[str(q)] = float(np.std(residuals[sel], ddof=1)) if sel.sum() > 1 else fallback
    return out


def tercile_thresholds(dates, values: np.ndarray, window: int = WINDOW_DAYS
                       ) -> dict[str, dict[int, float]]:
    """Empirical 1/3 and 2/3 quantiles per month from a +/-window band.

    Month-level bands (not day-of-year) because the terciles feed RPSS on a
    seasonal basis and 12 samples per band are more stable than ~8.
    """
    idx = pd.DatetimeIndex(dates)
    doy_all = doy_fractional(idx)
    finite = np.isfinite(values)

    out: dict[str, dict[int, float]] = {}
    for month in range(1, 13):
        # Band is +/-window DAYS around each calendar day of the month, not
        # +/-window months: config.climatology uses a 15-day window.
        first = pd.Timestamp(2001, month, 1)
        last = pd.Timestamp(2001, month, 1) + pd.offsets.MonthEnd(0)
        centres = np.arange(first.dayofyear, last.dayofyear + 1, dtype="float64")
        # Circular distance so late December also sees early January days.
        delta = np.abs(doy_all[:, None] - centres[None, :])
        dist = np.minimum(delta, np.abs(365.25 - delta)).min(axis=1)
        sel = (dist <= window) & finite
        pool = values[sel]
        if pool.size < 10:
            continue
        lo, hi = np.percentile(pool, [100 / 3, 200 / 3])
        # String keys: tercile labels 1/2/3 must survive a JSON round trip, and
        # int keys are silently coerced to "1"/"2" by json.dumps anyway.
        out[str(month)] = {"1": float(lo), "2": float(hi)}
    return out


# --- fold driver -----------------------------------------------------------

def train_window(fold: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inclusive last training date for a fold's `train: [y0, y1]` window."""
    y0, y1 = fold["train"]
    return pd.Timestamp(y0, 1, 1), pd.Timestamp(y1, 12, 31)


def compute_fold_climatology(daily: pd.DataFrame, fold: dict, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Fit every climatology variant on one fold's training window only."""
    clim_cfg = cfg.get("climatology", {})
    k = int(clim_cfg.get("harmonics_K", 3))
    period = float(clim_cfg.get("period_days", PERIOD_DAYS))

    train_start, train_end = train_window(fold)
    train = daily[(daily["date"] >= train_start) & (daily["date"] <= train_end)]
    train = train[train[TARGET].notna()]
    if train.empty:
        raise SystemExit(
            f"ERROR: fold {fold['id']} has no training days in "
            f"{train_start.date()}..{train_end.date()}"
        )

    doy_tr = doy_fractional(train["date"])
    y_tr = train[TARGET].to_numpy(dtype="float64")

    coef_c2 = fit_harmonic(doy_tr, y_tr, k, period, trend=False)
    coef_c3 = fit_harmonic(doy_tr, y_tr, k, period, trend=True)
    c1_smooth = fit_c1_window(train["date"], y_tr, WINDOW_DAYS)

    # Anomalies are defined against the fold's own C2 on every day it predicts.
    doy_all = doy_fractional(daily["date"])
    c2_all = eval_harmonic(coef_c2, doy_all, period)
    c3_all = eval_harmonic(coef_c3, doy_all, period)
    c1_all = apply_c1_window(c1_smooth, daily["date"])

    out = pd.DataFrame({
        "date": daily["date"],
        "valid": daily["valid"],
        "C2": c2_all,
        "C3": c3_all,
        "C1": c1_all,
        "A_C2": daily[TARGET].to_numpy(dtype="float64") - c2_all,
        "A_C3": daily[TARGET].to_numpy(dtype="float64") - c3_all,
        "A_C1": daily[TARGET].to_numpy(dtype="float64") - c1_all,
        "doy_frac": doy_all,
        "quarter": quarter_of(daily["date"]),
    })

    resid_dates = out.loc[out["valid"] & out["A_C2"].notna(), "date"]
    resid = out.loc[out["valid"] & out["A_C2"].notna(), "A_C2"].to_numpy(dtype="float64")
    windows = horizon_windows(cfg.get("target", {}).get("horizons", {"W1": [1, 7]}))
    sigma = {h: seasonal_sigma_hq(resid_dates, resid, win, train_start, train_end)
             for h, win in windows.items()}

    meta = {
        "fold": fold["id"],
        "role": fold.get("role"),
        "train_window": [str(train_start.date()), str(train_end.date())],
        "n_train_days": int(len(train)),
        "primary": "C2_harmonic",
        "harmonics_K": k,
        "period_days": period,
        "coefficients": {
            "C2": [float(c) for c in coef_c2],
            "C3": [float(c) for c in coef_c3],
        },
        "C1_window_days": WINDOW_DAYS,
        "sigma_hq": sigma,
        "terciles_C2": tercile_thresholds(
            train["date"], y_tr - eval_harmonic(coef_c2, doy_tr, period), WINDOW_DAYS
        ),
        "variance_explained": {
            "C2": float(1 - np.var(resid) / np.var(y_tr)) if np.var(y_tr) > 0 else np.nan,
        },
    }
    return out, meta


def main() -> None:
    cfg = load_config()
    if not DAILY_CSV.is_file():
        raise SystemExit(f"ERROR: {DAILY_CSV} not found — run 02_aggregate_daily.py first")
    ensure_dirs()
    print(paths_report())

    daily = read_station_keyed(DAILY_CSV, parse_dates=["date"])
    folds = cfg.get("validation", {}).get("folds", [])
    if not folds:
        raise SystemExit("ERROR: config.validation.folds is empty")

    stations = sorted(s for s in daily["station"].unique() if s) if "station" in daily.columns else []
    merged: pd.DataFrame | None = None
    summaries: dict[str, dict] = {}

    # One climatology per station, per fold. Fitting a single harmonic across
    # the pooled network is the failure this loop prevents: Pisco at 347 m and
    # Huancayo at 3298 m are 18 degC apart on any given day of the year, so the
    # pooled fit is not a noisier version of the right answer, it is a
    # different answer, and every station is then scored against a reference
    # that describes mostly the others.
    for code in progress(stations, desc="station", unit="st", level="fold"):
        block = daily[daily["station"] == code]
        for fold in progress(folds, desc=f"climatology {code}", unit="fold", level="fold"):
            out, meta = compute_fold_climatology(block, fold, cfg)
            meta["station"] = code
            path = OUTPUTS / "climatology" / code / f"{fold['id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(meta, path)

            # Evaluation days belong to exactly one fold: the one that tests them.
            test_year = fold["test"]
            mask = out["date"].dt.year == test_year
            piece = out.loc[mask].copy()
            piece["station"] = code
            merged = piece if merged is None else pd.concat([merged, piece], ignore_index=True)

            sig = meta["sigma_hq"]
            sig_txt = ", ".join(
                f"{h}:" + "/".join(f"{float(v):.2f}" for v in d.values())
                for h, d in sig.items()
            )
            print(f"[{code}/{fold['id']}] train {meta['train_window'][0]}..{meta['train_window'][1]} "
                  f"({meta['n_train_days']}d) | var expl. C2 = {meta['variance_explained']['C2']:.3f} "
                  f"| sigma_hq {sig_txt}")
            summaries[f"{code}/{fold['id']}"] = {
                "station": code,
                "fold": fold["id"],
                "train_window": meta["train_window"],
                "n_train_days": meta["n_train_days"],
                "variance_explained_C2": meta["variance_explained"]["C2"],
                "sigma_hq": sig,
                "test_year": test_year,
            }

    assert merged is not None
    merged = merged.sort_values(["station", "date"]).reset_index(drop=True)
    atomic_write_csv(merged, CLIM_CSV)

    print(f"\nevaluation rows (test years only): {len(merged)} across "
          f"{merged['station'].nunique()} station(s) "
          f"({merged['date'].min().date()}..{merged['date'].max().date()})")
    print(f"wrote {CLIM_CSV}")
    print(f"wrote {OUTPUTS / 'climatology'}/<station>/<fold>.json")

    write_manifest({"climatology": summaries,
                    "climatology_files": {
                        "daily_clim": rel_path(CLIM_CSV),
                        "per_fold": f"{rel_path(OUTPUTS / 'climatology')}/<station>/<fold>.json",
                    }},
                   replace=("climatology",))
    # Checked once per (station, fold): a horizon missing from any single
    # reference would otherwise print five warnings per horizon and be read as
    # one recurring problem rather than five separate ones.
    horizons = sorted({h for entry in summaries.values() for h in entry["sigma_hq"]})
    for key, entry in summaries.items():
        for h in ("W1", "W2", "W3_4"):
            if h not in entry["sigma_hq"]:
                print(f"WARNING: {key} sigma_hq missing horizon {h}")
    print(f"sigma_hq horizons present: {horizons}")


if __name__ == "__main__":
    main()
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Local predictors X_L (design §7.2). All dated <= d, as anomalies vs own climatology.

TT lags/means/A0, DTR/TTmax/TTmin, HR, log1p RR sums, target-midpoint
day-of-year sin/cos; plus PP level + tendency and 7-day u/v means only when the
source carries pressure and wind (SENAMHI carries neither, so those features are
not emitted rather than emitted as all-NaN columns).

Three properties this stage must guarantee (METHODOLOGY §4, README §12):

- **Trailing only.** Every window ends at the issuance date d and looks backwards.
  Nothing after d enters a row, otherwise the model reads its own target.
- **Per-fold anomalies.** The climatology is the fold's own, fitted on its training
  window (`outputs/climatology/<station>/<fold>.json`). A global climatology would let the
  blind folds see their own test years.
- **One climatology per variable.** DTR and HR have their own seasonal cycle; DTR
  ranges from ~10 degC in January to ~19 degC in July at this station. Subtracting
  the *temperature* climatology from DTR would leave a seasonal artefact that
  looks like skill, so each variable gets its own harmonic fit on the training
  window. Only TT_mean reuses the coefficients stored by `03`, and it reuses them
  verbatim so the target built by `04` and the lags here share one reference.

`config.predictors.min_window_coverage` sets how much of a trailing window must
be valid for its mean to be used; short windows become NaN rather than being
filled (the target is never imputed, and neither are its predictors).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from _common import (
    OUTPUTS,
    PROCESSED,
    atomic_write_csv,
    ensure_dirs,
    fold_windows,
    load_config,
    paths_report,
    progress,
    read_station_keyed,
    rel_path,
    write_manifest,
)
from _harmonic import doy_fractional, eval_harmonic, fit_harmonic

DAILY_CSV = PROCESSED / "daily.csv"
ISSUANCES_CSV = PROCESSED / "issuances.csv"
CLIM_JSON_DIR = OUTPUTS / "climatology"

# Daily columns each needs its own seasonal reference. TT_mean is excluded: its
# coefficients come from 03 and must match the target built by 04.
ANOMALY_VARS = ("TT_max", "TT_min", "DTR", "HR_mean", "PP_mean")

LAGS = (0, 1, 2, 3, 4, 5, 6)
MEAN_WINDOWS = (7, 14, 30)
A0_WINDOW = 7
RR_WINDOWS = (7, 30)
PP_TENDENCY_LAG = 3
WIND_WINDOW = 7


def configure(cfg: dict) -> None:
    """Read the window constants from `config.predictors.local`.

    The module defaults above are the design values and what the unit tests
    exercise; a config that names them overrides them for the run.
    """
    global LAGS, MEAN_WINDOWS, A0_WINDOW, RR_WINDOWS
    local = (cfg.get("predictors") or {}).get("local")
    if not isinstance(local, dict):
        return
    LAGS = tuple(int(x) for x in local.get("lags", LAGS))
    MEAN_WINDOWS = tuple(int(x) for x in local.get("mean_windows", MEAN_WINDOWS))
    A0_WINDOW = int(local.get("a0_window", A0_WINDOW))
    RR_WINDOWS = tuple(int(x) for x in local.get("rr_windows", RR_WINDOWS))


def _has_data(frame: pd.DataFrame, col: str) -> bool:
    return col in frame.columns and bool(frame[col].notna().any())


# --- seasonal references ---------------------------------------------------

def fit_variable_climatologies(daily: pd.DataFrame, coef_tt: np.ndarray,
                               train_start: pd.Timestamp, train_end: pd.Timestamp,
                               k: int, period: float) -> dict[str, dict]:
    """Per-fold harmonic coefficients for every anomaly variable."""
    train = daily[(daily["date"] >= train_start) & (daily["date"] <= train_end)]
    doy_tr = doy_fractional(train["date"])
    out = {"TT_mean": {"coef": coef_tt, "source": "climatology json"}}
    for var in ANOMALY_VARS:
        # A variable the provider does not carry (pressure, for SENAMHI) has no
        # climatology to fit; its features are skipped downstream.
        if not _has_data(train, var):
            continue
        values = train[var].to_numpy(dtype="float64")
        out[var] = {"coef": fit_harmonic(doy_tr, values, k, period), "source": "fitted here"}
    return out


def anomaly_frame(daily: pd.DataFrame, clims: dict[str, dict], period: float) -> pd.DataFrame:
    """Add one `A_<var>` column per variable against its own seasonal reference."""
    out = pd.DataFrame({"date": daily["date"], "valid": daily["valid"]})
    doy_all = doy_fractional(daily["date"])
    for var, spec in clims.items():
        clim = eval_harmonic(spec["coef"], doy_all, period)
        out[var] = daily[var].to_numpy(dtype="float64")
        out[f"A_{var}"] = out[var] - clim
    return out


# --- trailing features -----------------------------------------------------

def min_periods(window: int, coverage: float) -> int:
    """How many valid days a trailing window needs to be usable."""
    return max(1, int(np.ceil(window * coverage)))


def build_daily_features(anom: pd.DataFrame, rain: pd.Series, u: pd.Series | None,
                         v: pd.Series | None, coverage: float) -> pd.DataFrame:
    """Every feature that does not depend on the horizon, as one row per date.

    Windows are `rolling(...).mean()` on a date-sorted frame, so each includes the
    current day and looks backwards only. Means run over the *valid* mask: a day
    dropped by `02` must not contribute a fabricated value.
    """
    f = pd.DataFrame({"date": anom["date"], "valid": anom["valid"].astype(bool)})

    for lag in LAGS:
        f[f"TT_anom_lag_{lag}"] = anom["A_TT_mean"].shift(lag)

    for w in MEAN_WINDOWS:
        mp = min_periods(w, coverage)
        # A0_7d is the trailing 7-day anomaly mean (METHODOLOGY §2). config lists
        # it separately from TT_anom_mean_7_14_30, but it is the same quantity, so
        # the 7-day mean is emitted once under the A0 name; a second identical
        # column would be perfectly collinear with the first.
        name = "A0_7d" if w == A0_WINDOW else f"TT_anom_mean_{w}"
        f[name] = anom["A_TT_mean"].where(anom["valid"]).rolling(w, min_periods=mp).mean()

    for var, name in (("DTR", "DTR_anom_7d"), ("TT_max", "TTmax_anom_7d"),
                      ("TT_min", "TTmin_anom_7d"), ("HR_mean", "HR_anom_7d"),
                      ("PP_mean", "PP_anom_7d")):
        if f"A_{var}" not in anom.columns:
            continue
        mp = min_periods(A0_WINDOW, coverage)
        f[name] = anom[f"A_{var}"].where(anom["valid"]).rolling(
            A0_WINDOW, min_periods=mp).mean()

    for w in RR_WINDOWS:
        mp = min_periods(w, coverage)
        f[f"log1p_RR_sum_{w}"] = np.log1p(
            rain.where(anom["valid"]).rolling(w, min_periods=mp).sum())

    # HR also gets the 30-day window the design lists (HR_anom_7_30).
    if "A_HR_mean" in anom.columns and 30 in MEAN_WINDOWS:
        f["HR_anom_30d"] = anom["A_HR_mean"].where(anom["valid"]).rolling(
            30, min_periods=min_periods(30, coverage)).mean()

    # Tendency is a difference, not a mean: it needs the exact lag, so a missing
    # value at either end makes the whole feature missing.
    if "PP_mean" in anom.columns:
        pp = anom["PP_mean"].where(anom["valid"])
        f["PP_tendency_3d"] = pp - pp.shift(PP_TENDENCY_LAG)

    mp = min_periods(WIND_WINDOW, coverage)
    for name, series in (("u", u), ("v", v)):
        if series is None or not series.notna().any():
            continue
        f[f"{name}_mean_{WIND_WINDOW}d"] = series.where(
            anom["valid"]).rolling(WIND_WINDOW, min_periods=mp).mean()

    return f


def horizon_doy_sin_cos(issue_date: pd.Timestamp, horizon: tuple[int, int],
                         period: float = 365.25) -> tuple[float, float]:
    """sin/cos of the day-of-year at the middle of the horizon window.

    The midpoint differs per horizon, which is why these two columns are the only
    ones that make the feature table horizon-specific.
    """
    lag_start, lag_end = horizon
    midpoint = issue_date + pd.Timedelta(days=(lag_start + lag_end) / 2.0)
    doy = doy_fractional(pd.DatetimeIndex([midpoint]))[0]
    angle = 2 * np.pi * doy / period
    return float(np.sin(angle)), float(np.cos(angle))


# --- driver ----------------------------------------------------------------

def compute_fold_features(daily: pd.DataFrame, issuances: pd.DataFrame, fold: dict,
                          cfg: dict) -> pd.DataFrame:
    """Feature table for one fold: one row per (issue_date, horizon) of that fold."""
    clim_cfg = cfg.get("climatology", {})
    pred_cfg = cfg.get("predictors", {})
    k = int(clim_cfg.get("harmonics_K", 3))
    period = float(clim_cfg.get("period_days", 365.25))
    coverage = float(pred_cfg.get("min_window_coverage", 0.5))

    # 03 writes one coefficient set per (station, fold). Reading a single
    # station's anomalies against another's coefficients would leave a seasonal
    # artefact that the model could learn from, which is exactly the failure
    # the per-fold climatology exists to prevent.
    station = None
    if "station" in daily.columns:
        codes = [c for c in daily["station"].dropna().unique() if c]
        if len(codes) > 1:
            raise SystemExit(
                f"ERROR: compute_fold_features got {len(codes)} stations ({codes}); "
                "the caller must pass one station's block"
            )
        station = codes[0] if codes else None
    candidates = ([CLIM_JSON_DIR / station / f"{fold['id']}.json"] if station
                  else [CLIM_JSON_DIR / f"{fold['id']}.json",
                        *sorted(CLIM_JSON_DIR.glob(f"*/{fold['id']}.json"))])
    meta_path = next((p for p in candidates if p.is_file()), None)
    if meta_path is None:
        raise SystemExit(
            f"ERROR: no climatology for fold {fold['id']}"
            + (f" station {station}" if station else "")
            + " — run 03_climatology.py first"
        )
    coef_tt = np.asarray(json.loads(meta_path.read_text(encoding="utf-8"))
                         ["coefficients"]["C2"], dtype="float64")

    train_lo, train_hi, _, _ = fold_windows(fold, cfg)

    clims = fit_variable_climatologies(daily, coef_tt, train_lo, train_hi, k, period)
    anom = anomaly_frame(daily, clims, period)

    feats = build_daily_features(anom, daily["RR_sum"], daily.get("u_mean"),
                                 daily.get("v_mean"), coverage)

    rows = issuances[issuances["fold"] == fold["id"]].copy()
    if rows.empty:
        return rows

    lookup = feats.set_index("date")
    dates = rows["issue_date"]

    out = rows[["fold", "role", "issue_date", "kind", "horizon", "lag_start", "lag_end"]].copy()
    for col in feats.columns:
        if col in ("date", "valid"):
            continue
        out[col] = lookup[col].reindex(pd.DatetimeIndex(dates)).to_numpy()

    sin_cos = [
        horizon_doy_sin_cos(d, (int(a), int(b)), period)
        for d, a, b in zip(dates, rows["lag_start"], rows["lag_end"])
    ]
    out["doy_sin_target_midpoint"] = [s for s, _ in sin_cos]
    out["doy_cos_target_midpoint"] = [c for _, c in sin_cos]
    return out


def main() -> None:
    cfg = load_config()
    configure(cfg)
    for required in (DAILY_CSV, ISSUANCES_CSV):
        if not required.is_file():
            raise SystemExit(f"ERROR: {required} not found — run 02 and 04 first")
    ensure_dirs()
    print(paths_report())

    daily = read_station_keyed(DAILY_CSV, parse_dates=["date"])
    issuances = read_station_keyed(ISSUANCES_CSV, parse_dates=["issue_date"])
    folds = cfg.get("validation", {}).get("folds", [])

    stations = sorted(s for s in daily["station"].unique() if s) if "station" in daily.columns else []
    feature_cols: list[str] = []
    summary: dict[str, dict] = {}

    # Sorted by station then time. Every feature below is a lag, a rolling mean
    # or a difference over consecutive days, so two stations' rows must never
    # be adjacent. Sorting on date alone interleaves them and the lags silently
    # start measuring across an elevation gradient.
    for code in progress(stations, desc="features station", unit="st", level="fold"):
        block = (daily[daily["station"] == code].sort_values("date").reset_index(drop=True)
                 if "station" in daily.columns else daily)
        iss = (issuances[issuances["station"] == code]
               if "station" in issuances.columns else issuances)
        for fold in progress(folds, desc=f"features {code}", unit="fold", level="fold"):
            out = compute_fold_features(block, iss, fold, cfg)
            if out.empty:
                print(f"[{code}/{fold['id']}] no issuances")
                continue
            out["station"] = code
            path = PROCESSED / "features" / code / f"{fold['id']}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_csv(out, path)

            if not feature_cols:
                feature_cols = [c for c in out.columns
                                if c not in ("fold", "role", "issue_date", "kind",
                                             "horizon", "lag_start", "lag_end", "station")]
            numeric = out[feature_cols]
            missing = numeric.isna().mean().mul(100).round(1)
            print(f"[{code}/{fold['id']}] {len(out)} rows x {len(feature_cols)} features "
                  f"| missing % max {missing.max():.1f} ({missing.idxmax()}) "
                  f"| wholly-missing: {int((missing == 100).sum())}")
            summary[f"{code}/{fold['id']}"] = {
                "station": code,
                "fold": fold["id"],
                "rows": int(len(out)),
                "n_features": len(feature_cols),
                "missing_pct": {k: float(v) for k, v in missing.items()},
                "file": rel_path(path),
            }

    print(f"\nfeature columns ({len(feature_cols)}): {', '.join(feature_cols)}")
    print(f"wrote {PROCESSED}/features/<station>/<fold>.csv")
    write_manifest({"features": summary,
                    "feature_files": {k: v["file"] for k, v in summary.items()}},
                   replace=("features",))


if __name__ == "__main__":
    main()
"""Local predictors X_L (design §7.2). All dated <= d, as anomalies vs own climatology.

TT lags/means/A0, DTR/TTmax/TTmin, HR, log1p RR sums, PP level + tendency,
7-day u/v means, target-midpoint day-of-year sin/cos.

Three properties this stage must guarantee (METHODOLOGY §4, README §12):

- **Trailing only.** Every window ends at the issuance date d and looks backwards.
  Nothing after d enters a row, otherwise the model reads its own target.
- **Per-fold anomalies.** The climatology is the fold's own, fitted on its training
  window (`outputs/climatology/<fold>.json`). A global climatology would let the
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
    load_config,
    paths_report,
    progress,
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


# --- seasonal references ---------------------------------------------------

def fit_variable_climatologies(daily: pd.DataFrame, coef_tt: np.ndarray,
                               train_start: pd.Timestamp, train_end: pd.Timestamp,
                               k: int, period: float) -> dict[str, dict]:
    """Per-fold harmonic coefficients for every anomaly variable."""
    train = daily[(daily["date"] >= train_start) & (daily["date"] <= train_end)]
    doy_tr = doy_fractional(train["date"])
    out = {"TT_mean": {"coef": coef_tt, "source": "climatology json"}}
    for var in ANOMALY_VARS:
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


def build_daily_features(anom: pd.DataFrame, rain: pd.Series, u: pd.Series,
                         v: pd.Series, coverage: float) -> pd.DataFrame:
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
        mp = min_periods(A0_WINDOW, coverage)
        f[name] = anom[f"A_{var}"].where(anom["valid"]).rolling(
            A0_WINDOW, min_periods=mp).mean()

    for w in RR_WINDOWS:
        mp = min_periods(w, coverage)
        f[f"log1p_RR_sum_{w}"] = np.log1p(
            rain.where(anom["valid"]).rolling(w, min_periods=mp).sum())

    # Tendency is a difference, not a mean: it needs the exact lag, so a missing
    # value at either end makes the whole feature missing.
    pp = anom["PP_mean"].where(anom["valid"])
    f["PP_tendency_3d"] = pp - pp.shift(PP_TENDENCY_LAG)

    mp = min_periods(WIND_WINDOW, coverage)
    for name, series in (("u", u), ("v", v)):
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

    meta_path = CLIM_JSON_DIR / f"{fold['id']}.json"
    if not meta_path.is_file():
        raise SystemExit(f"ERROR: {meta_path} not found — run 03_climatology.py first")
    coef_tt = np.asarray(json.loads(meta_path.read_text(encoding="utf-8"))
                         ["coefficients"]["C2"], dtype="float64")

    train_lo = pd.Timestamp(fold["train"][0], 1, 1)
    train_hi = pd.Timestamp(fold["train"][1], 12, 31)

    clims = fit_variable_climatologies(daily, coef_tt, train_lo, train_hi, k, period)
    anom = anomaly_frame(daily, clims, period)

    feats = build_daily_features(anom, daily["RR_sum"], daily["u_mean"],
                                 daily["v_mean"], coverage)

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
    for required in (DAILY_CSV, ISSUANCES_CSV):
        if not required.is_file():
            raise SystemExit(f"ERROR: {required} not found — run 02 and 04 first")
    ensure_dirs()
    print(paths_report())

    daily = pd.read_csv(DAILY_CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    issuances = pd.read_csv(ISSUANCES_CSV, parse_dates=["issue_date"])
    folds = cfg.get("validation", {}).get("folds", [])

    feature_cols: list[str] = []
    summary: dict[str, dict] = {}

    for fold in progress(folds, desc="features fold", unit="fold"):
        out = compute_fold_features(daily, issuances, fold, cfg)
        if out.empty:
            print(f"[{fold['id']}] no issuances")
            continue
        path = PROCESSED / f"features_{fold['id']}.csv"
        atomic_write_csv(out, path)

        if not feature_cols:
            feature_cols = [c for c in out.columns
                            if c not in ("fold", "role", "issue_date", "kind",
                                         "horizon", "lag_start", "lag_end")]
        numeric = out[feature_cols]
        missing = numeric.isna().mean().mul(100).round(1)
        print(f"[{fold['id']}] {len(out)} rows x {len(feature_cols)} features "
              f"| missing % max {missing.max():.1f} ({missing.idxmax()}) "
              f"| wholly-missing: {int((missing == 100).sum())}")
        summary[fold["id"]] = {
            "rows": int(len(out)),
            "n_features": len(feature_cols),
            "missing_pct": {k: float(v) for k, v in missing.items()},
            "file": rel_path(path),
        }

    print(f"\nfeature columns ({len(feature_cols)}): {', '.join(feature_cols)}")
    print(f"wrote {PROCESSED}/features_<fold>.csv")
    write_manifest({"features": summary,
                    "feature_files": {k: v["file"] for k, v in summary.items()}})


if __name__ == "__main__":
    main()
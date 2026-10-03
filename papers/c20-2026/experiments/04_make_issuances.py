"""Issuances, targets and embargo (design §6 + §12.2).

Eval: weekly issuance (config weekday, default Monday). Training may use daily
issuance. Target A^h_d valid with >=5/7 (W1/W2) or >=10/14 (W3-4) valid days.
Training issuance d enters a fold only if d+28 < test start.

One row per (issue_date, horizon, fold). A daily `A^h_d` anomaly is the mean of
the daily anomalies over the horizon window; it is only valid when enough valid
days are present, and it is never imputed (METHODOLOGY §3).

Anti-leakage (§12)
------------------
- The target window starts at d+1, so no target day is at or before the issuance.
- An issuance's target must end before the fold's test start, or the model would
  be scored on days whose climatology it has already seen. For training rows the
  design fixes this with the 28-day embargo (d + embargo < test start), which
  also covers the longest horizon (W3-4 ends at d+28).
- An evaluation issuance whose target leaves the fold's test year is dropped for
  every fold, dev and blind alike. Otherwise dev folds would carry rows that can
  never be valid (their targets fall in the next year, outside the panel) while
  blind folds dropped them, making the two incomparable.
- `A^h_d` is built from `A_C2` of the fold that *tests* those days, i.e. the
  climatology fitted on that fold's own training window.
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
from _harmonic import doy_fractional, eval_harmonic

DAILY_CSV = PROCESSED / "daily.csv"
CLIM_CSV = PROCESSED / "daily_clim.csv"
CLIM_JSON_DIR = OUTPUTS / "climatology"

WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

ISSUANCE_COLUMNS = [
    "fold", "role", "issue_date", "weekday", "kind", "horizon",
    "lag_start", "lag_end", "target_start", "target_end",
    "n_days", "n_valid_days", "A_C2_target", "valid_target", "n_train_days",
    "C2_target",
]
# Secondary targets (03 fits their climatologies). Each adds an anomaly, a
# validity flag and the window-mean climatology, which is what reconstructs an
# absolute temperature (T = C + A) for the frost index.
SECONDARY_TARGETS = ("TT_min", "TT_max")


def secondary_columns(var: str) -> list[str]:
    return [f"A_C2_target_{var}", f"valid_target_{var}", f"C2_target_{var}"]


# --- calendar helpers ------------------------------------------------------

def weekly_dates(start: pd.Timestamp, end: pd.Timestamp, weekday: int) -> pd.DatetimeIndex:
    """Every `weekday` in [start, end]. dayofweek: Monday=0 .. Sunday=6."""
    if start > end:
        return pd.DatetimeIndex([])
    days = pd.date_range(start, end, freq="D")
    return days[days.dayofweek == weekday]


def horizon_windows(horizons: dict) -> dict[str, tuple[int, int]]:
    """{'W1': [1, 7]} -> {'W1': (1, 7)}; first element is the lag offset."""
    return {h: (int(v[0]), int(v[1])) for h, v in horizons.items()}


def load_fold_meta(fold_id: str, station: str | None = None) -> dict:
    """The fold's whole climatology JSON (same lookup as load_fold_coefficients)."""
    candidates = ([CLIM_JSON_DIR / station / f"{fold_id}.json"] if station
                  else [CLIM_JSON_DIR / f"{fold_id}.json",
                        *sorted(CLIM_JSON_DIR.glob(f"*/{fold_id}.json"))])
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    tried = ", ".join(str(c) for c in candidates)
    raise SystemExit(f"ERROR: no climatology for fold {fold_id} (tried: {tried}) — "
                     "run 03_climatology.py first")


def load_fold_coefficients(fold_id: str, station: str | None = None) -> np.ndarray:
    """Read the fold's C2 coefficients, from that station's own climatology.

    03 writes one coefficient set per (station, fold), and they are not
    interchangeable: two stations 3000 m apart have different harmonic
    coefficients, so loading the wrong one scores a station against a
    reference that describes somewhere else. `station=None` falls back to the
    pre-migration layout, and to the single folder the old layout would have
    produced, for data that predates the network.
    """
    candidates = ([CLIM_JSON_DIR / station / f"{fold_id}.json"] if station
                  else [CLIM_JSON_DIR / f"{fold_id}.json",
                        *sorted(CLIM_JSON_DIR.glob(f"*/{fold_id}.json"))])
    for path in candidates:
        if path.is_file():
            meta = json.loads(path.read_text(encoding="utf-8"))
            return np.asarray(meta["coefficients"]["C2"], dtype="float64")
    tried = ", ".join(str(c) for c in candidates)
    raise SystemExit(f"ERROR: no climatology for fold {fold_id} (tried: {tried}) — "
                     "run 03_climatology.py first")


def anomalies_for_window(daily: pd.DataFrame, coef: np.ndarray, start: pd.Timestamp,
                         end: pd.Timestamp, period: float,
                         variable: str = "TT_mean") -> pd.DataFrame:
    """Observed `variable` minus the fold's C2, restricted to [start, end].

    The climatology is reconstructed from the fold coefficients rather than read
    from `daily_clim.csv`, because training years are absent there by design.
    """
    sub = daily[(daily["date"] >= start) & (daily["date"] <= end)]
    if sub.empty:
        return sub
    doy = doy_fractional(sub["date"])
    sub = sub.copy()
    sub["C2"] = eval_harmonic(coef, doy, period)
    sub["A_C2"] = sub[variable] - sub["C2"]
    return sub


# --- targets ---------------------------------------------------------------

class AnomalyPanel:
    """Date-sorted anomalies with O(1) window lookup after one O(n) pass.

    `build_target` runs once per (issuance date, horizon): thousands of times per
    fold. Filtering the DataFrame three times per call made this stage take
    minutes; precomputed prefix sums make each window a subtraction.
    """

    def __init__(self, panel: pd.DataFrame) -> None:
        ordered = panel.sort_values("date")
        self.dates = ordered["date"].to_numpy()
        anomalies = ordered["A_C2"].to_numpy(dtype="float64")
        valid = ordered["valid"].fillna(False).to_numpy(dtype=bool)
        self.usable = valid & np.isfinite(anomalies)
        # Prefix sums over usable days: the mean of any window is a difference of
        # two lookups, so no scanning at all.
        self._csum = np.concatenate([[0.0], np.cumsum(self.usable.astype("float64"))])
        self._vsum = np.concatenate(
            [[0.0], np.cumsum(np.where(self.usable, anomalies, 0.0))])
        clim = (ordered["C2"].to_numpy(dtype="float64") if "C2" in ordered.columns
                else np.full(len(ordered), np.nan))
        self._csum_clim = np.concatenate(
            [[0.0], np.cumsum(np.where(self.usable, clim, 0.0))])
        self._i64 = self.dates.astype("datetime64[ns]").astype("int64")

    @staticmethod
    def _key(value: pd.Timestamp) -> np.int64:
        """datetime64 -> ns int64, matching self._i64 so searchsorted compares ints."""
        return np.datetime64(value, "ns").astype("int64")

    def _bounds(self, issue_date: pd.Timestamp, t1: pd.Timestamp) -> tuple[int, int]:
        lo = int(np.searchsorted(self._i64, self._key(issue_date), side="right"))
        hi = int(np.searchsorted(self._i64, self._key(t1), side="right"))
        return lo, hi

    def target(self, issue_date: pd.Timestamp, lag_start: int, lag_end: int,
               min_valid: int) -> dict:
        """Period-mean anomaly over (issue_date+lag_start, issue_date+lag_end]."""
        t0 = issue_date + pd.Timedelta(days=lag_start)
        t1 = issue_date + pd.Timedelta(days=lag_end)
        lo, hi = self._bounds(issue_date, t1)

        n_days = (t1 - t0).days + 1
        n_valid = int(self._csum[hi] - self._csum[lo])
        if n_valid >= min_valid:
            value = float((self._vsum[hi] - self._vsum[lo]) / n_valid)
            clim = float((self._csum_clim[hi] - self._csum_clim[lo]) / n_valid)
        else:
            value = np.nan  # never imputed (METHODOLOGY §3)
            clim = np.nan

        return {
            "target_start": t0,
            "target_end": t1,
            "n_days": int(n_days),
            "n_valid_days": n_valid,
            "A_C2_target": value,
            "valid_target": bool(n_valid >= min_valid),
            "C2_target": clim,
        }


def build_target(panel: pd.DataFrame, issue_date: pd.Timestamp, horizon: str,
                 lag_start: int, lag_end: int, min_valid: int) -> dict:
    """Single-call convenience wrapper; the driver reuses one AnomalyPanel."""
    return AnomalyPanel(panel).target(issue_date, lag_start, lag_end, min_valid)


# --- driver ----------------------------------------------------------------

def compute_fold_issuances(daily: pd.DataFrame, fold: dict, cfg: dict) -> pd.DataFrame:
    """Weekly evaluation rows plus embargoed daily training rows for one fold."""
    iss_cfg = cfg.get("issuance", {})
    val_cfg = cfg.get("validation", {})
    horizons = horizon_windows(cfg.get("target", {}).get("horizons", {}))
    if not horizons:
        raise SystemExit("ERROR: config.target.horizons is empty")
    min_valid = cfg.get("target", {}).get("min_valid_days", {})
    embargo = int(val_cfg.get("embargo_days", 28))
    period = float(cfg.get("climatology", {}).get("period_days", 365.25))

    weekday_name = str(iss_cfg.get("weekday", "monday")).lower()
    if weekday_name not in WEEKDAY_NAMES:
        raise SystemExit(f"ERROR: unknown issuance weekday {weekday_name!r}")
    weekday = WEEKDAY_NAMES[weekday_name]

    train_lo, train_hi, test_start, test_end = fold_windows(fold, cfg)

    # The caller hands in one station's block, so the code is recoverable from
    # it. Passing it explicitly would be clearer, but inferring keeps the
    # existing per-station signature and its tests intact.
    station = None
    if "station" in daily.columns:
        codes = [c for c in daily["station"].dropna().unique() if c]
        if len(codes) > 1:
            raise SystemExit(
                f"ERROR: compute_fold_issuances got {len(codes)} stations "
                f"({codes}); the caller must pass one station's block, or the "
                "climatology coefficients loaded below belong to the wrong site"
            )
        station = codes[0] if codes else None
    coef = load_fold_coefficients(fold["id"], station)
    # Panel spans the training window and the test year: a target may reach from
    # one into the other, and the embargo decides whether that is allowed.
    panel = AnomalyPanel(anomalies_for_window(daily, coef, train_lo, test_end, period))
    secondary_panels: dict[str, AnomalyPanel] = {}
    sec_meta = (load_fold_meta(fold["id"], station).get("secondary_targets") or {})
    for var in SECONDARY_TARGETS:
        if var in sec_meta and var in daily.columns:
            coef_v = np.asarray(sec_meta[var]["C2"], dtype="float64")
            secondary_panels[var] = AnomalyPanel(
                anomalies_for_window(daily, coef_v, train_lo, test_end, period, var))

    rows: list[dict] = []

    def add(issue_date: pd.Timestamp, kind: str, role: str) -> None:
        for horizon, (lag_start, lag_end) in horizons.items():
            need = int(min_valid.get(horizon, 0))
            tgt = panel.target(issue_date, lag_start, lag_end, need)
            # An evaluation issuance whose target leaves the fold's test year is
            # dropped, for every fold alike. The late-December Monday is the
            # usual case: its W3-4 window falls in January.
            if kind == "eval" and tgt["target_end"] > test_end:
                continue
            extra = {}
            for var in SECONDARY_TARGETS:
                if var in secondary_panels:
                    sec = secondary_panels[var].target(issue_date, lag_start, lag_end, need)
                    extra[f"A_C2_target_{var}"] = sec["A_C2_target"]
                    extra[f"valid_target_{var}"] = sec["valid_target"]
                    extra[f"C2_target_{var}"] = sec["C2_target"]
            rows.append({
                **extra,
                "fold": fold["id"],
                "role": fold.get("role", ""),
                "issue_date": issue_date,
                "weekday": issue_date.dayofweek,
                "kind": kind,
                "horizon": horizon,
                "lag_start": lag_start,
                "lag_end": lag_end,
                "n_train_days": int(panel.usable.sum()),
                **tgt,
            })

    # Evaluation: weekly on the configured weekday, inside the test year.
    for issue_date in weekly_dates(test_start, test_end, weekday):
        add(issue_date, "eval", fold.get("role", ""))

    # Training: daily issuance over the training window, embargoed.
    if iss_cfg.get("training", "daily_allowed") == "daily_allowed":
        for issue_date in pd.date_range(train_lo, train_hi, freq="D"):
            if issue_date + pd.Timedelta(days=embargo) >= test_start:
                break  # monotonically increasing: the rest is all embargoed out
            add(issue_date, "train", "train")

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["issue_date", "horizon", "kind"]).reset_index(drop=True)
        sec_cols = [c for var in SECONDARY_TARGETS for c in secondary_columns(var)
                    if c in out.columns]
        out = out[ISSUANCE_COLUMNS + sec_cols]
    return out


def main() -> None:
    cfg = load_config()
    for required in (DAILY_CSV,):
        if not required.is_file():
            raise SystemExit(f"ERROR: {required} not found — run 02_aggregate_daily.py first")
    if not CLIM_JSON_DIR.is_dir():
        raise SystemExit(f"ERROR: {CLIM_JSON_DIR} not found — run 03_climatology.py first")
    ensure_dirs()
    print(paths_report())

    daily = read_station_keyed(DAILY_CSV, parse_dates=["date"])
    folds = cfg.get("validation", {}).get("folds", [])
    if not folds:
        raise SystemExit("ERROR: config.validation.folds is empty")

    # One issuance set per station. Issuances are calendar dates, so the whole
    # network could in principle share one set; but the target a given issuance
    # points at is station-specific, so a shared frame keyed on issue_date would
    # carry one station's validity flag into another station's training pool.
    stations = sorted(s for s in daily["station"].unique() if s) if "station" in daily.columns else []
    frames = []
    for code in progress(stations, desc="issuances station", unit="st", level="fold"):
        block = daily[daily["station"] == code] if "station" in daily.columns else daily
        for f in progress(folds, desc=f"issuances {code}", unit="fold", level="fold"):
            part = compute_fold_issuances(block, f, cfg)
            if not part.empty:
                part["station"] = code
            frames.append(part)
    issuances = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    out_path = PROCESSED / "issuances.csv"
    atomic_write_csv(issuances, out_path)

    weekday_name = cfg.get("issuance", {}).get("weekday", "monday")
    embargo = cfg.get("validation", {}).get("embargo_days", 28)
    print(f"issuances: {len(issuances)} rows across {issuances['station'].nunique()} station(s) "
          f"| weekday={weekday_name} embargo={embargo}d")
    for fold in folds:
        sub = issuances[issuances["fold"] == fold["id"]]
        if sub.empty:
            print(f"[{fold['id']}] no issuances")
            continue
        ev = sub[sub["kind"] == "eval"]
        tr = sub[sub["kind"] == "train"]
        print(f"[{fold['id']}] eval={len(ev)} train={len(tr)} "
              f"| test {fold_windows(fold, cfg)[2].date()}..{fold_windows(fold, cfg)[3].date()} "
              f"| valid targets by horizon: "
              + ", ".join(
                  f"{h}:{int(g['valid_target'].sum())}/{len(g)}"
                  for h, g in sub.groupby("horizon")))

    eval_rows = issuances[issuances["kind"] == "eval"]
    if not eval_rows.empty:
        print(f"\nevaluation issuances: {eval_rows['issue_date'].nunique()} distinct dates "
              f"({eval_rows['issue_date'].min().date()}..{eval_rows['issue_date'].max().date()})")
    print(f"wrote {out_path}")

    # Keyed by (station, fold): a per-fold total across the network would hide
    # a station whose targets never became valid.
    summary = {
        f"{code}/{f['id']}": info
        for code in sorted(issuances["station"].unique())
        for f in folds
        for info in [{
            "station": code,
            "fold": f["id"],
            "eval_issue_dates": int(issuances[(issuances["fold"] == f["id"])
                                              & (issuances["station"] == code)
                                              & (issuances["kind"] == "eval")]["issue_date"].nunique()),
            "train_rows": int(((issuances["fold"] == f["id"])
                               & (issuances["station"] == code)
                               & (issuances["kind"] == "train")).sum()),
            "valid_targets": {
                str(h): int(g["valid_target"].sum())
                for h, g in issuances[(issuances["fold"] == f["id"])
                                      & (issuances["station"] == code)].groupby("horizon")
            },
        }]
    }
    write_manifest({"issuances": summary,
                    "issuance_files": {"issuances": rel_path(out_path)}},
                   replace=("issuances",))


if __name__ == "__main__":
    main()
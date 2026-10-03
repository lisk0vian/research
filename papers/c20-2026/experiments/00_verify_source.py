# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""V1-V6 source verification (design §2.1). Reads config.yaml + data/raw/dataset.csv.

Checks timezone (V1), hour convention (V2), missing codes (V3), coverage (V4),
UBIGEO constancy (V5) and timestamp duplicates (V6). Writes a completeness
report to outputs/tables/T1_completeness.csv. Never imputes the target.

V1 is resolved empirically from the mean diurnal TT cycle: for a station whose
timestamps were UTC, the daily minimum would sit near 10-11 local solar time
once shifted, whereas local-time data puts the minimum in the small hours. The
observed peak/minimum hours are written to T1 so the conclusion is auditable
instead of remaining TO_VERIFY in config.yaml.
"""

from __future__ import annotations

import pandas as pd

from _common import (
    NUMERIC_VARS,
    RAW_CSV,
    ensure_dirs,
    fold_windows,
    load_config,
    paths_report,
    read_hourly,
    station_codes,
    write_manifest,
    write_table,
)

EXPECTED_HOURS = range(24)


def check_v1_timezone(df) -> dict:
    """Infer the timestamp timezone from the diurnal TT cycle.

    Returns the local hour of maximum and minimum mean TT. For the Huayao
    high-Andean site, local time gives a minimum around 05:00-07:00; UTC-labelled
    rows would show a minimum around 10:00-11:00 after no shift.
    """
    valid = df[df["TT"].notna()]
    by_hour = valid.groupby(valid["timestamp"].dt.hour)["TT"].mean()
    peak = int(by_hour.idxmax())
    trough = int(by_hour.idxmin())
    amplitude = float(by_hour.max() - by_hour.min())
    return {
        "check": "V1_timezone",
        "detail": f"TT diurnal cycle: max {peak:02d}:00, min {trough:02d}:00, "
        f"amplitude {amplitude:.2f} degC",
        "verdict": "local_civil" if 3 <= trough <= 8 else "REVIEW_shift_required",
        "value": f"peak={peak};trough={trough}",
    }


def check_v2_hour_convention(df) -> dict:
    """Hours must span 0..23 exactly once per day."""
    hours = df["timestamp"].dt.hour
    span_ok = set(hours.dropna().unique()) == set(EXPECTED_HOURS)
    return {
        "check": "V2_hour_convention",
        "detail": f"hours present: {sorted(hours.dropna().unique().tolist())}",
        "verdict": "ok" if span_ok else "REVIEW_incomplete_hours",
        "value": f"n_hours={hours.nunique()}",
    }


def check_v3_missing(df, cfg) -> dict:
    """Inventory missing values per variable: empty strings and sentinel codes."""
    report = []
    total = len(df)
    for var in NUMERIC_VARS:
        col = df[var]
        empty = int(col.isna().sum())
        numeric = pd.to_numeric(col, errors="coerce")
        sentinels = int(numeric.isin([-999, -9999, 9999, 99999]).sum())
        report.append(f"{var}: empty={empty} sentinel={sentinels}")
    # Are the gaps row-wise (whole record missing) or sensor-wise?
    all_missing = df[list(NUMERIC_VARS)].isna().all(axis=1)
    any_missing = df[list(NUMERIC_VARS)].isna().any(axis=1)
    rowwise = bool((all_missing == any_missing).all())
    return {
        "check": "V3_missing_codes",
        "detail": "; ".join(report) + f" | row-wise pattern: {rowwise}",
        "verdict": "ok" if rowwise else "REVIEW_sensor_wise_gaps",
        "value": f"rows={total};all_vars_missing={int(all_missing.sum())}",
    }


def check_v4_coverage(df, cfg) -> dict:
    """First/last timestamp, per-month completeness and blind-year readiness."""
    ts = df["timestamp"].dropna()
    first, last = ts.min(), ts.max()
    days = ts.dt.normalize().nunique()
    per_day = ts.dt.normalize().value_counts()
    incomplete_days = int((per_day < 24).sum())
    years_declared = list(cfg.get("data", {}).get("coverage_declared", []))
    blind_folds = [f for f in cfg.get("validation", {}).get("folds", [])
                   if f.get("role") == "blind"]
    if any(isinstance(f.get("test"), (list, tuple)) for f in blind_folds):
        # v3 folds: a blind window is ready when every one of its months is
        # present in full, and the window may straddle two calendar years.
        days_present = set(per_day.index[per_day >= 24].normalize())
        complete, absent = [], []
        for f in blind_folds:
            _, _, t0, t1 = fold_windows(f, cfg)
            want = pd.date_range(t0, t1, freq="D")
            n = sum(d in days_present for d in want)
            label = f"{f['id']}({t0.date()}..{t1.date()})"
            if n == len(want):
                complete.append(label)
            elif n == 0:
                absent.append(label)
        return {
            "check": "V4_coverage",
            "detail": f"{first} -> {last} | days={days} | days with <24h={incomplete_days} "
            f"| declared={years_declared} | blind windows fully present={complete}"
            + (f" | blind windows absent from the data={absent}" if absent else ""),
            "verdict": "ok" if incomplete_days == 0 and len(complete) == len(blind_folds)
            else "REVIEW_coverage_gaps",
            "value": f"first={first};last={last};days={days}",
        }
    blind_years = [f["test"] for f in blind_folds]
    # A year absent from the frame is a coverage finding, not an exception.
    # Stations carry different windows and a synthetic dataset carries a short
    # one, so `per_day.loc[str(y)]` used to raise a bare KeyError naming nothing
    # useful. per_day is indexed by timestamp, so membership is tested against
    # the years the index actually holds.
    present_years = set(per_day.index.year)
    complete_blind = [
        y for y in blind_years
        if y in present_years and per_day.loc[str(y)].index.month.nunique() == 12
    ] if len(blind_years) else []
    missing_blind = [y for y in blind_years if y not in present_years]
    return {
        "check": "V4_coverage",
        "detail": f"{first} -> {last} | days={days} | days with <24h={incomplete_days} "
        f"| declared={years_declared} | blind years fully present={complete_blind}"
        + (f" | blind years absent from the data={missing_blind}" if missing_blind else ""),
        "verdict": "ok" if incomplete_days == 0 and complete_blind else "REVIEW_coverage_gaps",
        "value": f"first={first};last={last};days={days}",
    }


def check_v5_ubigeo(df, cfg) -> dict:
    """The stations present in the file must be exactly the declared stations.

    This check used to assert that UBIGEO was constant, which was the
    single-station design's way of saying "this is one observatory". Inverting
    it is the whole point: the file is now expected to carry the network, and
    the useful failures are the two that used to be invisible. A declared
    station with no rows means an entire elevation level silently absent from
    the gradient, and an undeclared station means the file is not the one the
    paper describes. Either one is a finding, not a review note.
    """
    present = set(df["UBIGEO"].dropna().unique().tolist()) - {""}
    declared = set(station_codes(cfg))
    if not declared:
        # No stations declared: the pre-migration contract, single station.
        verdict = "ok" if len(present) == 1 else "REVIEW_multi_station_undeclared"
        detail = f"present={sorted(present)} (no stations declared in config)"
    else:
        missing = sorted(declared - present)
        unexpected = sorted(present - declared)
        verdict = "ok" if not missing and not unexpected else "REVIEW_station_mismatch"
        detail = (f"present={len(present)} declared={len(declared)}"
                  + (f" missing={missing}" if missing else "")
                  + (f" undeclared={unexpected}" if unexpected else ""))
    return {
        "check": "V5_ubigeo_station_set",
        "detail": detail,
        "verdict": verdict,
        "value": f"n_present={len(present)}",
        "present": sorted(present),
        "declared": sorted(declared),
    }


def check_v6_duplicates(df) -> dict:
    """Duplicate (station, timestamp) pairs must be reported; keep the first.

    Scoping to the station matters now: with five stations every timestamp
    legitimately appears five times, so a whole-frame duplicate count reports
    roughly 400k and buries the real duplicates inside its own noise.
    """
    if "UBIGEO" in df.columns:
        dup_mask = df.duplicated(subset=["UBIGEO", "timestamp"], keep="first")
    else:
        dup_mask = df["timestamp"].duplicated(keep="first")
    n_dup = int(dup_mask.sum())
    return {
        "check": "V6_timestamp_duplicates",
        "detail": f"duplicated (station, timestamp) pairs: {n_dup}",
        "verdict": "ok" if n_dup == 0 else "REVIEW_deduplicate_first_occurrence",
        "value": f"duplicates={n_dup}",
    }


def main() -> None:
    cfg = load_config()
    if not RAW_CSV.is_file():
        raise SystemExit(f"ERROR: {RAW_CSV} not found — put dataset.csv there first")
    ensure_dirs()

    df = read_hourly(cfg=cfg)
    for var in NUMERIC_VARS:
        df[var] = pd.to_numeric(df[var], errors="coerce")

    print(paths_report())

    rows = [
        check_v1_timezone(df),
        check_v2_hour_convention(df),
        check_v3_missing(df, cfg),
        check_v4_coverage(df, cfg),
        check_v5_ubigeo(df, cfg),
        check_v6_duplicates(df),
    ]
    table = write_table(pd.DataFrame(rows, columns=["check", "detail", "verdict", "value"]),
                        "T1_completeness.csv")

    print(f"rows read: {len(df)}")
    for r in rows:
        print(f"  [{r['verdict']:<34}] {r['check']}: {r['detail']}")
    review = [r["check"] for r in rows if r["verdict"].startswith("REVIEW")]
    if review:
        print(f"REVIEW needed: {', '.join(review)}")
    print(f"wrote {table}")

    write_manifest({"tables": {"T1_completeness": "tables/T1_completeness.csv"}})


if __name__ == "__main__":
    main()
"""Hourly quality control (design §3.1). Reads config.qc_hourly.

Flags out-of-range values, TT steps > threshold and stuck-sensor runs.
Flagged values become missing; the target (TT) is never imputed.

Three independent causes are kept distinct, because they mean different things
in the completeness table T1:

- `missing_source` the provider delivered an empty record (all variables at
  once, verified by 00/V3). Not a sensor problem, so no range check applies.
- `out_of_range` a value outside `config.qc_hourly.range`, or HR above
  `hr_clip_upper`.
- `spike` / `stuck` TT discontinuities from `step_TT_max_degC` and
  `stuck_run_hours` runs of identical values.

QC never deletes rows: it only sets values to NaN and records the flag, so the
daily aggregation can still count how many hours survived (config
`daily_aggregation.min_hours`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from _common import (
    NUMERIC_VARS,
    RAW_CSV,
    ensure_dirs,
    load_config,
    paths_report,
    read_hourly,
    write_manifest,
)

QC_COLUMNS = [f"{v}_qc" for v in NUMERIC_VARS]


def flag_missing_source(df) -> pd.DataFrame:
    """Rows empty in every variable (provider gap, not a sensor fault)."""
    all_missing = df[list(NUMERIC_VARS)].isna().all(axis=1)
    for col in QC_COLUMNS:
        df[col] = pd.Series(pd.NA, index=df.index, dtype="string")
    df.loc[all_missing, QC_COLUMNS] = "missing_source"
    return df


def flag_out_of_range(df, cfg: dict) -> pd.DataFrame:
    """Apply config.qc_hourly.range per variable, plus the HR clip."""
    ranges = cfg.get("qc_hourly", {}).get("range", {})
    hr_clip = cfg.get("qc_hourly", {}).get("hr_clip_upper")
    for var in NUMERIC_VARS:
        col = f"{var}_qc"
        if var in ranges and isinstance(ranges[var], (list, tuple)):
            lo, hi = ranges[var]
            bad = df[var].notna() & ((df[var] < lo) | (df[var] > hi))
        else:
            bad = pd.Series(False, index=df.index)
        if var == "HR" and hr_clip is not None:
            bad = bad | (df[var].notna() & (df[var] > hr_clip))
        df.loc[bad, col] = "out_of_range"
        # A flagged value stops being data; downstream stages must not see it.
        df.loc[bad, var] = np.nan
    return df


def flag_tt_spikes(df, cfg: dict) -> pd.DataFrame:
    """Mark |TT_t - TT_{t-1}| > step_TT_max_degC within a continuous run.

    A simultaneous RR rise with a humidity rise identifies a genuine convective
    event rather than a sensor fault: an afternoon storm drops TT by ~9 degC and
    lifts HR by ~30 points at the same hour. Those hours are real meteorology
    and must be kept, so they are labelled `precip_event` and left intact.
    Anything still over the threshold is a genuine discontinuity.
    """
    step_max = cfg.get("qc_hourly", {}).get("step_TT_max_degC")
    col = "TT_qc"
    if step_max is None:
        return df
    tt = df["TT"]
    delta = tt.diff()
    # A gap larger than one hour breaks the series: no step can be measured.
    contiguous = df["timestamp"].diff() == pd.Timedelta(hours=1)
    spike = delta.abs() > step_max
    spike &= contiguous & tt.notna() & tt.shift(1).notna()

    if spike.any():
        # Co-occurring rain and humidity rise -> physically consistent.
        rr_rise = (df["RR"] - df["RR"].shift(1)) > 0.5
        hr_rise = (df["HR"] - df["HR"].shift(1)) > 5.0
        convective = spike & rr_rise & hr_rise
        df.loc[convective, col] = "precip_event"
        spike = spike & ~convective

    df.loc[spike, col] = "spike"
    # Only a true discontinuity destroys the value; a labelled storm keeps its TT.
    df.loc[spike, "TT"] = np.nan
    return df


def flag_stuck_runs(df, cfg: dict) -> pd.DataFrame:
    """Mark runs of identical consecutive values lasting >= stuck_run_hours."""
    run_hours = cfg.get("qc_hourly", {}).get("stuck_run_hours")
    col = "TT_qc"
    if run_hours is None:
        return df
    tt = df["TT"]
    contiguous = (df["timestamp"].diff() == pd.Timedelta(hours=1)).fillna(False)
    same_value = (tt.diff() == 0).fillna(False)
    # A run is a maximal stretch of consecutive identical, contiguous, valid values.
    group = (~same_value | ~contiguous | tt.isna()).cumsum()
    sizes = df.groupby(group).size()
    stuck_groups = sizes[sizes >= run_hours].index
    stuck = group.isin(stuck_groups) & tt.notna()
    df.loc[stuck, col] = "stuck"
    return df


def main() -> None:
    cfg = load_config()
    if not RAW_CSV.is_file():
        raise SystemExit(f"ERROR: {RAW_CSV} not found")
    ensure_dirs()

    df = read_hourly()
    for var in NUMERIC_VARS:
        df[var] = pd.to_numeric(df[var], errors="coerce")
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(paths_report())

    before = int(df[list(NUMERIC_VARS)].notna().to_numpy().sum())
    df = flag_missing_source(df)
    df = flag_out_of_range(df, cfg)
    df = flag_tt_spikes(df, cfg)
    df = flag_stuck_runs(df, cfg)
    after = int(df[list(NUMERIC_VARS)].notna().to_numpy().sum())

    # QC output is an intermediate: it feeds 02, so it stays in data/processed
    # (gitignored, regenerable) rather than polluting outputs/.
    from _common import PROCESSED, atomic_write_csv

    out = PROCESSED / "hourly_qc.csv"
    keep = ["timestamp", *NUMERIC_VARS, *QC_COLUMNS]
    atomic_write_csv(df[keep], out)

    summary = {}
    for col in QC_COLUMNS:
        vc = df[col].value_counts()
        summary[col.replace("_qc", "")] = {str(k): int(v) for k, v in vc.items() if pd.notna(k)}
    print(f"values before QC: {before}")
    print(f"values after  QC: {after}  (removed {before - after})")
    for var, s in summary.items():
        print(f"  {var}: {s}")
    print(f"wrote {out}")
    write_manifest({"qc": {"valid_values_before": before, "valid_values_after": after,
                           "flags": summary}})


if __name__ == "__main__":
    main()
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Hourly quality control (design §3.1). Reads config.qc_hourly.

Flags out-of-range values, TT steps > threshold and stuck-sensor runs.
Flagged values become missing; the target (TT) is never imputed.

Three independent causes are kept distinct, because they mean different things
in the completeness table T1:

- `missing_source` the provider delivered an empty record (all variables at
  once, verified by 00/V3). Not a sensor problem, so no range check applies.
- `out_of_range` a value outside `config.qc_hourly.range` (HR included: the
  range is the single policy, see `qc_hourly` in `config.yaml`).
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
    """Apply config.qc_hourly.range per variable.

    One policy per variable, applied once. `hr_clip_upper` used to add a second
    threshold for HR, but `range.HR` nulls every value above 100 before the
    103 clip could ever fire, so two declared parameters carried contradictory
    semantics and only one of them did anything. The key is gone; widening the
    HR range is now the only way to change the policy.
    """
    ranges = cfg.get("qc_hourly", {}).get("range", {})
    for var in NUMERIC_VARS:
        col = f"{var}_qc"
        if var in ranges and isinstance(ranges[var], (list, tuple)):
            lo, hi = ranges[var]
            bad = df[var].notna() & ((df[var] < lo) | (df[var] > hi))
        else:
            bad = pd.Series(False, index=df.index)
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


def apply_qc_flags(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Run the range, spike and stuck-run flags one station at a time.

    Every flag below reasons about consecutive rows: a step needs the previous
    hour, a stuck run needs the run to continue. With one station that is the
    whole frame. With five, the frame interleaves them, and three things break
    at once and quietly.

    `sort_values("timestamp")` interleaves stations, so `timestamp.diff()` is
    zero between two different sensors, which makes `contiguous` false, which
    means the spike test never fires on the last hour of any station. And
    `tt.diff() == 0` compares one station's reading against another's, so the
    stuck-run grouping runs across sensor boundaries.

    Grouping here rather than inside each flag keeps the per-station signatures
    the existing tests call, so the loop sits on top and the API underneath is
    unchanged.
    """
    flags = (flag_out_of_range, flag_tt_spikes, flag_stuck_runs)
    if "UBIGEO" not in df.columns:
        out = df
        for flag in flags:
            out = flag(out, cfg)
        return out

    parts = []
    for _, block in df.groupby("UBIGEO", sort=True):
        for flag in flags:
            block = flag(block, cfg)
        parts.append(block)
    return pd.concat(parts).sort_index()


def main() -> None:
    cfg = load_config()
    if not RAW_CSV.is_file():
        raise SystemExit(f"ERROR: {RAW_CSV} not found")
    ensure_dirs()

    df = read_hourly(cfg=cfg)
    missing = [v for v in NUMERIC_VARS if v not in df.columns]
    if missing:
        raise SystemExit(f"ERROR: internal variables {missing} absent after reading "
                         f"{RAW_CSV.name}; check config.variables")
    for var in NUMERIC_VARS:
        df[var] = pd.to_numeric(df[var], errors="coerce")
    # Station first, then time: the flags below read consecutive rows, so each
    # station's hours have to sit together. Sorting on timestamp alone is what
    # put two different sensors next to each other.
    by = ["UBIGEO", "timestamp"] if "UBIGEO" in df.columns else ["timestamp"]
    df = df.sort_values(by).reset_index(drop=True)
    print(paths_report())

    before = int(df[list(NUMERIC_VARS)].notna().to_numpy().sum())
    df = flag_missing_source(df)
    df = apply_qc_flags(df, cfg)
    after = int(df[list(NUMERIC_VARS)].notna().to_numpy().sum())

    # QC output is an intermediate: it feeds 02, so it stays in data/processed
    # (gitignored, regenerable) rather than polluting outputs/.
    from _common import PROCESSED, atomic_write_csv

    out = PROCESSED / "hourly_qc.csv"
    # UBIGEO is kept: dropping it here is what left 02 with no way to tell two
    # stations apart, and a daily frame keyed only on date silently averaged
    # them together.
    keep = [c for c in ["timestamp", "UBIGEO", *NUMERIC_VARS, *QC_COLUMNS] if c in df.columns]
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
"""Daily aggregation on the local civil day (design §3.2).

Builds TT_mean/max/min/DTR, HR/PP/FF means, RR_sum and vector-mean u/v with the
completeness rules from config.daily_aggregation. Wind is never averaged in
degrees: FF/DD are converted to u/v components, averaged as vectors, then
converted back. Calms contribute u = v = 0, so they dilute the vector mean
instead of biasing the direction.

Writes data/processed/daily.csv (gitignored, regenerable). No shift is applied:
00/V1 verified the source timestamps are already local civil time.

`n_hours` is carried explicitly so a day rejected by min_hours can be audited
after the fact.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from _common import (
    NUMERIC_VARS,
    PROCESSED,
    atomic_write_csv,
    ensure_dirs,
    load_config,
    paths_report,
    read_hourly,
)

QC_PATH = PROCESSED / "hourly_qc.csv"

DAILY_COLUMNS = [
    "date", "n_hours", "valid", "TT_mean", "TT_max", "TT_min", "DTR",
    "HR_mean", "PP_mean", "FF_mean", "DD_mean",
    "RR_sum", "u_mean", "v_mean", "RR_n_hours",
]


def add_wind_components(df: pd.DataFrame) -> pd.DataFrame:
    """u = -FF sin(DD), v = -FF cos(DD), meteorological convention."""
    ff = df["FF"].to_numpy(dtype="float64")
    dd = np.deg2rad(df["DD"].to_numpy(dtype="float64"))
    df["u"] = -ff * np.sin(dd)
    df["v"] = -ff * np.cos(dd)
    return df


def require_each_block(n_hours: pd.Series, hours_per_day: int, n_blocks: int = 4) -> pd.Series:
    """True when each of the 6h blocks is represented at least once."""
    return n_hours >= n_blocks


def aggregate(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Group the QC'd hourly frame by local calendar day."""
    agg_cfg = cfg.get("daily_aggregation", {})
    min_hours = int(agg_cfg.get("min_hours", 20))
    require_blocks = bool(agg_cfg.get("require_each_6h_block", True))
    rr_min_hours = int(agg_cfg.get("rr_min_hours", min_hours))

    df = df.copy()
    df["date"] = df["timestamp"].dt.normalize()
    df = add_wind_components(df)

    grouped = df.groupby("date", sort=True)
    daily = grouped.agg(
        n_hours=("TT", "count"),
        TT_mean=("TT", "mean"),
        TT_max=("TT", "max"),
        TT_min=("TT", "min"),
        HR_mean=("HR", "mean"),
        PP_mean=("PP", "mean"),
        FF_mean=("FF", "mean"),
        u_mean=("u", "mean"),
        v_mean=("v", "mean"),
        RR_n_hours=("RR", "count"),
        RR_sum=("RR", "sum"),
    )

    daily["DTR"] = daily["TT_max"] - daily["TT_min"]
    # Direction is the vector mean's bearing, not the mean of DD in degrees.
    daily["DD_mean"] = np.rad2deg(np.arctan2(-daily["u_mean"], -daily["v_mean"])) % 360.0

    daily["valid"] = daily["n_hours"] >= min_hours
    if require_blocks:
        # Every 6h block needs at least one observation for a reliable mean.
        blocks = df.groupby([df["date"], df["timestamp"].dt.hour // 6])["TT"].count()
        per_day = blocks.groupby(level=0).size()
        daily["valid"] &= daily.index.map(per_day).fillna(0).astype(int) >= 4

    daily.loc[daily["RR_n_hours"] < rr_min_hours, "RR_sum"] = np.nan
    daily["RR_n_hours"] = daily["RR_n_hours"].astype("Int64")

    daily = daily.reset_index()
    for col in DAILY_COLUMNS:
        if col not in daily.columns:
            daily[col] = np.nan
    return daily[DAILY_COLUMNS]


def main() -> None:
    cfg = load_config()
    ensure_dirs()

    if not QC_PATH.is_file():
        raise SystemExit(
            f"ERROR: {QC_PATH} not found — run 01_qc_hourly.py first"
        )
    df = pd.read_csv(QC_PATH, parse_dates=["timestamp"])
    for var in NUMERIC_VARS:
        df[var] = pd.to_numeric(df[var], errors="coerce")

    print(paths_report())
    daily = aggregate(df, cfg)
    out = PROCESSED / "daily.csv"
    atomic_write_csv(daily, out)

    n_days = len(daily)
    n_valid = int(daily["valid"].sum())
    print(f"days aggregated: {n_days} | valid by completeness: {n_valid}")
    print(f"TT_mean: mean={daily['TT_mean'].mean():.2f} "
          f"min={daily['TT_mean'].min():.2f} max={daily['TT_mean'].max():.2f} degC")
    print(f"n_hours distribution: {daily['n_hours'].describe()[['min', '50%', 'max']].round(1).to_dict()}")
    print(f"days rejected by min_hours: {n_days - n_valid}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
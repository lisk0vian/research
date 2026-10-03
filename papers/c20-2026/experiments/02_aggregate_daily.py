"""Daily aggregation on the local civil day (design §3.2).

Builds TT_mean/max/min/DTR, HR mean and RR_sum with the completeness rules from
config.daily_aggregation. Pressure (PP) and wind (FF/DD) are aggregated only
when the source carries them: SENAMHI has neither, and its `PP` is renamed to
`RR` at read time. Their columns stay in the contract as NaN so the schema does
not depend on the provider. When wind exists it is never averaged in degrees:
FF/DD become u/v components, averaged as vectors, then converted back. Calms
contribute u = v = 0, so they dilute the vector mean instead of biasing the
direction.

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
    read_station_keyed,
)

QC_PATH = PROCESSED / "hourly_qc.csv"

DAILY_COLUMNS = [
    "station", "date", "n_hours", "valid", "TT_mean", "TT_max", "TT_min", "DTR",
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


def aggregate_station(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Group one station's QC'd hourly frame by local calendar day.

    Single station by contract. The network-level entry point is `aggregate`,
    which calls this once per station; keeping the per-station shape here is
    what lets the existing tests keep working unchanged.
    """
    agg_cfg = cfg.get("daily_aggregation", {})
    min_hours = int(agg_cfg.get("min_hours", 20))
    require_blocks = bool(agg_cfg.get("require_each_6h_block", True))
    rr_min_hours = int(agg_cfg.get("rr_min_hours", min_hours))

    df = df.copy()
    df["date"] = df["timestamp"].dt.normalize()
    has_wind = {"FF", "DD"} <= set(df.columns)
    if has_wind:
        df = add_wind_components(df)

    spec = {
        "n_hours": ("TT", "count"),
        "TT_mean": ("TT", "mean"),
        "TT_max": ("TT", "max"),
        "TT_min": ("TT", "min"),
        "HR_mean": ("HR", "mean"),
        "RR_n_hours": ("RR", "count"),
        "RR_sum": ("RR", "sum"),
    }
    if "PP" in df.columns:
        spec["PP_mean"] = ("PP", "mean")
    if has_wind:
        spec.update(FF_mean=("FF", "mean"), u_mean=("u", "mean"), v_mean=("v", "mean"))
    grouped = df.groupby("date", sort=True)
    daily = grouped.agg(**spec)

    daily["DTR"] = daily["TT_max"] - daily["TT_min"]
    if has_wind:
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


def aggregate(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Daily frame for the whole network, one row per (station, date).

    This is the bug the multi-station refactor exists to prevent. Keying on
    `date` alone is fine while there is one station and wrong from the first
    day there are two: the group covers both, the aggregation averages them,
    and the output looks like an ordinary single-station daily frame. Nothing
    raises. Huancayo and Matucana end up as one row per date at a blended
    temperature, 877 m of elevation silently averaged away, and every
    downstream stage inherits it as fact.

    The loop is here rather than inside `aggregate_station` so that function
    keeps the single-station shape the existing tests call.
    """
    if "UBIGEO" not in df.columns:
        out = aggregate_station(df, cfg)
        if "station" not in out.columns:
            out["station"] = ""
        return out[DAILY_COLUMNS]

    parts = []
    for code, block in df.groupby("UBIGEO", sort=True):
        daily = aggregate_station(block, cfg)
        daily["station"] = code
        parts.append(daily)
    if not parts:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values(["station", "date"]).reset_index(drop=True)[DAILY_COLUMNS]


def main() -> None:
    cfg = load_config()
    ensure_dirs()

    if not QC_PATH.is_file():
        raise SystemExit(
            f"ERROR: {QC_PATH} not found — run 01_qc_hourly.py first"
        )
    df = read_station_keyed(QC_PATH, parse_dates=["timestamp"])
    for var in [v for v in NUMERIC_VARS if v in df.columns]:
        df[var] = pd.to_numeric(df[var], errors="coerce")

    print(paths_report())
    daily = aggregate(df, cfg)
    out = PROCESSED / "daily.csv"
    atomic_write_csv(daily, out)

    n_days = len(daily)
    n_valid = int(daily["valid"].sum())
    # Per station, because a network total hides the thing worth checking: two
    # stations with different coverage. One long, one short, and the pooled
    # count looks fine.
    print(f"days aggregated: {n_days} | valid by completeness: {n_valid}")
    for code, block in daily.groupby("station", sort=True):
        span = f"{block['date'].min():%Y-%m-%d}..{block['date'].max():%Y-%m-%d}"
        tt = block["TT_mean"]
        print(f"  {code}: {len(block):>5} days  {span}  "
              f"TT_mean mean={tt.mean():6.2f} min={tt.min():6.2f} max={tt.max():6.2f} degC")
    print(f"n_hours distribution: {daily['n_hours'].describe()[['min', '50%', 'max']].round(1).to_dict()}")
    print(f"days rejected by min_hours: {n_days - n_valid}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
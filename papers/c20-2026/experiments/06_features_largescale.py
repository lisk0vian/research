"""Large-scale predictors G (design §7.2) as an as-of daily series.

Weekly Niño 3.4 and Niño 1+2 SST anomalies (CPC OISST, weeks centred on
Wednesday) and the real-time OMI (ROMI, NOAA PSL), each with the operational
latency in `config.predictors.large_scale.*.lag_days`.

Output is one row per calendar day `d` holding the value a forecaster could
have known on `d`: the last Niño week centred on or before `d - 7` and the ROMI
of `d - 1`. Stage 07 joins it on the issuance date, so the latency is applied
once, here, and nowhere else. The series is network-wide (the same forcing for
every station) and has no fold dimension: nothing in it is fitted.

Why ROMI and not OMI or RMM. OMI is built from 30-96 day band-passed OLR with a
centred filter, which reads the future (the same leak as ONI/ICEN, both
excluded). RMM has no NOAA-hosted text file (DESIGN_DECISIONS §3). ROMI uses
only past data and is served by PSL as plain text.

Raw downloads are cached in `data/raw/largescale/` and their SHA-256 recorded in
the manifest; a cached file is reused unless `--refresh` is given, so a Colab
re-run does not depend on NOAA being reachable.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from _common import (
    DATA_DIR,
    PROCESSED,
    atomic_write_csv,
    ensure_dirs,
    load_config,
    paths_report,
    rel_path,
    write_manifest,
)

CACHE = DATA_DIR / "raw" / "largescale"
OUT = PROCESSED / "largescale_daily.csv"
G_COLUMNS = ["nino34_anom", "nino12_anom", "romi1", "romi2", "romi_amp"]
# Sensitivity only (R4): Takahashi E/C, monthly, never in the primary G set.
EC_COLUMNS = ["e_index", "c_index"]
UA = "Mozilla/5.0 (X11; Linux x86_64) c20-2026 research pipeline"

_FLOAT = re.compile(r"-?\d+\.\d+")


# --- parsing (pure, unit-tested) --------------------------------------------

def parse_cpc_weekly(text: str) -> pd.DataFrame:
    """CPC `wksst9120.for` -> week_centre, nino12_anom, nino34_anom.

    The file is fixed width and a negative anomaly is glued to the SST before it
    (`20.6-0.1`), so whitespace splitting fails. Each data row is a date and
    eight numbers in the order Niño1+2 SST/SSTA, Niño3, Niño3.4, Niño4.
    """
    rows = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(\d{2}[A-Z]{3}\d{4})\s+(.*)$", line)
        if not m:
            continue
        values = [float(v) for v in _FLOAT.findall(m.group(2))]
        if len(values) != 8:
            continue
        rows.append({
            "week_centre": pd.to_datetime(m.group(1), format="%d%b%Y"),
            "nino12_anom": values[1],
            "nino34_anom": values[5],
        })
    return pd.DataFrame(rows, columns=["week_centre", "nino12_anom", "nino34_anom"])


def parse_romi(text: str) -> pd.DataFrame:
    """PSL ROMI text -> date, romi1, romi2, romi_amp (one row per day)."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        try:
            date = pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))
            r1, r2, amp = float(parts[4]), float(parts[5]), float(parts[6])
        except ValueError:
            continue
        rows.append({"date": date, "romi1": r1, "romi2": r2, "romi_amp": amp})
    out = pd.DataFrame(rows, columns=["date", "romi1", "romi2", "romi_amp"])
    # PSL uses large sentinels for missing days in some products.
    for col in ("romi1", "romi2", "romi_amp"):
        out.loc[out[col].abs() > 90, col] = np.nan
    return out


def parse_ec(text: str) -> pd.DataFrame:
    """IGP `ecindex_ersstv5.txt` -> month_end, e_index, c_index."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4 or not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        month_end = pd.Timestamp(int(parts[0]), int(parts[1]), 1) + pd.offsets.MonthEnd(0)
        rows.append({"month_end": month_end, "e_index": float(parts[2]),
                     "c_index": float(parts[3])})
    return pd.DataFrame(rows, columns=["month_end", *EC_COLUMNS])


def as_of_monthly(days: pd.DatetimeIndex, monthly: pd.DataFrame, lag_days: int) -> pd.DataFrame:
    """Monthly value known on each day: the last month that ended `lag_days` before it."""
    frame = pd.DataFrame({"date": pd.DatetimeIndex(days).sort_values()})
    frame["key"] = frame["date"] - pd.Timedelta(days=lag_days)
    m = monthly.sort_values("month_end").assign(ec_month=lambda x: x["month_end"])
    out = pd.merge_asof(frame, m, left_on="key", right_on="month_end", direction="backward")
    return out[["date", *EC_COLUMNS, "ec_month"]]


# --- as-of construction -----------------------------------------------------

def as_of_daily(days: pd.DatetimeIndex, nino: pd.DataFrame, romi: pd.DataFrame,
                nino_lag: int, romi_lag: int) -> pd.DataFrame:
    """Value known on each day, honouring each source's latency.

    `merge_asof(direction="backward")` picks the last observation at or before
    `d - lag`, which is the definition of "known on d". Nothing later can enter.
    """
    frame = pd.DataFrame({"date": pd.DatetimeIndex(days).sort_values()})
    frame["nino_key"] = frame["date"] - pd.Timedelta(days=nino_lag)
    frame["romi_key"] = frame["date"] - pd.Timedelta(days=romi_lag)

    # Keep the week centre as a column: it records which week each row used,
    # so the latency is auditable row by row.
    n = nino.sort_values("week_centre").assign(nino_week=lambda x: x["week_centre"])
    out = pd.merge_asof(frame, n, left_on="nino_key", right_on="week_centre",
                        direction="backward")

    # ROMI must be the exact lagged day: a stale MJO phase is a different signal,
    # so a gap stays NaN instead of carrying an older value forward.
    r = romi.rename(columns={"date": "romi_key"})
    out = out.merge(r, on="romi_key", how="left")
    return out.sort_values("date").reset_index(drop=True)[["date", *G_COLUMNS, "nino_week"]]


# --- IO -----------------------------------------------------------------------

def fetch(url: str, dest: Path, refresh: bool, timeout: int = 60) -> tuple[str, str]:
    """Return (text, sha256), downloading only when the cache is absent or stale."""
    if dest.is_file() and not refresh:
        data = dest.read_bytes()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
        except urllib.error.URLError as exc:
            if dest.is_file():
                print(f"WARNING: {url} unreachable ({exc}); using cached {dest.name}")
                data = dest.read_bytes()
            else:
                raise SystemExit(f"ERROR: cannot download {url}: {exc}") from exc
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    return data.decode("utf-8", errors="replace"), hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="re-download even if cached")
    args = ap.parse_args(argv)

    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    ls = (cfg.get("predictors") or {}).get("large_scale") or {}
    nino_cfg, romi_cfg = ls.get("nino34_weekly") or {}, ls.get("romi") or {}

    nino_text, nino_sha = fetch(nino_cfg["url"], CACHE / "wksst9120.for", args.refresh)
    nino = parse_cpc_weekly(nino_text)
    romi_sources: dict = {}
    if romi_cfg.get("url"):
        romi_text, romi_sha = fetch(romi_cfg["url"], CACHE / "romi.cpcolr.1x.txt", args.refresh)
        romi = parse_romi(romi_text)
        romi_sources = {"url": romi_cfg["url"], "sha256": romi_sha, "rows": int(len(romi))}
    else:
        romi = pd.DataFrame(columns=["date", "romi1", "romi2", "romi_amp"])
    if nino.empty:
        raise SystemExit("ERROR: no Niño rows parsed; the CPC format may have changed")

    start = pd.Timestamp((cfg.get("validation") or {}).get("train_start", "2015-01-01"))
    end = pd.Timestamp((cfg.get("data") or {}).get("coverage_declared", [None, "2024-06-30"])[1])
    days = pd.date_range(start - pd.Timedelta(days=120), end, freq="D")
    out = as_of_daily(days, nino, romi, int(nino_cfg.get("lag_days", 7)),
                      int(romi_cfg.get("lag_days", 1)))
    ec_cfg = ls.get("ec_indices") or {}
    ec_sources: dict = {}
    if ec_cfg.get("url"):
        try:
            ec_text, ec_sha = fetch(ec_cfg["url"], CACHE / "ecindex_ersstv5.txt", args.refresh)
            ec = parse_ec(ec_text)
            out = out.merge(as_of_monthly(days, ec, int(ec_cfg.get("lag_days", 10))), on="date",
                            how="left")
            ec_sources = {"url": ec_cfg["url"], "sha256": ec_sha, "rows": int(len(ec))}
        except SystemExit as exc:
            # A sensitivity input must not take the primary analysis down with it.
            print(f"WARNING: E/C indices unavailable, sensitivity skipped: {exc}")
    atomic_write_csv(out, OUT)

    span = out[out["date"] >= start]
    print(f"Niño weeks parsed: {len(nino)} ({nino['week_centre'].min().date()}.."
          f"{nino['week_centre'].max().date()})")
    print(f"ROMI days parsed : {len(romi)}")
    present = [c for c in G_COLUMNS + EC_COLUMNS if c in span.columns]
    print(f"as-of rows       : {len(out)}  missing % in study span: "
          + ", ".join(f"{c}={span[c].isna().mean() * 100:.1f}" for c in present))
    print(f"wrote {OUT}")
    write_manifest({"largescale": {
        "file": rel_path(OUT),
        "columns": G_COLUMNS,
        "lags_days": {"nino": int(nino_cfg.get("lag_days", 7)),
                      "romi": int(romi_cfg.get("lag_days", 1))},
        "sources": {"nino": {"url": nino_cfg["url"], "sha256": nino_sha, "rows": int(len(nino))},
                    "romi": romi_sources, "ec": ec_sources},
    }}, replace=("largescale",))


if __name__ == "__main__":
    main()

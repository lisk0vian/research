# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""NOAA CFSv2 2 m temperature at the five stations, as horizon-window means.

Amendment A1 of the design (METHODOLOGY.md): an open dynamical reference for the
observation-only models. ECMWF S2S needs an account the author declined, so this
reads the public NOAA CFSv2 archive on AWS (`noaa-cfs-pds`), which needs none.

What is read. For every Monday (the weekly issuance day) from the archive's start,
the 00Z cycle, members 1-4: the per-variable file `tmp2m.<m>.<date>00.daily.grb2`.
Despite its name it holds the 6-hourly instantaneous 2 m temperature for the whole
9-month run (about 1200 messages, 96 MB). Only the first 28 days are needed and
the messages are contiguous, so one HTTP range request per (date, member) of the
`.idx`-addressed bytes fetches about 9 MB instead of 96.

What is computed. Bilinear interpolation of the 1 degree grid to each station,
the mean of the four UTC valid times of each calendar day after the issue date,
then the mean of those days over each horizon window (W1 1-7, W2 8-14, W3_4
15-28), per member. The ensemble mean and spread go to `cfs_windows.csv`.

Known limits, stated rather than corrected here: the day is a UTC day, not a
local (UTC-5) day; a 1 degree cell (about 110 km) does not resolve stations
2421-4475 m high, so a large and station-specific bias is expected and removed
downstream (07d) by train-only calibration; the model drifts with lead time.

Needs `eccodes` (pip install eccodes) to decode GRIB2. Colab installs it in the
notebook's dependency cell. Per-date results are cached in
`data/raw/dynamical/`, so a rerun after a disconnect skips what it already has.

    python 06b_dynamical.py --probe     # one date, one member, prints sanity values
"""

from __future__ import annotations

import argparse
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from _common import (
    DATA_DIR,
    PROCESSED,
    atomic_write_csv,
    ensure_dirs,
    load_config,
    normalize_ubigeo,
    paths_report,
    progress,
    rel_path,
    write_manifest,
)
from _panel import fast_mode

CACHE = DATA_DIR / "raw" / "dynamical"
OUT = PROCESSED / "cfs_windows.csv"
UA = "Mozilla/5.0 (X11; Linux x86_64) c20-2026 research pipeline"
STEP_H = 6          # hours between messages
TIMES_PER_DAY = 4   # 00, 06, 12, 18 UTC
KELVIN = 273.15
MAX_BROKEN_SHARE = 0.05  # above this share of dates failing, 06b fails instead of skipping


# --- planning (pure, unit-tested) ---------------------------------------------

def issue_dates(start: str, end: str, weekday: int = 0) -> list[pd.Timestamp]:
    """Every `weekday` (Monday = 0) in [start, end]."""
    days = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    return list(days[days.dayofweek == weekday])


def file_url(base: str, date: pd.Timestamp, cycle: str, member: int, var: str) -> str:
    d = f"{date:%Y%m%d}"
    m = f"{member:02d}"
    return f"{base}/cfs.{d}/{cycle}/time_grib_{m}/{var}.{m}.{d}{cycle}.daily.grb2"


def parse_idx(text: str) -> list[tuple[int, int]]:
    """`.idx` lines (`n:offset:d=...:TMP:2 m above ground:6 hour fcst:`) -> [(hour, offset)]."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^\d+:(\d+):.*?:(\d+) hour fcst", line)
        if m:
            out.append((int(m.group(2)), int(m.group(1))))
    return out


def needed_hours(max_lead_days: int) -> list[int]:
    """Valid-time steps of days 1..max_lead_days: 00, 06, 12, 18 UTC of each day."""
    return [24 * k + 6 * j for k in range(1, max_lead_days + 1) for j in range(TIMES_PER_DAY)]


def plan_range(idx: list[tuple[int, int]], hours: list[int]) -> tuple[int, int, list[tuple[int, int, int]]]:
    """Byte range covering `hours`, and (hour, start, end) of each message inside it.

    The needed messages are contiguous in the file, so one request covers them. The end of
    the last message is the start of the next one, which is why a message after
    the last needed hour must exist.
    """
    by_hour = dict(idx)
    ordered = sorted(idx)
    positions = {h: i for i, (h, _) in enumerate(ordered)}
    missing = [h for h in hours if h not in by_hour]
    if missing:
        raise ValueError(f"idx lacks forecast hours {missing[:3]}...")
    last = positions[max(hours)]
    if last + 1 >= len(ordered):
        raise ValueError("idx has no message after the last needed hour; range end unknown")
    first_off = by_hour[min(hours)]
    end_off = ordered[last + 1][1]
    msgs = []
    for h in sorted(hours):
        i = positions[h]
        msgs.append((h, ordered[i][1] - first_off, ordered[i + 1][1] - first_off))
    return first_off, end_off - 1, msgs


def bilinear(field: np.ndarray, lats: np.ndarray, lons: np.ndarray, lat: float, lon: float) -> float:
    """Bilinear interpolation on a regular grid; `lons` may be 0-360 and wrap.

    `field` is (nlat, nlon) with `lats` and `lons` its axes in either order.
    """
    lats = np.asarray(lats, dtype="float64")
    lons = np.asarray(lons, dtype="float64")
    if lats[0] > lats[-1]:
        lats, field = lats[::-1], field[::-1]
    lon = lon % 360.0
    lons = lons % 360.0
    dlon = float(np.median(np.diff(np.sort(lons))))
    i = int(np.searchsorted(lats, lat) - 1)
    i = min(max(i, 0), len(lats) - 2)
    j0 = int(np.floor((lon - lons[0]) / dlon)) % len(lons)
    j1 = (j0 + 1) % len(lons)
    tx = ((lon - lons[j0]) % 360.0) / dlon
    ty = (lat - lats[i]) / (lats[i + 1] - lats[i])
    ty = min(max(ty, 0.0), 1.0)
    top = field[i + 1, j0] * (1 - tx) + field[i + 1, j1] * tx
    bot = field[i, j0] * (1 - tx) + field[i, j1] * tx
    return float(bot * (1 - ty) + top * ty)


def daily_from_steps(step_values: np.ndarray, max_lead_days: int) -> np.ndarray:
    """(n_steps,) in `needed_hours` order -> (max_lead_days,) daily means."""
    return step_values.reshape(max_lead_days, TIMES_PER_DAY).mean(axis=1)


def window_means(daily: pd.DataFrame, horizons: dict[str, tuple[int, int]]) -> pd.DataFrame:
    """(station, member, lead_day, T) -> per (station, member, horizon) window mean."""
    rows = []
    for h, (a, b) in horizons.items():
        sel = daily[(daily["lead_day"] >= a) & (daily["lead_day"] <= b)]
        g = sel.groupby(["station", "member"])["T_c"].agg(["mean", "count"]).reset_index()
        g["horizon"] = h
        rows.append(g.rename(columns={"mean": "F", "count": "n_days"}))
    return pd.concat(rows, ignore_index=True)


def ensemble_windows(per_member: pd.DataFrame, issue: pd.Timestamp) -> pd.DataFrame:
    """Collapse members: ensemble mean, spread, and how many members agreed to exist."""
    g = per_member.groupby(["station", "horizon"], as_index=False).agg(
        F_mean=("F", "mean"), F_sd=("F", lambda x: float(np.std(x, ddof=1)) if len(x) > 1 else np.nan),
        n_members=("F", "size"), n_days=("n_days", "min"))
    g.insert(0, "issue_date", issue)
    return g


# --- IO -----------------------------------------------------------------------

def _get(url: str, headers: dict | None = None, retries: int = 3, timeout: int = 120) -> bytes | None:
    """GET with retries; None on HTTP 404 (a date the archive does not hold)."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}: {last}")


def framed(raw: bytes, msgs: list[tuple[int, int, int]]) -> bool:
    """True when every (hour, start, end) slice is one whole GRIB message."""
    return all(raw[s:s + 4] == b"GRIB" and raw[e - 4:e] == b"7777" for _, s, e in msgs)


def split_messages(blob: bytes) -> list[bytes]:
    """Walk a GRIB2 file by the total length in each Section 0 header."""
    out, off = [], 0
    while off < len(blob):
        if blob[off:off + 4] != b"GRIB" or blob[off + 7:off + 8] != b"\x02":
            raise ValueError(f"no GRIB2 header at byte {off}")
        length = int.from_bytes(blob[off + 8:off + 16], "big")
        msg = blob[off:off + length]
        if length < 16 or len(msg) != length or msg[-4:] != b"7777":
            raise ValueError(f"truncated GRIB message at byte {off}")
        out.append(msg)
        off += length
    return out


def reframe_from_file(blob: bytes, idx: list[tuple[int, int]], hours: list[int]
                      ) -> tuple[bytes, list[tuple[int, int, int]]]:
    """The needed messages of a whole file, located without trusting idx offsets.

    The archive sometimes holds a .grb2 that was rewritten after its .idx: the
    records are the same, in the same order, but the offsets drift by a few
    hundred bytes, so every slice taken from the idx cuts mid-message (seen on
    2021-03-22). The hours still come from the idx, matched by position.
    """
    parts = split_messages(blob)
    if len(parts) != len(idx):
        raise ValueError(f"file has {len(parts)} messages, its idx lists {len(idx)}")
    by_hour = {h: p for (h, _), p in zip(sorted(idx, key=lambda r: r[1]), parts)}
    out, msgs, pos = [], [], 0
    for h in sorted(hours):
        p = by_hour[h]
        out.append(p)
        msgs.append((h, pos, pos + len(p)))
        pos += len(p)
    return b"".join(out), msgs


def fetch_member(base: str, date: pd.Timestamp, cycle: str, member: int, var: str,
                 max_lead_days: int, retries: int) -> tuple[bytes, list[tuple[int, int, int]]] | None:
    """Download the needed messages of one (date, member); None if not archived.

    One range read when the idx matches the file (the norm); the whole file,
    walked header by header, when it does not.
    """
    url = file_url(base, date, cycle, member, var)
    idx_raw = _get(url + ".idx", retries=retries)
    if idx_raw is None:
        return None
    idx = parse_idx(idx_raw.decode("utf-8", "replace"))
    hours = needed_hours(max_lead_days)
    start, end, msgs = plan_range(idx, hours)
    raw = _get(url, headers={"Range": f"bytes={start}-{end}"}, retries=retries)
    if raw is None:
        return None
    if len(raw) != end - start + 1:
        raise RuntimeError(f"short read for {url}: {len(raw)} of {end - start + 1} bytes")
    if framed(raw, msgs):
        return raw, msgs
    blob = _get(url, retries=retries)
    if blob is None:
        return None
    return reframe_from_file(blob, idx, hours)


def _eccodes():
    try:
        import eccodes
        return eccodes
    except ImportError as exc:  # pragma: no cover - environment
        raise SystemExit("ERROR: eccodes is not installed (pip install eccodes); "
                         "the notebook's dependency cell does it on Colab") from exc


def decode_stations(raw: bytes, msgs: list[tuple[int, int, int]], stations: list[dict],
                    qc_range: tuple[float, float]) -> np.ndarray:
    """(n_steps, n_stations) in degC from the GRIB2 messages of one range read.

    The CFSv2 time series are on a T126 Gaussian grid (`regular_gg`), whose
    latitudes are not evenly spaced and which has no
    `jDirectionIncrementInDegrees`. So the axes are read from the per-point
    `latitudes`/`longitudes` arrays, which eccodes computes for any grid and
    which come in the same scan order as the values.
    """
    ec = _eccodes()
    out = np.full((len(msgs), len(stations)), np.nan)
    geom = None
    for k, (_, s, e) in enumerate(msgs):
        gid = ec.codes_new_from_message(raw[s:e])
        try:
            if geom is None:
                ni, nj = int(ec.codes_get(gid, "Ni")), int(ec.codes_get(gid, "Nj"))
                plat = np.asarray(ec.codes_get_array(gid, "latitudes"), dtype="float64")
                plon = np.asarray(ec.codes_get_array(gid, "longitudes"), dtype="float64")
                lats = plat.reshape(nj, ni)[:, 0]
                lons = plon.reshape(nj, ni)[0, :]
                geom = (ni, nj, lats, lons)
            ni, nj, lats, lons = geom
            field = ec.codes_get_values(gid).reshape(nj, ni) - KELVIN
        finally:
            ec.codes_release(gid)
        for j, st in enumerate(stations):
            out[k, j] = bilinear(field, lats, lons, st["lat"], st["lon"])
    lo, hi = qc_range
    bad = (out < lo) | (out > hi)
    if bad.any():
        raise RuntimeError(f"{int(bad.sum())} station values outside [{lo}, {hi}] degC after "
                           "K -> degC; the units or the grid orientation are not what 06b assumes")
    return out


def process_date(date: pd.Timestamp, cfg: dict, stations: list[dict], members: list[int],
                 fetched: dict[int, tuple[bytes, list[tuple[int, int, int]]] | None]) -> pd.DataFrame:
    """Decode the already-downloaded members of one date to a daily station table."""
    dyn = cfg["dynamical"]
    max_lead = max(int(v[1]) for v in cfg["target"]["horizons"].values())
    rows = []
    for m in members:
        got = fetched.get(m)
        if got is None:
            continue
        steps = decode_stations(got[0], got[1], stations, tuple(dyn["qc_range_degC"]))
        for j, st in enumerate(stations):
            daily = daily_from_steps(steps[:, j], max_lead)
            for k, t in enumerate(daily, start=1):
                rows.append((date, m, st["code"], k, float(t)))
    return pd.DataFrame(rows, columns=["issue_date", "member", "station", "lead_day", "T_c"])


def cache_path(date: pd.Timestamp) -> Path:
    return CACHE / f"cfs_{date:%Y%m%d}.csv"


def station_list(cfg: dict) -> list[dict]:
    return [{"code": normalize_ubigeo(s["ubigeo"]), "lat": float(s["lat"]), "lon": float(s["lon"])}
            for s in cfg["stations"]]


def build_windows(cfg: dict, dates: list[pd.Timestamp]) -> pd.DataFrame:
    horizons = {h: (int(v[0]), int(v[1])) for h, v in cfg["target"]["horizons"].items()}
    frames = []
    for d in dates:
        p = cache_path(d)
        if not p.is_file():
            continue
        daily = pd.read_csv(p, dtype={"station": str}, parse_dates=["issue_date"])
        pm = window_means(daily, horizons)
        frames.append(ensemble_windows(pm, d))
    if not frames:
        return pd.DataFrame(columns=["issue_date", "station", "horizon", "F_mean", "F_sd",
                                     "n_members", "n_days"])
    return pd.concat(frames, ignore_index=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true",
                    help="one date, one member; print sanity values and stop")
    args = ap.parse_args(argv)

    cfg = load_config()
    dyn = cfg.get("dynamical") or {}
    if not dyn.get("enabled", False):
        print("dynamical.enabled is false; nothing to do")
        return
    ensure_dirs()
    CACHE.mkdir(parents=True, exist_ok=True)
    print(paths_report())

    stations = station_list(cfg)
    members = [int(m) for m in dyn["members"]]
    max_lead = max(int(v[1]) for v in cfg["target"]["horizons"].values())
    weekday = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
               "saturday": 5, "sunday": 6}[str(cfg["issuance"].get("weekday", "monday")).lower()]
    end = (cfg.get("data") or {}).get("coverage_declared", [None, "2024-06-30"])[1]
    dates = issue_dates(dyn["start"], end, weekday)
    if fast_mode():
        # Spread over the whole record, not the first N: the calibration in 07d
        # needs training Mondays before B1 and evaluation Mondays inside B1/B2.
        n = min(int((dyn.get("fast") or {}).get("n_dates", 40)), len(dates))
        dates = [dates[i] for i in sorted(set(np.linspace(0, len(dates) - 1, n).round().astype(int)))]
        members = [int(m) for m in (dyn.get("fast") or {}).get("members", members[:1])]
        print(f"FAST MODE: {len(dates)} dates, members {members}; numbers are not citable")
    if args.probe:
        dates, members = dates[:1], members[:1]

    base, cycle, var = dyn["bucket_url"], str(dyn["cycle"]), str(dyn["variable"])
    retries, workers = int(dyn.get("retries", 3)), int(dyn.get("workers", 8))
    todo = [d for d in dates if not cache_path(d).is_file()]
    print(f"{len(dates)} Mondays from {dates[0].date()} to {dates[-1].date()}; "
          f"{len(dates) - len(todo)} cached, {len(todo)} to download "
          f"({len(members)} members x ~9 MB each)")

    missing: list[str] = []
    unreadable: list[str] = []
    t0 = time.perf_counter()
    nbytes = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for d in todo:
            for m in members:
                futures[pool.submit(fetch_member, base, d, cycle, m, var, max_lead, retries)] = (d, m)
        got: dict[pd.Timestamp, dict] = {}
        total = len(futures)
        for done, fut in enumerate(progress(as_completed(futures), desc="06b CFSv2", unit="req",
                                            total=total, level="step"), start=1):
            # pop, not index: a finished future keeps its ~9 MB result alive for as
            # long as anything references it, and the dict would hold all of them
            # (~8 GB for a full run) until the loop ends.
            d, m = futures.pop(fut)
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001 - one broken file must not end the stage
                res = None
                print(f"WARNING {d:%Y-%m-%d} member {m}: {type(exc).__name__}: {exc}")
                unreadable.append(f"{d:%Y-%m-%d}/m{m}: {type(exc).__name__}: {exc}")
            del fut
            got.setdefault(d, {})[m] = res
            if res is not None:
                nbytes += len(res[0])
            if len(got[d]) == len(members):
                fetched = got.pop(d)
                if all(v is None for v in fetched.values()):
                    missing.append(f"{d:%Y-%m-%d}")
                    continue
                try:
                    daily = process_date(d, cfg, stations, members, fetched)
                except Exception as exc:  # noqa: BLE001
                    print(f"WARNING {d:%Y-%m-%d}: not decodable, left out: {type(exc).__name__}: {exc}")
                    unreadable.append(f"{d:%Y-%m-%d}: {type(exc).__name__}: {exc}")
                    missing.append(f"{d:%Y-%m-%d}")
                    continue
                atomic_write_csv(daily, cache_path(d))
                del fetched, res
    print(f"downloaded {nbytes / 1e6:.0f} MB in {time.perf_counter() - t0:.0f} s; "
          f"{len(missing)} dates absent or unreadable, {len(unreadable)} problem(s)")
    # A few broken archive files are a fact of the archive; many are a bug here.
    broken_dates = {u.split("/")[0].split(":")[0] for u in unreadable}
    if todo and len(broken_dates) > max(2, MAX_BROKEN_SHARE * len(todo)):
        raise SystemExit(f"ERROR: {len(broken_dates)} of {len(todo)} dates failed to download "
                         f"or decode; first problems:\n  " + "\n  ".join(unreadable[:10]))

    if args.probe:
        p = cache_path(dates[0])
        d = pd.read_csv(p, dtype={"station": str})
        print(f"\nPROBE {dates[0].date()} member {members[0]}: station day-1/7/14/28 mean 2 m T (degC)")
        for st in stations:
            v = d[d["station"] == st["code"]].set_index("lead_day")["T_c"]
            print(f"  {st['code']}  lat {st['lat']:8.4f} lon {st['lon']:9.4f}  "
                  + "  ".join(f"d{k}={v.loc[k]:6.2f}" for k in (1, 7, 14, 28)))
        print("Compare with the station climatology (Imata ~3 degC, Matucana ~15 degC); a "
              "bias of several degC is expected on a 1 degree grid.")
        return

    windows = build_windows(cfg, dates)
    atomic_write_csv(windows, OUT)
    print(f"wrote {OUT}: {len(windows)} rows, {windows['issue_date'].nunique()} dates, "
          f"members per row min {windows['n_members'].min() if len(windows) else 0}")
    write_manifest({"dynamical": {
        "file": rel_path(OUT), "source": dyn["source"], "dates": len(dates),
        "members": members, "absent_dates": missing, "unreadable": unreadable,
        "fast_mode": fast_mode(),
        "note": "6-hourly CFSv2 00Z, UTC-day means, bilinear to station; calibrated in 07d"}},
        replace=("dynamical",))


if __name__ == "__main__":
    main()

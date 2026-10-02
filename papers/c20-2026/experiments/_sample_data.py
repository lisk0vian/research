"""Synthesise a small dataset.csv so the pipeline can be run locally.

Why this exists
---------------
The daily workflow needs a step "edit locally, check against a small dataset
before pushing to Drive". Without it, the only local check is the unit tests,
which use hand-built fixtures and never exercise the CLI, the atomic writes or
the stage wiring. With a real-shaped file, `run_all.py --only 02` is runnable on
a laptop in a second.

It is not a fixture and not a sample of the real data
-----------------------------------------------------
Tests must never read `data/`, by the rule in `tests/conftest.py`; that rule
protects the real numbers. This module is the other half of that rule: a
generator the tests are *allowed* to use, producing a file with the same column
contract as `data/raw/dataset.csv` but with invented values. It also does not
slice the real dataset, because a checked-in copy of real rows goes stale and
quietly becomes the thing everyone actually tests against.

Schema is configuration, not code
---------------------------------
`config.sample_data.schema` selects the shape, because the study of record is
the multi-station SENAMHI dataset (TEMP/HR/PP, five stations) while the pipeline
on disk still consumes the Huancayo contract (TT/HR/RR/PP/FF/DD). When the
migration lands this switches by config change, not by rewriting this file.

Usage
-----
    python _sample_data.py                       # writes to data/raw/dataset.csv path
    python _sample_data.py --years 3 --seed 7
    python _sample_data.py --out /tmp/probe.csv --print
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import _common

# Column contracts. Keys are the schema names config.sample_data.schema accepts.
HUANCAYO_COLUMNS = [
    "year", "month", "day", "hour", "FECHA_CORTE", "UBIGEO",
    "TT", "HR", "RR", "PP", "FF", "DD",
]
SENAMHI_COLUMNS = [
    "ID", "ESTACION", "FECHA", "HORA", "LONGITUD", "LATITUD", "ALTITUD",
    "TEMP", "HR", "PP", "RED", "DEPARTAMENTO", "PROVINCIA", "DISTRITO",
    "UBIGEO", "FECHA_CORTE",
]


def _hourly_index(years: int, start_year: int = 2018) -> pd.DatetimeIndex:
    end = pd.Timestamp(start_year + years, 1, 1)
    return pd.date_range(pd.Timestamp(start_year, 1, 1), end, freq="h", inclusive="left")


def _seasonal_temp(hours: pd.DatetimeIndex, rng: np.random.Generator,
                   mean_c: float, amp_c: float, sd_c: float) -> np.ndarray:
    """A plausible temperature series: annual cycle + diurnal cycle + noise.

    The diurnal trough at ~05:00 and peak at ~14:00 is what V1 checks for, so a
    synthetic series that misses it would fail stage 00 for the wrong reason and
    teach the reader nothing about the code.
    """
    doy = hours.dayofyear.to_numpy(dtype="float64")
    hod = hours.hour.to_numpy(dtype="float64")
    annual = amp_c * np.sin(2 * np.pi * (doy - 80.0) / 365.25)
    # The real diurnal cycle is asymmetric: trough and peak are ~9 h apart, not
    # 12, so a single cosine cannot place both. One harmonic puts the trough at
    # 05:00, and the second skews the peak back from 17:00 to 15:00. Stage 00's
    # V1 check tests the trough (3 <= hour <= 8), which is what this reproduces.
    diurnal = (amp_c / 2.4) * (
        np.cos(2 * np.pi * (hod - 17.0) / 24.0)
        + 0.35 * np.cos(4 * np.pi * (hod - 13.0) / 24.0)
    )
    return mean_c + annual + diurnal + rng.normal(0.0, sd_c, len(hours))


def build_huancayo(years: int, seed: int) -> pd.DataFrame:
    """The IGP Huancayo contract: one station, six variables, local civil time."""
    rng = np.random.default_rng(seed)
    hours = _hourly_index(years)
    n = len(hours)
    tt = _seasonal_temp(hours, rng, mean_c=10.0, amp_c=5.0, sd_c=1.4)
    # Precipitation is a burst process, not a normal draw: a handful of hours
    # carry the year's rain and most carry none. That shape is what stage 01's
    # PP_tendency and rain-sum features are meant to see.
    wet = rng.random(n) < 0.055
    rr = np.where(wet, rng.gamma(1.6, 1.4, n), 0.0)
    return pd.DataFrame({
        "year": hours.year.to_numpy(),
        "month": hours.month.to_numpy(),
        "day": hours.day.to_numpy(),
        "hour": hours.hour.to_numpy(),
        "FECHA_CORTE": f"{hours[-1].year}{hours[-1].month:02d}{hours[-1].day:02d}",
        "UBIGEO": "120904",
        "TT": np.round(tt, 1),
        "HR": np.clip(np.round(78 - 1.6 * (tt - 10) + rng.normal(0, 6, n), 1), 0, 100),
        "RR": np.round(rr, 1),
        "PP": np.round(1010 + rng.normal(0, 0.7, n), 1),
        "FF": np.round(np.clip(rng.gamma(3.0, 1.6, n), 0, 25), 1),
        "DD": np.round(rng.uniform(0, 360, n), 0),
    })


def build_senamhi(years: int, seed: int) -> pd.DataFrame:
    """The SENAMHI GBON contract, five stations over a 2054 m altitude range."""
    rng = np.random.default_rng(seed)
    hours = _hourly_index(years)
    stations = [
        # name, ubigeo, lat, lon, alt, mean_c, RED
        ("MATUCANA", "150701", -11.8391, -76.3780, 2421, 15.3, "RBON"),
        ("SAN_JOSE_DE_UZUNA", "040114", -16.5810, -71.3284, 3269, 10.3, "GBON"),
        ("CANDARAVE", "230201", -17.2680, -70.2541, 3410, 9.8, "RBON"),
        ("CARANIA", "151007", -12.3444, -75.8722, 3840, 8.4, "GBON"),
        ("IMATA", "040514", -15.8427, -71.0906, 4475, 3.0, "GBON"),
    ]
    frames = []
    for i, (name, ubi, lat, lon, alt, mean_c, red) in enumerate(stations):
        temp = _seasonal_temp(hours, rng, mean_c=mean_c, amp_c=5.0, sd_c=1.6)
        wet = rng.random(len(hours)) < 0.05
        frames.append(pd.DataFrame({
            "ID": np.arange(len(hours)),
            "ESTACION": name,
            # The real file writes YYYYMMDD / HHMMSS as integers; keeping that
            # shape means stage 00's date parsing is exercised, not bypassed.
            "FECHA": hours.strftime("%Y%m%d").astype(int),
            "HORA": hours.strftime("%H%M%S").astype(int),
            "LONGITUD": lon,
            "LATITUD": lat,
            "ALTITUD": alt,
            "TEMP": np.round(temp, 1),
            "HR": np.clip(np.round(78 - 1.6 * (temp - 10) + rng.normal(0, 6, len(hours)), 1), 0, 100),
            "PP": np.round(np.where(wet, rng.gamma(1.6, 1.4, len(hours)), 0.0), 1),
            "RED": red,
            "DEPARTAMENTO": ["Lima", "Arequipa", "Tacna", "Lima", "Arequipa"][i],
            "PROVINCIA": ["Huarochiri", "Arequipa", "Candarave", "Yauyos", "Caylloma"][i],
            "DISTRITO": name.lower(),
            "UBIGEO": ubi,
            "FECHA_CORTE": int(hours[-1].strftime("%Y%m%d")),
        }))
    return pd.concat(frames, ignore_index=True)


BUILDERS = {"huancayo": build_huancayo, "senamhi": build_senamhi}


def build(schema: str = "huancayo", years: int = 2, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic dataset with the named schema."""
    if schema not in BUILDERS:
        raise SystemExit(
            f"ERROR: unknown schema {schema!r}; known: {', '.join(sorted(BUILDERS))}"
        )
    return BUILDERS[schema](years, seed)


def main() -> int:
    cfg = _common.load_config()
    sample_cfg = cfg.get("sample_data", {})
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--schema", default=sample_cfg.get("schema", "huancayo"),
                    choices=sorted(BUILDERS))
    ap.add_argument("--years", type=int, default=int(sample_cfg.get("years", 2)))
    ap.add_argument("--seed", type=int, default=int(sample_cfg.get("seed", 42)))
    ap.add_argument("--out", default=None,
                    help="output path; defaults to $DATA_DIR/raw/dataset.csv")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="summarise without writing")
    args = ap.parse_args()

    df = build(args.schema, args.years, args.seed)

    if args.show:
        print(f"schema={args.schema} rows={len(df)} cols={len(df.columns)}")
        print(f"columns: {', '.join(df.columns)}")
        numeric = df.select_dtypes("number")
        if not numeric.empty:
            print("\nnumeric summary:")
            print(numeric.describe().T.iloc[:, :4].to_string())
        print("\nNOT written (--print).")
        return 0

    out = Path(args.out) if args.out else _common.RAW_CSV
    _common.atomic_write_csv(df, out)
    print(f"wrote {out} ({len(df)} rows x {len(df.columns)} cols, "
          f"schema={args.schema}, seed={args.seed}, years={args.years})")
    print(f"NOTE: synthetic values. Never cite anything derived from this file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
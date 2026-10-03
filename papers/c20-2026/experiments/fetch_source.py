"""Fetch the raw source dataset and record its provenance.

Run this before stage 00. It is deliberately not named `NN_*`: fetching is a
setup step, not a pipeline stage, so `run_all.py` never calls it implicitly.

Why this exists instead of "download the CSV by hand": the portal hands out a
resource URL that can rotate between one download and the next, and a paper
whose raw data has no recorded origin cannot be reproduced by a reader or by
ourselves later. This writes `data/SOURCE.json` next to the data holding the
package id, the exact resource URL, a sha256, the byte count, the download
timestamp, and a station inventory read out of the file itself.

The inventory is derived, never hardcoded. Hardcoding five station codes is how
a provenance record starts disagreeing with the bytes it claims to describe.

The bulk CSV lands in `data/raw/`, which is gitignored. `SOURCE.json` sits one
level up in `data/`, which is tracked. The provenance is small and reviewable;
the data is not. Both decisions are in `.gitignore` and are not ours to change.

Usage
-----
    python fetch_source.py            # download if missing, verify if present
    python fetch_source.py --force    # re-download even if a file is present
    python fetch_source.py --check    # verify the local file, no network at all
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from _common import DATA_DIR, ensure_dirs, load_config, paths_report, write_manifest

CHUNK = 1 << 20
SCHEMA_VERSION = 1

# Column families the pipeline needs. A resource missing any of these is the
# wrong file: the portal serves several SENAMHI packages and only one carries
# the hourly temperature series this paper uses. Failing here is much cheaper
# than failing in 03 with a KeyError on a column nobody remembered.
REQUIRED_FAMILIES = {
    "timestamp": ("fecha", "date", "datetime", "fec", "corte"),
    "station": ("ubigeo", "codigo", "station", "estacion", "station_code"),
    "temperature": ("temp", "tt", "temperature", "tmedia", "temp_media"),
}


class FetchError(RuntimeError):
    """Anything that makes the fetched file unusable as the source."""


def source_json_path() -> Path:
    return DATA_DIR / "SOURCE.json"


def resolve_resource(cfg: dict, timeout: int) -> dict:
    """Ask the catalogue which file backs this dataset and return that resource.

    The resource URL is discovered rather than hardcoded. The portal has
    republished these packages under new URLs before, and a pinned link is
    exactly the kind of thing that rots between submission and camera-ready.
    """
    src = cfg.get("source", {})
    api = (src.get("api") or "https://www.datos.gob.pe/api/3/action").rstrip("/")
    dataset_id = src.get("dataset_id")
    if not dataset_id:
        raise FetchError("config.source.dataset_id is missing")

    url = f"{api}/package_show?id={dataset_id}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise FetchError(
            f"cannot reach the catalogue at {url}: {exc}. "
            "Check the network, or place the CSV in data/raw/ by hand and run "
            "with --check to record its provenance."
        ) from exc

    if not payload.get("success"):
        raise FetchError(f"catalogue returned success=false for {dataset_id}")
    pkg = payload.get("result", {})
    resources = [r for r in pkg.get("resources", []) if r.get("url")]
    if not resources:
        raise FetchError(f"dataset {dataset_id} exposes no downloadable resource")

    for key, attr in (("prefer_name", "name"), ("prefer_format", "format")):
        want = (src.get(key) or "").strip().lower()
        if not want:
            continue
        for r in resources:
            if want == (r.get(attr) or "").strip().lower():
                return {"package": pkg, "resource": r}

    csvs = [r for r in resources
            if (r.get("format") or "").strip().lower() in {"csv", "text/csv", "text/plain"}]
    if len(csvs) == 1:
        return {"package": pkg, "resource": csvs[0]}
    raise FetchError(
        f"{len(resources)} resources on {dataset_id} and config.source does not "
        f"say which one: set source.prefer_name or source.prefer_format. "
        f"Available: {[r.get('name') for r in resources]}"
    )


def _stream(url: str, fh, timeout: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            fh.write(block)
            digest.update(block)
            total += len(block)
    return digest.hexdigest(), total


def download(url: str, dest: Path, timeout: int) -> tuple[str, int]:
    """Stream `url` into `dest` atomically, returning (sha256, bytes).

    The download lands on a temporary name first. An interrupted transfer would
    otherwise leave a truncated CSV that a later run happily verifies against a
    hash of itself and calls good.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with tmp.open("wb") as fh:
            digest, total = _stream(url, fh, timeout)
    except urllib.error.URLError as exc:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"download failed from {url}: {exc}") from exc
    if total == 0:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"{url} returned zero bytes")
    tmp.replace(dest)
    return digest, total


def sha256_of(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            digest.update(block)
            total += len(block)
    return digest.hexdigest(), total


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        try:
            return next(csv.reader(fh))
        except StopIteration:
            raise FetchError(f"{path} is empty") from None


def check_families(columns: list[str]) -> dict[str, str]:
    """Map each required column family onto the column actually found.

    Matching is by tier, not exact equality: exact first, then prefix, then
    substring, taking the shortest candidate at each tier. Equality alone is not
    enough because the real columns are compound — SENAMHI's date column is
    `FECHA_CORTE`, which is neither `fecha` nor `corte` but both at once. Shortest
    wins within a tier so `TEMP` is not stolen by `TEMP_MAX_CUMULADO`.
    """
    lowered = {c.strip().lower(): c for c in columns}
    found: dict[str, str] = {}
    for family, candidates in REQUIRED_FAMILIES.items():
        hit = None
        for tier in (lambda c, k: c == k,
                     lambda c, k: c.startswith(k),
                     lambda c, k: k in c):
            hits = [(c, lowered[c]) for c in lowered for k in candidates if tier(c, k)]
            if hits:
                hit = min(hits, key=lambda t: (len(t[0]), t[0]))[1]
                break
        if hit is not None:
            found[family] = hit
    missing = sorted(set(REQUIRED_FAMILIES) - set(found))
    if missing:
        raise FetchError(
            f"the downloaded file is missing column families {missing}; "
            f"columns present: {columns}"
        )
    return found


def station_inventory(path: Path, station_col: str, time_col: str) -> list[dict]:
    """Per-station row counts and date coverage, read from the file.

    `ubigeo` is reported raw and zero-padded to six digits because the portal
    serves that column as a float: codes below 100000 arrive as `40514.0`, and
    pandas reads the whole column as float64, so the leading zero is gone before
    anyone can notice. Recording both values makes the padding rule visible in
    the provenance instead of buried in the split step where it cannot be seen.
    """
    import pandas as pd

    frame = pd.read_csv(
        path,
        usecols=lambda c: c.strip() in {station_col, time_col},
        dtype=str,
    )
    out: list[dict] = []
    for raw, group in frame.groupby(frame[station_col].astype(str), sort=True):
        code = raw.strip()
        padded = code.split(".")[0].zfill(6)
        entry: dict = {
            "ubigeo_raw": code,
            "ubigeo": padded,
            "rows": int(len(group)),
            "needs_padding": padded != code,
        }
        stamps = pd.to_datetime(group[time_col], errors="coerce", format="mixed")
        if stamps.notna().any():
            entry["first"] = str(stamps.min().date())
            entry["last"] = str(stamps.max().date())
        out.append(entry)
    return out


def build_source_json(pkg: dict, resource: dict, local: Path, digest: str,
                      total: int, columns: list[str], stations: list[dict],
                      cfg: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalogue": {
            "dataset_id": pkg.get("id"),
            "name": pkg.get("name"),
            "title": pkg.get("title"),
            "license_title": pkg.get("license_title"),
            "license_id": pkg.get("license_id"),
            "metadata_modified": pkg.get("metadata_modified"),
            "organisation": (pkg.get("organization") or {}).get("title"),
        },
        "resource": {
            "name": resource.get("name"),
            "format": resource.get("format"),
            "url": resource.get("url"),
            "portal_last_modified": resource.get("last_modified"),
        },
        "local": {
            "path": f"data/raw/{local.name}",
            "bytes": total,
            "sha256": digest,
        },
        "declared": {
            "provider": cfg.get("source", {}).get("provider"),
            "declared_stations": cfg.get("station", {}).get("n_stations"),
            "declared_coverage": cfg.get("data", {}).get("coverage_declared"),
        },
        "columns": columns,
        "stations": stations,
        "notes": [
            "ubigeo is stored padded to six digits; the portal serves the raw "
            "column as float, so codes below 100000 lose their leading zero.",
            "Row counts and date coverage are read from the file, not declared. "
            "Compare them against 'declared' above: a mismatch is a finding, "
            "not a formatting detail.",
        ],
    }


def write_source_json(payload: dict) -> Path:
    path = source_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def read_source_json() -> dict | None:
    path = source_json_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("[warn] SOURCE.json is not valid JSON; it will be rewritten")
        return None


def compare(recorded: dict | None, digest: str) -> str:
    """'match', 'differ' or 'unrecorded'."""
    if not recorded:
        return "unrecorded"
    was = recorded.get("local", {}).get("sha256")
    if was is None:
        return "unrecorded"
    return "match" if was == digest else "differ"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="verify the local file against SOURCE.json, no network")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if the file is already present")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args(argv)

    cfg = load_config()
    src = cfg.get("source", {})
    filename = src.get("file", "dataset.csv")
    dest = DATA_DIR / "raw" / filename
    ensure_dirs()
    print(paths_report())
    print(f"source: dataset_id={src.get('dataset_id')} -> {dest}")

    recorded = read_source_json()

    if args.check:
        if not dest.is_file():
            raise FetchError(f"{dest} is not there; run without --check to fetch it")
        digest, total = sha256_of(dest)
        state = compare(recorded, digest)
        print(f"[check] {dest.name} sha256={digest[:16]} bytes={total:,} "
              f"provenance={state}")
        if state == "differ":
            print("[warn] the file on disk does not match SOURCE.json", file=sys.stderr)
            return 1
        return 0

    if dest.is_file() and not args.force:
        digest, total = sha256_of(dest)
        state = compare(recorded, digest)
        if state == "match":
            print(f"[skip] {dest.name} present, sha256 matches SOURCE.json")
            return 0
        reason = ("no provenance recorded yet" if state == "unrecorded"
                  else "sha256 differs from SOURCE.json")
        print(f"[info] {dest.name} present but {reason}; re-fetching")

    found = resolve_resource(cfg, args.timeout)
    pkg, resource = found["package"], found["resource"]
    url = resource["url"]
    print(f"fetching {resource.get('name') or url}")
    digest, total = download(url, dest, args.timeout)
    print(f"[ok] {total:,} bytes sha256={digest[:16]}")

    columns = read_header(dest)
    families = check_families(columns)
    stations = station_inventory(dest, families["station"], families["timestamp"])
    if not stations:
        raise FetchError("the file parses but contains no station rows")

    for s in stations:
        span = f"{s.get('first', '?')}..{s.get('last', '?')}"
        flag = "  <- leading zero recovered" if s["needs_padding"] else ""
        print(f"  {s['ubigeo']}  {s['rows']:>9,} rows  {span}{flag}")
    print(f"  {len(stations)} station(s); "
          f"config declares {cfg.get('station', {}).get('n_stations', '?')}")

    payload = build_source_json(pkg, resource, dest, digest, total, columns,
                                stations, cfg)
    write_source_json(payload)
    print(f"[ok] provenance -> {source_json_path()}")
    write_manifest({
        "source": {
            "dataset_id": pkg.get("id"),
            "local": payload["local"],
            "n_stations": len(stations),
            "retrieved_at": payload["retrieved_at"],
        }
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

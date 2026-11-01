# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Fetch the raw inputs into DATA_DIR/raw, resuming and verifying SHA-256.

Runs in Colab's setup cell (cell 2), before the pipeline: DATA_DIR is the
mounted Drive, so the files land there once and later sessions reuse them. The
registry is `_schema.DATASETS` (entries with `download: true`). A `.sha256`
sidecar next to each file makes later sessions a hash check, not a download.

    python _download_inputs.py          # fetch what is missing
    python _download_inputs.py --check  # verify only, never download
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from _schema import DATASETS

RAW = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[1] / "data")) / "raw"
CACHE = RAW / ".cache"
CHUNK = 1 << 20


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, expected: str | None) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    pos = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={pos}-"} if pos else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        if pos and resp.status != 206:  # server ignored Range: start over
            pos = 0
            part.unlink(missing_ok=True)
        total = int(resp.headers.get("Content-Length") or 0) + pos
        step = max(total // 20, 1)
        done, next_mark = pos, pos + step
        with part.open("ab" if pos else "wb") as fh:
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total and done >= next_mark:
                    print(f"  {dest.name}: {100 * done // total}% "
                          f"({done / 1e6:.0f}/{total / 1e6:.0f} MB)")
                    next_mark += step
    got = sha256(part)
    if expected and got != expected:
        part.unlink(missing_ok=True)
        raise SystemExit(f"{dest.name}: sha256 mismatch: got {got}, expected {expected}")
    os.replace(part, dest)
    return got


def _extract_7z(archive: Path, member: str, dest: Path) -> None:
    try:
        import py7zr
    except ImportError:
        raise SystemExit("py7zr is required to extract the SINADEF 7z; add it to "
                         "colab.yaml pip (it is installed by cell 2)") from None
    with tempfile.TemporaryDirectory(dir=archive.parent) as td:
        with py7zr.SevenZipFile(archive) as z:
            z.extract(path=td, targets=[member])
        os.replace(Path(td) / member, dest)


def ensure(entry: dict, force: bool = False) -> None:
    dest = RAW / entry["local_file"]
    side = dest.with_name(dest.name + ".sha256")
    want = entry.get("sha256")
    if dest.exists() and want and side.exists() and side.read_text().strip() == want and not force:
        print(f"[ok] {dest.name}")
        return
    if dest.exists() and want and not force:
        got = sha256(dest)
        if got == want:
            side.write_text(got + "\n")
            print(f"[ok] {dest.name} (verified)")
            return
    if dest.exists() and not want and side.exists() and not force:
        # no registered hash yet: keep the first download, its sidecar records the hash
        print(f"[ok] {dest.name} (unregistered hash {side.read_text().strip()[:12]})")
        return
    if entry.get("archive_member"):
        CACHE.mkdir(parents=True, exist_ok=True)
        archive = CACHE / entry["archive_member"].replace("/", "_")
        _download(entry.get("archive_url") or entry["file_url"], archive,
                  entry.get("archive_sha256"))
        _extract_7z(archive, entry["archive_member"], dest)
        archive.unlink(missing_ok=True)
        got = sha256(dest)
        if want and got != want:
            dest.unlink(missing_ok=True)
            raise SystemExit(f"{dest.name}: extracted sha256 mismatch: {got}")
        side.write_text(got + "\n")
    else:
        got = _download(entry.get("url") or entry["file_url"], dest, want)
        side.write_text(got + "\n")
    print(f"[ok] {dest.name} (downloaded)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify only; never download")
    ap.add_argument("--force", action="store_true", help="re-download even if current")
    args = ap.parse_args()

    todo = {k: v for k, v in DATASETS.items() if v.get("download")}
    if not todo:
        print("no downloadable datasets registered")
        return 0
    broken = [k for k, v in todo.items() if not (v.get("url") or v.get("file_url"))]
    if broken:
        raise SystemExit(f"registry without url: {', '.join(broken)}")

    missing = []
    for index, entry in enumerate(todo.values(), start=1):
        dest = RAW / entry["local_file"]
        print("#PROG " + json.dumps({"level": "download", "n": index,
                                     "total": len(todo), "desc": dest.name}), flush=True)
        if args.check:
            ok = dest.exists() and (
                not entry.get("sha256") or sha256(dest) == entry["sha256"])
            print(("[ok] " if ok else "[missing] ") + dest.name)
            if not ok:
                missing.append(dest.name)
            continue
        ensure(entry, args.force)

    if missing:
        print("missing: " + ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 07: read SINADEF (O1), build the death-level model frame.

Reads the 504 MB daily CSV in chunks (only the plan's columns), filters
2022-2025, maps the RENIEC code to the INEI UBIGEO by district names, and
writes the compact parquet frames plus the completeness table. The
`sinadef_accessed.json` marker records the exact time and the file hash; plan
v7 already carries `sinadef_outcome_data_accessed: true`.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _outcome import completeness, model_frame, read_deaths, resolve_ubigeo  # noqa: E402
from _paths import DATA_DIR, OUTPUTS, RUTA_CENSO  # noqa: E402
from _schema import DATASETS  # noqa: E402

RESULTS_VERSION = 3  # v3: 2020-2025 saved for the period sensitivity; resolved_by_name flag; excluded places dropped
SINADEF = DATA_DIR / "raw" / DATASETS["sinadef"]["local_file"]
IN3 = OUTPUTS / "03_access_travel_time"
OUT = OUTPUTS / "07_outcome_sinadef"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prog(level: str, n: int, total, desc: str) -> None:
    print("#PROG " + json.dumps({"level": level, "n": n, "total": total,
                                 "desc": desc}), flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()

    access = pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str})
    census = pd.read_csv(RUTA_CENSO, dtype={"ubigeo": str})
    total_rows = int(DATASETS["sinadef"].get("rows") or 0)

    prog("hash", 0, 1, "sha256 del CSV")
    digest = sha256(SINADEF)
    prog("hash", 1, 1, "sha256 del CSV")

    deaths, counts = read_deaths(SINADEF, years=(2020, 2025), total_rows=total_rows,
                                 progress=lambda n, t: prog("sinadef", n, t, "leyendo TB_SINADEF"))
    resolved, by_name, stats = resolve_ubigeo(deaths, census)
    deaths["ubigeo"] = resolved
    deaths["resolved_by_name"] = by_name
    counts["rows_all_periods"] = int(len(deaths))
    counts.update(stats)
    main_deaths = deaths[deaths["year"] >= 2022].reset_index(drop=True)
    counts["rows_in_period"] = int(len(main_deaths))

    frame = model_frame(main_deaths, access, census)
    comp = completeness(main_deaths, census)

    deaths.to_parquet(OUT / "deaths_all.parquet", index=False)
    main_deaths.to_parquet(OUT / "deaths.parquet", index=False)
    frame.to_parquet(OUT / "model_frame.parquet", index=False)
    comp.to_csv(OUT / "completeness.csv", index=False)

    marker = {
        "sinadef_outcome_data_accessed": True,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "file": SINADEF.name,
        "sha256": digest,
        "rows": counts["rows"],
        "rows_in_period": counts["rows_in_period"],
        "counts": counts,
        "model_rows": int(len(frame)),
        "period": [2022, 2025],
    }
    (OUT / "sinadef_accessed.json").write_text(json.dumps(marker, indent=2),
                                               encoding="utf-8")
    if counts["rows_in_period"] == 0 or len(frame) == 0:
        raise SystemExit("no deaths in the period; check the SINADEF file")
    print(json.dumps({k: marker[k] for k in ("rows_in_period", "model_rows")}, indent=2))
    print("Stage 07 done.")
    return 0


def synthetic() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ubigeo": ["010101"], "outside": [1]}).to_parquet(
        OUT / "deaths.parquet", index=False)
    pd.DataFrame({"ubigeo": ["010101"], "outside": [1]}).to_parquet(
        OUT / "model_frame.parquet", index=False)
    (OUT / "sinadef_accessed.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    print("smoke: synthetic outcome frame")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

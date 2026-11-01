# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Generate the machine-readable data dictionary in data/dictionary/.

    python _build_dictionary.py            # write the files
    python _build_dictionary.py --check    # exit 1 if they do not match _schema.py

Files (all UTF-8, meant to be read by people and by AI agents):

    renipress.yaml          the SUSALUD facility table: provenance, columns, value counts
    census2025.yaml         the INEI district table
    derived_variables.yaml  variables the pipeline creates, with their formulas
    columns.csv             one flat row per column of the three files above

The meaning of every variable lives in `_schema.py`. When the raw files are in
data/raw/ the YAML also carries a profile (non-missing share, distinct values,
value counts, ranges); without them the schema part is still written and the
profile is left as it was.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

import _schema as schema
from _paths import BASE, CENSUS_FILE, RENIPRESS_FILE

OUT_DIR = BASE / "data" / "dictionary"
RAW_DIR = BASE / "data" / "raw"
MAX_VALUES = 30                       # list value counts only for low-cardinality columns
NO_EXAMPLES = {"contact", "media"}   # never print example values of contact or photo columns


def _dump(data) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)


def _profile_renipress(path: Path) -> dict:
    df = pd.read_csv(path, encoding="utf-8-sig", sep=";", engine="python", on_bad_lines="skip", dtype=str)
    profile = {}
    for col in schema.RENIPRESS_COLUMNS:
        s = df[col["original"]].dropna().astype(str).str.strip()
        s = s[s != ""]
        entry = {"non_missing_pct": round(len(s) / len(df) * 100, 1), "n_distinct": int(s.nunique())}
        if s.nunique() <= MAX_VALUES:
            entry["value_counts"] = {str(k): int(v) for k, v in s.value_counts().items()}
        elif col["role"] not in NO_EXAMPLES:
            entry["examples"] = [str(x)[:60] for x in s.drop_duplicates().head(3)]
        profile[col["name"]] = entry
    return {"rows": len(df), "columns": profile}


def _profile_census(path: Path) -> dict:
    df = pd.read_csv(path, encoding="utf-8", dtype={"ubigeo": str})
    profile = {}
    for col in schema.CENSUS_COLUMNS:
        s = df[col["name"]]
        entry = {"non_missing_pct": float(round(s.notna().mean() * 100, 1)), "n_distinct": int(s.nunique())}
        if col["dtype"] == "int":
            entry.update(min=int(s.min()), median=float(s.median()), max=int(s.max()), total=int(s.sum()))
        elif col["dtype"] == "bool":
            entry["n_true"] = int(s.sum())
        profile[col["name"]] = entry
    return {"rows": len(df), "columns": profile}


def _without_profile(doc: dict) -> dict:
    """The schema part of a YAML document: the data profile depends on data/raw/."""
    doc = dict(doc)
    if "columns" in doc:
        doc["columns"] = [{k: v for k, v in c.items() if k != "profile"} for c in doc["columns"]]
    return doc


def _dataset_block(key: str) -> dict:
    meta = dict(schema.DATASETS[key])
    meta["raw_path"] = f"data/raw/{meta.pop('local_file')}"
    return {k: v for k, v in meta.items() if v is not None}


def _column_rows(columns: list[dict], profile: dict | None) -> list[dict]:
    rows = []
    for col in columns:
        row = {"name": col["name"], "original_name": col["original"], "dtype": col["dtype"],
               "role": col["role"], "description": col["description"], "notes": col["notes"]}
        if profile and col["name"] in profile["columns"]:
            row["profile"] = profile["columns"][col["name"]]
        rows.append(row)
    return rows


def build() -> dict[str, str]:
    renipress_path = RAW_DIR / RENIPRESS_FILE
    census_path = RAW_DIR / CENSUS_FILE
    ren_profile = _profile_renipress(renipress_path) if renipress_path.is_file() else None
    cen_profile = _profile_census(census_path) if census_path.is_file() else None

    renipress = {
        "dataset": "renipress",
        **_dataset_block("renipress"),
        "key": "ubigeo (district) and facility_code (facility)",
        "category_to_care_level": {
            **{k: v for k, v in schema.CARE_LEVEL_MAP.items()},
            schema.UNCATEGORIZED: 0,
        },
        "care_level_meaning": {
            "0": "no category: laboratories, imaging, dialysis, ambulances, doctors' offices, a few facilities pending categorisation",
            "1-4": "primary care (I-1 to I-4)", "5-6": "secondary care (II-1, II-E, II-2)",
            "7-8": "tertiary care (III-1, III-E, III-2)",
        },
        "columns": _column_rows(schema.RENIPRESS_COLUMNS, ren_profile),
    }
    census = {
        "dataset": "census2025",
        **_dataset_block("census2025"),
        "key": "ubigeo",
        "join": "census.ubigeo = renipress.ubigeo (six-digit text). In the October 2026 edition 1 district with active facilities has no census row.",
        "columns": _column_rows(schema.CENSUS_COLUMNS, cen_profile),
    }
    derived = {
        "dataset": "derived_variables",
        "description": "Variables created by the pipeline. stage 'etl' columns exist in df_activos/df_validas after _etl.py; the others are added by the named stage.",
        "variables": schema.DERIVED_COLUMNS,
    }

    flat = []
    for ds, cols in (("renipress", schema.RENIPRESS_COLUMNS), ("census2025", schema.CENSUS_COLUMNS)):
        for c in cols:
            flat.append({"dataset": ds, "name": c["name"], "original_name": c["original"], "dtype": c["dtype"],
                         "role": c["role"], "stage": "raw", "description": c["description"], "notes": c["notes"],
                         "formula": ""})
    for c in schema.DERIVED_COLUMNS:
        flat.append({"dataset": "derived", "name": c["name"], "original_name": "", "dtype": c["dtype"], "role": "derived",
                     "stage": c["stage"], "description": c["description"], "notes": c.get("notes", ""),
                     "formula": c["formula"]})
    csv_text = pd.DataFrame(flat).to_csv(index=False, lineterminator="\n")
    return {"renipress.yaml": _dump(renipress), "census2025.yaml": _dump(census),
            "derived_variables.yaml": _dump(derived), "columns.csv": csv_text}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the files differ from the schema")
    args = ap.parse_args()
    files = build()
    if args.check:
        # Only the schema part is comparable on a machine without data/raw/.
        stale = []
        for name, text in files.items():
            path = OUT_DIR / name
            if not path.is_file():
                stale.append(name)
            elif name == "columns.csv" and path.read_text(encoding="utf-8") != text:
                stale.append(name)
            elif name.endswith(".yaml"):
                old, new = (yaml.safe_load(x) for x in (path.read_text(encoding="utf-8"), text))
                if _without_profile(old) != _without_profile(new):
                    stale.append(name)
        if stale:
            print("stale dictionary files:", ", ".join(stale), "-> run: python _build_dictionary.py")
            return 1
        print("data dictionary is up to date")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT_DIR / name).write_text(text, encoding="utf-8", newline="\n")
        print("wrote", OUT_DIR / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())

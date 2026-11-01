# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Turn the two INEI census-2025 district workbooks into one clean CSV.

The workbooks come from the portal's "Cuadros interactivos" (level Distrital):
population by broad age group and population aged 5+ by disability condition.
Both carry title rows, a two-row header, a national total row and footnotes, so
the pipeline never reads them directly. This script is the only place that does.

    python census2025_prepare.py --age <edad.xlsx> --disability <discap.xlsx> \
        --out data/raw/censo-2025-distrital.csv

It fails loudly if the parsed districts do not add up to the national row of each
workbook, so a changed portal layout cannot slip through as plausible numbers.
"""

from __future__ import annotations

import argparse
import re
import warnings
from pathlib import Path

import pandas as pd

from _schema import CENSUS_REQUIRED

AGE_NAMES = ["ubigeo", "department", "province", "district",
             "population_total", "pop_0_14", "pop_15_59", "pop_60_plus"]
DISABILITY_NAMES = ["ubigeo", "department", "province", "district",
                    "pop5_total", "pop5_with_disability", "pop5_without_disability"]
_FOOTNOTE = re.compile(r"\s*[\d¹²³]+/\s*$")
_BOUNDARY_NOTE = re.compile(r"\b3/\s*$")


def _read_table(path: Path, names: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = pd.read_excel(path, header=None, dtype=str)
    national = raw[raw[1].astype(str).str.startswith("Per")].iloc[0]
    body = raw[raw[0].astype(str).str.fullmatch(r"\d+")].iloc[:, 1:1 + len(names)].copy()
    body.columns = names
    for col in names[4:]:
        body[col] = pd.to_numeric(body[col].str.replace(r"\s", "", regex=True), errors="raise").astype("int64")
    body["ubigeo"] = body["ubigeo"].str.strip().str.zfill(6)
    return body.reset_index(drop=True), national


def _clean_name(series: pd.Series) -> pd.Series:
    return series.str.replace(_FOOTNOTE, "", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()


def convert(age_xlsx: Path, disability_xlsx: Path) -> pd.DataFrame:
    age, age_total = _read_table(Path(age_xlsx), AGE_NAMES)
    dis, dis_total = _read_table(Path(disability_xlsx), DISABILITY_NAMES)

    assert age["ubigeo"].is_unique and dis["ubigeo"].is_unique, "duplicated UBIGEO in a workbook"
    assert set(age["ubigeo"]) == set(dis["ubigeo"]), "the two workbooks cover different districts"
    assert age["population_total"].sum() == int(age_total[5]), "districts do not add up to the national total"
    assert age["pop_60_plus"].sum() == int(age_total[8]), "age 60+ does not add up to the national row"
    assert dis["pop5_with_disability"].sum() == int(dis_total[6]), "disability does not add up to the national row"
    assert (age["pop_0_14"] + age["pop_15_59"] + age["pop_60_plus"] == age["population_total"]).all(), \
        "age groups do not add up to the district total"
    assert (dis["pop5_with_disability"] + dis["pop5_without_disability"] == dis["pop5_total"]).all(), \
        "disability groups do not add up to the 5+ total"

    merged = age.merge(dis[["ubigeo", "pop5_total", "pop5_with_disability", "pop5_without_disability"]],
                       on="ubigeo", how="inner", validate="one_to_one")
    merged["boundary_undefined"] = merged["district"].str.contains(_BOUNDARY_NOTE)
    for col in ("department", "province", "district"):
        merged[col] = _clean_name(merged[col])
    merged = merged[CENSUS_REQUIRED]
    assert list(merged.columns) == CENSUS_REQUIRED
    return merged.sort_values("ubigeo").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--age", required=True, type=Path, help="workbook: population by grandes grupos de edad")
    ap.add_argument("--disability", required=True, type=Path, help="workbook: discapacidad, 5 años y más")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    df = convert(args.age, args.disability)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, encoding="utf-8")
    print(f"wrote {args.out}: {len(df)} districts, {int(df['population_total'].sum()):,} people, "
          f"{int(df['boundary_undefined'].sum())} with undefined boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Export human-readable extracts of the INEI population input.

The canonical input is data/external/population.xlsx (a binary workbook, kept
byte for byte because the analysis plan checks its SHA-256). This script writes
plain-text extracts of it into outputs/derived/ so that the numbers can be read
without opening Excel. The pipeline itself always reads the workbook; the
extracts are documentation, not an input.

Usage (from experiments/ or anywhere):
    python experiments/export_population.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parent   # papers/c26-2026/experiments
PAPER = EXPERIMENTS.parent                      # papers/c26-2026
sys.path.insert(0, str(EXPERIMENTS / "src"))

import pandas as pd  # noqa: E402

from reniped.population import build_units, read_inei  # noqa: E402

XLSX = PAPER / "data" / "external" / "population.xlsx"
OUT = PAPER / "outputs" / "derived"
YEARS = list(range(2019, 2026))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ine = read_inei(XLSX)
    units = build_units(ine, YEARS)

    wide = OUT / "population-provinces.csv"
    ine.to_csv(wide, index=False, encoding="utf-8-sig")

    long = OUT / "population-units.csv"
    units.to_csv(long, index=False, encoding="utf-8-sig")

    doc = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": "data/external/population.xlsx",
        "source_note": "INEI, Peru: total population projected at 30 June of each year, by "
                       "department, province and district, 2018-2026 (Table No. 01); "
                       "preliminary and reference projections.",
        "source_url": "https://www.gob.pe/institucion/inei/informes-publicaciones/6894980",
        "derived_by": "experiments/export_population.py",
        "files": {
            "population-provinces.csv": "province-level projections as published (UBIGEO, name, 2018-2026)",
            "population-units.csv": "the 26 territorial units used by the analysis (2019-2025)",
        },
        "rows": {"provinces": int(len(ine)), "units": int(len(units))},
    }
    (OUT / "population.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    print(f"wrote {wide.name} ({len(ine)} provinces) and {long.name} ({len(units)} rows)")
    print("units per year:", units.groupby('ANO').size().to_dict())


if __name__ == "__main__":
    main()

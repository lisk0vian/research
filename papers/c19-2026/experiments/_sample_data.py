# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Synthesise tiny RENIPRESS + census files for the fast tests and local smoke runs.

It never slices the real data: a checked-in sample of real rows goes stale and
quietly becomes the thing everyone tests against. The columns are the contract
`_etl.py` reads; the values are invented.

Usage (a local smoke run needs data/, never Colab):

    python _sample_data.py --out /tmp/c19
    DATA_DIR=/tmp/c19 OUTPUT_DIR=/tmp/c19-out python run_all.py --only 00 01 02
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from _paths import CENSUS_FILE, RENIPRESS_FILE
from _schema import RENIPRESS_COLUMNS

DEPARTAMENTOS = [("LIMA", "Costa"), ("CUSCO", "Sierra"), ("LORETO", "Selva")]
CATEGORIAS = ["I-1", "I-2", "I-3", "I-4", "II-1", "II-2", "II-E", "III-1", "III-2"]
DISTRITOS_POR_DEPTO = 8
EESS_POR_DISTRITO = 8
RENIPRESS_ORIGINAL_COLUMNS = [c["original"] for c in RENIPRESS_COLUMNS]


def build_sample(seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (renipress, census) in the same formats as the real files.

    renipress has the 31 raw RENIPRESS columns (Spanish headers, as published);
    census has the English columns written by census2025_prepare.py.
    """
    rng = np.random.default_rng(seed)
    rows, census = [], []
    for d, (dpto, _region) in enumerate(DEPARTAMENTOS):
        for distrito in range(DISTRITOS_POR_DEPTO):
            ubigeo = f"{d + 1:02d}{distrito + 1:02d}00"
            lat = -12.0 + 3.0 * d + 0.2 * distrito
            lon = -77.0 + 3.0 * d + 0.2 * distrito
            # Same draws, in the same order, as the 2017-format fixture: the target
            # depends on them, and a test set with a single class breaks the smoke run.
            groups = [int(rng.integers(200, 5_000)) for _ in range(7)]
            n_dis = int(rng.integers(10, 200))
            n_total = sum(groups)
            n_5 = n_total - 50
            census.append({
                "ubigeo": ubigeo, "department": dpto.title(), "province": f"PROV{distrito}",
                "district": f"DIST{distrito}", "boundary_undefined": False,
                "population_total": n_total, "pop_0_14": groups[0] + groups[1],
                "pop_15_59": sum(groups[2:6]), "pop_60_plus": groups[6],
                "pop5_total": n_5, "pop5_with_disability": n_dis, "pop5_without_disability": n_5 - n_dis,
            })
            for k in range(EESS_POR_DISTRITO):
                n = distrito * EESS_POR_DISTRITO + k
                # Only district 0 holds level II/III hospitals, so distance to the
                # nearest complex hospital varies across districts (the target
                # depends on it); otherwise every point sits at ~0 km.
                category = (["II-1", "II-2", "II-E", "III-1", "III-2", "III-E", "II-2", "III-1"][k]
                            if distrito == 0 else CATEGORIAS[k % 4])
                classification = "HOSPITALES O CLINICAS DE ATENCION GENERAL" if distrito == 0 else "CENTROS DE SALUD O CENTROS MEDICOS"
                # Some facilities carry no category ('0'), like labs and doctors' offices.
                if distrito != 0 and distrito % 3 == 1 and k == 3:
                    category, classification = "0", "PATOLOGIA CLINICA"
                row = {c: "" for c in RENIPRESS_ORIGINAL_COLUMNS}
                row.update({
                    "INSTITUCION": "MINSA", "COD_IPRESS": f"{d * 1000 + n:08d}", "NOMBRE": f"EESS {ubigeo}-{k}",
                    "CLASIFICACION": classification,
                    "TIPO_ESTABLECIMIENTO": "ESTABLECIMIENTO DE SALUD SIN INTERNAMIENTO",
                    "DEPARTAMENTO": dpto, "PROVINCIA": f"PROV{distrito}", "DISTRITO": f"DIST{distrito}",
                    "UBIGEO": ubigeo, "DIRECCION": "CALLE 1", "CATEGORIA": category,
                    "INICIO_ACTIVIDAD": "2000-01-01 00:00:00",
                    "ESTADO": "ACTIVO" if k < 6 else "BAJA DEFINITIVA",
                    # A few off-territory points, so the invalid-coordinate path
                    # is exercised instead of assumed.
                    "NORTE": round(lat + 0.01 * k, 6) if n % 7 else 99.0,
                    "ESTE": round(lon + 0.01 * k, 6) if n % 11 else 99.0,
                })
                rows.append(row)
    return pd.DataFrame(rows, columns=RENIPRESS_ORIGINAL_COLUMNS), pd.DataFrame(census)


def write_sample(directory: Path) -> tuple[Path, Path]:
    """Write the two raw files under `directory`/raw, named as config.yaml says."""
    directory = Path(directory)
    raw = directory / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    renipress, census = build_sample()
    # utf-8-sig and ';' like the 2026 RENIPRESS editions.
    renipress.to_csv(raw / RENIPRESS_FILE, sep=";", index=False, encoding="utf-8-sig")
    census.to_csv(raw / CENSUS_FILE, index=False, encoding="utf-8")
    return raw / RENIPRESS_FILE, raw / CENSUS_FILE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="data/processed/sample",
                    help="directory to write raw/ under (never data/raw)")
    args = ap.parse_args()
    out = Path(args.out)
    if out.resolve() == (Path(__file__).resolve().parents[1] / "data" / "raw").resolve():
        raise SystemExit("refusing to overwrite the real data/raw/; pick another --out")
    renipress, censo = write_sample(out)
    print(f"wrote {renipress} and {censo}")
    print("synthetic values only; never cite anything derived from them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

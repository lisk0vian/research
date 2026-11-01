# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 00: verify datasets."""
# v1 (G5, 2026-11-01): forces one full re-run of every stage (the keys chain),
# so a single session produces all the numbers the manuscript cites.
RESULTS_VERSION = 1

import json
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import OUTPUTS, plan_record

# The analysis plan is frozen before outcome data is touched: a hash change
# with the same version stops the run here, before the ETL.
PLAN = HERE / "analysis_plan.yaml"
PLAN_RECORD = OUTPUTS / "logs" / "analysis_plan.json"
previous = (json.loads(PLAN_RECORD.read_text(encoding="utf-8"))
            if PLAN_RECORD.exists() else None)
record, error = plan_record(PLAN.read_text(encoding="utf-8"), previous)
if error:
    raise SystemExit(error)
PLAN_RECORD.parent.mkdir(parents=True, exist_ok=True)
PLAN_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")
print("analysis plan: v", record["version"], "sha256", record["sha256"])

from _common import *
from _schema import DATASETS

print("RENIPRESS hash:", hash_renipress)
print("Census hash:", hash_census)
print("RENIPRESS rows:", len(df), "cols:", len(df.columns))
print("Census districts:", len(df_census), "ubigeo unique:", df_census['ubigeo'].nunique())
print("activos:", N_ACTIVOS, "sin censo:", N_ACTIVOS_SIN_CENSO, "coords validas:", N_COORDS_VALIDAS)
if N_ACTIVOS_SIN_CENSO:
    print("districts with active facilities and no census row:", UBIGEO_SIN_CENSO)

# The fixed counts only make sense for the registered snapshots; a synthetic
# fixture (tests, local smoke) has a different hash and must not trip them.
# Provenance, links and hashes: data/SOURCES.md.
RENIPRESS_SHA256 = DATASETS["renipress"]["sha256"]   # October 2026 edition
CENSUS_SHA256 = DATASETS["census2025"]["sha256"]     # censo-2025-distrital.csv
if hash_renipress == RENIPRESS_SHA256:
    assert len(df) == 36246, "RENIPRESS row count changed"
    assert N_ACTIVOS == 27017, "RENIPRESS active count changed"
else:
    print("WARNING: not the registered RENIPRESS snapshot; skipping fixed row-count asserts.")
if hash_census == CENSUS_SHA256:
    assert len(df_census) == 1893, "census district count changed"
    # INEI national row: counted population 32,706,028 (omission-adjusted total is 34,157,732).
    assert int(df_census['population_total'].sum()) == 32_706_028, "census total does not match the national row"
else:
    print("WARNING: not the registered census table; skipping fixed census asserts.")
print("Stage 00 done.")
os.makedirs(os.path.join(DIR_SALIDA, "logs"), exist_ok=True)
with open(os.path.join(DIR_SALIDA, "logs", "verify.txt"), "w", encoding="utf-8") as f:
    f.write(f"renipress_sha256 {hash_renipress}\n")
    f.write(f"census_sha256 {hash_census}\n")
    f.write(f"renipress_rows {len(df)}\n")
    f.write(f"census_districts {df_census['ubigeo'].nunique()}\n")
    f.write(f"activos {N_ACTIVOS}\n")
    f.write(f"activos_sin_censo {N_ACTIVOS_SIN_CENSO}\n")
    f.write(f"coords_validas {N_COORDS_VALIDAS}\n")
print("Stage 00 verify.txt written.")

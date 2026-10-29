# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 00: verify datasets."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

print("RENIPRESS hash:", hash_renipress)
print("INEI hash:", hash_inei)
print("RENIPRESS rows:", len(df), "cols:", len(df.columns))
print("INEI distrital:", len(df_inei_dist), "ubigeo unique:", df_inei_dist['UBIGEO'].nunique())
print("activos:", N_ACTIVOS, "coords validas:", N_COORDS_VALIDAS)
assert len(df) == 35371, "RENIPRESS row count changed"
assert df_inei_dist['UBIGEO'].nunique() == 1678, "INEI district count changed"
print("Stage 00 done.")

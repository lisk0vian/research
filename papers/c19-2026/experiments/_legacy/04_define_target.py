# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 04: 04_define_target (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

prevalencia = float(df_activos["VULNERABLE"].mean() * 100)
print("Target prevalence:", prevalencia)
with open(os.path.join(DIR_SALIDA, "04_modelado_ml", "target_prevalence.txt"), "w", encoding="utf-8") as f:
    f.write(f"VULNERABLE_prevalence_pct {prevalencia:.4f}\n")
    f.write(f"n {len(df_activos)}\n")
print("Stage 04_define_target done.")

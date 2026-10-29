# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 04: 04_define_target (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

print("Target prevalence:", df_activos["VULNERABLE"].mean()*100)
print("Stage 04_define_target done.")
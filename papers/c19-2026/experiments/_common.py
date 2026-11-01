# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Shared entry point for the c19-2026 stages.

Every stage does `from _common import *`, which gives it:

- paths, config, helpers (`_paths.py`);
- the analysis frames (`df`, `df_census`, `df_activos`, `df_validas`) built
  once by `_etl.py` and cached as parquet in `data/processed/`.

`_common.py` itself stays free of modelling imports; a stage that trains or
plots adds `from _deps import *`. This is what lets stage 00/01 run before any
of the heavy packages are needed.
"""

from __future__ import annotations

from _etl import load_or_build
from _paths import *
from _paths import save_df_activos as _save_df_activos

ensure_output_dirs()

_STATE = load_or_build(RUTA_RENIPRESS, RUTA_CENSO, PROCESSED, SEED_BASE)
globals().update(_STATE)


def save_df_activos(df=None):
    """Persist the stage's enriched frame (stage 03 adds VULNERABLE/INVS to it)."""
    _save_df_activos(df_activos if df is None else df)

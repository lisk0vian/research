# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Paths, config and IO helpers for the c19-2026 pipeline.

Dependency-light on purpose (stdlib + pandas + numpy), so an early stage runs
before any modelling dependency is installed and so `_sample_data.py` and the
tests can import it without paying for the ETL.

The ETL itself lives in `_etl.py`; each stage imports the modelling or
plotting packages it needs itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time
import unicodedata
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE / "data"))
OUTPUTS = Path(os.environ.get("OUTPUT_DIR", BASE / "outputs"))
PROCESSED = DATA_DIR / "processed"

# The raw file names live in config.yaml (and are mirrored in colab.yaml's
# state_inputs), so moving to the next monthly RENIPRESS edition is a config
# change, not a code change.
CONFIG = yaml.safe_load((Path(__file__).with_name("config.yaml")).read_text(encoding="utf-8"))
RENIPRESS_FILE = CONFIG["data"]["renipress"]
CENSUS_FILE = CONFIG["data"]["census"]
RUTA_RENIPRESS = DATA_DIR / "raw" / RENIPRESS_FILE
RUTA_CENSO = DATA_DIR / "raw" / CENSUS_FILE

SEEDS = [42, 52, 62, 72, 82, 92, 102, 112, 122, 132]
SEED_BASE = SEEDS[0]
random.seed(SEED_BASE)
np.random.seed(SEED_BASE)
warnings.filterwarnings("ignore")

DIR_SALIDA = str(OUTPUTS)


def ensure_output_dirs() -> None:
    """Each stage creates its own output folder; only the root is shared."""
    OUTPUTS.mkdir(parents=True, exist_ok=True)


REGION_NATURAL_MAP = {
    "AMAZONAS": "Selva", "ANCASH": "Sierra", "APURIMAC": "Sierra", "AREQUIPA": "Costa",
    "AYACUCHO": "Sierra", "CAJAMARCA": "Sierra", "CALLAO": "Costa", "CUSCO": "Sierra",
    "HUANCAVELICA": "Sierra", "HUANUCO": "Selva", "ICA": "Costa", "JUNIN": "Sierra",
    "LA LIBERTAD": "Costa", "LAMBAYEQUE": "Costa", "LIMA": "Costa", "LORETO": "Selva",
    "MADRE DE DIOS": "Selva", "MOQUEGUA": "Costa", "PASCO": "Sierra", "PIURA": "Costa",
    "PUNO": "Sierra", "SAN MARTIN": "Selva", "TACNA": "Costa", "TUMBES": "Costa",
    "UCAYALI": "Selva",
}

def log(msg, also_print=False):
    """The canonical log is outputs/logs/<stage>.log, written by the runner."""
    print(msg)


def hash_archivo(ruta, bloque=8192):
    h = hashlib.sha256()
    try:
        with open(ruta, "rb") as f:
            for chunk in iter(lambda: f.read(bloque), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        return f"NO_DISPONIBLE ({e})"


def plan_record(plan_text: str, previous: dict | None) -> tuple[dict, str | None]:
    """Record of the frozen analysis plan, and the error if it drifted.

    The plan is frozen by version: a changed file is only legal together with a
    version bump, so thresholds cannot be tuned after seeing outcome data.
    """
    plan = yaml.safe_load(plan_text) or {}
    record = {
        "version": plan.get("version"),
        "frozen": plan.get("frozen"),
        "sha256": hashlib.sha256(plan_text.encode("utf-8")).hexdigest(),
    }
    if (previous and previous.get("sha256") != record["sha256"]
            and int(previous.get("version", 0) or 0) == int(record["version"] or 0)):
        return record, (
            f"analysis_plan.yaml changed without a version bump "
            f"(version {record['version']})")
    return record, None


def normalizar_cadena(texto):
    if pd.isna(texto):
        return ""
    t = str(texto).strip().upper()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _atomic_write(path: Path, write_fn) -> Path:
    """Temp sibling + os.replace: a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        write_fn(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def atomic_write_json(payload, path: Path) -> Path:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    return _atomic_write(path, lambda p: p.write_text(text, encoding="utf-8"))


def save_df_activos(df) -> None:
    """Persist the enriched frame so later stages reload instead of recomputing."""
    _atomic_write(PROCESSED / "df_activos.parquet",
                  lambda p: df.to_parquet(p, index=False))


def load_df_activos():
    p = PROCESSED / "df_activos.parquet"
    if p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:
            return None
    return None

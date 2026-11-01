# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Paths, config and IO helpers for the c19-2026 pipeline.

Dependency-light on purpose (stdlib + pandas + numpy), so an early stage runs
before any modelling dependency is installed and so `_sample_data.py` and the
tests can import it without paying for the ETL.

The ETL itself lives in `_etl.py`; the heavy modelling imports live in
`_deps.py`. A stage that trains or plots does `from _deps import *`.
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
SUBCARPETAS = [
    "01_prep", "02_clustering", "03_indice_invs", "04_modelado_ml", "05_shap",
    "06_equidad_calibracion", "07_drift_robustez", "08_final",
    "09_validacion_externa", "10_conformal", "11_sota", "12_sensibilidad_global",
    "13_shap_estabilidad", "14_temporal", "15_causal", "16_espacial_lisa_getis",
    "17_complejidad", "18_reproducibilidad", "19_permutation_importance",
    "20_robustez_ruido", "21_calidad_datos", "22_error_analysis",
    "23_decision_curve", "24_economico", "25_lodo", "26_simulacion",
    "27_modelos_persistidos", "28_metricas_extendidas", "29_figuras_pipeline",
    "30_tablas_dataset", "31_shap_avanzado", "32_pdp_ice", "33_metricas_clasificacion",
    "34_calibracion_avanzada", "35_correlacion_vif", "36_logs", "37_informe_final",
    "38_inferencia", "39_doi_package", "40_metricas_globales",
    "41_threshold_optimization", "42_learning_curve", "43_feature_stability",
    "44_reconciliacion_distritos", "45_sensibilidad_economica",
    "46_auc_interno_vs_externo",
]

# Written once per outputs folder. Creating 46 directories on every stage import
# costs seconds on a Drive mount; the marker turns that into a single stat.
DIRS_MARKER = ".dirs_ready"


def ensure_output_dirs() -> None:
    if (OUTPUTS / DIRS_MARKER).exists():
        return
    for sc in SUBCARPETAS:
        os.makedirs(os.path.join(DIR_SALIDA, sc), exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    (OUTPUTS / DIRS_MARKER).touch()


REGION_NATURAL_MAP = {
    "AMAZONAS": "Selva", "ANCASH": "Sierra", "APURIMAC": "Sierra", "AREQUIPA": "Costa",
    "AYACUCHO": "Sierra", "CAJAMARCA": "Sierra", "CALLAO": "Costa", "CUSCO": "Sierra",
    "HUANCAVELICA": "Sierra", "HUANUCO": "Selva", "ICA": "Costa", "JUNIN": "Sierra",
    "LA LIBERTAD": "Costa", "LAMBAYEQUE": "Costa", "LIMA": "Costa", "LORETO": "Selva",
    "MADRE DE DIOS": "Selva", "MOQUEGUA": "Costa", "PASCO": "Sierra", "PIURA": "Costa",
    "PUNO": "Sierra", "SAN MARTIN": "Selva", "TACNA": "Costa", "TUMBES": "Costa",
    "UCAYALI": "Selva",
}

REGISTRO_FIGURAS: list = []
REGISTRO_TABLAS: list = []
MODELOS_PERSISTIDOS: dict = {}


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


RUN_STATE = PROCESSED / "run_state.joblib"


def save_run_state(**objects) -> None:
    """Objects a later stage needs (model, splits, SHAP) live on disk, not in RAM.

    The original notebook kept them in one namespace; once it was split into
    stages, stages 06-13 referenced names nobody had defined. This is that
    namespace, persisted.
    """
    import joblib

    state = load_run_state()
    state.update(objects)
    _atomic_write(RUN_STATE, lambda p: joblib.dump(state, p))


def load_run_state() -> dict:
    p = RUN_STATE
    if not p.exists():
        return {}
    try:
        import joblib

        return joblib.load(p)
    except Exception:
        return {}

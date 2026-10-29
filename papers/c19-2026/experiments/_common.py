# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Shared helpers for the c19-2026 pipeline: paths, config, IO, data loading.

Adapted from the original monolithic notebook (Script_Hospital_CORREGIDO_26_08_25.ipynb).
Every stage does `from _common import *` and operates on `df` / `df_activos`.
"""

from __future__ import annotations
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import random
import os
import sys
import json
import subprocess
import warnings
import unicodedata
import shutil
import time
import platform
import socket
import hashlib
import logging
import tracemalloc
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE / "data"))
OUTPUTS = Path(os.environ.get("OUTPUT_DIR", BASE / "outputs"))
RUTA_RENIPRESS = DATA_DIR / "raw" / "renipress.csv"
RUTA_INEI = DATA_DIR / "raw" / "censo-2017.csv"

SEEDS = [42, 52, 62, 72, 82, 92, 102, 112, 122, 132]
SEED_BASE = SEEDS[0]
random.seed(SEED_BASE)

def instalar_dependencias(pkgs):
    for pkg in pkgs:
        modulo = pkg.replace('-', '_')
        try:
            __import__(modulo)
        except ImportError:
            try:
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install', pkg, '-q'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

print("Verificando dependencias...")
instalar_dependencias([
    'libpysal', 'esda', 'pyproj', 'optuna', 'kneed', 'shap', 'catboost',
    'statsmodels', 'scikit-learn', 'xgboost', 'mapie', 'SALib', 'psutil',
    'joblib', 'reportlab', 'factor_analyzer', 'matplotlib', 'seaborn',
])

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats import (spearmanr, friedmanchisquare, wilcoxon, norm, ks_2samp, chi2)
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.decomposition import PCA, FactorAnalysis
from sklearn.ensemble import (IsolationForest, ExtraTreesClassifier, HistGradientBoostingClassifier,
                             RandomForestClassifier)
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors
import lightgbm as lgb
from catboost import CatBoostClassifier
import xgboost as xgb
from sklearn.impute import SimpleImputer
from sklearn.model_selection import (StratifiedKFold, LeaveOneGroupOut, GroupKFold,
                                    train_test_split, learning_curve)
from sklearn.inspection import permutation_importance, PartialDependenceDisplay
from sklearn.metrics import (accuracy_score, roc_auc_score, f1_score, confusion_matrix,
                            brier_score_loss, matthews_corrcoef, cohen_kappa_score,
                            balanced_accuracy_score, precision_recall_curve,
                            average_precision_score, recall_score, precision_score,
                            fbeta_score, roc_curve)
from sklearn.calibration import calibration_curve
from sklearn.pipeline import Pipeline
from sklearn.utils import resample
from sklearn.utils.class_weight import compute_class_weight

import shap
import libpysal
from esda.moran import Moran, Moran_Local
from esda.getisord import G_Local
import optuna
optuna.logging.set_verbosity(optuna.logging.ERROR)
from pyproj import Transformer
try:
    from kneed import KneeLocator
    KNEED_OK = True
except Exception:
    KNEED_OK = False
import joblib

try:
    from mapie.classification import MapieClassifier
    MAPIE_OK = True
except Exception:
    MAPIE_OK = False

try:
    from SALib.sample import saltelli, morris as morris_sample
    from SALib.analyze import sobol as sobol_analyze
    from SALib.analyze import morris as morris_analyze
    SALIB_OK = True
except Exception:
    SALIB_OK = False

try:
    import psutil
    PSUTIL_OK = True
except Exception:
    PSUTIL_OK = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
                                     Table as RLTable, TableStyle, PageBreak)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors as rl_colors
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

np.random.seed(SEED_BASE)
warnings.filterwarnings('ignore')

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
for sc in SUBCARPETAS:
    os.makedirs(os.path.join(DIR_SALIDA, sc), exist_ok=True)

LOG_PATH = os.path.join(DIR_SALIDA, "36_logs", "pipeline.log")
logger = logging.getLogger("INVS_Pipeline")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = logging.FileHandler(LOG_PATH, mode='w', encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(fh)

def log(msg, also_print=False):
    try:
        logger.info(msg)
    except Exception:
        pass
    if also_print:
        print(msg)

def hash_archivo(ruta, bloque=8192):
    h = hashlib.sha256()
    try:
        with open(ruta, 'rb') as f:
            for chunk in iter(lambda: f.read(bloque), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        return f"NO_DISPONIBLE ({e})"

def normalizar_cadena(texto):
    if pd.isna(texto): return ''
    t = str(texto).strip().upper()
    t = unicodedata.normalize('NFD', t)
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn')

def reportar_recursos(tag, t_inicio, mem_inicio=None):
    t_fin = time.time()
    msg = f"  [{tag}] Tiempo: {t_fin - t_inicio:.3f}s"
    if PSUTIL_OK:
        try:
            ram_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 ** 2)
            msg += f" | RAM proceso: {ram_mb:.1f} MB"
        except Exception:
            pass
    print(msg)
    log(msg)
    return t_fin

def guardar_figura_multi(fig_or_plt, ruta_base_sin_ext, dpi=300):
    for ext in ["png", "svg", "pdf"]:
        ruta = f"{ruta_base_sin_ext}.{ext}"
        try:
            plt.savefig(ruta, dpi=dpi, bbox_inches='tight')
        except Exception:
            pass
    log(f"Figura exportada: {ruta_base_sin_ext}")

REGISTRO_FIGURAS = []
REGISTRO_TABLAS = []
MODELOS_PERSISTIDOS = {}

REGION_NATURAL_MAP = {
    'AMAZONAS': 'Selva', 'ANCASH': 'Sierra', 'APURIMAC': 'Sierra', 'AREQUIPA': 'Costa',
    'AYACUCHO': 'Sierra', 'CAJAMARCA': 'Sierra', 'CALLAO': 'Costa', 'CUSCO': 'Sierra',
    'HUANCAVELICA': 'Sierra', 'HUANUCO': 'Selva', 'ICA': 'Costa', 'JUNIN': 'Sierra',
    'LA LIBERTAD': 'Costa', 'LAMBAYEQUE': 'Costa', 'LIMA': 'Costa', 'LORETO': 'Selva',
    'MADRE DE DIOS': 'Selva', 'MOQUEGUA': 'Costa', 'PASCO': 'Sierra', 'PIURA': 'Costa',
    'PUNO': 'Sierra', 'SAN MARTIN': 'Selva', 'TACNA': 'Costa', 'TUMBES': 'Costa', 'UCAYALI': 'Selva'
}

# --- data loading (mirrors the notebook's ingestion) ---
hash_renipress = hash_archivo(str(RUTA_RENIPRESS))
hash_inei = hash_archivo(str(RUTA_INEI))
log(f"SHA256 RENIPRESS: {hash_renipress}")
log(f"SHA256 INEI: {hash_inei}")

with open(str(RUTA_RENIPRESS), encoding="latin1", errors='ignore') as f:
    N_FILAS_CRUDAS_RENIPRESS = sum(1 for _ in f) - 1

df = pd.read_csv(str(RUTA_RENIPRESS), encoding="latin1", sep=';', engine="python", on_bad_lines="skip")
df.columns = df.columns.str.strip().str.upper()
N_ANTES_DEDUP = len(df)
df = df.drop_duplicates()
N_DESPUES_DEDUP = len(df)
df['UBIGEO'] = df['UBIGEO'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(6)

df_inei = pd.read_csv(str(RUTA_INEI), encoding='utf-8', dtype={'UBIGEO': str})
df_inei = df_inei[df_inei['UBIGEO'].notna()].copy()
df_inei['UBIGEO'] = df_inei['UBIGEO'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(6)
df_inei_dist = df_inei[df_inei['Tipo'] == 'DISTRITAL'].copy()

cols_pob = [c for c in ['Primera infancia (0 - 5 años)', 'Niñez (6 - 11 años)', 'Adolescencia (12 - 17 años)',
             'Jóvenes (18 - 29 años)', 'Adultos/as jóvenes (30 - 44 años)', 'Adultos/as (45 - 59 años)',
             'Adultos/as mayores (60 y más años)'] if c in df_inei_dist.columns]
if not cols_pob:
    # fallback: match by normalized name
    cols_pob = [c for c in df_inei_dist.columns if any(k in str(c).lower() for k in ['infancia','niñez','adolescencia','jovenes','adultos'])]
df_inei_dist['poblacion_total'] = df_inei_dist[cols_pob].apply(pd.to_numeric, errors='coerce').sum(axis=1)
df_inei_dist['poblacion_adulto_mayor'] = pd.to_numeric(
    df_inei_dist[[c for c in df_inei_dist.columns if '60' in str(c)] or [df_inei_dist.columns[0]]].iloc[:, 0],
    errors='coerce').fillna(0)
df_inei_dist['poblacion_discapacidad'] = pd.to_numeric(
    df_inei_dist[[c for c in df_inei_dist.columns if 'discapacidad' in str(c).lower()] or [df_inei_dist.columns[0]]].iloc[:, 0],
    errors='coerce').fillna(0)

# --- base spatial features (bloque 1, up to anom merge) ---
for col in ['NORTE', 'ESTE']:
    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.', regex=False).str.strip(), errors='coerce')

mask_valida = df['NORTE'].between(-18.35, -0.02) & df['ESTE'].between(-81.40, -68.60)
df['LAT'] = df['NORTE'].where(mask_valida)
df['LON'] = df['ESTE'].where(mask_valida)
df['COORD_VALIDA'] = mask_valida.astype(int)
N_COORDS_VALIDAS = int(mask_valida.sum())
N_COORDS_INVALIDAS = int((~mask_valida).sum())

df_activos_todos = df[df['ESTADO'] == 'ACTIVO'].copy().reset_index(drop=True)
N_ACTIVOS = len(df_activos_todos)
N_INACTIVOS_EXCLUIDOS = len(df) - N_ACTIVOS
NIVEL_MAP = {'I-1':1,'I-2':2,'I-3':3,'I-4':4,'II-1':5,'II-2':6,'II-E':5,'III-1':7,'III-2':8}
df_activos_todos['NIVEL'] = df_activos_todos['CATEGORIA'].map(NIVEL_MAP).fillna(1).astype(int)
df_activos_todos['DEPARTAMENTO_NORM'] = df_activos_todos['DEPARTAMENTO'].apply(normalizar_cadena)
df_activos_todos['REGION_NATURAL'] = df_activos_todos['DEPARTAMENTO_NORM'].map(
    {normalizar_cadena(k): v for k, v in REGION_NATURAL_MAP.items()}).fillna('Sierra')

df_validas = df_activos_todos[df_activos_todos['COORD_VALIDA'] == 1].copy().reset_index(drop=True)
hosp_c = df_validas[df_validas['NIVEL'] >= 5].copy()
if len(hosp_c) > 0:
    nn = NearestNeighbors(n_neighbors=1, metric='haversine')
    nn.fit(np.radians(hosp_c[['LAT','LON']].values))
    dist_rad, _ = nn.kneighbors(np.radians(df_validas[['LAT','LON']].values))
    df_validas['dist_km_hosp_complejo'] = dist_rad[:,0] * 6371.0
else:
    df_validas['dist_km_hosp_complejo'] = 0.0

dist_ubigeo = df_validas.groupby('UBIGEO')['dist_km_hosp_complejo'].median().reset_index().rename(
    columns={'dist_km_hosp_complejo': 'dist_km_ubigeo'})
df_activos_todos = df_activos_todos.merge(dist_ubigeo, on='UBIGEO', how='left')
df_activos_todos['dist_km_hosp_complejo'] = df_activos_todos['dist_km_ubigeo'].fillna(
    df_validas['dist_km_hosp_complejo'].median() if len(df_validas) else 0.0)

df_activos = df_activos_todos.merge(
    df_inei_dist[['UBIGEO','poblacion_total','poblacion_discapacidad','poblacion_adulto_mayor']],
    on='UBIGEO', how='left')
for c in ['poblacion_total','poblacion_discapacidad','poblacion_adulto_mayor']:
    df_activos[c] = df_activos[c].fillna(0)
N_FINAL_ANALISIS = len(df_activos)

transformer = Transformer.from_crs("EPSG:4326", "EPSG:32718", always_xy=True)
try:
    utm_x, utm_y = transformer.transform(df_validas['LON'].values, df_validas['LAT'].values)
    X_utm = StandardScaler().fit_transform(np.column_stack([utm_x, utm_y]))
    dbscan_labels = DBSCAN(eps=0.15, min_samples=3).fit_predict(X_utm)
    df_validas['ANOMALIA_ESPACIAL'] = (
        (IsolationForest(contamination=0.08, random_state=SEED_BASE).fit_predict(X_utm) == -1).astype(int) +
        (LocalOutlierFactor(n_neighbors=20, contamination=0.08).fit_predict(X_utm) == -1).astype(int) +
        (dbscan_labels == -1).astype(int) >= 2).astype(int)
except Exception:
    df_validas['ANOMALIA_ESPACIAL'] = 0
anom_m = df_validas.groupby('UBIGEO')['ANOMALIA_ESPACIAL'].max().reset_index()
df_activos = df_activos.merge(anom_m, on='UBIGEO', how='left').fillna({'ANOMALIA_ESPACIAL': 0})

# --- state persistence helpers ---
import pickle

def _state_path(name="df_activos"):
    p = OUTPUTS / "processed"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{name}.parquet"

def save_df_activos():
    try:
        _state_path().parent.mkdir(parents=True, exist_ok=True)
        df_activos.to_parquet(_state_path(), index=False)
    except Exception as e:
        print("save_df_activos failed:", e)

def load_df_activos():
    p = _state_path()
    if p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:
            return None
    return None

# convenience: load persisted enriched df if available
_loaded = load_df_activos()
if _loaded is not None:
    df_activos = _loaded

print("c19-2026 _common loaded. df_activos shape:", getattr(df_activos, 'shape', None))

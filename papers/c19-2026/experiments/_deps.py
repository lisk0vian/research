# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Modelling, plotting and reporting imports for the c19-2026 pipeline.

Kept out of `_common.py` so the early stages (verify, data quality) run before
these packages are needed, and so importing `_common` in a test does not pull
half of PyPI. A stage that plots or trains does `from _deps import *`.
"""

from __future__ import annotations

import os
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import shap
from scipy.stats import chi2, friedmanchisquare, ks_2samp, norm, spearmanr, wilcoxon
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

from sklearn.calibration import calibration_curve
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA, FactorAnalysis
from sklearn.ensemble import (ExtraTreesClassifier, HistGradientBoostingClassifier,
                              IsolationForest, RandomForestClassifier)
from sklearn.impute import SimpleImputer
from sklearn.inspection import PartialDependenceDisplay, permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score,
                             balanced_accuracy_score, brier_score_loss, cohen_kappa_score,
                             confusion_matrix, f1_score, fbeta_score,
                             matthews_corrcoef, precision_recall_curve, precision_score,
                             recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import (GroupKFold, GroupShuffleSplit, LeaveOneGroupOut,
                                     StratifiedKFold, learning_curve, train_test_split)
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.utils import resample
from sklearn.utils.class_weight import compute_class_weight

from catboost import CatBoostClassifier
import lightgbm as lgb
import optuna
import xgboost as xgb

optuna.logging.set_verbosity(optuna.logging.ERROR)
import joblib
import libpysal
from esda.getisord import G_Local
from esda.moran import Moran, Moran_Local
from pyproj import Transformer

from _paths import SEED_BASE, log

try:
    from kneed import KneeLocator
    KNEED_OK = True
except Exception:
    KNEED_OK = False

try:
    from mapie.classification import MapieClassifier
    MAPIE_OK = True
except Exception:
    MAPIE_OK = False

try:
    from SALib.analyze import morris as morris_analyze
    from SALib.analyze import sobol as sobol_analyze
    from SALib.sample import morris as morris_sample
    from SALib.sample import saltelli
    SALIB_OK = True
except Exception:
    SALIB_OK = False

try:
    import psutil
    PSUTIL_OK = True
except Exception:
    PSUTIL_OK = False

try:
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table as RLTable,
                                    TableStyle)
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False


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
    return t_fin


def guardar_figura_multi(fig_or_plt, ruta_base_sin_ext, dpi=300):
    for ext in ["png", "svg", "pdf"]:
        ruta = f"{ruta_base_sin_ext}.{ext}"
        try:
            plt.savefig(ruta, dpi=dpi, bbox_inches="tight")
        except Exception:
            pass
    log(f"Figura exportada: {ruta_base_sin_ext}")


def construir_modelo(best_params):
    """Rebuild the winning model. Shared by stages 05, 07, 08, 10 and 11."""
    if best_params["model_type"] == "LightGBM":
        return lgb.LGBMClassifier(n_estimators=best_params.get("lgb_n", 80), verbosity=-1, random_state=SEED_BASE)
    if best_params["model_type"] == "CatBoost":
        return CatBoostClassifier(iterations=best_params.get("cat_i", 80), verbose=0, random_state=SEED_BASE)
    if best_params["model_type"] == "ExtraTrees":
        return ExtraTreesClassifier(n_estimators=best_params.get("et_n", 80), random_state=SEED_BASE)
    if best_params["model_type"] == "XGBoost":
        return xgb.XGBClassifier(n_estimators=best_params.get("xgb_n", 80), use_label_encoder=False,
                                 eval_metric="logloss", verbosity=0, random_state=SEED_BASE)
    return HistGradientBoostingClassifier(max_iter=best_params.get("hg_i", 80), random_state=SEED_BASE)

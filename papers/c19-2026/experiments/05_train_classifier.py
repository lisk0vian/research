# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 05: 05_train_classifier (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

# CORRECCIÓN METODOLÓGICA (Observación de revisión Q1 — fuga de información):
# `train_test_split(..., groups_ml, ...)` en la versión anterior NO agrupaba
# nada: sklearn.train_test_split no soporta partición por grupos, solo
# barajaba `groups_ml` como un arreglo más. Como muchos establecimientos
# (filas de RENIPRESS) comparten el mismo UBIGEO, y varias FEATURES
# (poblacion_total, tasa_vulnerabilidad_regional, ratio_adulto_mayor) y el
# propio VULNERABLE dependen de agregados a nivel distrital/departamental,
# la partición aleatoria dejaba filas del MISMO distrito en train Y test,
# inflando artificialmente el AUC interno. Se reemplaza por GroupShuffleSplit
# agrupando por UBIGEO (distrito), que garantiza que ningún distrito aparezca
# simultáneamente en ambos conjuntos.
# =============================================================================
FEATURES = ['NIVEL', 'poblacion_total', 'tasa_vulnerabilidad_regional', 'ratio_adulto_mayor']
X_ml = df_activos[FEATURES].copy()
y_ml = df_activos['VULNERABLE'].values
groups_ml = df_activos['DEPARTAMENTO_NORM'].values
groups_ubigeo_ml = df_activos['UBIGEO'].values
regiones_ml = df_activos['REGION_NATURAL'].values

from sklearn.model_selection import GroupShuffleSplit

gss_outer = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED_BASE)
idx_train, idx_test = next(gss_outer.split(X_ml, y_ml, groups=groups_ubigeo_ml))

X_train_puro, X_test_puro = X_ml.iloc[idx_train], X_ml.iloc[idx_test]          # conservan el índice original de df_activos (igual que antes)
y_train_puro, y_test_puro = y_ml[idx_train], y_ml[idx_test]
groups_train, groups_test = groups_ml[idx_train], groups_ml[idx_test]          # se preserva DEPARTAMENTO_NORM para el CV interno (Bloque 5)

# --- Verificación explícita de ausencia de fuga distrital -------------------
distritos_train = set(df_activos.iloc[idx_train]['UBIGEO'])
distritos_test = set(df_activos.iloc[idx_test]['UBIGEO'])
interseccion_distritos = distritos_train & distritos_test
print(f"🔎 Verificación anti-fuga (UBIGEO): {len(distritos_train)} distritos en train | "
      f"{len(distritos_test)} en test | {len(interseccion_distritos)} distritos en ambos conjuntos")
assert len(interseccion_distritos) == 0, (
    f"⚠️ FUGA DE INFORMACIÓN DETECTADA: {len(interseccion_distritos)} distritos (UBIGEO) "
    f"aparecen simultáneamente en train y test."
)
print(f"🎯 Prevalencia VULNERABLE — train: {y_train_puro.mean()*100:.2f}% | test: {y_test_puro.mean()*100:.2f}% "
      f"(sin estratificación forzada por y, ya que la partición ahora se rige por el grupo geográfico UBIGEO)")

print("\n" + "="*80 + "\n[📊 BLOQUE 5: NESTED SPATIAL CV CON OPTUNA (50 TRIALS) BASADO EN ESTRUCTURA TERRITORIAL]\n" + "="*80)
t5 = time.time()
spatial_inner_cv = GroupKFold(n_splits=3)

def optimizar_spatial_loop(trial, X_tr_raw, y_tr_raw, grps_tr):
    pipe = Pipeline([('imputer', SimpleImputer(strategy='median')), ('scaler', StandardScaler())])
    model_type = trial.suggest_categorical('model_type', ['LightGBM', 'CatBoost', 'ExtraTrees', 'HistGrad', 'XGBoost'])
    scores = []

    for train_idx, val_idx in spatial_inner_cv.split(X_tr_raw, y_tr_raw, groups=grps_tr):
        X_in_tr = pipe.fit_transform(X_tr_raw.iloc[train_idx]).astype(np.float32)
        X_in_va = pipe.transform(X_tr_raw.iloc[val_idx]).astype(np.float32)

        if model_type == 'LightGBM':
            m = lgb.LGBMClassifier(n_estimators=trial.suggest_int('lgb_n', 40, 120), verbosity=-1, random_state=SEED_BASE)
        elif model_type == 'CatBoost':
            m = CatBoostClassifier(iterations=trial.suggest_int('cat_i', 40, 120), verbose=0, random_state=SEED_BASE)
        elif model_type == 'ExtraTrees':
            m = ExtraTreesClassifier(n_estimators=trial.suggest_int('et_n', 40, 120), random_state=SEED_BASE)
        elif model_type == 'XGBoost':
            m = xgb.XGBClassifier(n_estimators=trial.suggest_int('xgb_n', 40, 120), use_label_encoder=False,
                                   eval_metric='logloss', verbosity=0, random_state=SEED_BASE)
        else:
            m = HistGradientBoostingClassifier(max_iter=trial.suggest_int('hg_i', 40, 120), random_state=SEED_BASE)

        m.fit(X_in_tr, y_tr_raw[train_idx])
        scores.append(roc_auc_score(y_tr_raw[val_idx], m.predict_proba(X_in_va)[:,1]))
    return np.mean(scores)

print("🔄 Iniciando Búsqueda Exhaustiva Espacial (50 Trials con Reporte de Convergencia)...")
study = optuna.create_study(direction='maximize')
for step in range(5):
    study.optimize(lambda t: optimizar_spatial_loop(t, X_train_puro, y_train_puro, groups_train), n_trials=10)
    print(f"   📈 Convergencia Parcial Iteración {(step+1)*10}/50 | Mejor AUC Histórico: {study.best_value:.4f}")

def construir_modelo(best_params):
    if best_params['model_type'] == 'LightGBM':
        return lgb.LGBMClassifier(n_estimators=best_params.get('lgb_n', 80), verbosity=-1, random_state=SEED_BASE)
    elif best_params['model_type'] == 'CatBoost':
        return CatBoostClassifier(iterations=best_params.get('cat_i', 80), verbose=0, random_state=SEED_BASE)
    elif best_params['model_type'] == 'ExtraTrees':
        return ExtraTreesClassifier(n_estimators=best_params.get('et_n', 80), random_state=SEED_BASE)
    elif best_params['model_type'] == 'XGBoost':
        return xgb.XGBClassifier(n_estimators=best_params.get('xgb_n', 80), use_label_encoder=False,
                                  eval_metric='logloss', verbosity=0, random_state=SEED_BASE)
    else:
        return HistGradientBoostingClassifier(max_iter=best_params.get('hg_i', 80), random_state=SEED_BASE)

pipe_final = Pipeline([('imputer', SimpleImputer(strategy='median')), ('scaler', StandardScaler())])
X_tr_sc = pipe_final.fit_transform(X_train_puro).astype(np.float32)
X_te_sc = pipe_final.transform(X_test_puro).astype(np.float32)

model_global = construir_modelo(study.best_params)
model_global.fit(X_tr_sc, y_train_puro)
probs_test = model_global.predict_proba(X_te_sc)[:,1]
t5 = reportar_recursos("Bloque 5 — Optuna 50 trials + entrenamiento final", t5)

# =============================================================================
# 5bis. PERSISTENCIA DE MODELOS Y OBJETOS (OBSERVACIÓN #2)
# =============================================================================

print("\n" + "="*80 + "\n[💾 BLOQUE 5bis: PERSISTENCIA DE MODELOS, PIPELINE, SCALER, IMPUTADOR Y OPTUNA STUDY]\n" + "="*80)
DIR_MODELOS = os.path.join(DIR_SALIDA, "27_modelos_persistidos")

ruta_modelo_final = os.path.join(DIR_MODELOS, "modelo_final.joblib")
joblib.dump(model_global, ruta_modelo_final)
MODELOS_PERSISTIDOS["modelo_final"] = ruta_modelo_final

ruta_pipeline = os.path.join(DIR_MODELOS, "pipeline_preprocesamiento.joblib")
joblib.dump(pipe_final, ruta_pipeline)
MODELOS_PERSISTIDOS["pipeline_preprocesamiento"] = ruta_pipeline

imputer_solo = pipe_final.named_steps['imputer']
scaler_solo = pipe_final.named_steps['scaler']
ruta_imputer = os.path.join(DIR_MODELOS, "imputer.joblib")
ruta_scaler = os.path.join(DIR_MODELOS, "scaler.joblib")
joblib.dump(imputer_solo, ruta_imputer)
joblib.dump(scaler_solo, ruta_scaler)
MODELOS_PERSISTIDOS["imputer"] = ruta_imputer
MODELOS_PERSISTIDOS["scaler"] = ruta_scaler

ruta_study = os.path.join(DIR_MODELOS, "optuna_study.joblib")
joblib.dump(study, ruta_study)
MODELOS_PERSISTIDOS["optuna_study"] = ruta_study

ruta_features = os.path.join(DIR_MODELOS, "features_list.json")
with open(ruta_features, "w") as f:
    json.dump({"FEATURES": FEATURES, "best_params": study.best_params}, f, indent=4, default=str)
MODELOS_PERSISTIDOS["features_list"] = ruta_features

for nombre, ruta in MODELOS_PERSISTIDOS.items():
    print(f"  💾 Persistido: {nombre} → {ruta}")
log(f"Objetos persistidos: {json.dumps(MODELOS_PERSISTIDOS, default=str)}")

print("\n" + "="*80 + "\n[🩹 VERIFICACIÓN POST-IMPUTACIÓN — DATOS PERDIDOS TRAS EL PIPELINE (Imputer+Scaler)]\n" + "="*80)
n_nan_train_post = int(np.isnan(X_tr_sc).sum())
n_nan_test_post = int(np.isnan(X_te_sc).sum())
filas_missing_post = []
for i, feat in enumerate(FEATURES):
    nan_tr = int(np.isnan(X_tr_sc[:, i]).sum())
    nan_te = int(np.isnan(X_te_sc[:, i]).sum())
    filas_missing_post.append({"Feature_ML": feat, "NaN_en_train_post_imputacion": nan_tr, "NaN_en_test_post_imputacion": nan_te})
df_missing_post = pd.DataFrame(filas_missing_post)
print(df_missing_post.to_string(index=False))
print(f"  ✅ Total NaN remanentes en TRAIN tras imputación: {n_nan_train_post} | en TEST: {n_nan_test_post}")
if n_nan_train_post == 0 and n_nan_test_post == 0:
    print("  ✅ Confirmado: el SimpleImputer(strategy='median') eliminó el 100% de los valores perdidos en las features del modelo.")
else:
    print("  ⚠️ ALERTA: persisten valores NaN tras la imputación; revisar el Pipeline antes de continuar.")

ruta_excel_missing_post = os.path.join(DIR_SALIDA, "30_tablas_dataset", "missing_data_post_imputacion.csv")
df_missing_post.to_csv(ruta_excel_missing_post, index=False)
df_missing_post.to_csv(os.path.join(DIR_SALIDA, "30_tablas_dataset", "missing_data_post_imputacion.csv"), index=False)
print(f"  💾 Excel/CSV exportados: {ruta_excel_missing_post}")
REGISTRO_TABLAS.append(("Verificación de datos perdidos POST-imputación", df_missing_post))

# =============================================================================
# 6. ABLATION STUDY PREDICTIVO SOBRE VARIABLES DEL CLASIFICADOR
# =============================================================================

print("\n" + "="*80 + "\n[📊 BLOQUE 6: ABLATION STUDY — IMPACTO EN CLASIFICADOR PREDICTIVO DE INFRAESTRUCTURA]\n" + "="*80)
base_auc = roc_auc_score(y_test_puro, probs_test)
ablation_pred_resultados = []
for i, feat in enumerate(FEATURES):
    cols_reduced = [f for f in FEATURES if f != feat]
    X_tr_r = pd.DataFrame(X_tr_sc, columns=FEATURES)[cols_reduced]
    X_te_r = pd.DataFrame(X_te_sc, columns=FEATURES)[cols_reduced]
    # CORRECCIÓN (observación de Edith): el ablation usaba SIEMPRE LGBMClassifier
    # sin importar cuál fue el algoritmo ganador de la optimización Optuna
    # (Bloque 5). Se reemplaza por construir_modelo(study.best_params), que
    # reconstruye el MISMO modelo/hiperparámetros seleccionados como final,
    # para que el ablation mida el impacto real del modelo que se reporta.
    m_abl = construir_modelo(study.best_params)
    m_abl.fit(X_tr_r, y_train_puro)
    delta_auc = base_auc - roc_auc_score(y_test_puro, m_abl.predict_proba(X_te_r)[:,1])
    print(f"  ❌ Removiendo Predictor: {feat:<30} | Pérdida Integral ΔAUC: {delta_auc:.4f}")
    ablation_pred_resultados.append({"Feature_removida": feat, "Delta_AUC": delta_auc})
pd.DataFrame(ablation_pred_resultados).to_csv(os.path.join(DIR_SALIDA, "04_modelado_ml/ablation_predictivo.csv"), index=False)
REGISTRO_TABLAS.append(("Ablation Study — predictores del clasificador", pd.DataFrame(ablation_pred_resultados)))

# =============================================================================
# 7. BOOTSTRAP DE 2000 ITERACIONES E INTERVALOS DE CONFIANZA DEL 95%
# =============================================================================


print("Stage 05_train_classifier done.")
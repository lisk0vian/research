# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 08: 08_test_geographic_transfer (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

print("\n" + "="*80 + "\n[🌍 BLOQUE 13bis: VALIDACIÓN DE GENERALIZACIÓN GEOGRÁFICA — LEAVE-ONE-REGION-OUT (COSTA / SIERRA / SELVA)]\n" + "="*80)
print("  ⚠️ NOTA TERMINOLÓGICA (observación de Edith): esto NO constituye una validación")
print("     'externa' en sentido estricto, ya que el target VULNERABLE y el índice INVS se")
print("     construyen a partir de las mismas fuentes usadas para entrenar el modelo")
print("     (RENIPRESS/INEI). Se trata de una validación de GENERALIZACIÓN GEOGRÁFICA:")
print("     el modelo se entrena excluyendo una macrorregión/departamento y se evalúa sobre")
print("     esa misma macrorregión/departamento excluido, dentro del mismo dataset. Una")
print("     validación externa real requeriría un dataset independiente (p.ej. otra fuente")
print("     de datos sanitarios o un corte temporal distinto).")
t13b = time.time()
resultados_logo_region = []
for region_excluida in sorted(set(regiones_ml)):
    mask_train_ext = regiones_ml != region_excluida
    mask_test_ext = regiones_ml == region_excluida
    X_tr_ext, X_te_ext = X_ml[mask_train_ext], X_ml[mask_test_ext]
    y_tr_ext, y_te_ext = y_ml[mask_train_ext], y_ml[mask_test_ext]
    if len(np.unique(y_te_ext)) < 2:
        print(f"  ⚠️ Región {region_excluida}: omitida (clase única en hold-out)")
        continue
    pipe_ext = Pipeline([('imputer', SimpleImputer(strategy='median')), ('scaler', StandardScaler())])
    X_tr_ext_sc = pipe_ext.fit_transform(X_tr_ext)
    X_te_ext_sc = pipe_ext.transform(X_te_ext)
    m_ext = construir_modelo(study.best_params)
    m_ext.fit(X_tr_ext_sc, y_tr_ext)
    auc_ext = roc_auc_score(y_te_ext, m_ext.predict_proba(X_te_ext_sc)[:,1])
    resultados_logo_region.append({"Región_Excluida_Validación": region_excluida, "N_obs_validacion": mask_test_ext.sum(), "AUC_generalizacion_geografica": auc_ext})
    print(f"  🌎 Entrenado SIN {region_excluida} → Validado EN {region_excluida} | AUC (holdout geográfico): {auc_ext:.4f} | N={mask_test_ext.sum()}")

df_logo_region = pd.DataFrame(resultados_logo_region)
df_logo_region.to_csv(os.path.join(DIR_SALIDA, "09_validacion_externa/leave_one_region_out.csv"), index=False)
REGISTRO_TABLAS.append(("Validación de Generalización Geográfica — Leave-One-Region-Out (Costa/Sierra/Selva)", df_logo_region))
print(f"  📌 AUC promedio de generalización geográfica (3 macrorregiones, NO validación externa a otra fuente de datos): {df_logo_region['AUC_generalizacion_geografica'].mean():.4f} ± {df_logo_region['AUC_generalizacion_geografica'].std():.4f}")
t13b = reportar_recursos("Bloque 13bis — Leave-One-Region-Out", t13b)

# =============================================================================
# 13ter. LEAVE-ONE-DEPARTMENT-OUT (OBSERVACIÓN #17 v19)
# =============================================================================

print("\n" + "="*80 + "\n[🌍 BLOQUE 13ter: LEAVE-ONE-DEPARTMENT-OUT — GENERALIZACIÓN GEOGRÁFICA ESTRICTA]\n" + "="*80)
t13c = time.time()
logo_dpto = LeaveOneGroupOut()
resultados_lodo = []
departamentos_unicos = pd.Series(groups_ml).unique()
for dpto in departamentos_unicos:
    mask_tr_d = groups_ml != dpto
    mask_te_d = groups_ml == dpto
    y_te_d = y_ml[mask_te_d]
    if len(np.unique(y_te_d)) < 2 or mask_te_d.sum() < 5:
        continue
    pipe_d = Pipeline([('imputer', SimpleImputer(strategy='median')), ('scaler', StandardScaler())])
    X_tr_d_sc = pipe_d.fit_transform(X_ml[mask_tr_d])
    X_te_d_sc = pipe_d.transform(X_ml[mask_te_d])
    m_d = lgb.LGBMClassifier(verbosity=-1, random_state=SEED_BASE).fit(X_tr_d_sc, y_ml[mask_tr_d])
    auc_d = roc_auc_score(y_te_d, m_d.predict_proba(X_te_d_sc)[:,1])
    resultados_lodo.append({"Departamento_excluido": dpto, "N": mask_te_d.sum(), "AUC": auc_d})

df_lodo = pd.DataFrame(resultados_lodo).sort_values("AUC")
print(df_lodo.to_string(index=False))
print(f"  📌 AUC LODO Promedio: {df_lodo['AUC'].mean():.4f} ± {df_lodo['AUC'].std():.4f} | Mín: {df_lodo['AUC'].min():.4f} | Máx: {df_lodo['AUC'].max():.4f}")
df_lodo.to_csv(os.path.join(DIR_SALIDA, "25_lodo/leave_one_department_out.csv"), index=False)
REGISTRO_TABLAS.append(("Validación de Generalización Geográfica — Leave-One-Department-Out", df_lodo))
t13c = reportar_recursos("Bloque 13ter — Leave-One-Department-Out", t13c)

# =============================================================================
# 13ter-B. COMPARACIÓN FORMAL AUC INTERNO vs EXTERNO (LORO / LODO)      [NUEVO v21]
# =============================================================================

print("\n" + "="*80 + "\n[⚖️ BLOQUE 13ter-B: COMPARACIÓN FORMAL AUC INTERNO vs EXTERNO (LORO / LODO)]\n" + "="*80)
t13x = time.time()
auc_interno_test = float(roc_auc_score(y_test_puro, probs_test))
auc_loro_medio = float(df_logo_region['AUC_generalizacion_geografica'].mean())
auc_lodo_medio = float(df_lodo['AUC'].mean())

df_comparacion_auc = pd.DataFrame([
    {"Esquema_de_validacion": "Hold-out interno (80/20 estratificado, mismo dominio geográfico)", "AUC_medio": auc_interno_test, "Delta_vs_interno": 0.0},
    {"Esquema_de_validacion": "Leave-One-Region-Out (Costa/Sierra/Selva)", "AUC_medio": auc_loro_medio, "Delta_vs_interno": auc_loro_medio - auc_interno_test},
    {"Esquema_de_validacion": "Leave-One-Department-Out (generalización geográfica estricta)", "AUC_medio": auc_lodo_medio, "Delta_vs_interno": auc_lodo_medio - auc_interno_test},
])
print(df_comparacion_auc.round(4).to_string(index=False))

brecha_generalizacion = auc_interno_test - min(auc_loro_medio, auc_lodo_medio)
if brecha_generalizacion > 0.10:
    veredicto_brecha = ("Brecha AMPLIA (>0.10) entre validación interna y externa: el modelo probablemente "
                         "captura patrones ligados a la cercanía geográfica entre train y test del hold-out "
                         "aleatorio. El AUC interno NO debe reportarse como medida principal de desempeño "
                         "generalizable; se recomienda priorizar el AUC de LODO/LORO en el manuscrito y "
                         "presentar el AUC interno solo como referencia secundaria.")
elif brecha_generalizacion > 0.05:
    veredicto_brecha = ("Brecha MODERADA (0.05–0.10): existe pérdida de desempeño al generalizar a regiones/"
                         "departamentos no vistos durante el entrenamiento; debe discutirse explícitamente "
                         "como limitación del estudio, con referencia a las regiones/departamentos de menor AUC.")
else:
    veredicto_brecha = "Brecha PEQUEÑA (<0.05): el modelo generaliza razonablemente bien fuera de su dominio geográfico de entrenamiento."
print(f"\n  💡 Brecha de generalización (AUC interno − mín(AUC LORO, AUC LODO)): {brecha_generalizacion:.4f}")
print(f"  💡 Veredicto automático: {veredicto_brecha}")
print("\n  🌍 El detalle por macrorregión/departamento con menor AUC externo ya está exportado en las tablas")
print("     'Validación de Generalización Geográfica — Leave-One-Region-Out' y 'Leave-One-Department-Out' (Bloques 13bis/13ter);")
print("     deben citarse explícitamente en la sección de limitaciones del manuscrito.")

df_comparacion_auc.to_csv(os.path.join(DIR_SALIDA, "46_auc_interno_vs_externo/comparacion_auc_interno_externo.csv"), index=False)
REGISTRO_TABLAS.append(("Comparación formal AUC interno vs validación de generalización geográfica (LORO/LODO) — NO es validación contra fuente de datos externa, ya que VULNERABLE se construye a partir de RENIPRESS/INEI", df_comparacion_auc))
t13x = reportar_recursos("Bloque 13ter-B — Comparación AUC interno vs externo", t13x)

# =============================================================================
# 13quater. VALIDACIÓN TEMPORAL (OBSERVACIÓN #6 v19) — CONDICIONADA A DISPONIBILIDAD
# =============================================================================

print("\n" + "="*80 + "\n[🕒 BLOQUE 13quater: VALIDACIÓN TEMPORAL — TIME SPLIT / ROLLING WINDOW]\n" + "="*80)
COLS_FECHA_CANDIDATAS = [c for c in df.columns if 'FECHA' in c or 'ANIO' in c or 'AÑO' in c]
if COLS_FECHA_CANDIDATAS:
    col_fecha = COLS_FECHA_CANDIDATAS[0]
    print(f"  📅 Columna temporal detectada: {col_fecha}. Ejecutando Time Split + Rolling Window...")
    df_activos['_FECHA_TMP'] = pd.to_datetime(df_activos.get(col_fecha), errors='coerce')
    df_temporal = df_activos.dropna(subset=['_FECHA_TMP']).sort_values('_FECHA_TMP')
    if len(df_temporal) > 50:
        corte_temporal = df_temporal['_FECHA_TMP'].quantile(0.8)
        train_t = df_temporal[df_temporal['_FECHA_TMP'] <= corte_temporal]
        test_t = df_temporal[df_temporal['_FECHA_TMP'] > corte_temporal]
        pipe_t = Pipeline([('imputer', SimpleImputer(strategy='median')), ('scaler', StandardScaler())])
        Xtr_t = pipe_t.fit_transform(train_t[FEATURES])
        Xte_t = pipe_t.transform(test_t[FEATURES])
        m_temporal = lgb.LGBMClassifier(verbosity=-1, random_state=SEED_BASE).fit(Xtr_t, train_t['VULNERABLE'])
        auc_temporal = roc_auc_score(test_t['VULNERABLE'], m_temporal.predict_proba(Xte_t)[:,1])
        print(f"  📌 AUC Validación Temporal (corte en {corte_temporal}): {auc_temporal:.4f}")
    else:
        print("  ⚠️ Insuficientes registros con fecha válida tras limpieza; se omite validación temporal cuantitativa.")
else:
    print("  ⚠️ RENIPRESS es un snapshot transversal (sin columna de fecha de habilitación operativa estandarizada).")
    print("     Limitación declarada explícitamente en el manuscrito: la validación dinámica/temporal del INVS")
    print("     queda como trabajo futuro condicionado a la disponibilidad de series RENIPRESS multi-corte")
    print("     (p.ej. snapshots trimestrales 2024-2026) para implementar Rolling Window / Time Split formal.")

# =============================================================================
# 13quinquies. CONFORMAL PREDICTION — INCERTIDUMBRE POR OBSERVACIÓN (OBS. #2 v19)
# =============================================================================


print("Stage 08_test_geographic_transfer done.")
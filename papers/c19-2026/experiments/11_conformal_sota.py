# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 11: 11_conformal_sota (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

print("\n" + "="*80 + "\n[🎯 BLOQUE 13quinquies: CONFORMAL PREDICTION (MAPIE) — INTERVALOS POR OBSERVACIÓN]\n" + "="*80)
t13d = time.time()
if MAPIE_OK:
    # CORRECCIÓN (observación de Edith): aunque este split es interno a train
    # (no toca X_test_puro), se agrupa igualmente por UBIGEO para mantener el
    # mismo criterio de partición geográfica en TODOS los splits del pipeline,
    # evitando que establecimientos del mismo distrito queden repartidos entre
    # el subconjunto de ajuste y el de calibración conforme.
    ubigeo_train_puro = df_activos.loc[X_train_puro.index, 'UBIGEO'].values
    gss_cal = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=SEED_BASE)
    idx_train_cal, idx_calib = next(gss_cal.split(X_tr_sc, y_train_puro, groups=ubigeo_train_puro))
    X_train_cal, X_calib = X_tr_sc[idx_train_cal], X_tr_sc[idx_calib]
    y_train_cal, y_calib = y_train_puro[idx_train_cal], y_train_puro[idx_calib]
    modelo_base_conformal = construir_modelo(study.best_params)
    modelo_base_conformal.fit(X_train_cal, y_train_cal)
    mapie_clf = MapieClassifier(estimator=modelo_base_conformal, cv="prefit", method="lac")
    mapie_clf.fit(X_calib, y_calib)
    y_pred_mapie, y_set_mapie = mapie_clf.predict(X_te_sc, alpha=0.10)
    cobertura_empirica = np.mean([y_test_puro[i] in np.where(y_set_mapie[i, :, 0])[0] for i in range(len(y_test_puro))])
    print(f"  📌 Cobertura Empírica del Conjunto de Predicción (objetivo 90%): {cobertura_empirica*100:.2f}%")
    tamano_promedio_set = y_set_mapie[:, :, 0].sum(axis=1).mean()
    print(f"  📌 Tamaño Promedio del Conjunto de Predicción Conforme: {tamano_promedio_set:.3f}")
    df_conformal = pd.DataFrame({
        "Prob_Vulnerable": probs_test,
        "Set_incluye_0": y_set_mapie[:, 0, 0],
        "Set_incluye_1": y_set_mapie[:, 1, 0],
        "Y_real": y_test_puro
    })
    df_conformal.to_csv(os.path.join(DIR_SALIDA, "10_conformal/conformal_prediction_sets.csv"), index=False)
    print("  💡 Ejemplo de salida enriquecida: P(vulnerable)=0.84 con conjunto conforme al 90% → {Vulnerable} (set unitario, alta confianza)")
else:
    print("  ⚠️ MAPIE no disponible en el entorno; se documenta como dependencia opcional. Alternativa manual:")
    z_critico = norm.ppf(0.95)
    se_aprox = np.sqrt(probs_test * (1 - probs_test) / len(probs_test))
    ic_inf = np.clip(probs_test - z_critico * se_aprox, 0, 1)
    ic_sup = np.clip(probs_test + z_critico * se_aprox, 0, 1)
    print(f"  📌 IC90% aproximado (Wald, fallback): ancho promedio = {(ic_sup - ic_inf).mean():.4f}")
t13d = reportar_recursos("Bloque 13quinquies — Conformal Prediction", t13d)

# =============================================================================
# 13sexies. ANÁLISIS DE SENSIBILIDAD GLOBAL — SOBOL Y MORRIS (OBS. #4 v19)
# =============================================================================

print("\n" + "="*80 + "\n[🔬 BLOQUE 13sexies: ANÁLISIS DE SENSIBILIDAD GLOBAL — SOBOL & MORRIS]\n" + "="*80)
t13e = time.time()
if SALIB_OK:
    # CORRECCIÓN (observación de Edith): los límites (bounds) del análisis de
    # sensibilidad se calculaban sobre X_ml completo (train + test), es decir,
    # el conjunto de prueba se estaba incorporando al proceso de validación de
    # robustez. Se usa únicamente X_train_puro para definir el rango de
    # muestreo Sobol/Morris, dejando test fuera de cualquier etapa de ajuste
    # o construcción de la validación.
    bounds_problem = {
        'num_vars': len(FEATURES),
        'names': FEATURES,
        'bounds': [[float(X_train_puro[f].min()), float(X_train_puro[f].max())] for f in FEATURES]
    }

    def funcion_caja_negra(X_input):
        df_input = pd.DataFrame(X_input, columns=FEATURES)
        X_input_sc = pipe_final.transform(df_input)
        return model_global.predict_proba(X_input_sc)[:, 1]

    print("  🔄 Ejecutando muestreo Saltelli + análisis Sobol...")
    param_values_sobol = saltelli.sample(bounds_problem, 256)
    Y_sobol = funcion_caja_negra(param_values_sobol)
    Si_sobol = sobol_analyze.analyze(bounds_problem, Y_sobol, print_to_console=False)
    df_sobol = pd.DataFrame({"Feature": FEATURES, "S1": Si_sobol['S1'], "ST": Si_sobol['ST']}).sort_values("ST", ascending=False)
    print("  📌 Índices de Sobol (S1 = efecto principal, ST = efecto total con interacciones):")
    print(df_sobol.to_string(index=False))

    print("\n  🔄 Ejecutando muestreo Morris + análisis de trayectorias...")
    param_values_morris = morris_sample.sample(bounds_problem, N=100)
    Y_morris = funcion_caja_negra(param_values_morris)
    Si_morris = morris_analyze.analyze(bounds_problem, param_values_morris, Y_morris, print_to_console=False)
    df_morris = pd.DataFrame({"Feature": FEATURES, "mu_star": Si_morris['mu_star'], "sigma": Si_morris['sigma']}).sort_values("mu_star", ascending=False)
    print("  📌 Índices de Morris (mu_star = importancia media, sigma = no linealidad/interacción):")
    print(df_morris.to_string(index=False))

    df_sobol.to_csv(os.path.join(DIR_SALIDA, "12_sensibilidad_global/sobol.csv"), index=False)
    df_morris.to_csv(os.path.join(DIR_SALIDA, "12_sensibilidad_global/morris.csv"), index=False)
    REGISTRO_TABLAS.append(("Análisis de Sensibilidad Global — Índices de Sobol (S1/ST)", df_sobol))
    REGISTRO_TABLAS.append(("Análisis de Sensibilidad Global — Índices de Morris (mu_star/sigma)", df_morris))
else:
    print("  ⚠️ SALib no disponible; análisis de sensibilidad global omitido y declarado como dependencia opcional.")
t13e = reportar_recursos("Bloque 13sexies — Sensibilidad Global Sobol/Morris", t13e)

# =============================================================================
# 13septies. DISCUSIÓN CAUSAL (OBSERVACIÓN #7 v19)
# =============================================================================

print("\n" + "="*80 + "\n[🧩 BLOQUE 13septies: DISCUSIÓN CAUSAL — DAG CUALITATIVO Y AJUSTE POR CONFUSORES]\n" + "="*80)
t13f = time.time()
print("  📌 DAG cualitativo propuesto (relación hipotética, no estimación causal fuerte):")
print("     REGION_NATURAL → dist_km_hosp_complejo → VULNERABLE")
print("     poblacion_total → tasa_vulnerabilidad_regional → VULNERABLE")
print("     NIVEL (categoría EESS) → Dim2_Resolutividad → VULNERABLE")
print("  💡 El diseño es observacional y transversal: las asociaciones reportadas (SHAP, AUC, Sobol) son")
print("     predictivas/asociativas, no causales en sentido estricto (no hay manipulación experimental")
print("     ni identificación de instrumentos). Como aproximación de robustez, se ajusta un modelo lineal")
print("     generalizado controlando confusores estructurales:")

X_causal = sm.add_constant(df_activos[['dist_km_hosp_complejo', 'NIVEL', 'poblacion_total']].fillna(0))
modelo_glm_causal = sm.GLM(df_activos['VULNERABLE'], X_causal, family=sm.families.Binomial()).fit()
print(modelo_glm_causal.summary().tables[1])
print("  💡 Línea de trabajo futuro declarada: Double Machine Learning (DoWhy/EconML) con instrumentos")
print("     geográficos (p.ej. distancia a vías troncales) para una identificación causal más robusta.")
t13f = reportar_recursos("Bloque 13septies — Discusión Causal", t13f)

# =============================================================================
# 13octies. ROBUSTNESS TEST FRENTE A RUIDO (OBSERVACIÓN #12 v19)
# =============================================================================

print("\n" + "="*80 + "\n[📊 BLOQUE 12: TABLA DE EVALUACIÓN COMPARATIVA SOTA]\n" + "="*80)
t12 = time.time()
dict_baselines = {
    "Logistic Regression": LogisticRegression(random_state=SEED_BASE),
    "Random Forest": RandomForestClassifier(random_state=SEED_BASE),
    "Extra Trees": ExtraTreesClassifier(random_state=SEED_BASE),
    "Hist Gradient Boosting": HistGradientBoostingClassifier(random_state=SEED_BASE),
    "XGBoost": xgb.XGBClassifier(use_label_encoder=False, eval_metric='logloss', verbosity=0, random_state=SEED_BASE),
    "CatBoost (default)": CatBoostClassifier(verbose=0, random_state=SEED_BASE),
    f"{study.best_params['model_type']} (Optimizado Optuna)": model_global
}

tabla_comp = []
for name, clf in dict_baselines.items():
    t_modelo = time.time()
    if clf is not model_global:
        clf.fit(X_tr_sc, y_train_puro)
    tiempo_entrenamiento = time.time() - t_modelo
    p_comp = clf.predict_proba(X_te_sc)[:,1]
    pred_comp = clf.predict(X_te_sc)
    auc_c = roc_auc_score(y_test_puro, p_comp)
    f1_c = f1_score(y_test_puro, pred_comp)
    br_c = brier_score_loss(y_test_puro, p_comp)
    mcc_c = matthews_corrcoef(y_test_puro, pred_comp)
    bacc_c = balanced_accuracy_score(y_test_puro, pred_comp)
    recall_c = recall_score(y_test_puro, pred_comp, zero_division=0)          # <-- NUEVO v21
    ap_c = average_precision_score(y_test_puro, p_comp)                       # <-- NUEVO v21
    tabla_comp.append({"Algoritmo": name, "AUC-ROC": auc_c, "Average_Precision": ap_c, "F1-Score": f1_c,
                        "Recall_Sensitivity": recall_c, "Brier Score": br_c,
                        "MCC": mcc_c, "Balanced_Accuracy": bacc_c, "Tiempo_train_s": round(tiempo_entrenamiento, 4)})

df_tabla_comp = pd.DataFrame(tabla_comp)
print(df_tabla_comp.to_string(index=False))
print("\n  💡 Nota metodológica: TabNet/FT-Transformer/TabPFN requieren GPU dedicada y volumen muestral mayor;")
print("     se reporta SOTA clásico (boosting/ensemble) como benchmark primario, dejando arquitecturas")
print("     de deep tabular learning como línea de trabajo futuro explícitamente declarada en el manuscrito.")
df_tabla_comp.to_csv(os.path.join(DIR_SALIDA, "11_sota/tabla_comparativa_sota.csv"), index=False)
REGISTRO_TABLAS.append(("Tabla comparativa SOTA", df_tabla_comp))
t12 = reportar_recursos("Bloque 12 — Comparación SOTA", t12)

# =============================================================================
# 12bis. LEARNING CURVES — DIAGNÓSTICO DE SESGO/VARIANZA               [NUEVO v21]
# =============================================================================

print("\n" + "="*80 + "\n[📉 BLOQUE 12bis: LEARNING CURVES — DIAGNÓSTICO DE SESGO (BIAS) Y VARIANZA (OVERFITTING)]\n" + "="*80)
t12b = time.time()
X_completo_sc = np.vstack([X_tr_sc, X_te_sc])
y_completo = np.concatenate([y_train_puro, y_test_puro])
modelo_lc = construir_modelo(study.best_params)

train_sizes_abs, train_scores_lc, val_scores_lc = learning_curve(
    modelo_lc, X_completo_sc, y_completo,
    train_sizes=np.linspace(0.1, 1.0, 8),
    cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED_BASE),
    scoring='roc_auc', n_jobs=-1, random_state=SEED_BASE
)
train_mean_lc, train_std_lc = train_scores_lc.mean(axis=1), train_scores_lc.std(axis=1)
val_mean_lc, val_std_lc = val_scores_lc.mean(axis=1), val_scores_lc.std(axis=1)

plt.figure(figsize=(7, 4.5))
plt.plot(train_sizes_abs, train_mean_lc, 'o-', label="AUC — Entrenamiento", color="#1f6f8b")
plt.fill_between(train_sizes_abs, train_mean_lc - train_std_lc, train_mean_lc + train_std_lc, alpha=0.15, color="#1f6f8b")
plt.plot(train_sizes_abs, val_mean_lc, 'o-', label="AUC — Validación (CV)", color="#c0392b")
plt.fill_between(train_sizes_abs, val_mean_lc - val_std_lc, val_mean_lc + val_std_lc, alpha=0.15, color="#c0392b")
plt.xlabel("Tamaño del conjunto de entrenamiento (n observaciones)")
plt.ylabel("AUC-ROC")
plt.title("Learning Curve — Diagnóstico de Sesgo/Varianza", fontsize=10, fontweight='bold', pad=10)
plt.legend()
plt.tight_layout()
ruta_lc = os.path.join(DIR_SALIDA, "42_learning_curve/learning_curve")
guardar_figura_multi(plt, ruta_lc)
REGISTRO_FIGURAS.append((ruta_lc + ".png", "Learning curve (AUC train vs validación CV) para diagnóstico de sesgo/varianza."))
plt.show()

brecha_final = float(train_mean_lc[-1] - val_mean_lc[-1])
if brecha_final > 0.07:
    diagnostico_lc = "Brecha train-validación amplia: señal de posible sobreajuste (alta varianza)."
elif val_mean_lc[-1] < 0.65:
    diagnostico_lc = "AUC de validación bajo incluso con toda la muestra: señal de posible sesgo alto (underfitting)."
else:
    diagnostico_lc = "Brecha train-validación moderada y AUC de validación razonable: balance sesgo/varianza aceptable."
print(f"  📌 Brecha AUC (train − validación) con muestra completa: {brecha_final:.4f}")
print(f"  💡 Diagnóstico automático: {diagnostico_lc}")

df_learning_curve = pd.DataFrame({
    "N_entrenamiento": train_sizes_abs,
    "AUC_train_media": train_mean_lc, "AUC_train_std": train_std_lc,
    "AUC_val_media": val_mean_lc, "AUC_val_std": val_std_lc
})
df_learning_curve.to_csv(os.path.join(DIR_SALIDA, "42_learning_curve/learning_curve_valores.csv"), index=False)
REGISTRO_TABLAS.append(("Learning Curve — AUC train vs validación por tamaño de muestra", df_learning_curve))
t12b = reportar_recursos("Bloque 12bis — Learning Curves", t12b)

# =============================================================================
# 13bis. VALIDACIÓN DE GENERALIZACIÓN GEOGRÁFICA — LEAVE-ONE-REGION-OUT (OBSERVACIÓN #1 v19)
# =============================================================================


print("Stage 11_conformal_sota done.")
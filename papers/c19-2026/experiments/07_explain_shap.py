# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 07: 07_explain_shap (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

print("\n" + "="*80 + "\n[📈 BLOQUE 11: DIAGNÓSTICOS DE EXPLICABILIDAD SHAP COMPLETOS EN CONSOLA]\n" + "="*80)
explainer = shap.TreeExplainer(model_global)
shap_values_raw = explainer(X_te_sc)

if len(shap_values_raw.shape) == 3 and shap_values_raw.shape[2] == 2:
    shap_values = shap.Explanation(values=shap_values_raw.values[:, :, 1], base_values=shap_values_raw.base_values[:, 1], data=X_test_puro.values, feature_names=FEATURES)
else:
    shap_values = shap_values_raw
    shap_values.data = X_test_puro.values
    shap_values.feature_names = FEATURES

print("\n📸 [PROCESANDO GRÁFICO 1/4] Beeswarm Plot Global...")
plt.figure(figsize=(7, 4))
shap.plots.beeswarm(shap_values, show=False)
plt.title("SHAP Beeswarm Plot Global", fontsize=11, fontweight='bold', pad=12)
plt.tight_layout()
ruta_bee = os.path.join(DIR_SALIDA, "05_shap/shap_beeswarm")
guardar_figura_multi(plt, ruta_bee)
REGISTRO_FIGURAS.append((ruta_bee + ".png", "SHAP Beeswarm Plot — impacto global de cada predictor."))
plt.show()

print("\n📸 [PROCESANDO GRÁFICO 2/4] Scatter Dependence Plot...")
plt.figure(figsize=(6, 4))
shap.plots.scatter(shap_values[:, FEATURES[0]], color=shap_values, show=False)
plt.title("SHAP Dependence Plot (Feature Central)", fontsize=10, fontweight='bold', pad=12)
plt.tight_layout()
ruta_dep = os.path.join(DIR_SALIDA, "05_shap/shap_dependence")
guardar_figura_multi(plt, ruta_dep)
REGISTRO_FIGURAS.append((ruta_dep + ".png", f"SHAP Dependence Plot de {FEATURES[0]}."))
plt.show()

print("\n📸 [PROCESANDO GRÁFICO 3/4] Waterfall Plot Local...")
plt.figure(figsize=(7, 4))
shap.plots.waterfall(shap_values[0], show=False)
plt.title("SHAP Waterfall Plot - Instancia Local (0)", fontsize=10, fontweight='bold', pad=12)
plt.tight_layout()
ruta_wf = os.path.join(DIR_SALIDA, "05_shap/shap_waterfall")
guardar_figura_multi(plt, ruta_wf)
REGISTRO_FIGURAS.append((ruta_wf + ".png", "SHAP Waterfall Plot — explicación local de una instancia."))
plt.show()

print("\n📸 [PROCESANDO GRÁFICO 4/4] Decision Plot Colectivo...")
plt.figure(figsize=(7, 4))
# CORRECCIÓN: explainer.expected_value puede venir como escalar, como array de
# 1 elemento (salida binaria en log-odds, caso típico de LightGBM/XGBoost) o
# como array/list de 2 elementos (uno por clase). Indexar [1] a ciegas rompe
# cuando el modelo ganador solo expone 1 valor esperado (como en esta corrida).
ev = explainer.expected_value
ev_arr = np.atleast_1d(ev)
base_val = ev_arr[1] if ev_arr.shape[0] > 1 else ev_arr[0]
shap.decision_plot(base_val, shap_values.values[:50], feature_names=FEATURES, show=False)
plt.title("SHAP Decision Plot - Trayectoria Colectiva (Top 50)", fontsize=10, fontweight='bold', pad=12)
plt.tight_layout()
ruta_dec = os.path.join(DIR_SALIDA, "05_shap/shap_decision")
guardar_figura_multi(plt, ruta_dec)
REGISTRO_FIGURAS.append((ruta_dec + ".png", "SHAP Decision Plot de las primeras 50 instancias del test."))
plt.show()

# =============================================================================
# 11ter-A. SHAP INTERACTION VALUES (OBSERVACIÓN #8)
# =============================================================================

print("\n" + "="*80 + "\n[📈 BLOQUE 11ter-A: SHAP INTERACTION VALUES Y SUMMARY PLOT DE INTERACCIONES]\n" + "="*80)
t11i = time.time()
try:
    shap_interaction_values = explainer.shap_interaction_values(X_te_sc)
    if isinstance(shap_interaction_values, list):
        shap_interaction_values = shap_interaction_values[1]  # clase positiva
    interaccion_media = np.abs(shap_interaction_values).mean(axis=0)
    df_interaccion = pd.DataFrame(interaccion_media, index=FEATURES, columns=FEATURES)
    print("  📌 Matriz de interacción SHAP (promedio |valor| entre pares de features):")
    print(df_interaccion.round(4).to_string())

    plt.figure(figsize=(6, 4))
    shap.summary_plot(shap_interaction_values, X_te_sc, feature_names=FEATURES, show=False)
    plt.title("SHAP Interaction Summary Plot", fontsize=10, fontweight='bold', pad=10)
    plt.tight_layout()
    ruta_inter = os.path.join(DIR_SALIDA, "31_shap_avanzado/shap_interaction_summary")
    guardar_figura_multi(plt, ruta_inter)
    REGISTRO_FIGURAS.append((ruta_inter + ".png", "SHAP Interaction Summary Plot — interacciones entre predictores."))
    plt.show()

    df_interaccion.to_csv(os.path.join(DIR_SALIDA, "31_shap_avanzado/shap_interaction_matrix.csv"))
except Exception as e:
    print(f"  ⚠️ No se pudieron calcular SHAP Interaction Values para este tipo de modelo: {e}")
t11i = reportar_recursos("Bloque 11ter-A — SHAP Interaction Values", t11i)

# =============================================================================
# 11ter-B. PARTIAL DEPENDENCE PLOT (PDP) E ICE CURVES (OBSERVACIONES #9, #10)
# =============================================================================

print("\n" + "="*80 + "\n[📈 BLOQUE 11ter-B: PARTIAL DEPENDENCE PLOT (PDP) E INDIVIDUAL CONDITIONAL EXPECTATION (ICE)]\n" + "="*80)
t11p = time.time()
modelo_wrapper_pdp = model_global
X_te_sc_df = pd.DataFrame(X_te_sc, columns=FEATURES)

fig_pdp, axes_pdp = plt.subplots(1, len(FEATURES), figsize=(4*len(FEATURES), 3.5))
PartialDependenceDisplay.from_estimator(
    modelo_wrapper_pdp, X_te_sc_df, features=list(range(len(FEATURES))),
    feature_names=FEATURES, kind="average", ax=axes_pdp
)
fig_pdp.suptitle("Partial Dependence Plots (PDP) — Todas las Features", fontsize=11, fontweight='bold')
plt.tight_layout()
ruta_pdp = os.path.join(DIR_SALIDA, "32_pdp_ice/pdp_todas_features")
guardar_figura_multi(plt, ruta_pdp)
REGISTRO_FIGURAS.append((ruta_pdp + ".png", "Partial Dependence Plots de todas las variables predictoras."))
plt.show()

fig_ice, axes_ice = plt.subplots(1, len(FEATURES), figsize=(4*len(FEATURES), 3.5))
PartialDependenceDisplay.from_estimator(
    modelo_wrapper_pdp, X_te_sc_df, features=list(range(len(FEATURES))),
    feature_names=FEATURES, kind="individual", ax=axes_ice,
    subsample=80, random_state=SEED_BASE
)
fig_ice.suptitle("ICE Curves (Individual Conditional Expectation) — Todas las Features", fontsize=11, fontweight='bold')
plt.tight_layout()
ruta_ice = os.path.join(DIR_SALIDA, "32_pdp_ice/ice_curves_todas_features")
guardar_figura_multi(plt, ruta_ice)
REGISTRO_FIGURAS.append((ruta_ice + ".png", "ICE Curves de todas las variables predictoras (submuestra de 80 instancias)."))
plt.show()
t11p = reportar_recursos("Bloque 11ter-B — PDP e ICE", t11p)

# =============================================================================
# 11bis. ESTABILIDAD SHAP MULTISEMILLA + BOOTSTRAP SHAP CI95% (OBS. #5 y #19)
# =============================================================================

print("\n" + "="*80 + "\n[📈 BLOQUE 11bis: ESTABILIDAD SHAP MULTISEMILLA — MEDIA / DESVIACIÓN / JACCARD TOP-K / BOOTSTRAP CI95%]\n" + "="*80)
t11b = time.time()
matriz_importancia_shap = []
top_k_sets = []
K_TOP = 3
for s in SEEDS:
    m_s = construir_modelo(study.best_params)
    try:
        m_s.set_params(random_state=s)
    except Exception:
        pass
    m_s.fit(X_tr_sc, y_train_puro)
    expl_s = shap.TreeExplainer(m_s)
    sv_s = expl_s(X_te_sc)
    if len(sv_s.shape) == 3 and sv_s.shape[2] == 2:
        vals_s = sv_s.values[:, :, 1]
    else:
        vals_s = sv_s.values
    imp_s = np.abs(vals_s).mean(0)
    matriz_importancia_shap.append(imp_s)
    top_k_sets.append(set(np.argsort(imp_s)[::-1][:K_TOP]))

matriz_importancia_shap = np.array(matriz_importancia_shap)
shap_mean = matriz_importancia_shap.mean(0)
shap_std = matriz_importancia_shap.std(0)
df_shap_stability = pd.DataFrame({"Feature": FEATURES, "SHAP_media": shap_mean, "SHAP_std": shap_std}).sort_values("SHAP_media", ascending=False)
print(df_shap_stability.to_string(index=False))

jaccards = []
for i in range(len(top_k_sets)):
    for j in range(i+1, len(top_k_sets)):
        inter = len(top_k_sets[i] & top_k_sets[j])
        union = len(top_k_sets[i] | top_k_sets[j])
        jaccards.append(inter / union if union > 0 else 1.0)
print(f"  📌 Jaccard Similarity promedio (Top-{K_TOP} features, {len(SEEDS)} semillas): {np.mean(jaccards):.4f}")
df_shap_stability.to_csv(os.path.join(DIR_SALIDA, "13_shap_estabilidad/shap_stability.csv"), index=False)

print("\n  🔄 Calculando Bootstrap SHAP CI95% (B=300, remuestreo de instancias)...")
shap_vals_base = shap_values.values
boot_shap_importancias = []
for b in range(300):
    idx_b = resample(np.arange(shap_vals_base.shape[0]), replace=True, random_state=SEED_BASE + b)
    boot_shap_importancias.append(np.abs(shap_vals_base[idx_b]).mean(axis=0))
boot_shap_importancias = np.array(boot_shap_importancias)
shap_ic_inf = np.percentile(boot_shap_importancias, 2.5, axis=0)
shap_ic_sup = np.percentile(boot_shap_importancias, 97.5, axis=0)
df_shap_bootstrap_ci = pd.DataFrame({
    "Feature": FEATURES,
    "SHAP_importancia_media": np.abs(shap_vals_base).mean(axis=0),
    "IC95_inf": shap_ic_inf,
    "IC95_sup": shap_ic_sup
}).sort_values("SHAP_importancia_media", ascending=False)
print(df_shap_bootstrap_ci.to_string(index=False))
df_shap_bootstrap_ci.to_csv(os.path.join(DIR_SALIDA, "31_shap_avanzado/shap_bootstrap_ci95.csv"), index=False)
REGISTRO_TABLAS.append(("Bootstrap SHAP CI95% (B=300)", df_shap_bootstrap_ci))
t11b = reportar_recursos("Bloque 11bis — Estabilidad SHAP multisemilla + Bootstrap CI95%", t11b)

# =============================================================================
# 11ter. PERMUTATION IMPORTANCE + IC VÍA BOOTSTRAP (OBSERVACIÓN #11 v19)
# =============================================================================

print("\n" + "="*80 + "\n[📈 BLOQUE 11ter: PERMUTATION IMPORTANCE CON INTERVALO DE CONFIANZA BOOTSTRAP]\n" + "="*80)
t11c = time.time()
perm_result = permutation_importance(model_global, X_te_sc, y_test_puro, n_repeats=50, random_state=SEED_BASE, scoring='roc_auc')
df_perm = pd.DataFrame({
    "Feature": FEATURES,
    "Importancia_media": perm_result.importances_mean,
    "IC95_inf": perm_result.importances_mean - 1.96 * perm_result.importances_std,
    "IC95_sup": perm_result.importances_mean + 1.96 * perm_result.importances_std
}).sort_values("Importancia_media", ascending=False)
print(df_perm.to_string(index=False))
df_perm.to_csv(os.path.join(DIR_SALIDA, "19_permutation_importance/permutation_importance.csv"), index=False)
t11c = reportar_recursos("Bloque 11ter — Permutation Importance", t11c)

# =============================================================================
# 11quater. ESTABILIDAD DE SELECCIÓN DE FEATURES — JACCARD MULTI-MÉTODO   [NUEVO v21]
#           MULTISEMILLA (SHAP + Permutation + importancia nativa)
# =============================================================================

print("\n" + "="*80 + "\n[🧬 BLOQUE 11quater: ESTABILIDAD DE SELECCIÓN DE FEATURES — JACCARD MULTI-MÉTODO MULTISEMILLA]\n" + "="*80)
t11d = time.time()
K_TOP_STAB = 3
top_sets_shap, top_sets_perm, top_sets_gain = [], [], []
for s in SEEDS:
    m_s = construir_modelo(study.best_params)
    try:
        m_s.set_params(random_state=s)
    except Exception:
        pass
    m_s.fit(X_tr_sc, y_train_puro)

    expl_s = shap.TreeExplainer(m_s)
    sv_s = expl_s(X_te_sc)
    vals_s = sv_s.values[:, :, 1] if (len(sv_s.shape) == 3 and sv_s.shape[2] == 2) else sv_s.values
    top_sets_shap.append(set(np.argsort(np.abs(vals_s).mean(0))[::-1][:K_TOP_STAB]))

    perm_s = permutation_importance(m_s, X_te_sc, y_test_puro, n_repeats=15, random_state=s, scoring='roc_auc')
    top_sets_perm.append(set(np.argsort(perm_s.importances_mean)[::-1][:K_TOP_STAB]))

    if hasattr(m_s, "feature_importances_"):
        top_sets_gain.append(set(np.argsort(m_s.feature_importances_)[::-1][:K_TOP_STAB]))

def _jaccard_promedio(lista_sets):
    if len(lista_sets) < 2:
        return np.nan
    vals = []
    for i in range(len(lista_sets)):
        for j in range(i + 1, len(lista_sets)):
            inter = len(lista_sets[i] & lista_sets[j])
            union = len(lista_sets[i] | lista_sets[j])
            vals.append(inter / union if union > 0 else 1.0)
    return float(np.mean(vals))

df_feature_stability = pd.DataFrame([
    {"Metodo": "SHAP |valor medio|", "Jaccard_promedio_TopK": _jaccard_promedio(top_sets_shap), "N_semillas": len(SEEDS)},
    {"Metodo": "Permutation Importance (AUC)", "Jaccard_promedio_TopK": _jaccard_promedio(top_sets_perm), "N_semillas": len(SEEDS)},
    {"Metodo": "Importancia nativa del modelo (gain/impurity)",
     "Jaccard_promedio_TopK": _jaccard_promedio(top_sets_gain) if top_sets_gain else np.nan,
     "N_semillas": len(SEEDS) if top_sets_gain else 0},
])
print(f"  📌 Estabilidad de selección de Top-{K_TOP_STAB} features en {len(SEEDS)} semillas (Jaccard, 1.0 = máxima estabilidad):")
print(df_feature_stability.round(4).to_string(index=False))
print("  💡 Un Jaccard promedio cercano a 1.0 indica que, más allá de la semilla aleatoria, distintos métodos")
print("     de atribución de importancia convergen en el mismo subconjunto de predictores, reforzando la")
print("     robustez del conjunto FEATURES elegido para el modelo final.")

df_feature_stability.to_csv(os.path.join(DIR_SALIDA, "43_feature_stability/feature_selection_stability.csv"), index=False)
REGISTRO_TABLAS.append(("Estabilidad de selección de features — Jaccard multi-método multisemilla", df_feature_stability))
t11d = reportar_recursos("Bloque 11quater — Estabilidad de selección de features", t11d)

# =============================================================================
# 12. TABLA COMPARATIVA EXPLÍCITA DE MÉTODOS (SOTA AMPLIADO — OBSERVACIÓN #3 v19)
#     [MODIFICADO v21: se agregan columnas Recall/Sensitivity y Average Precision]
# =============================================================================


print("Stage 07_explain_shap done.")
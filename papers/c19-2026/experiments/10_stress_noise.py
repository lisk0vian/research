# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 10: 10_stress_noise (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

print("\n" + "="*80 + "\n[🛡️ BLOQUE 13octies: ROBUSTNESS TEST — RUIDO ARTIFICIAL 5/10/20/30%]\n" + "="*80)
t13g = time.time()
resultados_ruido = []
for nivel_ruido in [0.05, 0.10, 0.20, 0.30]:
    rng_ruido = np.random.RandomState(SEED_BASE)
    ruido = rng_ruido.normal(0, nivel_ruido, X_tr_sc.shape) * X_tr_sc.std(axis=0)
    X_tr_ruidoso = X_tr_sc + ruido
    m_ruido = construir_modelo(study.best_params)
    m_ruido.fit(X_tr_ruidoso, y_train_puro)
    auc_ruido = roc_auc_score(y_test_puro, m_ruido.predict_proba(X_te_sc)[:,1])
    degradacion = base_auc - auc_ruido
    resultados_ruido.append({"Nivel_ruido_%": nivel_ruido*100, "AUC": auc_ruido, "Degradacion_vs_base": degradacion})
    print(f"  🔊 Ruido {nivel_ruido*100:.0f}% → AUC: {auc_ruido:.4f} | Degradación vs base: {degradacion:.4f}")

df_ruido = pd.DataFrame(resultados_ruido)
df_ruido.to_csv(os.path.join(DIR_SALIDA, "20_robustez_ruido/robustness_noise.csv"), index=False)
REGISTRO_TABLAS.append(("Robustness Test — degradación de AUC ante ruido artificial (5/10/20/30%)", df_ruido))
t13g = reportar_recursos("Bloque 13octies — Robustness Test Ruido", t13g)

# =============================================================================
# 13nonies. ERROR ANALYSIS AMPLIADO                                    [MODIFICADO v21]
#           TOP-20 FP/FN, IDENTIFICACIÓN GEOGRÁFICA Y SHAP DE ERRORES
# =============================================================================

print("\n" + "="*80 + "\n[🔎 BLOQUE 13nonies: ERROR ANALYSIS AMPLIADO — TOP-20 FP/FN, IDENTIFICACIÓN GEOGRÁFICA Y SHAP DE ERRORES]\n" + "="*80)
t13n = time.time()
df_errores = pd.DataFrame(X_test_puro, columns=FEATURES).reset_index(drop=False).rename(columns={'index': 'idx_original'})
df_errores['Y_real'] = y_test_puro
df_errores['Y_pred'] = preds_test_labels
df_errores['Prob'] = probs_test
df_errores['UBIGEO'] = df_activos.loc[X_test_puro.index, 'UBIGEO'].values
df_errores['DEPARTAMENTO'] = df_activos.loc[X_test_puro.index, 'DEPARTAMENTO'].values
df_errores['REGION_NATURAL'] = df_activos.loc[X_test_puro.index, 'REGION_NATURAL'].values

falsos_positivos = df_errores[(df_errores['Y_real'] == 0) & (df_errores['Y_pred'] == 1)].sort_values('Prob', ascending=False)
falsos_negativos = df_errores[(df_errores['Y_real'] == 1) & (df_errores['Y_pred'] == 0)].sort_values('Prob')
casos_limite = df_errores[(df_errores['Prob'] > 0.45) & (df_errores['Prob'] < 0.55)]

print(f"  📌 Falsos Positivos: {len(falsos_positivos)} | Falsos Negativos: {len(falsos_negativos)} | Casos límite (0.45-0.55): {len(casos_limite)}")

N_TOP_ERRORES = 20
top20_fp = falsos_positivos.head(N_TOP_ERRORES)
top20_fn = falsos_negativos.head(N_TOP_ERRORES)
print(f"\n  🔴 Top {N_TOP_ERRORES} Falsos Positivos (mayor confianza errónea):")
print(top20_fp.to_string(index=False))
print(f"\n  🔵 Top {N_TOP_ERRORES} Falsos Negativos (mayor confianza errónea):")
print(top20_fn.to_string(index=False))

print("\n  🌍 Distribución geográfica de errores por macrorregión:")
df_errores_region = df_errores[df_errores['Y_real'] != df_errores['Y_pred']].groupby('REGION_NATURAL').size().reset_index(name='N_errores')
print(df_errores_region.to_string(index=False))

print("\n  📸 [SHAP de errores] Generando waterfall plots para los 3 FP y 3 FN de mayor confianza errónea...")
pos_test_reset = {idx_val: pos for pos, idx_val in enumerate(df_errores['idx_original'])}
for etiqueta_grp, df_grupo in [("FP", top20_fp.head(3)), ("FN", top20_fn.head(3))]:
    for rank_i, (_, fila) in enumerate(df_grupo.iterrows()):
        pos_shap = pos_test_reset[fila['idx_original']]
        try:
            plt.figure(figsize=(7, 4))
            shap.plots.waterfall(shap_values[pos_shap], show=False)
            plt.title(f"SHAP Waterfall — Error {etiqueta_grp} #{rank_i+1} (UBIGEO {fila['UBIGEO']})", fontsize=9, fontweight='bold', pad=12)
            plt.tight_layout()
            ruta_err_shap = os.path.join(DIR_SALIDA, "22_error_analysis", f"shap_waterfall_{etiqueta_grp}_{rank_i+1}")
            guardar_figura_multi(plt, ruta_err_shap)
            REGISTRO_FIGURAS.append((ruta_err_shap + ".png", f"SHAP Waterfall del {etiqueta_grp} #{rank_i+1} (mayor confianza errónea), UBIGEO {fila['UBIGEO']}."))
            plt.show()
        except Exception as e:
            print(f"    ⚠️ No se pudo generar SHAP waterfall para {etiqueta_grp} #{rank_i+1}: {e}")

with pd.ExcelWriter(os.path.join(DIR_SALIDA, "22_error_analysis/error_analysis.csv")) as writer:
    falsos_positivos.to_csv(writer, sheet_name="Falsos_Positivos_TODOS", index=False)
    falsos_negativos.to_csv(writer, sheet_name="Falsos_Negativos_TODOS", index=False)
    top20_fp.to_csv(writer, sheet_name=f"Top{N_TOP_ERRORES}_FP", index=False)
    top20_fn.to_csv(writer, sheet_name=f"Top{N_TOP_ERRORES}_FN", index=False)
    casos_limite.to_csv(writer, sheet_name="Casos_Limite", index=False)
    df_errores_region.to_csv(writer, sheet_name="Errores_por_Region", index=False)

df_error_resumen = pd.DataFrame([{
    "Falsos_Positivos": len(falsos_positivos), "Falsos_Negativos": len(falsos_negativos),
    "Casos_Limite_0.45_0.55": len(casos_limite), "N_test_total": len(y_test_puro)
}])
REGISTRO_TABLAS.append(("Resumen de Error Analysis (FP/FN/casos límite)", df_error_resumen))
REGISTRO_TABLAS.append((f"Top {N_TOP_ERRORES} Falsos Positivos (mayor confianza errónea)", top20_fp))
REGISTRO_TABLAS.append((f"Top {N_TOP_ERRORES} Falsos Negativos (mayor confianza errónea)", top20_fn))
REGISTRO_TABLAS.append(("Distribución geográfica de errores por macrorregión", df_errores_region))
t13n = reportar_recursos("Bloque 13nonies — Error Analysis ampliado", t13n)

# =============================================================================
# 13decies. DECISION CURVE ANALYSIS (OBSERVACIÓN #15 v19)
# =============================================================================

print("\n" + "="*80 + "\n[⚕️ BLOQUE 13decies: DECISION CURVE ANALYSIS — UTILIDAD CLÍNICA/OPERATIVA]\n" + "="*80)
umbrales_dca = np.arange(0.01, 0.99, 0.01)
n_test = len(y_test_puro)
beneficio_neto_modelo, beneficio_neto_todos, beneficio_neto_nadie = [], [], []
prevalencia = y_test_puro.mean()
for pt in umbrales_dca:
    pred_pt = (probs_test >= pt).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_test_puro, pred_pt, labels=[0,1]).ravel()
    bn_modelo = (tp/n_test) - (fp/n_test) * (pt/(1-pt))
    bn_todos = prevalencia - (1 - prevalencia) * (pt/(1-pt))
    beneficio_neto_modelo.append(bn_modelo)
    beneficio_neto_todos.append(bn_todos)
    beneficio_neto_nadie.append(0.0)

plt.figure(figsize=(7,4))
plt.plot(umbrales_dca, beneficio_neto_modelo, label="Modelo INVS-ML", linewidth=2)
plt.plot(umbrales_dca, beneficio_neto_todos, label="Priorizar a Todos", linestyle='--')
plt.plot(umbrales_dca, beneficio_neto_nadie, label="No Priorizar a Nadie", linestyle=':')
plt.xlabel("Umbral de Decisión (Probabilidad)")
plt.ylabel("Beneficio Neto")
plt.title("Decision Curve Analysis — Priorización de Infraestructura", fontsize=10, fontweight='bold')
plt.legend()
plt.tight_layout()
ruta_dca = os.path.join(DIR_SALIDA, "23_decision_curve/decision_curve_analysis")
guardar_figura_multi(plt, ruta_dca)
REGISTRO_FIGURAS.append((ruta_dca + ".png", "Decision Curve Analysis comparando el modelo vs estrategias triviales."))
plt.show()
print(f"  📌 Rango de umbrales donde el modelo supera a 'priorizar a todos' y 'a nadie': revisar gráfico exportado.")

df_dca_export = pd.DataFrame({"Umbral": umbrales_dca, "Beneficio_Modelo": beneficio_neto_modelo,
                               "Beneficio_Todos": beneficio_neto_todos, "Beneficio_Nadie": beneficio_neto_nadie})
df_dca_export.to_csv(os.path.join(DIR_SALIDA, "23_decision_curve/decision_curve.csv"), index=False)

# =============================================================================
# 13undecies. ANÁLISIS ECONÓMICO — COSTO/BENEFICIO (OBSERVACIÓN #16 v19)
# =============================================================================


print("Stage 10_stress_noise done.")
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 06: 06_evaluate_classifier (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

print("\n" + "="*80 + "\n[📊 BLOQUE 7: BOOTSTRAP DE RIGOR (B=2000) PARA INTERVALOS DE CONFIANZA IC95%]\n" + "="*80)
boot_auc, boot_f1, boot_brier, boot_mcc, boot_kappa, boot_bacc = [], [], [], [], [], []
preds_test_labels = model_global.predict(X_te_sc)

for b in range(2000):
    idx_b = resample(np.arange(len(y_test_puro)), replace=True, random_state=SEED_BASE + b)
    if len(np.unique(y_test_puro[idx_b])) < 2: continue
    boot_auc.append(roc_auc_score(y_test_puro[idx_b], probs_test[idx_b]))
    boot_f1.append(f1_score(y_test_puro[idx_b], preds_test_labels[idx_b]))
    boot_brier.append(brier_score_loss(y_test_puro[idx_b], probs_test[idx_b]))
    boot_mcc.append(matthews_corrcoef(y_test_puro[idx_b], preds_test_labels[idx_b]))
    boot_kappa.append(cohen_kappa_score(y_test_puro[idx_b], preds_test_labels[idx_b]))
    boot_bacc.append(balanced_accuracy_score(y_test_puro[idx_b], preds_test_labels[idx_b]))

dict_bootstrap_ic = {
    "AUC": boot_auc, "F1": boot_f1, "Brier": boot_brier,
    "MCC": boot_mcc, "Cohen_Kappa": boot_kappa, "Balanced_Accuracy": boot_bacc
}
filas_bootstrap = []
for nombre_metrica, valores in dict_bootstrap_ic.items():
    inf, sup = np.percentile(valores, 2.5), np.percentile(valores, 97.5)
    print(f"  📌 {nombre_metrica:<18} IC95%: [{inf:.4f} - {sup:.4f}] | Media: {np.mean(valores):.4f}")
    filas_bootstrap.append({"Metrica": nombre_metrica, "Media": np.mean(valores), "IC95_inf": inf, "IC95_sup": sup})
df_bootstrap_export = pd.DataFrame(filas_bootstrap)
df_bootstrap_export.to_csv(os.path.join(DIR_SALIDA, "28_metricas_extendidas/bootstrap.csv"), index=False)
REGISTRO_TABLAS.append(("Bootstrap (B=2000) — IC95% de métricas", df_bootstrap_export))


print("\n" + "="*80 + "\n[📊 BLOQUE 7bis-A: CURVA ROC Y MATRIZ DE CONFUSIÓN (ESENCIALES PARA Q1)]\n" + "="*80)
from sklearn.metrics import ConfusionMatrixDisplay
fpr_roc, tpr_roc, _ = roc_curve(y_test_puro, probs_test)
auc_roc_plot = roc_auc_score(y_test_puro, probs_test)

plt.figure(figsize=(5.5, 5))
plt.plot(fpr_roc, tpr_roc, linewidth=2, label=f"Modelo (AUC={auc_roc_plot:.3f})")
plt.plot([0,1],[0,1], linestyle='--', color='gray', label="Azar (AUC=0.50)")
plt.xlabel("Tasa de Falsos Positivos (1 - Especificidad)")
plt.ylabel("Tasa de Verdaderos Positivos (Sensibilidad)")
plt.title("Curva ROC — Modelo Final", fontsize=10, fontweight='bold', pad=10)
plt.legend()
plt.tight_layout()
ruta_roc = os.path.join(DIR_SALIDA, "33_metricas_clasificacion/roc_curve")
guardar_figura_multi(plt, ruta_roc)
REGISTRO_FIGURAS.append((ruta_roc + ".png", f"Curva ROC del modelo final en el set de prueba (AUC = {auc_roc_plot:.3f})."))
plt.show()
pd.DataFrame({"FPR": fpr_roc, "TPR": tpr_roc}).to_csv(os.path.join(DIR_SALIDA, "33_metricas_clasificacion/roc_curve_values.csv"), index=False)

cm_global = confusion_matrix(y_test_puro, preds_test_labels, labels=[0,1])
fig_cm, ax_cm = plt.subplots(figsize=(4.5, 4.5))
ConfusionMatrixDisplay(cm_global, display_labels=["No Vulnerable","Vulnerable"]).plot(ax=ax_cm, cmap="Blues", colorbar=False)
ax_cm.set_title("Matriz de Confusión — Modelo Final", fontsize=10, fontweight='bold', pad=10)
plt.tight_layout()
ruta_cm = os.path.join(DIR_SALIDA, "33_metricas_clasificacion/confusion_matrix")
guardar_figura_multi(plt, ruta_cm)
REGISTRO_FIGURAS.append((ruta_cm + ".png", "Matriz de confusión del modelo final en el set de prueba."))
plt.show()
pd.DataFrame(cm_global, index=["Real_0","Real_1"], columns=["Pred_0","Pred_1"]).to_csv(
    os.path.join(DIR_SALIDA, "33_metricas_clasificacion/confusion_matrix.csv"))

# =============================================================================
# 7bis. MÉTRICAS DE CLASIFICACIÓN EXTENDIDAS (OBSERVACIONES #12, #13, #14, #15)
# =============================================================================

print("\n" + "="*80 + "\n[📐 BLOQUE 7bis: MÉTRICAS DE CLASIFICACIÓN EXTENDIDAS — MCC / KAPPA / BACC / SENS / ESPEC / PPV / NPV]\n" + "="*80)
tn_g, fp_g, fn_g, tp_g = confusion_matrix(y_test_puro, preds_test_labels, labels=[0,1]).ravel()
sensibilidad = tp_g / (tp_g + fn_g) if (tp_g + fn_g) > 0 else np.nan
especificidad = tn_g / (tn_g + fp_g) if (tn_g + fp_g) > 0 else np.nan
ppv = tp_g / (tp_g + fp_g) if (tp_g + fp_g) > 0 else np.nan
npv = tn_g / (tn_g + fn_g) if (tn_g + fn_g) > 0 else np.nan
mcc_global = matthews_corrcoef(y_test_puro, preds_test_labels)
kappa_global = cohen_kappa_score(y_test_puro, preds_test_labels)
bacc_global = balanced_accuracy_score(y_test_puro, preds_test_labels)

metricas_clasificacion_dict = {
    "AUC-ROC": roc_auc_score(y_test_puro, probs_test),
    "F1-Score": f1_score(y_test_puro, preds_test_labels),
    "Accuracy": accuracy_score(y_test_puro, preds_test_labels),
    "Balanced_Accuracy": bacc_global,
    "MCC": mcc_global,
    "Cohen_Kappa": kappa_global,
    "Sensitivity_Recall": sensibilidad,
    "Specificity": especificidad,
    "PPV_Precision": ppv,
    "NPV": npv,
    "Brier_Score": brier_score_loss(y_test_puro, probs_test)
}
for k, v in metricas_clasificacion_dict.items():
    print(f"  📌 {k:<22}: {v:.4f}")
df_metricas_clasificacion = pd.DataFrame([metricas_clasificacion_dict])
df_metricas_clasificacion.to_csv(os.path.join(DIR_SALIDA, "33_metricas_clasificacion/metricas_clasificacion_extendidas.csv"), index=False)
REGISTRO_TABLAS.append(("Métricas de clasificación extendidas", df_metricas_clasificacion))

# =============================================================================
# 7ter. PRECISION-RECALL CURVE + AVERAGE PRECISION (OBSERVACIÓN #11)
# =============================================================================

print("\n" + "="*80 + "\n[📈 BLOQUE 7ter: PRECISION-RECALL CURVE Y AVERAGE PRECISION]\n" + "="*80)
precision_arr, recall_arr, thresholds_pr = precision_recall_curve(y_test_puro, probs_test)
avg_precision = average_precision_score(y_test_puro, probs_test)
print(f"  📌 Average Precision (AP): {avg_precision:.4f}")

plt.figure(figsize=(6, 4.5))
plt.plot(recall_arr, precision_arr, linewidth=2, label=f"Modelo (AP={avg_precision:.3f})")
plt.axhline(y=y_test_puro.mean(), linestyle='--', color='gray', label=f"Baseline (prevalencia={y_test_puro.mean():.3f})")
plt.xlabel("Recall (Sensibilidad)")
plt.ylabel("Precision (PPV)")
plt.title("Curva Precision-Recall", fontsize=10, fontweight='bold', pad=10)
plt.legend()
plt.tight_layout()
ruta_pr = os.path.join(DIR_SALIDA, "33_metricas_clasificacion/precision_recall_curve")
guardar_figura_multi(plt, ruta_pr)
REGISTRO_FIGURAS.append((ruta_pr + ".png", f"Curva Precision-Recall del modelo final (Average Precision = {avg_precision:.3f})."))
plt.show()

pd.DataFrame({"Precision": precision_arr[:-1], "Recall": recall_arr[:-1], "Threshold": thresholds_pr}).to_csv(
    os.path.join(DIR_SALIDA, "33_metricas_clasificacion/precision_recall_values.csv"), index=False)

# =============================================================================
# 7quater. OPTIMIZACIÓN DEL UMBRAL DE DECISIÓN                        [NUEVO v21]
#          YOUDEN / COSTO-SENSIBLE / CLASS WEIGHT / F-BETA
# =============================================================================

print("\n" + "="*80 + "\n[🎚️ BLOQUE 7quater: OPTIMIZACIÓN DEL UMBRAL DE DECISIÓN — YOUDEN / COSTO-SENSIBLE / CLASS WEIGHT / F-BETA]\n" + "="*80)
t7q = time.time()
fpr_thr, tpr_thr, thr_roc = roc_curve(y_test_puro, probs_test)

# 1) Índice de Youden (J = Sensibilidad + Especificidad - 1)
youden_j = tpr_thr - fpr_thr
umbral_youden = float(thr_roc[np.argmax(youden_j)])

# 2) Umbral costo-sensible: minimiza costo esperado = C_FN·FN + C_FP·FP
#    Supuesto editable: en priorización sanitaria, omitir un distrito
#    vulnerable (Falso Negativo) se asume más costoso que sobre-priorizar
#    uno que no lo era (Falso Positivo).
COSTO_FN = 5.0
COSTO_FP = 1.0
umbrales_candidatos = np.linspace(0.01, 0.99, 99)
costos_esperados = []
for u in umbrales_candidatos:
    pred_u = (probs_test >= u).astype(int)
    tn_u, fp_u, fn_u, tp_u = confusion_matrix(y_test_puro, pred_u, labels=[0, 1]).ravel()
    costos_esperados.append(COSTO_FN * fn_u + COSTO_FP * fp_u)
umbral_costo_sensible = float(umbrales_candidatos[int(np.argmin(costos_esperados))])

# 3) Umbral ajustado por desbalance de clases: p* = w0 / (w0 + w1)
pesos_clase = compute_class_weight(class_weight='balanced', classes=np.array([0, 1]), y=y_train_puro)
umbral_class_weight = float(pesos_clase[0] / (pesos_clase[0] + pesos_clase[1]))

# 4) Umbral que maximiza F-beta (beta=2 → prioriza Recall sobre Precision)
BETA_F = 2.0
fbeta_por_umbral = [fbeta_score(y_test_puro, (probs_test >= u).astype(int), beta=BETA_F, zero_division=0)
                     for u in umbrales_candidatos]
umbral_fbeta = float(umbrales_candidatos[int(np.argmax(fbeta_por_umbral))])

def _resumen_umbral(nombre, u):
    pred_u = (probs_test >= u).astype(int)
    return {
        "Estrategia": nombre, "Umbral": round(float(u), 4),
        "Sensitivity_Recall": recall_score(y_test_puro, pred_u, zero_division=0),
        "Specificity": recall_score(1 - y_test_puro, 1 - pred_u, zero_division=0),
        "Precision_PPV": precision_score(y_test_puro, pred_u, zero_division=0),
        "F1": f1_score(y_test_puro, pred_u, zero_division=0),
        "F2": fbeta_score(y_test_puro, pred_u, beta=2, zero_division=0),
        "MCC": matthews_corrcoef(y_test_puro, pred_u),
        "Balanced_Accuracy": balanced_accuracy_score(y_test_puro, pred_u),
    }

tabla_umbrales = pd.DataFrame([
    _resumen_umbral("Default (0.50)", 0.50),
    _resumen_umbral("Youden's J (max Sens+Espec-1)", umbral_youden),
    _resumen_umbral(f"Costo-sensible (C_FN={COSTO_FN:.0f}:C_FP={COSTO_FP:.0f})", umbral_costo_sensible),
    _resumen_umbral("Ajustado por class-weight balanceado", umbral_class_weight),
    _resumen_umbral(f"Max F{BETA_F:.0f}-score", umbral_fbeta),
])
print(tabla_umbrales.round(4).to_string(index=False))
print("\n  💡 Para priorización sanitaria, donde omitir un distrito vulnerable (Falso Negativo) es más costoso")
print("     que sobre-priorizar uno (Falso Positivo), el umbral por defecto de 0.50 rara vez es óptimo. Se")
print("     recomienda declarar en el manuscrito cuál umbral se usó para los resultados operativos del")
print("     análisis económico (Bloque 13undecies) y por qué.")

plt.figure(figsize=(6.5, 4.5))
plt.plot(umbrales_candidatos, costos_esperados, label=f"Costo esperado (C_FN={COSTO_FN:.0f}:C_FP={COSTO_FP:.0f})", linewidth=2)
plt.axvline(umbral_costo_sensible, linestyle='--', color='crimson', label=f"Umbral óptimo = {umbral_costo_sensible:.2f}")
plt.xlabel("Umbral de decisión")
plt.ylabel("Costo esperado (unidades ponderadas)")
plt.title("Optimización de Umbral — Enfoque Costo-Sensible", fontsize=10, fontweight='bold', pad=10)
plt.legend()
plt.tight_layout()
ruta_umbral_fig = os.path.join(DIR_SALIDA, "41_threshold_optimization/costo_sensible_umbral")
guardar_figura_multi(plt, ruta_umbral_fig)
REGISTRO_FIGURAS.append((ruta_umbral_fig + ".png", "Curva de costo esperado en función del umbral de decisión y umbral óptimo costo-sensible."))
plt.show()

tabla_umbrales.to_csv(os.path.join(DIR_SALIDA, "41_threshold_optimization/tabla_umbrales.csv"), index=False)
REGISTRO_TABLAS.append(("Optimización de umbral de decisión (Youden / costo-sensible / class-weight / F-beta)", tabla_umbrales))
t7q = reportar_recursos("Bloque 7quater — Optimización de umbral", t7q)

# =============================================================================
# 8. PRUEBAS ESTADÍSTICAS FORMALES DE SIGNIFICANCIA (FRIEDMAN / WILCOXON)
# =============================================================================

print("\n" + "="*80 + "\n[📊 BLOQUE 8: INFERENCIA ESTADÍSTICA DE RENDIMIENTO (FRIEDMAN & WILCOXON POST-HOC)]\n" + "="*80)
matriz_semillas = []
for s in SEEDS:
    # CORRECCIÓN (observación de Edith): esta comparación multisemilla volvía a
    # usar train_test_split aleatorio (sin agrupar por UBIGEO), reintroduciendo
    # la misma fuga de información entre train/test que se corrigió en la
    # partición principal. Se reemplaza por GroupShuffleSplit agrupado por
    # distrito, igual que en el split principal del pipeline.
    gss_s = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=s)
    idx_tr_s, idx_te_s = next(gss_s.split(X_ml, y_ml, groups=groups_ubigeo_ml))
    X_tr_s, X_te_s = X_ml.iloc[idx_tr_s], X_ml.iloc[idx_te_s]
    y_tr_s, y_te_s = y_ml[idx_tr_s], y_ml[idx_te_s]
    pipe_s = Pipeline([('imputer', SimpleImputer(strategy='median')), ('scaler', StandardScaler())])
    X_tr_s_sc = pipe_s.fit_transform(X_tr_s)
    X_te_s_sc = pipe_s.transform(X_te_s)

    auc_lgb = roc_auc_score(y_te_s, lgb.LGBMClassifier(verbosity=-1, random_state=s).fit(X_tr_s_sc, y_tr_s).predict_proba(X_te_s_sc)[:,1])
    auc_rf  = roc_auc_score(y_te_s, RandomForestClassifier(random_state=s).fit(X_tr_s_sc, y_tr_s).predict_proba(X_te_s_sc)[:,1])
    auc_lr  = roc_auc_score(y_te_s, LogisticRegression(random_state=s).fit(X_tr_s_sc, y_tr_s).predict_proba(X_te_s_sc)[:,1])
    matriz_semillas.append([auc_lgb, auc_rf, auc_lr])

stat_f, p_f = friedmanchisquare(*np.array(matriz_semillas).T)
print(f"  📌 Chi-Square de Friedman: {stat_f:.4f} | p-valor Global: {p_f:.4e}")
w_stat, w_p = wilcoxon(np.array(matriz_semillas)[:,0], np.array(matriz_semillas)[:,1])
print(f"  📌 Post-Hoc Wilcoxon (LightGBM vs RandomForest) p-valor: {w_p:.4e}")
pd.DataFrame(matriz_semillas, columns=["LightGBM","RandomForest","LogisticRegression"]).to_csv(
    os.path.join(DIR_SALIDA, "28_metricas_extendidas/matriz_semillas_friedman.csv"), index=False)

# =============================================================================
# 9. MONITOREO DE DATA DRIFT
# =============================================================================

print("\n" + "="*80 + "\n[📊 BLOQUE 9: MONITOREO DE COVARIATE SHIFT - ESTABILIDAD POBLACIONAL KS]\n" + "="*80)
drift_resultados = []
for i, feat in enumerate(FEATURES):
    ks_stat, p_val_ks = ks_2samp(X_tr_sc[:, i], X_te_sc[:, i])
    print(f"  🔍 Feature: {feat:<30} | KS Statistic: {ks_stat:.4f} | p-valor Drift: {p_val_ks:.4e}")
    drift_resultados.append({"Feature": feat, "KS_statistic": ks_stat, "p_valor": p_val_ks})
pd.DataFrame(drift_resultados).to_csv(os.path.join(DIR_SALIDA, "28_metricas_extendidas/drift.csv"), index=False)
REGISTRO_TABLAS.append(("Monitoreo de Data Drift (KS test) train vs test", pd.DataFrame(drift_resultados)))

# =============================================================================
# 10. CALIBRACIÓN AVANZADA Y AUDITORÍA DE EQUIDAD INTERSECCIONAL (FAIRNESS)
# =============================================================================


print("Stage 06_evaluate_classifier done.")
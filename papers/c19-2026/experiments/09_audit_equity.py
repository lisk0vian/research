# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 09: 09_audit_equity (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

print("\n" + "="*80 + "\n[📊 BLOQUE 10: CALIBRACIÓN DE PROBABILIDADES Y PROTOCOLOS DE EQUIDAD SOCIAL]\n" + "="*80)
prob_true, prob_pred = calibration_curve(y_test_puro, probs_test, n_bins=10, strategy='uniform')
ece = np.mean(np.abs(prob_true - prob_pred))
print(f"📌 Expected Calibration Error (ECE): {ece:.4f}")

plt.figure(figsize=(6, 4.5))
plt.plot(prob_pred, prob_true, marker='o', label=f"Modelo (ECE={ece:.3f})")
plt.plot([0,1],[0,1], linestyle='--', color='gray', label="Calibración perfecta")
plt.xlabel("Probabilidad Predicha Media")
plt.ylabel("Frecuencia Observada")
plt.title("Curva de Calibración", fontsize=10, fontweight='bold', pad=10)
plt.legend()
plt.tight_layout()
ruta_calib = os.path.join(DIR_SALIDA, "34_calibracion_avanzada/calibration_curve")
guardar_figura_multi(plt, ruta_calib)
REGISTRO_FIGURAS.append((ruta_calib + ".png", f"Curva de calibración de probabilidades (ECE = {ece:.3f})."))
plt.show()

df_fair = pd.DataFrame({'REGION': df_activos.loc[X_test_puro.index, 'REGION_NATURAL'], 'Y_TRUE': y_test_puro, 'Y_PRED': preds_test_labels})
tprs_f = {}
fairness_rows = []
for name, grp in df_fair.groupby('REGION'):
    tn, fp, fn, tp = confusion_matrix(grp['Y_TRUE'], grp['Y_PRED'], labels=[0,1]).ravel()
    tprs_f[name] = tp / (tp + fn) if (tp + fn) > 0 else 0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
    tasa_seleccion = grp['Y_PRED'].mean()
    print(f"  🌍 Macrozona: {name:<10} | TPR (Equal Opp.): {tprs_f[name]:.4f} | FPR: {fpr:.4f} | Tasa de Selección: {tasa_seleccion:.4f}")
    fairness_rows.append({"Region": name, "TPR": tprs_f[name], "FPR": fpr, "Tasa_seleccion": tasa_seleccion, "N": len(grp)})

eod = max(tprs_f.values()) - min(tprs_f.values())
print(f"  ⚖️ Equal Opportunity Difference (EOD): {eod:.4f}")
df_fairness = pd.DataFrame(fairness_rows)
df_fairness.to_csv(os.path.join(DIR_SALIDA, "28_metricas_extendidas/fairness.csv"), index=False)
REGISTRO_TABLAS.append(("Auditoría de equidad por macrorregión", df_fairness))

# =============================================================================
# 10bis. HOSMER-LEMESHOW TEST (OBSERVACIÓN #16)
# =============================================================================

print("\n" + "="*80 + "\n[🧪 BLOQUE 10bis: HOSMER-LEMESHOW GOODNESS-OF-FIT TEST PARA LA CALIBRACIÓN]\n" + "="*80)
def hosmer_lemeshow_test(y_true, y_prob, n_grupos=10):
    df_hl = pd.DataFrame({"y": y_true, "p": y_prob})
    df_hl['decil'] = pd.qcut(df_hl['p'], n_grupos, duplicates='drop')
    tabla = df_hl.groupby('decil').agg(Observado_1=('y', 'sum'), N=('y', 'count'), Prob_media=('p', 'mean'))
    tabla['Esperado_1'] = tabla['Prob_media'] * tabla['N']
    tabla['Observado_0'] = tabla['N'] - tabla['Observado_1']
    tabla['Esperado_0'] = tabla['N'] - tabla['Esperado_1']
    chi2_stat = (((tabla['Observado_1'] - tabla['Esperado_1'])**2 / tabla['Esperado_1'].replace(0, np.nan)) +
                 ((tabla['Observado_0'] - tabla['Esperado_0'])**2 / tabla['Esperado_0'].replace(0, np.nan))).sum()
    gl = n_grupos - 2
    p_val = 1 - chi2.cdf(chi2_stat, gl) if gl > 0 else np.nan
    return chi2_stat, p_val, tabla

hl_stat, hl_p, tabla_hl = hosmer_lemeshow_test(y_test_puro, probs_test, n_grupos=10)
print(f"  📌 Estadístico Hosmer-Lemeshow: {hl_stat:.4f} | p-valor: {hl_p:.4f}")
print("  💡 Interpretación: p-valor alto (>0.05) sugiere buen ajuste de calibración (no se rechaza H0).")
tabla_hl.to_csv(os.path.join(DIR_SALIDA, "34_calibracion_avanzada/hosmer_lemeshow.csv"))
REGISTRO_TABLAS.append(("Hosmer-Lemeshow Goodness-of-Fit", tabla_hl.reset_index()))

# =============================================================================
# 11. EXPLICABILIDAD POST-HOC MULTI-GRÁFICO SHAP (RENDER TOTAL EN CONSOLA)
# =============================================================================


print("Stage 09_audit_equity done.")
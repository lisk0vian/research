# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 01: 01_clean_renipress (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

print("\n" + "="*80 + "\n[🧪 BLOQUE 0bis: DATA QUALITY ASSESSMENT — MISSINGNESS / DUPLICADOS / OUTLIERS / COBERTURA]\n" + "="*80)
t0 = time.time()
reporte_calidad = []
for col in ['UBIGEO', 'DEPARTAMENTO', 'ESTADO', 'CATEGORIA', 'NORTE', 'ESTE']:
    if col in df.columns:
        faltantes = df[col].isna().mean() * 100
        reporte_calidad.append({"Variable": col, "Faltantes_%": round(faltantes, 2)})
df_calidad = pd.DataFrame(reporte_calidad)
n_duplicados_originales = N_ANTES_DEDUP - N_DESPUES_DEDUP
print(f"  📋 Duplicados detectados (antes de drop): {n_duplicados_originales}")
print(df_calidad.to_string(index=False))

def outliers_iqr(serie):
    q1, q3 = serie.quantile(0.25), serie.quantile(0.75)
    iqr = q3 - q1
    lim_inf, lim_sup = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return ((serie < lim_inf) | (serie > lim_sup)).mean() * 100

outliers_resumen = []
for col_num in ['NORTE', 'ESTE']:
    serie_num = pd.to_numeric(df[col_num].astype(str).str.replace(',', '.', regex=False), errors='coerce').dropna()
    pct_out = outliers_iqr(serie_num)
    print(f"  📌 Outliers IQR en {col_num}: {pct_out:.2f}%")
    outliers_resumen.append({"Variable": col_num, "Outliers_IQR_%": round(pct_out, 2)})

cobertura_dptos = df['DEPARTAMENTO'].nunique() if 'DEPARTAMENTO' in df.columns else np.nan
print(f"  🗺️ Cobertura geográfica: {cobertura_dptos} departamentos representados en RENIPRESS")
df_calidad.to_csv(os.path.join(DIR_SALIDA, "21_calidad_datos/data_quality_report.csv"), index=False)
pd.DataFrame(outliers_resumen).to_csv(os.path.join(DIR_SALIDA, "21_calidad_datos/outliers_iqr.csv"), index=False)
t0 = reportar_recursos("Data Quality Assessment", t0)

# =============================================================================
# 1. AUDITORÍA GEOESPACIAL Y FILTRADO POR CONSENSO DE ANOMALÍAS ESPACIALES
# =============================================================================


try:
    save_df_activos()
except Exception as e:
    print("persist failed:", e)

print("Stage 01_clean_renipress done.")
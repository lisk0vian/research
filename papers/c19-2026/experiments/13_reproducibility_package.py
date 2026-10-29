# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 13: 13_reproducibility_package (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

print("\n" + "="*80 + "\n[🗺️ BLOQUE 14: FIGURA RESUMEN DEL PIPELINE Y FLOWCHART TIPO PRISMA]\n" + "="*80)

def dibujar_caja(ax, x, y, w, h, texto, color="#1f6f8b"):
    rect = plt.Rectangle((x, y), w, h, facecolor=color, edgecolor="black", alpha=0.85, zorder=2)
    ax.add_patch(rect)
    ax.text(x + w/2, y + h/2, texto, ha='center', va='center', fontsize=8.5,
             color='white', fontweight='bold', wrap=True, zorder=3)

etapas_pipeline = [
    "RENIPRESS\n(Ingesta)", "Data Quality\nAssessment", "Auditoría\nEspacial",
    "Construcción\nINVS", "Machine\nLearning", "Validación\n(Externa/LODO/Temporal)",
    "Explicabilidad\n(SHAP/PDP/ICE)", "Soporte de\nDecisión (DCA/Económico)"
]
fig_pipe, ax_pipe = plt.subplots(figsize=(13, 2.6))
ax_pipe.set_xlim(0, len(etapas_pipeline) * 2)
ax_pipe.set_ylim(0, 2)
for i, etapa in enumerate(etapas_pipeline):
    dibujar_caja(ax_pipe, i*2 + 0.1, 0.4, 1.7, 1.2, etapa)
    if i < len(etapas_pipeline) - 1:
        ax_pipe.annotate("", xy=(i*2 + 2.0, 1.0), xytext=(i*2 + 1.8, 1.0),
                          arrowprops=dict(arrowstyle="->", lw=1.8, color='black'))
ax_pipe.axis('off')
ax_pipe.set_title("Figura: Flujo General del Pipeline INVS", fontsize=11, fontweight='bold')
plt.tight_layout()
ruta_pipeline_fig = os.path.join(DIR_SALIDA, "29_figuras_pipeline/pipeline_general")
guardar_figura_multi(plt, ruta_pipeline_fig)
REGISTRO_FIGURAS.append((ruta_pipeline_fig + ".png", "Figura resumen del flujo general del pipeline metodológico."))
plt.show()

fig_prisma, ax_prisma = plt.subplots(figsize=(7, 9))
ax_prisma.set_xlim(0, 10)
ax_prisma.set_ylim(0, 22)
cajas_prisma = [
    (f"Registros crudos RENIPRESS\n(n = {N_FILAS_CRUDAS_RENIPRESS:,})", 18.5),
    (f"Tras eliminación de duplicados\n(n = {N_DESPUES_DEDUP:,}; excluidos = {n_duplicados_originales:,})", 15.5),
    (f"Establecimientos ACTIVOS\n(n = {N_ACTIVOS:,}; excluidos inactivos = {N_INACTIVOS_EXCLUIDOS:,})", 12.5),
    (f"Coordenadas geográficas válidas\n(n = {N_COORDS_VALIDAS:,}; inválidas = {N_COORDS_INVALIDAS:,})", 9.5),
    (f"Unión con datos poblacionales INEI\ny construcción de variables derivadas", 6.5),
    (f"Muestra final de análisis\n(n = {N_FINAL_ANALISIS:,})", 3.0),
]
for texto, y_pos in cajas_prisma:
    dibujar_caja(ax_prisma, 1.0, y_pos, 8.0, 2.2, texto, color="#274472")
for i in range(len(cajas_prisma) - 1):
    y_origen = cajas_prisma[i][1]
    y_destino = cajas_prisma[i+1][1] + 2.2
    ax_prisma.annotate("", xy=(5.0, y_origen + 0.0), xytext=(5.0, y_destino),
                        arrowprops=dict(arrowstyle="->", lw=1.8, color='black'))
ax_prisma.axis('off')
ax_prisma.set_title("Diagrama de Flujo tipo PRISMA — Filtrado de Datos RENIPRESS", fontsize=11, fontweight='bold', pad=15)
plt.tight_layout()
ruta_prisma_fig = os.path.join(DIR_SALIDA, "29_figuras_pipeline/flowchart_prisma")
guardar_figura_multi(plt, ruta_prisma_fig)
REGISTRO_FIGURAS.append((ruta_prisma_fig + ".png", "Diagrama de flujo tipo PRISMA del proceso de filtrado de datos."))
plt.show()

# =============================================================================
# 15. TABLA RESUMEN DEL DATASET (TABLA 1) Y TABLA FINAL DE VARIABLES (OBS. #6 y #7)
# =============================================================================

print("\n" + "="*80 + "\n[📋 BLOQUE 15: TABLA 1 (RESUMEN DEL DATASET) Y TABLA DE VARIABLES]\n" + "="*80)
tabla1_dict = {
    "Establecimientos crudos (RENIPRESS)": N_FILAS_CRUDAS_RENIPRESS,
    "Duplicados eliminados": n_duplicados_originales,
    "Establecimientos ACTIVOS": N_ACTIVOS,
    "Establecimientos INACTIVOS excluidos": N_INACTIVOS_EXCLUIDOS,
    "Coordenadas geográficas válidas": N_COORDS_VALIDAS,
    "Coordenadas geográficas inválidas": N_COORDS_INVALIDAS,
    "Departamentos representados": int(cobertura_dptos) if not pd.isna(cobertura_dptos) else "N/D",
    "Distritos únicos (UBIGEO)": df_activos['UBIGEO'].nunique(),
    "Muestra final de análisis (n)": N_FINAL_ANALISIS,
    "Prevalencia del target VULNERABLE (%)": round(df_activos['VULNERABLE'].mean()*100, 2),
    "Variables predictoras utilizadas": len(FEATURES),
    "Dimensiones del índice INVS": len(COLS_INVS),
}
df_tabla1 = pd.DataFrame(list(tabla1_dict.items()), columns=["Descripción", "Valor"])
print(df_tabla1.to_string(index=False))
df_tabla1.to_csv(os.path.join(DIR_SALIDA, "30_tablas_dataset/tabla1_resumen_dataset.csv"), index=False)
REGISTRO_TABLAS.append(("Tabla 1 — Resumen del dataset", df_tabla1))

tabla_variables = pd.DataFrame([
    {"Variable": "NIVEL", "Tipo": "Ordinal (1-8)", "Fuente": "RENIPRESS (CATEGORIA mapeada)", "Uso": "Predictor — resolutividad del EESS"},
    {"Variable": "poblacion_total", "Tipo": "Numérica continua", "Fuente": "INEI Censo 2017", "Uso": "Predictor — demanda poblacional"},
    {"Variable": "tasa_vulnerabilidad_regional", "Tipo": "Numérica continua", "Fuente": "Derivada (RENIPRESS + INEI)", "Uso": "Predictor — contexto regional"},
    {"Variable": "ratio_adulto_mayor", "Tipo": "Numérica continua (proporción)", "Fuente": "Derivada (INEI)", "Uso": "Predictor — vulnerabilidad etaria"},
    {"Variable": "dist_km_hosp_complejo", "Tipo": "Numérica continua", "Fuente": "Derivada (geoespacial, NearestNeighbors)", "Uso": "Insumo del índice INVS (Dim1)"},
    {"Variable": "ANOMALIA_ESPACIAL", "Tipo": "Binaria", "Fuente": "Derivada (IsolationForest+LOF+DBSCAN)", "Uso": "Insumo del índice INVS (Dim6) y del target"},
    {"Variable": "INVS", "Tipo": "Numérica continua (0-1)", "Fuente": "Derivada (PCA sobre 6 dimensiones)", "Uso": "Índice compuesto de vulnerabilidad"},
    {"Variable": "VULNERABLE", "Tipo": "Binaria", "Fuente": "Derivada (regla de consenso de expertos)", "Uso": "Variable objetivo (target) del clasificador"},
    {"Variable": "REGION_NATURAL", "Tipo": "Categórica (Costa/Sierra/Selva)", "Fuente": "Mapeo manual por departamento", "Uso": "Grupo de validación de generalización geográfica (LORO)"},
    {"Variable": "DEPARTAMENTO_NORM", "Tipo": "Categórica", "Fuente": "RENIPRESS (normalizada)", "Uso": "Grupo de validación (GroupKFold/LODO)"},
])
print("\n" + tabla_variables.to_string(index=False))
tabla_variables.to_csv(os.path.join(DIR_SALIDA, "30_tablas_dataset/tabla_variables.csv"), index=False)
REGISTRO_TABLAS.append(("Tabla de variables del estudio", tabla_variables))

# =============================================================================
# 15bis. RECONCILIACIÓN DEL CONTEO DE DISTRITOS (UBIGEO) ENTRE FUENTES  [NUEVO v21]
# =============================================================================

print("\n" + "="*80 + "\n[🗺️ BLOQUE 15bis: RECONCILIACIÓN DEL CONTEO DE DISTRITOS (UBIGEO) ENTRE FUENTES]\n" + "="*80)
t15b = time.time()
ubigeos_renipress_crudo = set(df['UBIGEO'].dropna().unique())
ubigeos_renipress_activos = set(df_activos['UBIGEO'].dropna().unique())
ubigeos_inei_distrital = set(df_inei_dist['UBIGEO'].dropna().unique())
ubigeos_interseccion = ubigeos_renipress_activos & ubigeos_inei_distrital
ubigeos_renipress_sin_inei = ubigeos_renipress_activos - ubigeos_inei_distrital
ubigeos_inei_sin_renipress = ubigeos_inei_distrital - ubigeos_renipress_activos

df_reconciliacion_distritos = pd.DataFrame([
    {"Fuente": "RENIPRESS (crudo, todos los estados)", "N_distritos_UBIGEO_unicos": len(ubigeos_renipress_crudo)},
    {"Fuente": "RENIPRESS (solo establecimientos ACTIVOS)", "N_distritos_UBIGEO_unicos": len(ubigeos_renipress_activos)},
    {"Fuente": "INEI Censo 2017 (nivel DISTRITAL)", "N_distritos_UBIGEO_unicos": len(ubigeos_inei_distrital)},
    {"Fuente": "Intersección RENIPRESS(activos) ∩ INEI(distrital)", "N_distritos_UBIGEO_unicos": len(ubigeos_interseccion)},
    {"Fuente": "Distritos con EESS activo pero SIN dato censal INEI", "N_distritos_UBIGEO_unicos": len(ubigeos_renipress_sin_inei)},
    {"Fuente": "Distritos con dato censal INEI pero SIN EESS activo en RENIPRESS", "N_distritos_UBIGEO_unicos": len(ubigeos_inei_sin_renipress)},
    {"Fuente": "Distritos únicos en la muestra final de análisis (df_activos)", "N_distritos_UBIGEO_unicos": df_activos['UBIGEO'].nunique()},
])
print(df_reconciliacion_distritos.to_string(index=False))
print("\n  💡 La cifra reportada en el manuscrito como 'número de distritos analizados' DEBE corresponder a la")
print("     fila 'Distritos únicos en la muestra final de análisis (df_activos)'. Cualquier otra cifra (p.ej.")
print("     distritos INEI totales o distritos RENIPRESS crudos) mide algo distinto; esta tabla documenta la")
print("     trazabilidad completa entre ambas fuentes para evitar inconsistencias numéricas entre secciones del paper.")

df_reconciliacion_distritos.to_csv(os.path.join(DIR_SALIDA, "44_reconciliacion_distritos/reconciliacion_distritos.csv"), index=False)
REGISTRO_TABLAS.append(("Reconciliación del conteo de distritos entre fuentes (RENIPRESS vs INEI)", df_reconciliacion_distritos))
t15b = reportar_recursos("Bloque 15bis — Reconciliación de distritos", t15b)

# =============================================================================
# 16. REPRODUCIBILIDAD AUTOMÁTICA REAL (OBSERVACIÓN #1)
# =============================================================================

print("\n" + "="*80 + "\n[♻️ BLOQUE 16: PAQUETE DE REPRODUCIBILIDAD AUTOMÁTICA COMPLETA]\n" + "="*80)
t13h = time.time()

info_hardware = {
    "CPU_count_logico": os.cpu_count(),
    "Sistema": platform.system(),
    "Release": platform.release(),
    "Maquina": platform.machine(),
    "Procesador": platform.processor(),
}
if PSUTIL_OK:
    info_hardware["RAM_total_GB"] = round(psutil.virtual_memory().total / (1024**3), 2)

info_entorno = {
    "Python": platform.python_version(),
    "Plataforma": platform.platform(),
    "Pandas": pd.__version__,
    "NumPy": np.__version__,
    "scikit-learn": __import__('sklearn').__version__,
    "LightGBM": lgb.__version__,
    "CatBoost": __import__('catboost').__version__,
    "XGBoost": xgb.__version__,
    "SHAP": shap.__version__,
    "Optuna": optuna.__version__,
    "statsmodels": sm.__version__,
    "MAPIE_disponible": MAPIE_OK,
    "SALib_disponible": SALIB_OK,
    "Semillas_utilizadas": SEEDS,
    "Hardware": info_hardware,
    "Hash_SHA256_RENIPRESS": hash_renipress,
    "Hash_SHA256_INEI": hash_inei,
}
with open(os.path.join(DIR_SALIDA, "18_reproducibilidad/environment_info.json"), "w") as f:
    json.dump(info_entorno, f, indent=4, default=str)

with open(os.path.join(DIR_SALIDA, "18_reproducibilidad/versions.txt"), "w") as f:
    for k, v in info_entorno.items():
        f.write(f"{k}: {v}\n")

try:
    freeze = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True, timeout=60)
    with open(os.path.join(DIR_SALIDA, "18_reproducibilidad/requirements.txt"), "w") as f:
        f.write(freeze.stdout)
    print("  📌 requirements.txt generado correctamente.")
except Exception as e:
    print(f"  ⚠️ No se pudo generar requirements.txt automáticamente: {e}")

print(json.dumps(info_entorno, indent=2, default=str))
t13h = reportar_recursos("Bloque 16 — Reproducibilidad automática completa", t13h)

# =============================================================================
# 17. COMPLEJIDAD COMPUTACIONAL CONSOLIDADA
# =============================================================================

print("\n" + "="*80 + "\n[🖥️ BLOQUE 17: REPORTE CONSOLIDADO DE COMPLEJIDAD COMPUTACIONAL]\n" + "="*80)
pico_mem_actual, pico_mem_max = tracemalloc.get_traced_memory()
print(f"  📌 Memoria pico (tracemalloc): {pico_mem_max / (1024**2):.2f} MB")
complejidad_modelos = {
    "LightGBM": "O(n · d · log n) por árbol (histogram-based)",
    "XGBoost": "O(n · d · log n) por árbol (boosting secuencial)",
    "CatBoost": "O(n · d) por árbol con oblivious trees",
    "ExtraTrees / RandomForest": "O(n_trees · n log n · d)",
    "HistGradientBoosting": "O(n · d) por bin histogram",
    "SHAP TreeExplainer": "O(T · L · D²) — T árboles, L hojas, D profundidad",
    "Bootstrap (B=2000)": "O(B · n) para remuestreo + cómputo de métricas",
    "Optuna (50 trials, GroupKFold k=3)": "O(50 · 3 · costo_entrenamiento_modelo)"
}
for k, v in complejidad_modelos.items():
    print(f"  🔧 {k:<35} → Complejidad teórica aproximada: {v}")
tracemalloc.stop()

# =============================================================================
# 18. METADATA, RESUMEN INTEGRAL Y EXPORTACIÓN DE METRICAS GLOBALES
# =============================================================================
print("\n" + "="*80 + "\n[📝 RESUMEN NUMÉRICO INTEGRAL DE EJECUCIÓN EN CONSOLA]\n" + "="*80)
print(f"🔹 Clasificador Líder: {study.best_params['model_type']} | Trials Computados: 50")
print(f"🔹 Área Bajo la Curva ROC (AUC Central): {roc_auc_score(y_test_puro, probs_test):.4f}")
print(f"🔹 AUC de generalización geográfica (Leave-One-Region-Out; no es una validación contra fuente externa): {df_logo_region['AUC_generalizacion_geografica'].mean():.4f} ± {df_logo_region['AUC_generalizacion_geografica'].std():.4f}")
print(f"🔹 AUC LODO (Leave-One-Department-Out): {df_lodo['AUC'].mean():.4f} ± {df_lodo['AUC'].std():.4f}")
print(f"🔹 Magnitud de Importancia Territorial SHAP Absoluta Promedio (multisemilla):")
print(df_shap_stability.to_string(index=False))
print("-" * 80)

metadata_experimento = {
    "Timestamp_Ejecucion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "Tiempo_Ejecucion_Segundos": time.time() - tiempo_inicio_global,
    "Optuna_Mejores_Parametros": study.best_params,
    "Umbral_Diseno_KM": float(UMBRAL_DIST_KM),
    "AUC_Test_Interno": float(roc_auc_score(y_test_puro, probs_test)),
    "AUC_Generalizacion_Geografica_LORO_promedio": float(df_logo_region['AUC_generalizacion_geografica'].mean()),
    "AUC_LODO_promedio": float(df_lodo['AUC'].mean()),
    "Memoria_pico_MB": float(pico_mem_max / (1024**2)),
    "MCC": float(mcc_global), "Cohen_Kappa": float(kappa_global), "Balanced_Accuracy": float(bacc_global),
    "Average_Precision": float(avg_precision), "ECE": float(ece),
    "Hosmer_Lemeshow_p": float(hl_p) if not pd.isna(hl_p) else None,
    "Umbral_Youden": float(umbral_youden), "Umbral_Costo_Sensible": float(umbral_costo_sensible),
    "Brecha_Generalizacion_AUC": float(brecha_generalizacion),
}
with open(os.path.join(DIR_SALIDA, "08_final/auditoria_experimento.json"), "w") as f:
    json.dump(metadata_experimento, f, indent=4, default=str)

df_metricas_globales = pd.DataFrame([metadata_experimento])
df_metricas_globales.to_csv(os.path.join(DIR_SALIDA, "40_metricas_globales/metricas_globales.csv"), index=False)
REGISTRO_TABLAS.append(("Métricas globales consolidadas del experimento", df_metricas_globales))

# =============================================================================
# 19. SCRIPT DE INFERENCIA INDEPENDIENTE — predict.py (OBSERVACIÓN #23)
# =============================================================================

print("\n" + "="*80 + "\n[🧰 BLOQUE 19: GENERACIÓN DE SCRIPT DE INFERENCIA INDEPENDIENTE (predict.py)]\n" + "="*80)
PREDICT_PY_CONTENT = f'''"""
predict.py — Script de inferencia independiente para el modelo INVS.

Uso:
    python predict.py --input nuevos_casos.csv --output predicciones.csv

El CSV de entrada debe contener, como mínimo, las columnas:
{FEATURES}

Carga el modelo final, el pipeline de preprocesamiento (imputador + scaler)
y produce probabilidades de vulnerabilidad (P_VULNERABLE) junto con la
clase predicha (PRED_VULNERABLE) para cada fila del archivo de entrada.
"""
import argparse
import json
import joblib
import pandas as pd

FEATURES = {FEATURES}

def cargar_artefactos(dir_modelos):
    modelo = joblib.load(f"{{dir_modelos}}/modelo_final.joblib")
    pipeline = joblib.load(f"{{dir_modelos}}/pipeline_preprocesamiento.joblib")
    return modelo, pipeline

def main():
    parser = argparse.ArgumentParser(description="Inferencia INVS — predicción de vulnerabilidad sanitaria")
    parser.add_argument("--input", required=True, help="Ruta al CSV de entrada con las columnas requeridas")
    parser.add_argument("--output", required=True, help="Ruta de salida para el CSV con predicciones")
    parser.add_argument("--dir_modelos", default="./27_modelos_persistidos", help="Carpeta con los artefactos joblib")
    args = parser.parse_args()

    modelo, pipeline = cargar_artefactos(args.dir_modelos)
    df_input = pd.read_csv(args.input)

    faltantes = [c for c in FEATURES if c not in df_input.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas requeridas en el CSV de entrada: {{faltantes}}")

    X_input_sc = pipeline.transform(df_input[FEATURES])
    probs = modelo.predict_proba(X_input_sc)[:, 1]
    preds = (probs >= 0.5).astype(int)

    df_input["P_VULNERABLE"] = probs
    df_input["PRED_VULNERABLE"] = preds
    df_input.to_csv(args.output, index=False)
    print(f"✅ Predicciones generadas para {{len(df_input)}} registros → {{args.output}}")

if __name__ == "__main__":
    main()
'''
ruta_predict_py = os.path.join(DIR_SALIDA, "38_inferencia", "predict.py")
with open(ruta_predict_py, "w", encoding="utf-8") as f:
    f.write(PREDICT_PY_CONTENT)
print(f"  ✅ predict.py generado en: {ruta_predict_py}")

# =============================================================================
# 20. README.md AUTOMÁTICO (OBSERVACIÓN #24)
# =============================================================================

print("\n" + "="*80 + "\n[📄 BLOQUE 20: GENERACIÓN AUTOMÁTICA DE README.md]\n" + "="*80)
README_CONTENT = f"""# Índice Nacional de Vulnerabilidad Sanitaria (INVS) — Pipeline v21 Q1 ULTRA

## Descripción
Pipeline de investigación reproducible para la identificación de desiertos
médicos y priorización de infraestructura hospitalaria en el Perú, mediante
aprendizaje automático híbrido, análisis espacial y un riguroso protocolo de
validación orientado a publicación científica Q1. La v21 añade optimización
de umbral, learning curves, estabilidad de selección de features, comparación
formal de generalización geográfica, error analysis ampliado y sensibilidad
económica sobre la base metodológica ya validada en v20.

## Dataset
- **RENIPRESS**: {N_FILAS_CRUDAS_RENIPRESS:,} registros crudos → {N_FINAL_ANALISIS:,} registros tras limpieza y fusión.
- **INEI Censo 2017**: información poblacional distrital.
- Hash SHA256 RENIPRESS: `{hash_renipress}`
- Hash SHA256 INEI: `{hash_inei}`
- Distritos únicos en la muestra final de análisis: **{df_activos['UBIGEO'].nunique():,}** (ver reconciliación completa en `44_reconciliacion_distritos/`).

## Ejecución
1. Ejecutar el script principal en Google Colab (requiere montar Google Drive).
2. Las dependencias se instalan automáticamente al inicio del script.
3. Todos los resultados se exportan a: `{DIR_SALIDA}`

## Resultados principales
- Modelo líder: **{study.best_params['model_type']}**
- AUC-ROC (interno): **{roc_auc_score(y_test_puro, probs_test):.4f}**
- AUC de generalización geográfica (Leave-One-Region-Out; no validación externa a otra fuente de datos): **{df_logo_region['AUC_generalizacion_geografica'].mean():.4f} ± {df_logo_region['AUC_generalizacion_geografica'].std():.4f}**
- AUC LODO (Leave-One-Department-Out): **{df_lodo['AUC'].mean():.4f} ± {df_lodo['AUC'].std():.4f}**
- Brecha de generalización (interno − externo): **{brecha_generalizacion:.4f}** (ver `46_auc_interno_vs_externo/`)
- MCC: **{mcc_global:.4f}** | Cohen's Kappa: **{kappa_global:.4f}** | Balanced Accuracy: **{bacc_global:.4f}**
- Average Precision: **{avg_precision:.4f}** | ECE (calibración): **{ece:.4f}**
- Umbral óptimo costo-sensible: **{umbral_costo_sensible:.2f}** (default 0.50 no es necesariamente óptimo — ver `41_threshold_optimization/`)

## Estructura de carpetas de resultados
Cada subcarpeta numerada en `{os.path.basename(DIR_SALIDA.rstrip('/'))}` corresponde a un bloque
metodológico del pipeline (calidad de datos, validación de generalización geográfica, conformal
prediction, sensibilidad global, explicabilidad SHAP/PDP/ICE, robustez,
análisis de error, decision curve, análisis económico, simulación de
escenarios, modelos persistidos, métricas extendidas, optimización de
umbral, learning curves, estabilidad de features, reconciliación de
distritos, sensibilidad económica y comparación AUC interno/externo, etc.).

## Inferencia sobre nuevos datos
Use el script `38_inferencia/predict.py`:
```
python predict.py --input nuevos_casos.csv --output predicciones.csv --dir_modelos 27_modelos_persistidos
```

## Reproducibilidad
Ver `18_reproducibilidad/` para `requirements.txt`, `versions.txt` y
`environment_info.json` con todas las versiones de librerías, semillas
utilizadas y hashes de los datasets de origen.

## Licencia
Ver archivo `LICENSE` incluido en el paquete DOI-ready (`39_doi_package/`).

## Citación sugerida
Evangelista Gamarra, [Año]. *Índice Nacional de Vulnerabilidad Sanitaria
(INVS): Identificación de Desiertos Médicos y Priorización de
Infraestructura Hospitalaria en el Perú mediante Aprendizaje Híbrido,
Robustez Multivariada y Evaluación Multisemilla*. [Repositorio/DOI pendiente].
"""
ruta_readme = os.path.join(DIR_SALIDA, "README.md")
with open(ruta_readme, "w", encoding="utf-8") as f:
    f.write(README_CONTENT)
print(f"  ✅ README.md generado en: {ruta_readme}")

# =============================================================================
# 21. INFORME FINAL AUTOMÁTICO EN PDF (OBSERVACIÓN #22)
# =============================================================================

print("\n" + "="*80 + "\n[📑 BLOQUE 21: GENERACIÓN DE INFORME FINAL AUTOMÁTICO RESULTADOS_FINALES_Q1.pdf]\n" + "="*80)
RUTA_INFORME_PDF = os.path.join(DIR_SALIDA, "37_informe_final", "RESULTADOS_FINALES_Q1.pdf")

if REPORTLAB_OK:
    try:
        doc = SimpleDocTemplate(RUTA_INFORME_PDF, pagesize=A4)
        styles = getSampleStyleSheet()
        elementos = []

        elementos.append(Paragraph("Informe Final — Índice Nacional de Vulnerabilidad Sanitaria (INVS)", styles['Title']))
        elementos.append(Paragraph(f"Generado automáticamente: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
        elementos.append(Spacer(1, 14))

        elementos.append(Paragraph("1. Resumen Ejecutivo de Métricas", styles['Heading2']))
        resumen_texto = (f"Modelo líder: {study.best_params['model_type']}. AUC-ROC interno: "
                          f"{roc_auc_score(y_test_puro, probs_test):.4f}. AUC externo LORO: "
                          f"{df_logo_region['AUC_generalizacion_geografica'].mean():.4f}. AUC LODO: {df_lodo['AUC'].mean():.4f}. "
                          f"Brecha de generalización: {brecha_generalizacion:.4f}. "
                          f"MCC: {mcc_global:.4f}. Cohen's Kappa: {kappa_global:.4f}. "
                          f"Balanced Accuracy: {bacc_global:.4f}. Average Precision: {avg_precision:.4f}. "
                          f"ECE: {ece:.4f}. Hosmer-Lemeshow p-valor: {hl_p:.4f}. "
                          f"Umbral óptimo costo-sensible: {umbral_costo_sensible:.2f}.")
        elementos.append(Paragraph(resumen_texto, styles['Normal']))
        elementos.append(Spacer(1, 12))

        elementos.append(Paragraph("2. Tablas de Resultados", styles['Heading2']))
        for titulo_tabla, df_tabla in REGISTRO_TABLAS:
            elementos.append(Paragraph(titulo_tabla, styles['Heading3']))
            df_show = df_tabla.copy()
            if len(df_show) > 15:
                df_show = df_show.head(15)
            df_show = df_show.round(4) if df_show.select_dtypes(include=[np.number]).shape[1] > 0 else df_show
            data_tabla = [list(df_show.columns)] + df_show.astype(str).values.tolist()
            t = RLTable(data_tabla, hAlign='LEFT')
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), rl_colors.HexColor("#274472")),
                ('TEXTCOLOR', (0,0), (-1,0), rl_colors.white),
                ('FONTSIZE', (0,0), (-1,-1), 6.5),
                ('GRID', (0,0), (-1,-1), 0.4, rl_colors.grey),
            ]))
            elementos.append(t)
            elementos.append(Spacer(1, 10))
        elementos.append(PageBreak())

        elementos.append(Paragraph("3. Figuras del Pipeline", styles['Heading2']))
        for ruta_fig, caption in REGISTRO_FIGURAS:
            try:
                if os.path.exists(ruta_fig):
                    elementos.append(RLImage(ruta_fig, width=420, height=230))
                    elementos.append(Paragraph(caption, styles['Italic']))
                    elementos.append(Spacer(1, 10))
            except Exception:
                continue

        doc.build(elementos)
        print(f"  ✅ Informe final PDF generado en: {RUTA_INFORME_PDF}")
    except Exception as e:
        print(f"  ⚠️ No se pudo generar el informe PDF automáticamente: {e}")
else:
    print("  ⚠️ reportlab no disponible; se omite la generación del informe PDF. Tablas/figuras ya exportadas por separado.")

# =============================================================================
# 22. PAQUETE DOI-READY (OBSERVACIÓN #25)
# =============================================================================

print("\n" + "="*80 + "\n[📦 BLOQUE 22: ENSAMBLAJE DE PAQUETE DOI-READY (ZENODO-COMPATIBLE)]\n" + "="*80)
DIR_DOI = os.path.join(DIR_SALIDA, "39_doi_package")

LICENSE_CONTENT = """MIT License

Copyright (c) 2026 Evangelista Gamarra

Se concede permiso, libre de cargos, a cualquier persona que obtenga una copia
de este software y de los archivos de documentación asociados (el "Software"),
para utilizar el Software sin restricción, incluyendo sin limitación los
derechos a usar, copiar, modificar, fusionar, publicar, distribuir, sublicenciar
y/o vender copias del Software, sujeto a las siguientes condiciones:

El aviso de copyright anterior y este aviso de permiso se incluirán en todas
las copias o partes sustanciales del Software.

EL SOFTWARE SE PROPORCIONA "TAL CUAL", SIN GARANTÍA DE NINGÚN TIPO.
"""
with open(os.path.join(DIR_DOI, "LICENSE"), "w", encoding="utf-8") as f:
    f.write(LICENSE_CONTENT)

try:
    shutil.copy(ruta_readme, os.path.join(DIR_DOI, "README.md"))
    shutil.copy(os.path.join(DIR_SALIDA, "18_reproducibilidad", "requirements.txt"), os.path.join(DIR_DOI, "requirements.txt"))
    shutil.copy(__file__, os.path.join(DIR_DOI, "invs_pipeline_v21.py")) if '__file__' in dir() else None
    shutil.copy(ruta_predict_py, os.path.join(DIR_DOI, "predict.py"))
except Exception as e:
    print(f"  ⚠️ Algunos archivos no pudieron copiarse al paquete DOI-ready: {e}")

DIR_DOI_RESULTS = os.path.join(DIR_DOI, "results")
os.makedirs(DIR_DOI_RESULTS, exist_ok=True)
for sc in SUBCARPETAS:
    if sc in ("39_doi_package",):
        continue
    origen = os.path.join(DIR_SALIDA, sc)
    destino = os.path.join(DIR_DOI_RESULTS, sc)
    if os.path.exists(origen):
        shutil.copytree(origen, destino, dirs_exist_ok=True)

shutil.make_archive(DIR_DOI.rstrip('/'), 'zip', DIR_DOI)
print(f"  ✅ Paquete DOI-ready ensamblado y comprimido en: {DIR_DOI.rstrip('/')}.zip")

print("\n" + "="*80)
print("[📝 RESUMEN FINAL: TABLAS Y FIGURAS REGISTRADAS PARA EL INFORME]")
print(f"  📊 Tablas registradas: {len(REGISTRO_TABLAS)} | 🖼️ Figuras registradas: {len(REGISTRO_FIGURAS)}")
print("="*80)

shutil.make_archive(DIR_SALIDA.rstrip('/'), 'zip', DIR_SALIDA)
log("Pipeline v21 finalizado correctamente. ZIP completo generado.")

# =============================================================================
# 23. DESCARGA AUTOMÁTICA DE LOS ZIP AL PC DEL USUARIO
# =============================================================================

print("\n" + "="*80 + "\n[⬇️ BLOQUE 23: DESCARGA AUTOMÁTICA DE RESULTADOS COMPRIMIDOS AL EQUIPO LOCAL]\n" + "="*80)
RUTA_ZIP_COMPLETO = DIR_SALIDA.rstrip('/') + ".zip"
RUTA_ZIP_DOI = DIR_DOI.rstrip('/') + ".zip"

try:
    from google.colab import files as colab_files
    print(f"  📦 Preparando descarga: {RUTA_ZIP_COMPLETO}")
    colab_files.download(RUTA_ZIP_COMPLETO)
    print(f"  📦 Preparando descarga: {RUTA_ZIP_DOI}")
    colab_files.download(RUTA_ZIP_DOI)
    print("  ✅ Descarga automática iniciada — revisa la carpeta de descargas de tu navegador/PC.")
    print("     (Si el navegador bloqueó descargas múltiples, autoriza 'múltiples archivos' y vuelve a ejecutar este bloque.)")
except Exception as e:
    print(f"  ⚠️ No se pudo iniciar la descarga automática (entorno sin soporte de google.colab.files): {e}")
    print(f"     Los ZIP ya están disponibles manualmente en Google Drive en:")
    print(f"       • {RUTA_ZIP_COMPLETO}")
    print(f"       • {RUTA_ZIP_DOI}")

print("\n" + "=" * 95)
print("✅ PIPELINE COMPLETO V21 Q1 ULTRA PRODUCIDO — 25 MEJORAS v20 + 9 MEJORAS METODOLÓGICAS v21 ATENDIDAS")
print("=" * 95)


print("Stage 13_reproducibility_package done.")
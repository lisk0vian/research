# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 03: 03_build_invs (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *
from _deps import *

print("\n" + "="*80 + "\n[📊 BLOQUE 2: OPTIMIZACIÓN Y VALIDACIÓN DEL TARGET POR CONVENIO DE EXPERTOS]\n" + "="*80)
umbrales_t = [30, 40, 50, 60, 70]
conteos_v = [(df_activos['dist_km_complex_hospital'] > u).sum() for u in umbrales_t]
kl = KneeLocator(umbrales_t, conteos_v, curve='convex', direction='decreasing')
UMBRAL_DIST_KM = kl.knee if kl.knee else 50

for pert in [-5, 0, 5]:
    print(f"  🔬 Sensibilidad Umbral = {UMBRAL_DIST_KM + pert}km → Casos Vulnerables: {(df_activos['dist_km_complex_hospital'] > (UMBRAL_DIST_KM + pert)).sum()}")

df_activos['extreme_vulnerable_ratio'] = (df_activos['pop_60_plus'] + df_activos['pop5_with_disability']) / (df_activos['population_total'] + 1)
q_corte = df_activos['extreme_vulnerable_ratio'].quantile(0.75)
print(f"  🔬 Sensibilidad del percentil de corte (extreme_vulnerable_ratio, q75={q_corte:.4f}):")
for q_test in [0.70, 0.75, 0.80, 0.85]:
    q_val = df_activos['extreme_vulnerable_ratio'].quantile(q_test)
    n_casos = ((df_activos['dist_km_complex_hospital'] > UMBRAL_DIST_KM) & (df_activos['extreme_vulnerable_ratio'] > q_val)).sum()
    print(f"      q={q_test} → corte={q_val:.4f} → casos que cumplen criterio distancia+vulnerabilidad: {n_casos}")
df_activos['VULNERABLE'] = (((df_activos['dist_km_complex_hospital'] > UMBRAL_DIST_KM) & (df_activos['extreme_vulnerable_ratio'] > q_corte)) | (df_activos['spatial_anomaly'] == 1)).astype(int)
print(f"🎯 Prevalencia Sanitaria del Target Validado Exteriormente: {df_activos['VULNERABLE'].mean()*100:.2f}%")

# =============================================================================
# 3. ARQUITECTURA MULTI-METODOLÓGICA DEL INVS
# =============================================================================

print("\n" + "="*80 + "\n[📊 BLOQUE 3: ENFOQUE MULTI-METODOLÓGICO DEL INVS (PCA vs FA vs EWM)]\n" + "="*80)
df_activos['dim1_isolation'] = MinMaxScaler().fit_transform(df_activos[['dist_km_complex_hospital']]).flatten()
df_activos['dim2_resolution'] = MinMaxScaler().fit_transform((1 - df_activos['care_level']/8).values.reshape(-1,1)).flatten()
df_activos['dim3_demand'] = MinMaxScaler().fit_transform(np.log1p(df_activos['population_total']).values.reshape(-1,1)).flatten()
df_activos['dim4_age_vulnerability'] = MinMaxScaler().fit_transform((df_activos['pop_60_plus']/(df_activos['population_total']+1)).values.reshape(-1,1)).flatten()
df_activos['dim5_disability'] = MinMaxScaler().fit_transform((df_activos['pop5_with_disability']/(df_activos['population_total']+1)).values.reshape(-1,1)).flatten()
df_activos['dim6_spatial_fragility'] = MinMaxScaler().fit_transform(df_activos[['spatial_anomaly']].values.astype(float)).flatten()

COLS_INVS = ['dim1_isolation', 'dim2_resolution', 'dim3_demand', 'dim4_age_vulnerability', 'dim5_disability', 'dim6_spatial_fragility']
X_invs_6d = StandardScaler().fit_transform(df_activos[COLS_INVS])

invs_pca = MinMaxScaler().fit_transform(PCA(n_components=1, random_state=SEED_BASE).fit_transform(X_invs_6d)[:,0].reshape(-1,1)).flatten()
invs_fa = MinMaxScaler().fit_transform(FactorAnalysis(n_components=1, random_state=SEED_BASE).fit_transform(X_invs_6d)[:,0].reshape(-1,1)).flatten()

X_minmax = MinMaxScaler().fit_transform(df_activos[COLS_INVS]) + 1e-10
p_ij = X_minmax / X_minmax.sum(axis=0)
entropy = - (1.0 / np.log(len(df_activos))) * (p_ij * np.log(p_ij)).sum(axis=0)
w_entropy = (1.0 - entropy) / (1.0 - entropy).sum()
invs_ewm = MinMaxScaler().fit_transform(np.dot(X_minmax, w_entropy).reshape(-1,1)).flatten()

df_activos['INVS'] = invs_pca
print(f"  📈 Validación del Índice (Spearman) | PCA vs FA: {spearmanr(invs_pca, invs_fa)[0]:.4f} | PCA vs EWM: {spearmanr(invs_pca, invs_ewm)[0]:.4f}")

# =============================================================================
# 3bis. DOCUMENTACIÓN COMPLETA DEL INVS — ponderación, normalización y validación
# (Observación de revisión Q1: "documentar completamente la construcción,
# ponderación, normalización y validación del INVS")
# =============================================================================

print("\n" + "="*80 + "\n[📐 BLOQUE 3bis: DOCUMENTACIÓN DE PONDERACIÓN Y VALIDACIÓN DEL ÍNDICE INVS]\n" + "="*80)
from factor_analyzer.factor_analyzer import calculate_kmo, calculate_bartlett_sphericity

# --- Normalización: ya documentada arriba (MinMaxScaler por dimensión antes de
#     StandardScaler conjunto para PCA/FA, y MinMaxScaler+1e-10 para EWM) ------

# --- Ponderación PCA: loadings del primer componente + varianza explicada ---
pca_1c = PCA(n_components=1, random_state=SEED_BASE).fit(X_invs_6d)
df_loadings_pca = pd.DataFrame({
    "Dimension": COLS_INVS,
    "Loading_PC1": pca_1c.components_[0],
    "Peso_EWM": w_entropy,
}).sort_values("Loading_PC1", key=abs, ascending=False)
print(f"  📊 Varianza explicada por PC1: {pca_1c.explained_variance_ratio_[0]*100:.2f}%")
print(df_loadings_pca.to_string(index=False))

# --- Validación de factorabilidad (requisito para PCA/FA sobre variables compuestas) ---
kmo_all, kmo_model = calculate_kmo(df_activos[COLS_INVS])
chi_sq, p_bartlett = calculate_bartlett_sphericity(df_activos[COLS_INVS])
print(f"  🧪 KMO (adecuación muestral): {kmo_model:.4f} "
      f"({'aceptable (>0.6)' if kmo_model > 0.6 else 'INSUFICIENTE (<0.6): PCA/FA no recomendable sobre estas 6 dimensiones'})")
print(f"  🧪 Test de esfericidad de Bartlett: chi²={chi_sq:.2f}, p={p_bartlett:.4g} "
      f"({'variables correlacionadas — PCA/FA justificado' if p_bartlett < 0.05 else 'variables NO correlacionadas — PCA/FA no justificado'})")

df_validacion_invs = pd.DataFrame([
    {"Prueba": "KMO (adecuación muestral)", "Valor": round(kmo_model, 4), "Umbral_referencia": "> 0.6"},
    {"Prueba": "Bartlett chi²", "Valor": round(chi_sq, 2), "Umbral_referencia": "p < 0.05"},
    {"Prueba": "Bartlett p-valor", "Valor": p_bartlett, "Umbral_referencia": "p < 0.05"},
    {"Prueba": "Varianza explicada PC1", "Valor": round(pca_1c.explained_variance_ratio_[0], 4), "Umbral_referencia": "reportar, sin umbral fijo"},
])
df_loadings_pca.to_csv(os.path.join(DIR_SALIDA, "03_indice_invs", "invs_loadings_y_pesos.csv"), index=False)
df_validacion_invs.to_csv(os.path.join(DIR_SALIDA, "03_indice_invs", "invs_validacion_factorabilidad.csv"), index=False)
REGISTRO_TABLAS.append(("INVS — Loadings PCA y pesos EWM por dimensión", df_loadings_pca))
REGISTRO_TABLAS.append(("INVS — Validación de factorabilidad (KMO/Bartlett)", df_validacion_invs))

# =============================================================================
# 4. ABLATION STUDY POOL DEL INVS
# =============================================================================

print("\n" + "="*80 + "\n[📊 BLOQUE 4: ABLATION STUDY ESTRUCTURAL SOBRE LAS DIMENSIONES DEL INVS]\n" + "="*80)
ablation_invs_resultados = []
for d_dim in COLS_INVS:
    cols_red_invs = [c for c in COLS_INVS if c != d_dim]
    X_red = StandardScaler().fit_transform(df_activos[cols_red_invs])
    invs_red = MinMaxScaler().fit_transform(PCA(n_components=1, random_state=SEED_BASE).fit_transform(X_red)[:,0].reshape(-1,1)).flatten()
    r_degradacion, _ = spearmanr(df_activos['INVS'], invs_red)
    print(f"  ❌ Removiendo Componente INVS: {d_dim:<30} → Correlación de Retención Indexal: {r_degradacion:.4f} (Δ: {1.0 - r_degradacion:.4f})")
    ablation_invs_resultados.append({"Dimension_removida": d_dim, "Correlacion_retencion": r_degradacion, "Delta": 1.0 - r_degradacion})
pd.DataFrame(ablation_invs_resultados).to_csv(os.path.join(DIR_SALIDA, "03_indice_invs/ablation_invs.csv"), index=False)
REGISTRO_TABLAS.append(("Ablation Study — dimensiones del índice INVS", pd.DataFrame(ablation_invs_resultados)))

df_activos['region_pop_ratio'] = df_activos.groupby('natural_region')['population_total'].transform('sum') / (df_activos['population_total'] + 1)
df_activos['share_60_plus'] = df_activos['pop_60_plus'] / (df_activos['population_total'] + 1)

FEATURES = ['care_level', 'population_total', 'region_pop_ratio', 'share_60_plus']
X_ml = df_activos[FEATURES].copy()
y_ml = df_activos['VULNERABLE'].values
groups_ml = df_activos['department_norm'].values          # grupo grueso (departamento), usado en LODO
groups_ubigeo_ml = df_activos['ubigeo'].values               # grupo fino (distrito), usado para la partición principal
regiones_ml = df_activos['natural_region'].values

# =============================================================================
# CORRECCIÓN METODOLÓGICA (Observación de revisión Q1 — fuga de información):
# `train_test_split(..., groups_ml, ...)` en la versión anterior NO agrupaba
# nada: sklearn.train_test_split no soporta partición por grupos, solo
# barajaba `groups_ml` como un arreglo más. Como muchos establecimientos
# (filas de RENIPRESS) comparten el mismo ubigeo, y varias FEATURES
# (population_total, region_pop_ratio, share_60_plus) y el
# propio VULNERABLE dependen de agregados a nivel distrital/departamental,
# la partición aleatoria dejaba filas del MISMO distrito en train Y test,
# inflando artificialmente el AUC interno. Se reemplaza por GroupShuffleSplit
# agrupando por ubigeo (distrito), que garantiza que ningún distrito aparezca
# simultáneamente en ambos conjuntos.
# =============================================================================
from sklearn.model_selection import GroupShuffleSplit

gss_outer = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED_BASE)
idx_train, idx_test = next(gss_outer.split(X_ml, y_ml, groups=groups_ubigeo_ml))

X_train_puro, X_test_puro = X_ml.iloc[idx_train], X_ml.iloc[idx_test]          # conservan el índice original de df_activos (igual que antes)
y_train_puro, y_test_puro = y_ml[idx_train], y_ml[idx_test]
groups_train, groups_test = groups_ml[idx_train], groups_ml[idx_test]          # se preserva department_norm para el CV interno (Bloque 5)

# --- Verificación explícita de ausencia de fuga distrital -------------------
distritos_train = set(df_activos.iloc[idx_train]['ubigeo'])
distritos_test = set(df_activos.iloc[idx_test]['ubigeo'])
interseccion_distritos = distritos_train & distritos_test
print(f"🔎 Verificación anti-fuga (ubigeo): {len(distritos_train)} distritos en train | "
      f"{len(distritos_test)} en test | {len(interseccion_distritos)} distritos en ambos conjuntos")
assert len(interseccion_distritos) == 0, (
    f"⚠️ FUGA DE INFORMACIÓN DETECTADA: {len(interseccion_distritos)} distritos (ubigeo) "
    f"aparecen simultáneamente en train y test."
)
print(f"🎯 Prevalencia VULNERABLE — train: {y_train_puro.mean()*100:.2f}% | test: {y_test_puro.mean()*100:.2f}% "
      f"(sin estratificación forzada por y, ya que la partición ahora se rige por el grupo geográfico ubigeo)")

# =============================================================================
# DIAGNÓSTICO DE CIRCULARIDAD METODOLÓGICA (Observación de revisión Q1):
# Se cuantifica la superposición entre las FEATURES del clasificador y las
# variables usadas para construir el índice INVS (COLS_INVS) y el target
# VULNERABLE, ya que ambos comparten insumos crudos (population_total,
# pop_60_plus). Este reporte debe incorporarse como evidencia en
# la sección de limitaciones / respuesta a revisores.
# =============================================================================
print("\n" + "="*80 + "\n[⚠️ DIAGNÓSTICO: CIRCULARIDAD ENTRE FEATURES, COLS_INVS Y EL TARGET VULNERABLE]\n" + "="*80)
solapamiento = []
for feat in FEATURES:
    usado_en_invs = feat in ['population_total', 'share_60_plus']  # insumos directos de Dim3/Dim4
    corr_con_invs = float(pd.Series(df_activos[feat]).corr(df_activos['INVS']))
    corr_con_ratio_extremo = float(pd.Series(df_activos[feat]).corr(df_activos['extreme_vulnerable_ratio']))
    solapamiento.append({
        "Feature_ML": feat,
        "Comparte_insumo_crudo_con_INVS": usado_en_invs,
        "Correlacion_con_INVS": round(corr_con_invs, 4),
        "Correlacion_con_ratio_extremo_vulnerable(insumo_del_target)": round(corr_con_ratio_extremo, 4),
    })
df_circularidad = pd.DataFrame(solapamiento)
print(df_circularidad.to_string(index=False))
print("\n  📌 'population_total' es insumo directo de dim3_demand (COLS_INVS) y del denominador de")
print("     extreme_vulnerable_ratio (insumo del target VULNERABLE).")
print("     'share_60_plus' ES dim4_age_vulnerability (COLS_INVS) y comparte 'pop_60_plus'")
print("     con el numerador de extreme_vulnerable_ratio (insumo del target VULNERABLE).")
print("     ⇒ El modelo no predice un resultado independiente del INVS: lo aproxima parcialmente.")
print("     Debe declararse explícitamente como 'aproximador/emulador del INVS' en el manuscrito,")
print("     o bien sustituirse el target por un resultado externo e independiente (p. ej. brecha real")
print("     de capacidad hospitalaria, tiempos de referencia, indicadores de acceso reportados por")
print("     fuentes distintas a RENIPRESS/INEI-censo, no derivados del propio índice).")
df_circularidad.to_csv(os.path.join(DIR_SALIDA, "30_tablas_dataset", "diagnostico_circularidad_invs.csv"), index=False)
REGISTRO_TABLAS.append(("Diagnóstico de circularidad — FEATURES vs INVS/target", df_circularidad))

# =============================================================================
# 0ter. INVENTARIO COMPLETO DE VARIABLES DE AMBOS DATASETS Y MANEJO DE
#       DATOS PERDIDOS (NUEVA OBSERVACIÓN — TRANSPARENCIA METODOLÓGICA)
#  - Cuántas variables tiene RENIPRESS (crudo) y cuántas tiene INEI (crudo)
#  - Cuántas variables se usan efectivamente en la investigación
#  - Cómo se manejan los datos perdidos en cada variable usada
#  - Exportación a Excel, CSV e imagen (PNG/SVG/PDF) + reporte en consola
#  NOTA v21: este bloque se reubicó aquí (justo después de que el Bloque 4
#  define FEATURES, COLS_INVS y X_ml, que este bloque referencia). En v20
#  estaba antes del Bloque 1 y producía NameError por uso antes de
#  definición; queda corregido sin alterar su contenido ni su lógica interna.
# =============================================================================

print("\n" + "="*80 + "\n[🧾 BLOQUE 0ter: INVENTARIO DE VARIABLES (AMBOS DATASETS) Y MANEJO DE DATOS PERDIDOS]\n" + "="*80)
t0ter = time.time()
DIR_VARS = os.path.join(DIR_SALIDA, "30_tablas_dataset")

# --- 1) Inventario crudo de cada dataset fuente ---------------------------
n_vars_renipress_crudo = df.shape[1]
n_filas_renipress_crudo_actual = df.shape[0]
n_vars_inei_crudo = df_census.shape[1]
n_filas_inei_crudo = df_census.shape[0]
n_vars_inei_distrital = df_census.shape[1]
n_filas_inei_distrital = df_census.shape[0]

print(f"  📁 Dataset 1 — RENIPRESS (crudo, post-deduplicación):")
print(f"      • N° de variables (columnas): {n_vars_renipress_crudo}")
print(f"      • N° de registros (filas):    {n_filas_renipress_crudo_actual:,}")
print(f"  📁 Dataset 2 — INEI Censo 2025 (tabla distrital):")
print(f"      • N° de variables (columnas): {n_vars_inei_crudo}")
print(f"      • N° de registros (filas):    {n_filas_inei_crudo:,}")

df_inventario_datasets = pd.DataFrame([
    {"Dataset": "RENIPRESS (crudo, post-dedup)", "N_variables_columnas": n_vars_renipress_crudo,
     "N_registros_filas": n_filas_renipress_crudo_actual, "Rol_en_investigacion": "Fuente primaria — establecimientos de salud"},
    {"Dataset": "INEI Censo 2025 (tabla distrital)", "N_variables_columnas": n_vars_inei_crudo,
     "N_registros_filas": n_filas_inei_crudo, "Rol_en_investigacion": "Fuente secundaria — datos poblacionales"},
])
print("\n" + df_inventario_datasets.to_string(index=False))

# --- 2) Listado completo de columnas de cada dataset crudo (para anexo) ---
df_columnas_renipress = pd.DataFrame({"Columna_RENIPRESS": df.columns.tolist()})
df_columnas_inei = pd.DataFrame({"Columna_INEI": df_census.columns.astype(str).tolist()})

# --- 3) Variables EFECTIVAMENTE utilizadas en la investigación ------------
# (a) Variables predictoras finales del modelo de Machine Learning
vars_predictoras_ml = list(FEATURES)
# (b) Variables insumo del índice INVS (6 dimensiones compuestas)
vars_indice_invs = list(COLS_INVS)
# (c) Variables crudas/derivadas que alimentan directa o indirectamente
#     a las anteriores (trazabilidad completa variable final -> variable origen)
vars_origen_utilizadas = [
    "ubigeo", "department", "status", "category", "lat_raw", "lon_raw",
    "population_total", "pop_60_plus", "pop5_with_disability"
]
vars_derivadas_utilizadas = [
    "lat", "lon", "coord_valid", "care_level", "department_norm", "natural_region",
    "dist_km_complex_hospital", "spatial_anomaly", "extreme_vulnerable_ratio",
    "VULNERABLE", "INVS", "region_pop_ratio", "share_60_plus"
]
TODAS_LAS_VARIABLES_UTILIZADAS = sorted(set(
    vars_predictoras_ml + vars_indice_invs + vars_origen_utilizadas + vars_derivadas_utilizadas + ["VULNERABLE"]
))

print(f"\n  🎯 Variables crudas de origen utilizadas (de ambos datasets): {len(vars_origen_utilizadas)} de "
      f"{n_vars_renipress_crudo + n_vars_inei_distrital} disponibles en total (RENIPRESS + INEI distrital)")
print(f"  🎯 Variables derivadas/calculadas a partir de las anteriores: {len(vars_derivadas_utilizadas)}")
print(f"  🎯 Variables predictoras finales del clasificador ML (FEATURES): {len(vars_predictoras_ml)} → {vars_predictoras_ml}")
print(f"  🎯 Variables insumo del índice compuesto INVS (COLS_INVS): {len(vars_indice_invs)} → {vars_indice_invs}")
print(f"  🎯 TOTAL de variables (origen + derivadas) utilizadas en toda la investigación: {len(TODAS_LAS_VARIABLES_UTILIZADAS)}")

df_resumen_uso_variables = pd.DataFrame([
    {"Categoría": "Variables disponibles en RENIPRESS (crudo)", "N_variables": n_vars_renipress_crudo},
    {"Categoría": "Variables disponibles en INEI (nivel distrital)", "N_variables": n_vars_inei_distrital},
    {"Categoría": "TOTAL variables disponibles (ambos datasets)", "N_variables": n_vars_renipress_crudo + n_vars_inei_distrital},
    {"Categoría": "Variables crudas de origen utilizadas", "N_variables": len(vars_origen_utilizadas)},
    {"Categoría": "Variables derivadas/calculadas utilizadas", "N_variables": len(vars_derivadas_utilizadas)},
    {"Categoría": "Variables predictoras finales del modelo ML (FEATURES)", "N_variables": len(vars_predictoras_ml)},
    {"Categoría": "Variables insumo del índice INVS (COLS_INVS)", "N_variables": len(vars_indice_invs)},
    {"Categoría": "TOTAL variables utilizadas en la investigación (origen+derivadas, sin duplicar)", "N_variables": len(TODAS_LAS_VARIABLES_UTILIZADAS)},
])
print("\n" + df_resumen_uso_variables.to_string(index=False))

filas_tabla_variables_completa = []
for v in vars_origen_utilizadas:
    origen_ds = "RENIPRESS" if v in df.columns else ("INEI" if v in df_census.columns else "RENIPRESS/INEI")
    filas_tabla_variables_completa.append({"Variable": v, "Categoria": "Cruda de origen", "Dataset_fuente": origen_ds})
for v in vars_derivadas_utilizadas:
    filas_tabla_variables_completa.append({"Variable": v, "Categoria": "Derivada/calculada", "Dataset_fuente": "RENIPRESS+INEI (procesado)"})
df_tabla_variables_completa = pd.DataFrame(filas_tabla_variables_completa).drop_duplicates(subset="Variable")
print("\n  📋 Tabla completa de variables utilizadas (origen + derivadas):")
print(df_tabla_variables_completa.to_string(index=False))

# --- 4) MANEJO DE DATOS PERDIDOS — diagnóstico ANTES de imputar -----------
print("\n  🩹 Diagnóstico de datos perdidos (% faltantes) en las variables crudas de origen:")
filas_missing_crudo = []
for v in vars_origen_utilizadas:
    if v in df.columns:
        pct_na = df[v].isna().mean() * 100
        n_na = int(df[v].isna().sum())
        ds_origen = "RENIPRESS"
    elif v in df_census.columns:
        pct_na = df_census[v].isna().mean() * 100
        n_na = int(df_census[v].isna().sum())
        ds_origen = "INEI"
    else:
        pct_na, n_na, ds_origen = np.nan, np.nan, "N/D"
    filas_missing_crudo.append({"Variable": v, "Dataset": ds_origen, "N_faltantes": n_na, "Pct_faltantes": round(pct_na, 2)})
df_missing_crudo = pd.DataFrame(filas_missing_crudo).sort_values("Pct_faltantes", ascending=False)
print(df_missing_crudo.to_string(index=False))

print("\n  🩹 Diagnóstico de datos perdidos en las variables FINALES usadas por el modelo (antes de imputar):")
filas_missing_features = []
for v in FEATURES:
    pct_na = X_ml[v].isna().mean() * 100
    n_na = int(X_ml[v].isna().sum())
    filas_missing_features.append({"Feature_ML": v, "N_faltantes_pre_imputacion": n_na, "Pct_faltantes_pre_imputacion": round(pct_na, 2)})
df_missing_features = pd.DataFrame(filas_missing_features)
print(df_missing_features.to_string(index=False))

# --- 5) Estrategia de manejo de datos perdidos (documentación explícita) --
print("\n  🛠️ Estrategia de manejo de datos perdidos aplicada en este pipeline:")
estrategia_missing = [
    {"Variable_o_grupo": "population_total / pop_60_plus / pop5_with_disability",
     "Estrategia": "fillna(0) tras el merge con INEI por ubigeo",
     "Justificacion": "Ausencia de match censal se interpreta como sin información poblacional registrada; "
                       "se documenta como limitación y no como imputación estadística."},
    {"Variable_o_grupo": "dist_km_complex_hospital",
     "Estrategia": "fillna(mediana global de dist_km_complex_hospital)",
     "Justificacion": "Evita pérdida de filas sin coordenadas válidas; la mediana es robusta a la asimetría "
                       "propia de distancias geográficas."},
    {"Variable_o_grupo": "care_level (category)",
     "Estrategia": "fillna(1) vía diccionario de mapeo NIVEL_MAP",
     "Justificacion": "Categoría no reconocida/ausente se asigna al nivel de menor resolutividad (I-1) "
                       "como supuesto conservador, explicitado en el manuscrito."},
    {"Variable_o_grupo": "spatial_anomaly",
     "Estrategia": "fillna(0) tras merge de anomalías por ubigeo",
     "Justificacion": "Distritos sin cobertura de coordenadas válidas se asumen sin anomalía espacial detectada."},
    {"Variable_o_grupo": "FEATURES (care_level, population_total, region_pop_ratio, share_60_plus)",
     "Estrategia": "SimpleImputer(strategy='median') dentro del Pipeline de scikit-learn",
     "Justificacion": "Imputación robusta ajustada SOLO en train (anti-leakage) y aplicada a train/test/"
                       "validaciones externas mediante el mismo Pipeline persistido."},
    {"Variable_o_grupo": "lat_raw / lon_raw (coordenadas)",
     "Estrategia": "No se imputan: se excluyen del análisis espacial (coord_valid=0) si están fuera de rango o son NaN",
     "Justificacion": "Imputar coordenadas geográficas introduciría sesgo espacial artificial; se prefiere "
                       "exclusión explícita y cuantificada (ver Bloque 0bis / PRISMA)."},
]
df_estrategia_missing = pd.DataFrame(estrategia_missing)
print(df_estrategia_missing.to_string(index=False))

print("\n  ✅ La verificación POST-imputación (0% de NaN esperado tras el Pipeline) se reporta en el")
print("     Bloque 5bis (junto con la persistencia del Pipeline) y se exporta en missing_data_post_imputacion.csv")

df_inventario_datasets.to_csv(os.path.join(DIR_VARS, "resumen_datasets.csv"), index=False)
df_resumen_uso_variables.to_csv(os.path.join(DIR_VARS, "uso_variables.csv"), index=False)
df_tabla_variables_completa.to_csv(os.path.join(DIR_VARS, "variables_utilizadas.csv"), index=False)
df_missing_crudo.to_csv(os.path.join(DIR_VARS, "missing_crudo_origen.csv"), index=False)
df_missing_features.to_csv(os.path.join(DIR_VARS, "missing_features_pre_imputacion.csv"), index=False)
df_estrategia_missing.to_csv(os.path.join(DIR_VARS, "estrategia_manejo_missing.csv"), index=False)
print(f"  💾 CSVs exportados en: {DIR_VARS}")

plt.figure(figsize=(8, 4.5))
df_missing_plot = df_missing_crudo.dropna(subset=["Pct_faltantes"]).sort_values("Pct_faltantes")
colores_barras = ["#c0392b" if p > 20 else ("#e67e22" if p > 5 else "#27ae60") for p in df_missing_plot["Pct_faltantes"]]
plt.barh(df_missing_plot["Variable"], df_missing_plot["Pct_faltantes"], color=colores_barras)
plt.xlabel("% de Datos Perdidos")
plt.title("Datos Perdidos por Variable de Origen (RENIPRESS + INEI)", fontsize=10, fontweight='bold', pad=10)
for i, (val, _) in enumerate(zip(df_missing_plot["Pct_faltantes"], df_missing_plot["Variable"])):
    plt.text(val + 0.3, i, f"{val:.1f}%", va='center', fontsize=8)
plt.tight_layout()
ruta_missing_fig = os.path.join(DIR_VARS, "missing_data_por_variable")
guardar_figura_multi(plt, ruta_missing_fig)
REGISTRO_FIGURAS.append((ruta_missing_fig + ".png", "Porcentaje de datos perdidos por variable cruda de origen (RENIPRESS + INEI)."))
plt.show()

REGISTRO_TABLAS.append(("Inventario de variables — ambos datasets", df_inventario_datasets))
REGISTRO_TABLAS.append(("Uso de variables en la investigación", df_resumen_uso_variables))
REGISTRO_TABLAS.append(("Datos perdidos — variables de origen", df_missing_crudo))
REGISTRO_TABLAS.append(("Estrategia de manejo de datos perdidos", df_estrategia_missing))

t0ter = reportar_recursos("Bloque 0ter — Inventario de variables y manejo de datos perdidos", t0ter)


# =============================================================================
# 4bis. FEATURE CORRELATION HEATMAP + VIF (OBSERVACIONES #17 y #18)
# =============================================================================

print("\n" + "="*80 + "\n[🧮 BLOQUE 4bis: MATRIZ DE CORRELACIÓN DE FEATURES Y VARIANCE INFLATION FACTOR (VIF)]\n" + "="*80)
t4b = time.time()
corr_matrix = X_ml.corr(method='pearson')
print(corr_matrix.round(3).to_string())

plt.figure(figsize=(6, 5))
sns.heatmap(corr_matrix, annot=True, fmt=".2f", cmap="coolwarm", center=0, square=True,
            cbar_kws={'label': 'Correlación de Pearson'})
plt.title("Mapa de Calor de Correlación entre Predictores", fontsize=10, fontweight='bold', pad=10)
plt.tight_layout()
ruta_corr = os.path.join(DIR_SALIDA, "35_correlacion_vif/correlation_heatmap")
guardar_figura_multi(plt, ruta_corr)
REGISTRO_FIGURAS.append((ruta_corr + ".png", "Mapa de calor de correlación de Pearson entre predictores."))
plt.show()
corr_matrix.to_csv(os.path.join(DIR_SALIDA, "35_correlacion_vif/correlation_matrix.csv"))

X_vif = sm.add_constant(X_ml.fillna(0))
vif_data = []
for i in range(1, X_vif.shape[1]):  # se omite la constante
    vif_val = variance_inflation_factor(X_vif.values, i)
    vif_data.append({"Variable": X_vif.columns[i], "VIF": vif_val})
df_vif = pd.DataFrame(vif_data).sort_values("VIF", ascending=False)
print("\n  📌 Variance Inflation Factor (VIF) — umbral de preocupación referencial: VIF > 10")
print(df_vif.to_string(index=False))
df_vif.to_csv(os.path.join(DIR_SALIDA, "35_correlacion_vif/vif_predictores.csv"), index=False)
REGISTRO_TABLAS.append(("Variance Inflation Factor (VIF)", df_vif))
t4b = reportar_recursos("Bloque 4bis — Correlación y VIF", t4b)

# =============================================================================
# 5. NESTED SPATIAL CROSS-VALIDATION Y OPTUNA (50 TRIALS - ANTI-LEAKAGE)
# =============================================================================


try:
    save_df_activos()
except Exception as e:
    print("persist failed:", e)
save_run_state(COLS_INVS=COLS_INVS, UMBRAL_DIST_KM=UMBRAL_DIST_KM)

print("Stage 03_build_invs done.")
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 02: 02_spatial_clusters (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

print("\n" + "="*80 + "\n[📊 BLOQUE 1: AUDITORÍA GEOESPACIAL Y AUTOCORRELACIÓN MORAN'S I]\n" + "="*80)
t1 = time.time()
for col in ['NORTE', 'ESTE']:
    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.', regex=False).str.strip(), errors='coerce')

mask_valida = df['NORTE'].between(-18.35, -0.02) & df['ESTE'].between(-81.40, -68.60)
df['LAT'] = df['NORTE'].where(mask_valida)
df['LON'] = df['ESTE'].where(mask_valida)
df['COORD_VALIDA'] = mask_valida.astype(int)
N_COORDS_VALIDAS = int(mask_valida.sum())
N_COORDS_INVALIDAS = int((~mask_valida).sum())

df_activos_todos = df[df['ESTADO'] == 'ACTIVO'].copy().reset_index(drop=True)
N_ACTIVOS = len(df_activos_todos)
N_INACTIVOS_EXCLUIDOS = len(df) - N_ACTIVOS
NIVEL_MAP = {'I-1':1,'I-2':2,'I-3':3,'I-4':4,'II-1':5,'II-2':6,'II-E':5,'III-1':7,'III-2':8}
df_activos_todos['NIVEL'] = df_activos_todos['CATEGORIA'].map(NIVEL_MAP).fillna(1).astype(int)
df_activos_todos['DEPARTAMENTO_NORM'] = df_activos_todos['DEPARTAMENTO'].apply(normalizar_cadena)
df_activos_todos['REGION_NATURAL'] = df_activos_todos['DEPARTAMENTO_NORM'].map({normalizar_cadena(k): v for k, v in REGION_NATURAL_MAP.items()}).fillna('Sierra')

df_validas = df_activos_todos[df_activos_todos['COORD_VALIDA'] == 1].copy().reset_index(drop=True)
hosp_c = df_validas[df_validas['NIVEL'] >= 5].copy()
nn = NearestNeighbors(n_neighbors=1, metric='haversine')
nn.fit(np.radians(hosp_c[['LAT','LON']].values))
dist_rad, _ = nn.kneighbors(np.radians(df_validas[['LAT','LON']].values))
df_validas['dist_km_hosp_complejo'] = dist_rad[:,0] * 6371.0

dist_ubigeo = df_validas.groupby('UBIGEO')['dist_km_hosp_complejo'].median().reset_index().rename(columns={'dist_km_hosp_complejo': 'dist_km_ubigeo'})
df_activos_todos = df_activos_todos.merge(dist_ubigeo, on='UBIGEO', how='left')
df_activos_todos['dist_km_hosp_complejo'] = df_activos_todos['dist_km_ubigeo'].fillna(df_validas['dist_km_hosp_complejo'].median())

df_activos = df_activos_todos.merge(df_inei_dist[['UBIGEO','poblacion_total','poblacion_discapacidad','poblacion_adulto_mayor']], on='UBIGEO', how='left')
for c in ['poblacion_total','poblacion_discapacidad','poblacion_adulto_mayor']:
    df_activos[c] = df_activos[c].fillna(0)
N_FINAL_ANALISIS = len(df_activos)

transformer = Transformer.from_crs("EPSG:4326", "EPSG:32718", always_xy=True)
utm_x, utm_y = transformer.transform(df_validas['LON'].values, df_validas['LAT'].values)
X_utm = StandardScaler().fit_transform(np.column_stack([utm_x, utm_y]))

dbscan_labels = DBSCAN(eps=0.15, min_samples=3).fit_predict(X_utm)
df_validas['ANOMALIA_ESPACIAL'] = ((IsolationForest(contamination=0.08, random_state=SEED_BASE).fit_predict(X_utm) == -1).astype(int) +
                                   (LocalOutlierFactor(n_neighbors=20, contamination=0.08).fit_predict(X_utm) == -1).astype(int) +
                                   (dbscan_labels == -1).astype(int) >= 2).astype(int)
anom_m = df_validas.groupby('UBIGEO')['ANOMALIA_ESPACIAL'].max().reset_index()
df_activos = df_activos.merge(anom_m, on='UBIGEO', how='left').fillna({'ANOMALIA_ESPACIAL': 0})

# CORRECCIÓN (observación de Edith): antes se tomaba una MUESTRA ALEATORIA de
# coordenadas (coords_moran) pero luego se leían los valores de
# dist_km_hosp_complejo de las PRIMERAS N filas en orden original — filas
# distintas a las efectivamente muestreadas, desincronizando coordenadas y
# valores del Índice de Moran. Se muestrea una sola vez sobre el DataFrame
# completo para garantizar que coordenadas y valores correspondan siempre
# al mismo registro.
df_muestra_moran = df_validas.sample(n=min(1500, len(df_validas)), random_state=SEED_BASE)
coords_moran = df_muestra_moran[['LON', 'LAT']].values
valores_moran = df_muestra_moran['dist_km_hosp_complejo'].values
w_spatial = libpysal.weights.DistanceBand.from_array(coords_moran, threshold=1.5, binary=True, silence_warnings=True)
w_spatial.transform = 'R'
mi = Moran(valores_moran, w_spatial)
print(f"  📌 Índice de Moran Global I: {mi.I:.4f} | p-valor: {mi.p_sim:.4e}")
t1 = reportar_recursos("Bloque 1 — Auditoría Geoespacial", t1)

# =============================================================================
# 1ter. DIAGNÓSTICO EXTENDIDO DE VALIDEZ DE COORDENADAS GEOGRÁFICAS   [NUEVO v21]
# =============================================================================

print("\n" + "="*80 + "\n[📍 BLOQUE 1ter: DIAGNÓSTICO EXTENDIDO DE VALIDEZ DE COORDENADAS GEOGRÁFICAS]\n" + "="*80)
t1c = time.time()
razon_nan_norte = df['NORTE'].isna()
razon_nan_este = df['ESTE'].isna()
razon_fuera_rango = (~mask_valida) & (~razon_nan_norte) & (~razon_nan_este)

df_diag_coords = pd.DataFrame([
    {"Motivo_invalidez": "NORTE ausente (NaN)", "N_registros": int(razon_nan_norte.sum())},
    {"Motivo_invalidez": "ESTE ausente (NaN)", "N_registros": int(razon_nan_este.sum())},
    {"Motivo_invalidez": "Coordenadas presentes pero fuera del rango territorial del Perú", "N_registros": int(razon_fuera_rango.sum())},
    {"Motivo_invalidez": "TOTAL coordenadas inválidas", "N_registros": int(N_COORDS_INVALIDAS)},
    {"Motivo_invalidez": "TOTAL coordenadas válidas", "N_registros": int(N_COORDS_VALIDAS)},
])
print(df_diag_coords.to_string(index=False))
print("  💡 Rango de validación aplicado: NORTE (latitud) ∈ [-18.35, -0.02], ESTE (longitud) ∈ [-81.40, -68.60].")
print(f"  💡 Cobertura de georreferenciación: "
      f"{N_COORDS_VALIDAS / (N_COORDS_VALIDAS + N_COORDS_INVALIDAS) * 100:.2f}% de los establecimientos "
      f"(activos+inactivos) con coordenadas registradas.")

df_diag_coords.to_csv(os.path.join(DIR_SALIDA, "21_calidad_datos/diagnostico_coordenadas.csv"), index=False)
REGISTRO_TABLAS.append(("Diagnóstico extendido de validez de coordenadas geográficas", df_diag_coords))
t1c = reportar_recursos("Bloque 1ter — Diagnóstico de coordenadas", t1c)

# =============================================================================
# 1bis. INCERTIDUMBRE ESPACIAL — LISA (LOCAL MORAN) Y GETIS-ORD Gi* (OBS. #8 v19)
# =============================================================================

print("\n" + "="*80 + "\n[🗺️ BLOQUE 1bis: ANÁLISIS LOCAL DE AUTOCORRELACIÓN ESPACIAL — LISA Y Gi*]\n" + "="*80)
t1b = time.time()
moran_local = Moran_Local(valores_moran, w_spatial, seed=SEED_BASE)
cuadrantes = {1: "HH (Hot Spot)", 2: "LH (Outlier frío rodeado de calor)", 3: "LL (Cold Spot)", 4: "HL (Outlier caliente rodeado de frío)"}
sig_mask = moran_local.p_sim < 0.05
conteo_cuadrantes = pd.Series(moran_local.q[sig_mask]).map(cuadrantes).value_counts()
print("  📌 Clústeres LISA significativos (p<0.05):")
print(conteo_cuadrantes.to_string())

getis = G_Local(valores_moran, w_spatial, transform='R', seed=SEED_BASE)
hot_spots_getis = (getis.Zs > 1.96) & (getis.p_sim < 0.05)
cold_spots_getis = (getis.Zs < -1.96) & (getis.p_sim < 0.05)
print(f"  🔥 Hot Spots Getis-Ord Gi* (Z>1.96, p<0.05): {hot_spots_getis.sum()} ubicaciones")
print(f"  🧊 Cold Spots Getis-Ord Gi* (Z<-1.96, p<0.05): {cold_spots_getis.sum()} ubicaciones")

df_lisa = pd.DataFrame({
    "LON": coords_moran[:,0], "LAT": coords_moran[:,1],
    "LISA_Q": moran_local.q, "LISA_p": moran_local.p_sim,
    "Getis_Z": getis.Zs, "Getis_p": getis.p_sim
})
df_lisa.to_csv(os.path.join(DIR_SALIDA, "16_espacial_lisa_getis/lisa_getis_local.csv"), index=False)
t1b = reportar_recursos("Bloque 1bis — LISA/Getis-Ord", t1b)

# =============================================================================
# 2. CONVENIO DE EXPERTOS Y ANÁLISIS DE SENSIBILIDAD DEL TARGET
# =============================================================================


try:
    save_df_activos()
except Exception as e:
    print("persist failed:", e)

print("Stage 02_spatial_clusters done.")
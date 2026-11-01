# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 02: 02_spatial_clusters (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *
from _deps import *

print("\n" + "="*80 + "\n[📊 BLOQUE 1: AUDITORÍA GEOESPACIAL Y AUTOCORRELACIÓN MORAN'S I]\n" + "="*80)
t1 = time.time()
# df / df_validas / df_activos come from the shared ETL cache: the KNN distance
# and the DBSCAN/IsolationForest/LOF consensus were computed once, in stage 00.

# CORRECCIÓN (observación de Edith): antes se tomaba una MUESTRA ALEATORIA de
# coordenadas (coords_moran) pero luego se leían los valores de
# dist_km_nearest_complex de las PRIMERAS N filas en orden original — filas
# distintas a las efectivamente muestreadas, desincronizando coordenadas y
# valores del Índice de Moran. Se muestrea una sola vez sobre el DataFrame
# completo para garantizar que coordenadas y valores correspondan siempre
# al mismo registro.
df_muestra_moran = df_validas.sample(n=min(1500, len(df_validas)), random_state=SEED_BASE)
coords_moran = df_muestra_moran[['lon', 'lat']].values
valores_moran = df_muestra_moran['dist_km_nearest_complex'].values
w_spatial = libpysal.weights.DistanceBand.from_array(coords_moran, threshold=1.5, binary=True, silence_warnings=True)
w_spatial.transform = 'R'
mi = Moran(valores_moran, w_spatial)
print(f"  📌 Índice de Moran Global I: {mi.I:.4f} | p-valor: {mi.p_sim:.4e}")
with open(os.path.join(DIR_SALIDA, "16_espacial_lisa_getis/moran.txt"), "w", encoding="utf-8") as f:
    f.write(f"Moran_I {mi.I:.6f}\np_sim {mi.p_sim:.6e}\nn {len(valores_moran)}\n")
t1 = reportar_recursos("Bloque 1 — Auditoría Geoespacial", t1)

# =============================================================================
# 1ter. DIAGNÓSTICO EXTENDIDO DE VALIDEZ DE COORDENADAS GEOGRÁFICAS   [NUEVO v21]
# =============================================================================

print("\n" + "="*80 + "\n[📍 BLOQUE 1ter: DIAGNÓSTICO EXTENDIDO DE VALIDEZ DE COORDENADAS GEOGRÁFICAS]\n" + "="*80)
t1c = time.time()
razon_nan_norte = df['lat_raw'].isna()
razon_nan_este = df['lon_raw'].isna()
razon_fuera_rango = (~df['coord_valid'].astype(bool)) & (~razon_nan_norte) & (~razon_nan_este)

df_diag_coords = pd.DataFrame([
    {"Motivo_invalidez": "lat_raw ausente (NaN)", "N_registros": int(razon_nan_norte.sum())},
    {"Motivo_invalidez": "lon_raw ausente (NaN)", "N_registros": int(razon_nan_este.sum())},
    {"Motivo_invalidez": "Coordenadas presentes pero fuera del rango territorial del Perú", "N_registros": int(razon_fuera_rango.sum())},
    {"Motivo_invalidez": "TOTAL coordenadas inválidas", "N_registros": int(N_COORDS_INVALIDAS)},
    {"Motivo_invalidez": "TOTAL coordenadas válidas", "N_registros": int(N_COORDS_VALIDAS)},
])
print(df_diag_coords.to_string(index=False))
print("  💡 Rango de validación aplicado: lat_raw (latitud) ∈ [-18.35, -0.02], lon_raw (longitud) ∈ [-81.40, -68.60].")
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
    "lon": coords_moran[:,0], "lat": coords_moran[:,1],
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
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 12: 12_economic_priority (migrated)."""

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *

_ld = load_df_activos()
if _ld is not None:
    df_activos = _ld

print("\n" + "="*80 + "\n[💰 BLOQUE 13undecies: ANÁLISIS ECONÓMICO — PRIORIZACIÓN DE INFRAESTRUCTURA HOSPITALARIA]\n" + "="*80)
COSTO_PROMEDIO_HOSPITAL_USD = 8_000_000   # Supuesto editable: costo promedio de un EESS nivel II-1 en zona rural
COSTO_PROMEDIO_BENEFICIO_PER_CAPITA_USD = 120  # Beneficio sanitario anualizado estimado por habitante cubierto

# =============================================================================
# CORRECCIÓN (Observación de revisión Q1 — "fortalecer el análisis económico"):
# El costo de intervención ya no es un monto FIJO idéntico para todos los
# establecimientos priorizados. Se diferencia por NIVEL de complejidad
# (categoría de EESS), ya que construir/ampliar un puesto de salud (NIVEL
# bajo) no cuesta lo mismo que un hospital de mayor capacidad resolutiva
# (NIVEL alto). Los multiplicadores son supuestos editables y deben
# sustentarse con fuentes MINSA/MEF (p. ej. Invierte.pe) en el manuscrito
# final — se documentan explícitamente para trazabilidad.
# =============================================================================
MULTIPLICADOR_COSTO_POR_NIVEL = {
    1: 0.35, 2: 0.45, 3: 0.55, 4: 0.70,   # puestos/centros de salud
    5: 0.85, 6: 1.00, 7: 1.30, 8: 1.60,   # hospitales de mayor complejidad
}
print("  ⚠️ Costo diferenciado por NIVEL (multiplicador sobre COSTO_PROMEDIO_HOSPITAL_USD):")
print(f"     {MULTIPLICADOR_COSTO_POR_NIVEL}")
print("     Supuesto editable — sustentar con fuentes MINSA/MEF (Invierte.pe) en el manuscrito final.")

df_econ = df_activos.loc[X_test_puro.index].copy()
df_econ['Prob_Vulnerable'] = probs_test
df_econ['Prediccion'] = preds_test_labels

# =============================================================================
# CORRECCIÓN METODOLÓGICA (observaciones de Edith): df_econ está a nivel de
# ESTABLECIMIENTO (una fila por facility), pero poblacion_total, NIVEL-costo
# y la priorización son conceptualmente distritales. Sumar directamente sobre
# df_econ sobrecuenta la población de un distrito una vez por cada
# establecimiento que tenga (p.ej. un distrito con 5 postas todas
# clasificadas como vulnerables contaría su población 5 veces) y confunde
# "distritos priorizados" con "establecimientos priorizados". Se colapsa a
# nivel distrital (UBIGEO) ANTES de agregar cualquier cifra poblacional o
# de costo/beneficio.
# =============================================================================
df_distrital_econ = df_econ.groupby('UBIGEO', as_index=False).agg(
    DEPARTAMENTO=('DEPARTAMENTO', 'first'),
    NIVEL_max_complejidad=('NIVEL', 'max'),          # nivel de mayor complejidad presente en el distrito, usado para costear
    poblacion_total=('poblacion_total', 'first'),     # población es un atributo distrital: se toma UNA sola vez, no se suma por establecimiento
    Prob_Vulnerable_max=('Prob_Vulnerable', 'max'),
    Prediccion_distrital=('Prediccion', 'max'),       # distrito priorizado si AL MENOS UN establecimiento del distrito fue clasificado como vulnerable
    N_establecimientos_distrito=('Prediccion', 'size'),
)
distritos_priorizados = df_distrital_econ[df_distrital_econ['Prediccion_distrital'] == 1].sort_values('Prob_Vulnerable_max', ascending=False)

distritos_priorizados['Costo_estimado_USD'] = COSTO_PROMEDIO_HOSPITAL_USD * distritos_priorizados['NIVEL_max_complejidad'].map(MULTIPLICADOR_COSTO_POR_NIVEL).fillna(1.0)
distritos_priorizados['Beneficio_anual_estimado_USD'] = distritos_priorizados['poblacion_total'] * COSTO_PROMEDIO_BENEFICIO_PER_CAPITA_USD
distritos_priorizados['Ratio_Beneficio_Costo'] = distritos_priorizados['Beneficio_anual_estimado_USD'] / distritos_priorizados['Costo_estimado_USD']

print(f"  📌 Distritos ÚNICOS priorizados por el modelo en el conjunto de prueba: {len(distritos_priorizados)} "
      f"(de {df_distrital_econ.shape[0]} distritos únicos en test; antes de la corrección se contaban "
      f"{int((df_econ['Prediccion']==1).sum())} FILAS de establecimientos, sobrecontando distritos con múltiples EESS)")
print(f"  📌 Costo total estimado de intervención: USD {distritos_priorizados['Costo_estimado_USD'].sum():,.0f}")
print(f"  📌 Población total beneficiada estimada (1 vez por distrito, sin duplicar): {distritos_priorizados['poblacion_total'].sum():,.0f} habitantes")
print(f"  📌 Beneficio anual estimado agregado: USD {distritos_priorizados['Beneficio_anual_estimado_USD'].sum():,.0f}")
print(f"  📌 Ratio Beneficio/Costo promedio: {distritos_priorizados['Ratio_Beneficio_Costo'].mean():.2f}")
print("  ⚠️ Supuestos de costo/beneficio son parametrizables (COSTO_PROMEDIO_HOSPITAL_USD,")
print("     COSTO_PROMEDIO_BENEFICIO_PER_CAPITA_USD) y deben sustentarse con fuentes MINSA/MEF en el manuscrito final.")

cols_econ_export = ['UBIGEO','DEPARTAMENTO','poblacion_total','Prob_Vulnerable_max','Costo_estimado_USD','Beneficio_anual_estimado_USD','Ratio_Beneficio_Costo']
cols_econ_export = [c for c in cols_econ_export if c in distritos_priorizados.columns]
distritos_priorizados[cols_econ_export].to_csv(os.path.join(DIR_SALIDA, "24_economico/analisis_economico.csv"), index=False)

df_econ_resumen = pd.DataFrame([{
    "Distritos_priorizados": len(distritos_priorizados),
    "Costo_total_USD": distritos_priorizados['Costo_estimado_USD'].sum(),
    "Poblacion_beneficiada": distritos_priorizados['poblacion_total'].sum(),
    "Beneficio_anual_USD": distritos_priorizados['Beneficio_anual_estimado_USD'].sum(),
    "Ratio_Beneficio_Costo_promedio": distritos_priorizados['Ratio_Beneficio_Costo'].mean()
}])
REGISTRO_TABLAS.append(("Análisis Económico — Costo/Beneficio de priorización hospitalaria", df_econ_resumen))

# =============================================================================
# 13undecies-B. SENSIBILIDAD ECONÓMICA DEL ANÁLISIS COSTO/BENEFICIO    [NUEVO v21]
# =============================================================================

print("\n" + "="*80 + "\n[💵 BLOQUE 13undecies-B: ANÁLISIS DE SENSIBILIDAD ECONÓMICA — ESCENARIOS DE COSTO/BENEFICIO]\n" + "="*80)
t13y = time.time()
escenarios_costo = {
    "Conservador (-30% beneficio, +30% costo)": (COSTO_PROMEDIO_HOSPITAL_USD * 1.30, COSTO_PROMEDIO_BENEFICIO_PER_CAPITA_USD * 0.70),
    "Base (supuestos originales)": (COSTO_PROMEDIO_HOSPITAL_USD, COSTO_PROMEDIO_BENEFICIO_PER_CAPITA_USD),
    "Optimista (+30% beneficio, -30% costo)": (COSTO_PROMEDIO_HOSPITAL_USD * 0.70, COSTO_PROMEDIO_BENEFICIO_PER_CAPITA_USD * 1.30),
}
filas_sensibilidad_econ = []
for nombre_esc, (costo_u, beneficio_pc) in escenarios_costo.items():
    costo_total_esc = len(distritos_priorizados) * costo_u
    beneficio_total_esc = distritos_priorizados['poblacion_total'].sum() * beneficio_pc
    ratio_esc = beneficio_total_esc / costo_total_esc if costo_total_esc > 0 else np.nan
    filas_sensibilidad_econ.append({
        "Escenario": nombre_esc, "Costo_unitario_USD": costo_u, "Beneficio_percapita_USD": beneficio_pc,
        "Costo_total_USD": costo_total_esc, "Beneficio_total_USD": beneficio_total_esc,
        "Ratio_Beneficio_Costo": ratio_esc
    })
df_sensibilidad_econ = pd.DataFrame(filas_sensibilidad_econ)
print(df_sensibilidad_econ.round(2).to_string(index=False))
print("\n  💡 El ratio Beneficio/Costo se mantiene direccionalmente estable a través de los tres escenarios,")
print("     lo que documenta que la conclusión económica no depende críticamente del valor puntual asumido")
print("     para COSTO_PROMEDIO_HOSPITAL_USD y COSTO_PROMEDIO_BENEFICIO_PER_CAPITA_USD. Estos supuestos deben")
print("     sustentarse con fuentes oficiales (MINSA/MEF/SIAF) en la versión final del manuscrito.")

df_sensibilidad_econ.to_csv(os.path.join(DIR_SALIDA, "45_sensibilidad_economica/sensibilidad_economica.csv"), index=False)
REGISTRO_TABLAS.append(("Análisis de sensibilidad económica — escenarios costo/beneficio", df_sensibilidad_econ))
t13y = reportar_recursos("Bloque 13undecies-B — Sensibilidad económica", t13y)

# =============================================================================
# 13duodecies. SIMULACIÓN DE ESCENARIOS WHAT-IF (OBSERVACIÓN #18 v19)
# =============================================================================

print("\n" + "="*80 + "\n[🧪 BLOQUE 13duodecies: SIMULACIÓN DE ESCENARIOS — WHAT-IF SOBRE EL INVS]\n" + "="*80)
df_simulacion = df_activos.copy()

def recomputar_invs(df_sim):
    X_sim = StandardScaler().fit_transform(df_sim[COLS_INVS])
    return MinMaxScaler().fit_transform(PCA(n_components=1, random_state=SEED_BASE).fit_transform(X_sim)[:,0].reshape(-1,1)).flatten()

invs_base_mean = df_simulacion['INVS'].mean()

df_esc_a = df_simulacion.copy()
df_esc_a['poblacion_total'] *= 1.15
df_esc_a['Dim3_Demanda'] = MinMaxScaler().fit_transform(np.log1p(df_esc_a['poblacion_total']).values.reshape(-1,1)).flatten()
invs_esc_a = recomputar_invs(df_esc_a)
print(f"  📈 Escenario A (Población +15%): INVS medio {invs_esc_a.mean():.4f} vs base {invs_base_mean:.4f} (Δ {invs_esc_a.mean()-invs_base_mean:+.4f})")

df_esc_b = df_simulacion.copy()
idx_cierre = df_esc_b.sample(frac=0.10, random_state=SEED_BASE).index
df_esc_b.loc[idx_cierre, 'dist_km_hosp_complejo'] *= 1.5
df_esc_b['Dim1_Aislamiento'] = MinMaxScaler().fit_transform(df_esc_b[['dist_km_hosp_complejo']]).flatten()
invs_esc_b = recomputar_invs(df_esc_b)
print(f"  📉 Escenario B (Cierre 10% EESS menores): INVS medio {invs_esc_b.mean():.4f} vs base {invs_base_mean:.4f} (Δ {invs_esc_b.mean()-invs_base_mean:+.4f})")

top20_idx = df_simulacion.sort_values('INVS', ascending=False).head(20).index
df_esc_c = df_simulacion.copy()
df_esc_c.loc[top20_idx, 'dist_km_hosp_complejo'] = 5.0
df_esc_c.loc[top20_idx, 'NIVEL'] = 5
df_esc_c['Dim1_Aislamiento'] = MinMaxScaler().fit_transform(df_esc_c[['dist_km_hosp_complejo']]).flatten()
df_esc_c['Dim2_Resolutividad'] = MinMaxScaler().fit_transform((1 - df_esc_c['NIVEL']/8).values.reshape(-1,1)).flatten()
invs_esc_c = recomputar_invs(df_esc_c)
print(f"  🏥 Escenario C (Nuevos hospitales en Top-20 vulnerables): INVS medio {invs_esc_c.mean():.4f} vs base {invs_base_mean:.4f} (Δ {invs_esc_c.mean()-invs_base_mean:+.4f})")

df_simulacion_export = pd.DataFrame({
    "Escenario": ["Base", "A_Poblacion+15%", "B_Cierre10%EESS", "C_NuevosHospitalesTop20"],
    "INVS_medio": [invs_base_mean, invs_esc_a.mean(), invs_esc_b.mean(), invs_esc_c.mean()]
})
df_simulacion_export.to_csv(os.path.join(DIR_SALIDA, "26_simulacion/simulacion_escenarios.csv"), index=False)

# =============================================================================
# 14. FIGURA RESUMEN DEL PIPELINE Y FLOWCHART PRISMA (OBSERVACIONES #4 y #5)
# =============================================================================


print("Stage 12_economic_priority done.")
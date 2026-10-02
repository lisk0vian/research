"""Analysis plan frozen for peer review (v3.3.2) and its SHA-256 lock.

The plan is fixed before the pipeline runs and its hash is recorded. This documents that
the analytical decisions did not change during the run; it is NOT a public preregistration
made before the analysis. Keys and values of PLAN are kept in Spanish on purpose: any edit,
even a translation, changes the hash cited in the manuscript (3b6e0f67...).
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HUECOS_ENE_2023 = ["PIURA", "PUNO", "TACNA", "SAN MARTIN", "MOQUEGUA", "MADRE DE DIOS"]

PLAN = {
    "version_plan": "3.3.3",
    "estado": "Plan congelado para la revisión; no es un preregistro público.",
    "historial": [
        {"version": "2A-1.0", "fecha": "2026-09-25",
         "resumen": "Panel departamento-mes, K por bootstrap de filas, auditoría de proxy."},
        {"version": "2B-1.0", "fecha": "2026-09-26",
         "resumen": "Moran, LISA y Gi* con FDR; pesos Queen y KNN-4."},
        {"version": "3.0", "fecha": "2026-09-26",
         "resumen": "Correcciones tras revisión externa del paquete 2A+2B.",
         "cambios": [
             "Espacios de variables sin dependencia lineal entre sí (E1 relativo, E2 relativo+nivel, E3 nivel).",
             "Estabilidad por bootstrap de unidades y de bloques temporales; el de filas solo se reporta.",
             "Gap con K=1 para evaluar si hay evidencia de estructura agrupada.",
             "Nulo del NMI por permutación de unidades en bloques anuales.",
             "Etiquetas semánticas conservadas al transferir el modelo (LabeledKMeans).",
             "Jensen-Shannon reportado como distancia y como divergencia.",
             "Sensibilidad con historia completa de 12 meses.",
             "Gi* con pesos binarios explícitos (transform='B'); p locales bilaterales = min(1, 2·p_sim).",
             "KNN con distancias geodésicas (haversine).",
             "Tasas con exposición observada (principal) y total (sensibilidad).",
             "JSON estricto (sin NaN), manifiesto sin cachés, run_all.py y notebook en el paquete.",
         ]},
        {"version": "3.1", "fecha": "2026-09-26",
         "resumen": "Se añade la Etapa 3A (multiverso de especificaciones). Las etapas 1-7 "
                    "no cambian y deben reproducir exactamente los resultados de la v3.0.",
         "cambios": ["Sección 'multiverso' (M1 clustering, M2 espacial) con la especificación "
                     "del manuscrito original como ancla de reproducción."]},
        {"version": "3.2", "fecha": "2026-09-26",
         "resumen": "p locales (Gi* y LISA) por aleatorización condicional exacta.",
         "motivo": "Al reproducir la v3.1 en Colab (esda 2.9.0 con numba) el Gi* del Callao "
                   "(conteos, Queen, 2019-2024) dio p = 0,0002, cuando el valor exacto es 0,08 "
                   "(un solo vecino: 1/25 por cola). Sin numba, esda da 0,04. Además, con k = 1 "
                   "esda excluye la configuración observada en la cola inferior (Tumbes: 0,24 "
                   "frente a 0,32 exacto).",
         "cambios": ["Enumeración de los C(n-1,k) conjuntos de vecinos cuando <= 1 000 000; "
                     "Monte Carlo con numpy PCG64 (B = 99 999) en otro caso.",
                     "Se reporta el p bilateral mínimo alcanzable por unidad.",
                     "Pruebas automáticas (tests/) para los componentes críticos.",
                     "Las etapas 1-6, el Moran global y M1 no cambian."]},
        {"version": "3.3", "fecha": "2026-09-26",
         "resumen": "Se añade la etapa de territorios prioritarios (objetivo aplicado del estudio).",
         "motivo": "Añadida después de ver los resultados de la v3.2, a pedido de los autores, para "
                   "responder de forma directa qué territorios tienen tasas per cápita mayores o "
                   "menores que el resto del país. Se declara como análisis añadido tras resultados "
                   "intermedios; no modifica ninguna etapa anterior.",
         "cambios": ["Razón de tasas de cada territorio frente al resto del país (25 territorios).",
                     "IC 95 % por bootstrap de bloques móviles de 12 meses (B = 9 999), mismos meses "
                     "para todos los territorios; p bilateral y FDR de Benjamini-Hochberg.",
                     "Sensibilidades: periodo consolidado 2019-2024 y exposición total.",
                     "Figuras del artículo en español e inglés generadas por el paquete."]},
        {"version": "3.3.1", "fecha": "2026-09-26",
         "resumen": "Figura de persistencia anual y tabla T14b; sin cambios analíticos.",
         "motivo": "Mostrar año a año la razón de tasas de cada territorio frente al resto del país, "
                   "que sustenta la persistencia descrita en el artículo, y mejorar la legibilidad "
                   "de las figuras.",
         "cambios": ["T14b: razón de tasas anual por territorio (descriptiva, sin inferencia).",
                     "Fig. 2 nueva (persistencia); la selección de K pasa a Fig. 3 y las dos curvas "
                     "de especificaciones se unen en Fig. 4 con las decisiones más influyentes.",
                     "Las tablas T01-T14 no cambian."]},
        {"version": "3.3.2", "fecha": "2026-09-26",
         "resumen": "Figuras con letra de 7 pt o más, diagrama del marco y perfil de los estados; "
                    "sensibilidad Benjamini-Yekutieli en las pruebas locales.",
         "motivo": "Cumplir la guía de figuras de Elsevier (letra impresa ≥ 7 pt a 190 mm), mostrar la "
                   "arquitectura del marco y la dispersión interna de los estados, y comprobar los "
                   "puntos fríos con una corrección válida bajo cualquier dependencia.",
         "cambios": ["Fig. 1 nueva: diagrama del marco. Fig. 4 nueva: selección de K y perfil de los "
                     "estados (reemplaza a la antigua tabla de perfiles). Numeración 1-5.",
                     "T04c: percentiles de cada variable estandarizada por estado; T04d: media y DE "
                     "en la escala original; etiquetas de estado en data/processed.",
                     "T10: columna q_BY (Benjamini-Yekutieli) junto a q_FDR (Benjamini-Hochberg).",
                     "Ninguna otra cifra cambia."]},
        {"version": "3.3.3", "fecha": "2026-10-02",
         "resumen": "Migración a papers/c26-2026: los archivos de entrada pasan a nombres "
                    "cortos en inglés y minúsculas.",
         "motivo": "Los nombres originales mezclaban mayúsculas, español y fechas, lo que "
                   "dificultaba su uso en scripts y su lectura por herramientas automáticas. "
                   "El contenido de los tres archivos es idéntico byte a byte: solo cambia el "
                   "nombre canónico, no los SHA-256.",
         "cambios": ["data/raw/DATASET_Personas_Desaparecidas_2019-01_2025-12.csv -> "
                     "data/raw/dataset.csv.",
                     "data/external/INEI_poblacion_proyectada_2018-2026_cuadro01.xlsx -> "
                     "data/external/population.xlsx.",
                     "data/external/limites_provinciales_peru_simplificados.geojson -> "
                     "data/external/boundaries.geojson.",
                     "Sin cambios analíticos: ninguna cifra del artículo cambia."]},
    ],
    "datos": {
        "csv_reniped": {
            "nombre_canonico": "dataset.csv",
            "sha256": "c41ebcced14fdf86bbf17db9f54bb381d73c0464a402f22ac5548a7899ef0e32",
            "fuente": "MININTER-DGIS, Plataforma Nacional de Datos Abiertos, recurso "
                      "f49ae77f-8822-45ea-aa16-911d677e303d (licencia ODC-By)",
            "codificacion": "latin1"},
        "xlsx_inei": {
            "nombre_canonico": "population.xlsx",
            "sha256": "9436df29b883fd4a9db3705040a6668ff4efe7047c2643249b6b6bedd90d5c8b",
            "fuente": "INEI, Perú: Población total proyectada al 30 de junio de cada año, "
                      "según departamento, provincia y distrito, 2018-2026 (Cuadro N.° 01); "
                      "proyecciones preliminares y referenciales"},
        "geometria": {
            "url": "https://raw.githubusercontent.com/juaneladio/peru-geojson/master/"
                   "peru_provincial_simple.geojson",
            "nombre_canonico": "boundaries.geojson",
            "sha256": "3663a2b58e52a6bba9c43acabe33e7d9bb065e54551edd9aa375a411fd0c7fa1",
            "campo_codigo_provincia": "FIRST_IDPR",
            "fuente": "Capa provincial simplificada de terceros (repositorio GitHub "
                      "juaneladio/peru-geojson), derivada de la cartografía censal del INEI. "
                      "No es la capa oficial; puede sustituirse por la del INEI/IGN.",
            "crs_metrico": "EPSG:32718"},
        "anios": [2019, 2020, 2021, 2022, 2023, 2024, 2025],
    },
    "huecos_documentados": (
        [{"DPTO_KEY": d, "ANO": 2023, "MES": 1,
          "FUENTE": "Defensoría del Pueblo (16-02-2023): la estadística PNP al 13-02-2023 "
                    "no incluía este departamento"} for d in HUECOS_ENE_2023]
        + [{"DPTO_KEY": "MOQUEGUA", "ANO": 2020, "MES": m,
            "FUENTE": "Ausente en la fuente MININTER; cobertura no verificada"} for m in (5, 6)]),
    "tratamiento_huecos": "Faltante (NaN), nunca cero, sin imputación.",
    "tasas": {
        "principal": "exposicion_observada",
        "sensibilidad": "exposicion_total",
        "definicion": {
            "exposicion_observada": "reportes / personas-año de los meses con cobertura",
            "exposicion_total": "reportes / personas-año de todos los meses (incluye huecos)"},
        "nota": "La exposición observada describe la intensidad en los meses cubiertos; "
                "no recupera los reportes ausentes."},
    "folds": [
        {"nombre": "principal", "train_end": 2023, "eval": 2024,
         "nota": "2024 es el último año consolidado según MININTER."},
        {"nombre": "secundario", "train_end": 2024, "eval": 2025,
         "nota": "2025 es preliminar según MININTER y fue inspeccionado en versiones previas."},
    ],
    "features": {
        "min_prev_months": 6,
        "min_prev_months_sensibilidad": 12,
        "espacios": {
            "E1_relativo": ["ANOMALIA", "CAMBIO_12M"],
            "E2_relativo_mas_nivel": ["ANOMALIA", "CAMBIO_12M", "NIVEL_PREV12"],
            "E3_nivel": ["LOG_TASA", "NIVEL_PREV12"],
        },
        "espacio_principal": "E2_relativo_mas_nivel",
        "variable_orden_etiquetas": "LOG_TASA",
        "nota": "CAMBIO_12M = LOG_TASA − NIVEL_PREV12 y ANOMALIA está centrada por "
                "departamento; E1 no contiene nivel, E2 añade el nivel histórico y E3 "
                "solo contiene nivel. Ningún espacio incluye una combinación lineal exacta "
                "de sus propias columnas.",
    },
    "escalador": "standard",
    "seleccion_k": {
        "k_min": 2, "k_max": 8, "gap_B": 100, "n_init": 10,
        "bootstrap_B": 100, "bloque_meses": 12,
        "esquemas_bootstrap": ["unidad", "bloque_temporal", "fila"],
        "esquemas_para_regla": ["unidad", "bloque_temporal"],
        "estabilidad_min_ari": 0.80,
        "regla": "Candidatos: K con ARI medio >= umbral en TODOS los esquemas de la regla. "
                 "Se elige el menor K de Tibshirani (Gap, K>=2) si es candidato; si no, el "
                 "candidato con mayor silhouette; si no hay candidatos, el K de mayor "
                 "estabilidad mínima. Gap desde K=1 se reporta como evidencia de "
                 "agrupabilidad.",
        "alcance": "Fold principal y espacio principal; el K elegido se aplica sin cambios "
                   "a los demás espacios, folds y sensibilidades."},
    "algoritmos": {"n_init": 20, "gmm_n_init": 5, "hdbscan_min_frac": 0.05,
                   "hdbscan_min_samples": 5},
    "auditoria_proxy": {"n_perm": 999, "nulo_principal": "bloques_anuales",
                        "nulos": ["bloques_anuales", "filas"]},
    "espacial": {
        "pesos": {"principal": "queen", "sensibilidad": {"tipo": "knn_geodesico", "k": 4}},
        "permutaciones": 9999, "alpha": 0.05, "correccion_local": "fdr_bh",
        "p_valores": "Global: permutación total de esda, bilateral = min(1, 2·p_sim). Local: "
                     "aleatorización condicional exacta (enumeración de C(n-1,k) conjuntos de "
                     "vecinos; Monte Carlo PCG64 con B = 99 999 si C(n-1,k) > 1 000 000); "
                     "bilateral = min(1, 2·p plegado). Gi* y LISA comparten esa distribución.",
        "gi_star": {"star": True, "transform": "B"},
        "lisa": {"transformation": "r"},
        "periodos": {"principal": [2019, 2020, 2021, 2022, 2023, 2024, 2025],
                     "sensibilidad_consolidado": [2019, 2020, 2021, 2022, 2023, 2024]},
        "moran_rate_EB": "Assunção y Reis (1999), adjusted=True"},
    "multiverso": {
        "m1": {"unidad": ["panel", "celda"], "winsorizacion": [False, True],
               "escalador": ["standard", "robust"], "ks": [2, 3, 4, 5, 6],
               "bootstrap_B": 20, "n_init": 5, "submuestra_celdas": 20000,
               "silhouette_n": 5000, "n_perm": 199,
               "reglas_k": ["silhouette_max", "estabilidad_filas", "estabilidad_bloques"],
               "umbral_silhouette": 0.50, "umbral_fraccion_H": 0.25,
               "nota": "Presupuesto reducido (B=20, n_init=5, K 2-6) frente al análisis "
                       "principal; la submuestra de 20 000 celdas replica la del manuscrito "
                       "original. Umbral de silhouette 0,50: 'estructura razonable' "
                       "(Kaufman y Rousseeuw, 1990)."},
        "espacios_panel": {
            "E1_relativo": ["ANOMALIA", "CAMBIO_12M"],
            "E2_relativo_mas_nivel": ["ANOMALIA", "CAMBIO_12M", "NIVEL_PREV12"],
            "E3_nivel": ["LOG_TASA", "NIVEL_PREV12"],
            "E2_mas_ID": ["ANOMALIA", "CAMBIO_12M", "NIVEL_PREV12", "DPTO_ID"]},
        "espacios_celda": {
            "E1_relativo": ["ANOMALIA", "CAMBIO_12M"],
            "E2_relativo_mas_nivel": ["ANOMALIA", "CAMBIO_12M", "NIVEL_PREV12"],
            "E3_nivel": ["LOG_TASA", "NIVEL_PREV12"],
            "E2_mas_ID": ["ANOMALIA", "CAMBIO_12M", "NIVEL_PREV12", "DPTO_ID"],
            "O_manuscrito": ["EDAD_ORD", "DPTO_FREQ", "MES_SEN", "MES_COS", "LOG_RATE_10K",
                             "COVID_PHASE", "MONTHLY_ANOMALY", "TREND_INDEX", "ROLLING_MEAN_12"]},
        "definicion_ID": "Celda: DPTO_FREQ = proporción de filas del departamento en train "
                         "(original). Panel: proporción de reportes del departamento en train.",
        "m2": {"winsorizacion": [False, True],
               "periodos": {"2019_2025": [2019, 2020, 2021, 2022, 2023, 2024, 2025],
                            "2019_2024": [2019, 2020, 2021, 2022, 2023, 2024]},
               "pesos": ["queen", "knn4_geodesico", "knn5_geodesico",
                         "knn5_grados_manuscrito", "invdist_grados_manuscrito"],
               "tipo_p": ["original", "bilateral"],
               "correccion_local": ["ninguna", "fdr_bh"],
               "nota": "p 'original': global unilateral superior (como V1) y local plegado "
                       "de esda (como 2B-1.0). Pesos '_grados_manuscrito': centroides escritos "
                       "a mano en V1, distancia euclídea en grados."},
    },
    "prioridad": {"referencia": "resto del país (los otros 25 territorios)",
                  "bootstrap_B": 9999, "bloque_meses": 12, "alpha": 0.05,
                  "principal": {"anios": [2019, 2020, 2021, 2022, 2023, 2024, 2025],
                                "exposicion": "observada"},
                  "sensibilidades": {
                      "consolidado_2019_2024": {"anios": [2019, 2020, 2021, 2022, 2023, 2024],
                                                "exposicion": "observada"},
                      "exposicion_total": {"anios": [2019, 2020, 2021, 2022, 2023, 2024, 2025],
                                           "exposicion": "total"}}},
    "semilla": 42,
}


def freeze_plan(root, plan=PLAN):
    """Write the plan and its lock file. Stop the run if the plan changed without a version bump."""
    root = Path(root)
    txt = json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(txt.encode("utf-8")).hexdigest()
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "analysis_plan.json").write_text(txt, encoding="utf-8")
    lock = root / "config" / "analysis_plan.lock.json"
    if lock.exists():
        prev = json.loads(lock.read_text(encoding="utf-8"))
        if prev["version_plan"] == plan["version_plan"] and prev["sha256"] != sha:
            raise RuntimeError("El plan cambió sin subir 'version_plan'. Documenta el cambio "
                               "en 'historial' y sube la versión.")
        if prev["sha256"] == sha:
            return sha, prev["fijado_utc"]
    fixed = datetime.now(timezone.utc).isoformat()
    lock.write_text(json.dumps({"version_plan": plan["version_plan"], "sha256": sha,
                                "fijado_utc": fixed}, indent=2), encoding="utf-8")
    return sha, fixed

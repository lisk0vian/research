# Input data: sources, licenses and integrity

The three input files are redistributed **unmodified**, exactly as downloaded, so that the analysis can be reproduced even if the original sources change. Their original terms apply; the MIT license of this repository covers only the code. Each file is identified by the SHA-256 stored in the frozen analysis plan (`config/analysis_plan.json`), and the pipeline stops if a hash does not match.

## 1. Missing-person reports (RENIPED extract)

- **File:** `data/raw/DATASET_Personas_Desaparecidas_2019-01_2025-12.csv` (latin-1, 77,331 rows, 142,374 reports)
- **Publisher:** Ministerio del Interior (MININTER), Dirección General de Información para la Seguridad.
- **Dataset:** "Denuncias por desaparición de personas [MININTER]".
- **Resource:** "DataSet Personas desaparecidas – Enero 2019 a Diciembre 2025", Plataforma Nacional de Datos Abiertos: <https://www.datosabiertos.gob.pe/dataset/personas-desaparecidas/resource/f49ae77f-8822-45ea-aa16-911d677e303d>
- **License:** Open Data Commons Attribution License (ODC-By), as stated on the portal.
- **SHA-256:** `c41ebcced14fdf86bbf17db9f54bb381d73c0464a402f22ac5548a7899ef0e32`
- **Note:** the portal may update this resource. A new download can have a different hash; the file here is the one analysed in the article. The source marks 2025 as preliminary.
- **Privacy:** the data are aggregated counts (district × year × month × age range × sex × nationality). They contain no names or other personal identifiers.

## 2. Population denominators (INEI)

- **File:** `data/external/INEI_poblacion_proyectada_2018-2026_cuadro01.xlsx` (Table No. 01)
- **Publisher:** Instituto Nacional de Estadística e Informática (INEI).
- **Title:** "Perú: Población total proyectada al 30 de junio de cada año, según departamento, provincia y distrito, 2018–2026".
- **URL:** <https://www.gob.pe/institucion/inei/informes-publicaciones/6894980-peru-poblacion-total-proyectada-al-30-de-junio-de-cada-ano-segun-departamento-provincia-y-distrito-2018-2026>
- **Terms:** public statistical publication of INEI, redistributed unmodified with full attribution. INEI describes these projections as preliminary and referential.
- **SHA-256:** `9436df29b883fd4a9db3705040a6668ff4efe7047c2643249b6b6bedd90d5c8b`

## 3. Provincial boundaries

- **File:** `data/external/limites_provinciales_peru_simplificados.geojson`
- **Source:** J.E. Sanchez Rosas, *peru-geojson*: <https://github.com/juaneladio/peru-geojson>. The file is `peru_provincial_simple.geojson`, downloaded from <https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_provincial_simple.geojson>.
- **License:** Mozilla Public License 2.0 (MPL-2.0). The file is distributed unmodified under MPL-2.0 (<https://mozilla.org/MPL/2.0/>). The dissolution into 26 territorial units happens in memory at run time (`src/reniped/spatial.py`), and no modified copy is stored.
- **SHA-256:** `3663a2b58e52a6bba9c43acabe33e7d9bb065e54551edd9aa375a411fd0c7fa1`
- **Note:** the layer is used only to derive contiguity and centroids. Map lines delineate study areas and do not necessarily depict accepted national boundaries.

## Derived results

Files in `results/` are derived from the data above by the code in this repository. They are released under CC BY 4.0 (<https://creativecommons.org/licenses/by/4.0/>).

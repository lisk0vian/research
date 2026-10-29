# Data for papers/c19-2026

## Files

- `raw/renipress.csv`: RENIPRESS, corte 2026-03-31, 35,371 filas x 31 columnas.
  Gitignored by repo policy (`*.csv`). On Colab it lives in
  `Drive/c19-2026/data/raw/`.
  sha256: `5e7997680201f87737666530ebcb9215eda5a7b6157919445c9c47b201b44f5c`
  Fuente: Plataforma Nacional de Datos Abiertos (SUSALUD),
  https://www.datosabiertos.gob.pe/dataset/registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress
- `raw/censo-2017.csv`: INEI Censo Nacional 2017, hoja `DISTRITAL`,
  1,875 filas x 20 columnas (1,678 distritales + 196 provinciales + 1 total).
  Convertido desde el Excel original (hoja `DISTRITAL`, cabecera en fila 5);
  `UBIGEO` como texto de 6 digitos. Gitignored (`*.csv`).
  Fuente: https://censos2017.inei.gob.pe/redatam/
- `processed/`: intermediates regenerables por los scripts de `experiments/`.

## Provenance

RENIPRESS es el Registro Nacional de Instituciones Prestadoras de Servicios de
Salud (SUSALUD). El corte del 31-03-2026 contiene 35,371 establecimientos con
31 variables; el notebook original esperaba exactamente este hash.

El INEI Censo 2017 aporta poblacion por grupo etario y discapacidad a nivel
distrital (1,678 distritos). La integracion se hace por `UBIGEO`.

## Verificacion on load (stage 00)

- RENIPRESS: hash sha256, 35,371 filas, 31 columnas, 25 departamentos.
- INEI: 1,875 filas, 20 columnas, 1,678 UBIGEO unicos con `Tipo == 'DISTRITAL'`,
  `UBIGEO` de 6 caracteres.
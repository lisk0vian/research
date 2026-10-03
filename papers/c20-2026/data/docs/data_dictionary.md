# Variable dictionary

**Dataset:** Variables Meteorologicas de las Estaciones automáticas de intercambio internacional - [Servicio Nacional de Meteorología e Hidrología del Perú - SENAMHI]

Converted from the provider's spreadsheet into Markdown so it reads without a
spreadsheet program. Regenerate with `python portal_docs.py --xlsx <file>` after
fetching the portal resource; see `data/SOURCE.json` for where it came from.

| Variable | Descripción | Tipo de dato | Tamaño | Recurso relacionado | Información Adicional |
|---|---|---|---|---|---|
| ID | Identificador unico de registro | Numérico | 10 |  |  |
| ESTACION | Nombre de la Estación Meteorológica Automática para intercambio internacional | Texto | 20 |  |  |
| FECHA | Fecha en la que se realiza la medición en la Estación Meteorológica Automática para intercambio internacional | Numérico | 8 |  | Formato: aaaammdd |
| HORA | Hora en la que se realiza la medición en la Estación Meteorológica Automática para intercambio internacional | Alfanumerico | 6 |  | Formato: hhmmss |
| LONGITUD | Es la distancia en grados, minutos y segundos que hay con respecto al meridiano principal, que es el meridiano de Greenwich (0º). (X) | Numérico | 20 |  |  |
| LATITUD | Es la distancia en grados, minutos y segundos que hay con respecto al paralelo principal, que es el ecuador (0º). La latitud puede ser norte y sur. (Y) | Numérico | 20 |  |  |
| ALTITUD | Medida que indica la altura de un punto en relación al nivel medio del mar. En metros sobre nivel del mar (msnm) | Numérico | 10 |  |  |
| TEMP | Temperatura promedio horaria (unidad: °C) | Numérico | 10 |  |  |
| HR | Humedad relativa promedio horaria (unidad: %) | Numérico | 10 |  |  |
| PP | Precipitación total horaria (unidad: milimetros por hora) | Numérico | 10 |  |  |
| RED | Estaciones pertenecientes a la Red Global de Observación Basica (GBON, por sus siglas en ingles) o Red Regional de Observación Básica (RBON, por sus siglas en ingles) | Texto | 4 |  |  |
| DEPARTAMENTO | Departamento donde se encuentra ubicada la Estación Meteorológica Automática para intercambio internacional | Texto | 20 | Catálogo del INEI |  |
| PROVINCIA | Provincia donde se encuentra ubicada la Estación Meteorológica Automática para intercambio internacional | Texto | 20 | Catálogo del INEI |  |
| DISTRITO | Distrito donde se encuentra ubicada la Estación Meteorológica Automática para intercambio internacional | Texto | 25 | Catálogo del INEI |  |
| UBIGEO | Código de ubicación geográfica donde se encuentra ubicada la Estación Meteorológica Automática para intercambio internacional | Alfanumerico | 6 | Catálogo del INEI |  |
| FECHA_CORTE | Día en que se generó el dataset | Numérico | 8 |  | Formato: aaaammdd |

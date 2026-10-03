"""Rebuild notebooks/experiments.ipynb from a plain cell spec.

Keeps the notebook valid JSON by construction (json.dump handles escaping),
which hand-editing a one-line .ipynb does not.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "notebooks" / "experiments.ipynb"

CELLS: list[tuple[str, str]] = [
    ("md", """# c20-2026 — Pipeline Colab (Drive-only)

Replica el patrón de `papers/c15-2026` (`AGENTS.md` §5-§6): **sin git y sin `GITHUB_TOKEN`** en Colab.

- El agente sube `experiments/` a `Drive/c20-2026/code/` vía MCP `gdrive` (`uploadFile`), preservando rutas relativas.
- Este notebook monta Drive, exporta `DATA_DIR`/`OUTPUT_DIR` **antes de importar nada**, y copia `code/` a `/content/c20-2026/experiments`.
- Los módulos leen esas variables en `_common.py`, así que `data/` y `outputs/` caen en Drive y sobreviven al recycle del runtime.
- Refresh: repetí la última celda después de que el agente suba cambios.

Prerrequisitos:

- Carpeta `c20-2026` en Drive con `code/` y `data/raw/dataset.csv` (ya montada).
- Este notebook abierto desde Drive.

> Al subirlo a Drive hay que pasar `mimeType: application/x-ipynb+json`; con el
> default (`application/octet-stream`) Colab no lo reconoce como notebook."""),

    ("md", "## 1. Montar Drive"),
    ("code", """from google.colab import drive

drive.mount("/content/drive", force_remount=False)
print("[ok] Drive montado en /content/drive")"""),

    ("md", """## 2. Definir rutas y cargar el snapshot de código

`DATA_DIR` y `OUTPUT_DIR` se exportan **antes** de que se importe `_common`, porque ese módulo las lee en tiempo de import."""),

    ("code", """import os
import pathlib
import shutil

# Carpeta del proyecto en Drive (mapea a GDRIVE_FOLDER_ID del .env local).
PROJECT_DIR = "/content/drive/MyDrive/c20-2026"

# Debe exportarse ANTES de importar _common.
os.environ["DATA_DIR"] = f"{PROJECT_DIR}/data"
os.environ["OUTPUT_DIR"] = f"{PROJECT_DIR}/outputs"
os.environ["GDRIVE_NOTEBOOK_NAME"] = "experiments.ipynb"

CODE_DIR = pathlib.Path(f"{PROJECT_DIR}/code")
REPO_DIR = pathlib.Path("/content/c20-2026")
EXPERIMENTS_DIR = REPO_DIR / "experiments"

if not CODE_DIR.is_dir():
    raise RuntimeError(
        f"Drive code snapshot missing: {CODE_DIR} — pedile al agente que suba "
        "experiments/ via MCP gdrive uploadFile"
    )
EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
shutil.copytree(CODE_DIR, EXPERIMENTS_DIR, dirs_exist_ok=True)

print(f"[ok] DATA_DIR={os.environ['DATA_DIR']}")
print(f"[ok] OUTPUT_DIR={os.environ['OUTPUT_DIR']}")
print(f"[ok] code: {CODE_DIR} -> {EXPERIMENTS_DIR}")"""),

    ("md", "## 3. Verificar el snapshot y el contrato de config"),

    ("code", """# Prueba de frescura: confirma que corres el codigo recien sincronizado.
import datetime

%cd /content/c20-2026/experiments

_cfg = EXPERIMENTS_DIR / "config.yaml"
if not _cfg.is_file():
    raise RuntimeError(f"config.yaml ausente en {_cfg}")
_st = _cfg.stat()
_mtime = datetime.datetime.fromtimestamp(_st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
print(f"[ok] config.yaml mtime={_mtime} size={_st.st_size}")

import yaml
cfg = yaml.safe_load(_cfg.read_text(encoding="utf-8"))
print(f"[ok] project={cfg.get('project')} design={cfg.get('design_version')}")
print(f"[ok] station={(cfg.get('station') or {}).get('name')}")
print(f"[ok] weekday={(cfg.get('issuance') or {}).get('weekday')}")

# Rutas segun _common: deben caer en Drive, no en /content.
import _common
print(_common.paths_report())"""),

    ("code", """# Estructura de trabajo: crear las carpetas del contrato en Drive
import _common

_common.ensure_dirs()
print(_common.paths_report())

# El dataset crudo no viene del snapshot de codigo: se baja del portal y deja
# su procedencia en data/SOURCE.json. Si el archivo ya esta y el hash coincide,
# la celda no vuelve a bajarlo.
SRC = pathlib.Path(os.environ["DATA_DIR"]) / "raw"
print(f"[info] data/raw: {SRC}")
print(f"[info] procedencia: {(pathlib.Path(os.environ['DATA_DIR']) / 'SOURCE.json').is_file()}")

QC = pathlib.Path(os.environ["DATA_DIR"]) / "processed/hourly_qc.csv"
print(f"[info] QC previo presente: {QC.is_file()}")

steps = sorted(p.stem.split("_")[0] for p in pathlib.Path(
    "/content/c20-2026/experiments").glob("[0-9][0-9]_*.py"))
print(f"pasos declarados: {steps}")"""),

    ("md", """## 3b. Bajar el dataset crudo con su procedencia

`fetch_source.py` resuelve el recurso del portal por API en vez de tener una URL fija —el portal republica estos paquetes con enlaces nuevos— y escribe `data/SOURCE.json` con el id del paquete, la URL exacta, un **sha256**, los bytes, la fecha, y el inventario de estaciones leído del archivo mismo.

El nombre del archivo sale de `config.source.file`, que es el mismo que leen las etapas: si el fetch escribiera un nombre y las etapas leyeran otro, la corrida entera usaría el archivo viejo sin decirlo.

**Si el portal no resuelve** (pasa: `www.datos.gob.pe` dio NXDOMAIN desde Colab), descargalo vos en el navegador y subilo a `Drive/c20-2026/data/raw/senamhi.csv`. Después corré `--adopt`, que registra la procedencia completa sin red: checksum, columnas, inventario de estaciones y cobertura. Lo único que queda sin registro es de dónde se descargó, y eso queda escrito en el `SOURCE.json`.

El CSV va a `data/raw/` (gitignored). `SOURCE.json` va a `data/` arriba, que sí se versiona: la procedencia es chica y revisable, los datos no."""),

    ("code", """%%bash
# El compute corre en los servidores de Colab, no en tu maquina.
# %%bash debe ser la PRIMERA linea de la celda; si no, Colab la parsea como Python.
cd /content/c20-2026/experiments
# Si el portal no resuelve, bajalo a mano y usá esto en vez de la línea siguiente:
#   python fetch_source.py --adopt
python fetch_source.py
"""),

    ("code", """# Que dice la procedencia: estaciones, cobertura y checksum.
import json, pathlib

sj = pathlib.Path(os.environ["DATA_DIR"]) / "SOURCE.json"
if not sj.is_file():
    raise RuntimeError(f"SOURCE.json ausente — corré fetch_source.py primero")

info = json.loads(sj.read_text(encoding="utf-8"))
loc = info["local"]
print(f"dataset : {info['catalogue']['dataset_id']}")
print(f"licencia: {info['catalogue']['license_title']}")
print(f"archivo : {loc['path']}  {loc['bytes']:,} bytes")
print(f"sha256  : {loc['sha256']}")
print(f"bajado  : {info['retrieved_at']}")
print(f"columnas: {len(info['columns'])} -> {info['columns'][:8]}")
print()
def _stations_in_config():
    import yaml
    cfg = yaml.safe_load(open("/content/c20-2026/experiments/config.yaml",
                              encoding="utf-8"))
    return [s["ubigeo"] for s in (cfg.get("stations") or [])]


print(f"{'UBIGEO':>8} {'filas':>10}  cobertura")
for s in info["stations"]:
    flag = "  <- leading zero recuperado" if s["needs_padding"] else ""
    span = (f"{s.get('first')}..{s.get('last')}" if s.get("first")
            else "DESCONOCIDA (sin columna de tiempo)")
    print(f"{s['ubigeo']:>8} {s['rows']:>10,}  {span}{flag}")
print()
present = [s["ubigeo"] for s in info["stations"]]
print(f"config declara {len(_stations_in_config())} estación(es) | "
      f"el archivo trae {len(present)}")
absent = [c for c in _stations_in_config() if c not in present]
extra = [c for c in present if c not in _stations_in_config()]
if absent:
    print(f"[REVIEW] declaradas pero AUSENTES en el archivo: {', '.join(absent)}")
    print("          -> la etapa 00 va a marcar REVIEW_station_mismatch hasta")
    print("             que la config y los datos coincidan. Es el chequeo")
    print("             funcionando, no fallando.")
if extra:
    print(f"[REVIEW] en el archivo pero no declaradas: {', '.join(extra)}")
print(f"cobertura declarada en config: {info['declared']['declared_coverage']}")
print("[info] si la cobertura real no llega al final del train, los folds se recortan")"""),

    ("code", """# Dependencias. Con marca: si ya se instalaron en ESTE runtime, no se repite.
# Perder el runtime es lo unico que hay que recuperar, y por eso esto tiene marca.
import os, subprocess, sys
_MARK = "/content/.deps_c20_2026"
if os.path.exists(_MARK):
    print("[skip] deps ya instaladas en este runtime")
else:
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                        "requirements-experiments.txt", "--quiet"])
    if r.returncode != 0:
        raise RuntimeError(f"pip install fallo con exit={r.returncode}; no se escribe la marca")
    open(_MARK, "w").write("installed")
    print("[ok] deps instaladas")
!python --version"""),

    ("md", """## 4. Etapas del pipeline (una celda por paso)

Corre en orden. `02` depende del QC de `01`, así que no te saltes una.

Los módulos `00`-`05` están implementados. `06` en adelante siguen siendo stubs: cuando fallen con `NotImplementedError`, implementalos local y repetí la última celda.

Las etapas emiten eventos de progreso `#PROG` y la celda los dibuja como barras fijas con `tqdm.notebook`; en terminal local el mismo protocolo se dibuja con `tqdm.std`. Las etapas vectorizadas de `01` y `02` no iteran, pero igual reportan su avance a nivel etapa, así que siempre ves en qué paso estás.

`06_features_largescale.py` necesita descargas externas (Niño CPC, RMM, ERA5) y su dominio/variables siguen marcados `TO_CONFIRM_D4` en `config.yaml`."""),

    ("md", """## 4b. Correr todo de una (recomendado)

Las etapas se ejecutan en orden porque cada una consume la salida de la anterior. Esta celda las encadena, se detiene en el primer fallo, y deja un log por etapa en `outputs/logs/`.

Cada etapa escribe `outputs/logs/<etapa>.log` con header (comando, timestamp, rutas activas), la salida completa, y footer con **exit code y elapsed**. Ese footer va dentro del archivo, no en la consola: por eso el log se sostiene solo y se puede leer desde Drive sin el notebook.

El nombre del archivo es fijo y se sobreescribe en cada corrida, asi que su id de Drive no cambia nunca. El agregado queda en `outputs/logs/run_all.log`."""),

    ("code", '''# Corre 00 -> 10 en orden, con barras fijas dibujadas por el kernel.
# Cada etapa es un subproceso que emite eventos #PROG y este runner los dibuja
# como widgets que se quedan quietos (nada de \\r en la salida capturada).
import sys
sys.path.insert(0, "/content/c20-2026/experiments")
from _progress import run_and_render

rc = run_and_render([sys.executable, "run_all.py"], cwd="/content/c20-2026/experiments")
print(f"[run_all exit={rc}]")
'''),

    ("code", '''# Una etapa, con el prefijo numerico. Cambia solo el argumento.
#
#   paso("03")                    # abreviatura de 03_climatology (unica coincidencia)
#   paso("03", "05")              # varias
#   paso(desde="03", hasta="05")   # rango, inclusive
#   paso("05", config="mi.yaml")  # otra config
#
# Cada paso es un SUBPROCESO que emite eventos #PROG; el runner los dibuja como
# widgets fijos. El kernel no guarda estado entre ellos, asi que nada se pierde
# si Colab recicla el runtime.
import sys
sys.path.insert(0, "/content/c20-2026/experiments")
from _progress import run_and_render

def paso(*etapas, **kw):
    argv = [sys.executable, "run_all.py"]
    if etapas:
        argv += ["--only", *etapas]
    if kw.get("desde") or kw.get("hasta"):
        argv += ["--from", kw.get("desde", "00"), "--to", kw.get("hasta", "10")]
    if kw.get("config"):
        argv += ["--config", kw["config"]]
    print("::", " ".join(argv[1:]))
    return run_and_render(argv, cwd="/content/c20-2026/experiments")

# Ejemplos:
# paso("03")
# paso("03", "05")
# paso(desde="03", hasta="05")
# paso("05", config="mi.yaml")
'''),

    ("md", """### Que escribe cada etapa

| Etapa | Escribe |
|---|---|
| `00_verify_source` | `outputs/tables/T1_completeness.csv` (V1-V6) |
| `01_qc_hourly` | `data/processed/hourly_qc.csv` |
| `02_aggregate_daily` | `data/processed/daily.csv` |
| `03_climatology` | `data/processed/daily_clim.csv` + `outputs/climatology/<fold>.json` |
| `04_make_issuances` | `data/processed/issuances.csv` |
| `05_features_local` | `data/processed/features_<fold>.csv` |

Todas las escrituras son atomicas (temporal hermano + `os.replace`): una
desconexion a mitad de escritura deja el archivo anterior o nada, nunca un CSV
a medias que la etapa siguiente leeria como completo.

`run_all.py` ademas escribe `outputs/run_meta.json`: que etapas corrieron, con
que commit, que versiones de pandas/numpy/etc. se importaron de verdad, y cuanto
tardo cada una. Nombre fijo a proposito, porque un nombre con timestamp
crearia un archivo nuevo de Drive en cada corrida.""",),

    ("md", """### Leyendo los logs desde Drive

Cada corrida deja su log en Drive, asi que sobrevive a que Colab recicle el runtime. Para revisar una corrida sin el notebook, leé `outputs/logs/<etapa>.log`: el footer dice que etapa fallo, con que exit code, y en cuanto tiempo.

Los logs guardan marcadores de fase (`# progress <paso>: n/total`) en vez de barras: dicen qué fase corría sin enterrar el diagnóstico en redraws. El archivo es texto plano y se puede leer con cualquier herramienta."""),

    ("md", "## 5. Estado (solo lectura)"),

    ("code", """# Inventario de outputs/ en Drive + estado del daily
DATA_DIR = os.environ["DATA_DIR"]
OUTPUT_DIR = os.environ["OUTPUT_DIR"]

print(f"--- outputs/{OUTPUT_DIR} ---")
for p in sorted(pathlib.Path(OUTPUT_DIR).rglob("*")):
    if p.is_file():
        print(f"  {p.relative_to(OUTPUT_DIR)}  {p.stat().st_size} bytes")

daily = pathlib.Path(DATA_DIR) / "processed/daily.csv"
if daily.is_file():
    import pandas as pd
    d = pd.read_csv(daily, parse_dates=["date"])
    print(f"daily.csv: {len(d)} dias, {int(d['valid'].sum())} validos")
    print(d.groupby(d["date"].dt.year)["TT_mean"].agg(["mean", "count"]).round(2).to_string())
else:
    print("daily.csv aun no generado")

clim = pathlib.Path(DATA_DIR) / "processed/daily_clim.csv"
if clim.is_file():
    c = pd.read_csv(clim, parse_dates=["date"])
    print(f"\\ndaily_clim.csv: {len(c)} dias de evaluacion "
          f"({c['date'].min().date()}..{c['date'].max().date()})")
    print("A_C2 por anio de test (debe centrarse cerca de 0):")
    print(c.groupby(c["date"].dt.year)["A_C2"].agg(["mean", "std", "count"]).round(3).to_string())
else:
    print("daily_clim.csv aun no generado (corre el paso 03)")

isu = pathlib.Path(DATA_DIR) / "processed/issuances.csv"
if isu.is_file():
    i = pd.read_csv(isu, parse_dates=["issue_date", "target_start", "target_end"])
    ev = i[i["kind"] == "eval"]
    print(f"\\nissuances.csv: {len(i)} filas | eval {len(ev)} train {len(i) - len(ev)}")
    print(f"emisiones eval por fold: "
          f"{ev.groupby('fold')['issue_date'].nunique().to_dict()}")
    print(f"violaciones anti-leakage (target_start <= issue_date): "
          f"{int((i['target_start'] <= i['issue_date']).sum())}")
    print("targets validos por fold y horizonte:")
    print(ev.groupby(["fold", "horizon"])["valid_target"]
          .agg(["sum", "count"]).to_string())
else:
    print("issuances.csv aun no generado (corre el paso 04)")

# Diagnostico de features: missing y correlacion con el target.
feat_files = sorted(pathlib.Path(DATA_DIR).glob("processed/features_*.csv"))
if feat_files:
    print(f"\\n--- features ({len(feat_files)} archivo/s) ---")
    for f in feat_files:
        d = pd.read_csv(f, parse_dates=["issue_date"])
        meta = ["fold", "role", "issue_date", "kind", "horizon", "lag_start", "lag_end"]
        cols = [c for c in d.columns if c not in meta]
        miss = d[cols].isna().mean().mul(100)
        print(f"{f.name}: {len(d)} filas x {len(cols)} features | "
              f"missing medio {miss.mean():.1f}% | peor {miss.idxmax()} {miss.max():.1f}%")
        if "B2" in f.name:
            tgt = i[(i["fold"] == "B2") & (i["horizon"] == "W1")]
            m = d[(d["kind"] == "eval") & (d["horizon"] == "W1")].merge(
                tgt[["issue_date", "A_C2_target"]], on="issue_date")
            corr = m[cols + ["A_C2_target"]].corr(numeric_only=True)["A_C2_target"]
            corr = corr.drop("A_C2_target").dropna().sort_values(key=abs, ascending=False)
            print("\\n  Correlacion de cada feature con el target W1 (B2, eval):")
            print("  " + "\\n  ".join(f"{k:32s} {v:+.3f}" for k, v in corr.head(8).items()))
else:
    print("features_<fold>.csv aun no generado (corre el paso 05)")"""),

    ("code", """# Logs de la corrida
logs = pathlib.Path(os.environ["OUTPUT_DIR"]) / "logs"
files = sorted(p for p in logs.glob("*") if p.is_file())
if not files:
    print("no logs yet")
for f in files:
    print("\\n--- {} ({} bytes) ---".format(f.name, f.stat().st_size))
    print(f.read_text(encoding="utf-8", errors="ignore")[:2000])"""),

    ("md", "## 6. Refrescar el código cuando el agente suba cambios"),

    ("code", """# Drive code/ -> /content. Repetir despues de cada sync del agente.
import shutil

shutil.rmtree("/content/c20-2026/experiments", ignore_errors=True)
shutil.copytree(CODE_DIR, EXPERIMENTS_DIR, dirs_exist_ok=True)
print(f"[ok] code refrescado desde {CODE_DIR}")
%cd /content/c20-2026/experiments
!ls -1 *.py
!python -c "import _common; print(_common.paths_report())"
"""),
]


def main() -> None:
    # Colab only accepts "code" | "markdown"; a shorthand such as "md" makes it
    # fail with `unexpected value md!` even though the JSON parses fine.
    valid = {"code", "markdown"}

    cells = []
    for kind, src in CELLS:
        cell_type = "markdown" if kind == "md" else kind
        if cell_type not in valid:
            raise SystemExit(f"ERROR: invalid cell_type {cell_type!r} (allowed: {valid})")
        cell = {
            "cell_type": cell_type,
            "metadata": {},
            "source": src.splitlines(keepends=True),
        }
        if cell_type == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        cells.append(cell)

    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "colab": {"provenance": [], "name": "experiments.ipynb", "toc_visible": True},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")

    # Self-check: fail here rather than in Colab's renderer.
    written = json.loads(OUT.read_text(encoding="utf-8"))
    for i, c in enumerate(written["cells"]):
        if c["cell_type"] not in valid:
            raise SystemExit(f"ERROR: cell {i} has cell_type {c['cell_type']!r}")

    # Colab parses a line that starts with neither `!` nor `%` as Python, so a
    # bare shell command is a SyntaxError at run time. Rather than guessing from
    # keywords (which collide with Python: `if`, `for`, `python`), just parse the
    # cell as Python and report the real error. Cells opened with `%%bash` are
    # exempt: every line in them is shell by design.
    import ast

    for i, c in enumerate(written["cells"]):
        if c["cell_type"] != "code":
            continue
        lines = c["source"]
        if lines and lines[0].strip().startswith("%%"):
            continue
        body = "\n".join(l for l in lines if not l.strip().startswith(("%", "!")))
        try:
            ast.parse(body or "pass")
        except SyntaxError as exc:
            bad_line = (body.splitlines()[(exc.lineno or 1) - 1]
                        if body.splitlines() else "")
            raise SystemExit(
                f"ERROR: cell {i} does not parse as Python ({exc.msg} at line "
                f"{exc.lineno}: {bad_line.strip()!r}). Colab treats unprefixed "
                "lines as Python, so shell must use '!' or the cell must start "
                "with %%bash."
            ) from exc

    n_code = sum(1 for c in written["cells"] if c["cell_type"] == "code")
    print(f"wrote {OUT} ({len(cells)} cells: {n_code} code, {len(cells) - n_code} markdown)")


if __name__ == "__main__":
    main()
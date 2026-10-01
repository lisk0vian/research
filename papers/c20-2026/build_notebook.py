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

raw = pathlib.Path(os.environ["DATA_DIR"]) / "raw/dataset.csv"
if raw.is_file():
    print(f"[ok] dataset.csv presente ({raw.stat().st_size} bytes)")
else:
    raise RuntimeError(f"dataset.csv ausente en {raw} — subilo a Drive/c20-2026/data/raw/")

QC = pathlib.Path(os.environ["DATA_DIR"]) / "processed/hourly_qc.csv"
print(f"[info] QC previo presente: {QC.is_file()}")

steps = sorted(p.stem.split("_")[0] for p in pathlib.Path(
    "/content/c20-2026/experiments").glob("[0-9][0-9]_*.py"))
print(f"pasos declarados: {steps}")"""),

    ("code", """# Dependencias
%cd /content/c20-2026/experiments
!pip install -r requirements-experiments.txt --quiet
!python -c "import pandas, numpy, sklearn, lightgbm, yaml, click; print('[ok] deps import OK')"
!python --version"""),

    ("md", """## 4. Etapas del pipeline (una celda por paso)

Corre en orden. `02` depende del QC de `01`, así que no te saltes una.

Los módulos `00`-`05` están implementados. `06` en adelante siguen siendo stubs: cuando fallen con `NotImplementedError`, implementalos local y repetí la última celda.

`06_features_largescale.py` necesita descargas externas (Niño CPC, RMM, ERA5) y su dominio/variables siguen marcados `TO_CONFIRM_D4` en `config.yaml`."""),

    ("md", """## 4b. Correr todo de una (recomendado)

`00` a `04` se ejecutan en orden porque cada uno consume la salida del anterior. Esta celda los encadena y se detiene en el primer fallo."""),

    ("code", '''%%bash
# Encadena 00 -> 04. El compute corre en los servidores de Colab, no en tu maquina.
# %%bash debe ser la PRIMERA linea de la celda; si no, Colab la parsea como Python.
cd /content/c20-2026/experiments
for s in 00_verify_source 01_qc_hourly 02_aggregate_daily 03_climatology \
         04_make_issuances 05_features_local; do
  echo "===== $s ====="
  python "$s.py" || { echo "FALLO en $s"; break; }
done
'''),

    ("code", '''# Paso 00: V1-V6 verificacion de fuente -> outputs/tables/T1_completeness.csv
%cd /content/c20-2026/experiments
!python 00_verify_source.py\n'''),

    ("code", '''# Paso 01: QC horario -> data/processed/hourly_qc.csv
# Flags: missing_source (gap del proveedor), out_of_range, spike,
# precip_event (tormenta convectiva, se conserva)
%cd /content/c20-2026/experiments
!python 01_qc_hourly.py\n'''),

    ("code", '''# Paso 02: agregacion diaria local -> data/processed/daily.csv
%cd /content/c20-2026/experiments
!python 02_aggregate_daily.py\n'''),

    ("code", '''# Paso 03: climatologias C1/C2/C3 + sigma_h,q + terciles, train-only por fold
# -> data/processed/daily_clim.csv + outputs/climatology/<fold>.json
%cd /content/c20-2026/experiments
!python 03_climatology.py\n'''),

    ("code", '''# Paso 04: emisiones semanales, targets A^h_d y embargo de 28 dias
# -> data/processed/issuances.csv (una fila por issue_date x horizonte x fold)
%cd /content/c20-2026/experiments
!python 04_make_issuances.py\n'''),

    ("code", '''# Paso 05: predictores locales X_L (22 columnas, solo informacion <= d)
# -> data/processed/features_<fold>.csv
%cd /content/c20-2026/experiments
!python 05_features_local.py\n'''),

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
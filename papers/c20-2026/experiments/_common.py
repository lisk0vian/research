"""Shared helpers for the c20-2026 pipeline: paths, config, IO.

Kept dependency-light on purpose (pandas + pyyaml only) so the early stages
run in a Colab cell before any modelling dependency is installed.

Every module reads `config.yaml`; nothing hardcodes a threshold.

Paths resolve in two modes, mirroring `papers/c15-2026/experiments/src/paths.py`:

- Local: no env vars set, so DATA_DIR/OUTPUT_DIR fall back to `../data` and
  `../outputs` relative to the paper root (`parents[1]` of this file).
- Drive (Colab): the notebook exports DATA_DIR and OUTPUT_DIR pointing into
  the mounted Drive before importing anything, so `data/` and `outputs/` land
  on Drive and survive a runtime recycle instead of vanishing with `/content`.

The env vars are read once at import time, so the notebook must set them before
running any stage.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import yaml

BASE = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE / "experiments" / "config.yaml"

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE / "data"))
OUTPUTS = Path(os.environ.get("OUTPUT_DIR", BASE / "outputs"))
RAW_CSV = DATA_DIR / "raw" / "dataset.csv"
PROCESSED = DATA_DIR / "processed"
TABLES = OUTPUTS / "tables"
FIGURES = OUTPUTS / "figures"
LOGS = OUTPUTS / "logs"

NUMERIC_VARS = ("TT", "HR", "RR", "PP", "FF", "DD")


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}


def read_hourly(path: Path | None = None) -> pd.DataFrame:
    """Read dataset.csv with local civil timestamps already built.

    The `year/month/day/hour` columns are authoritative; `FECHA_CORTE` is a
    snapshot date and is not a per-row timestamp, so it is dropped (it is in
    `config.data.non_predictors`).
    """
    df = pd.read_csv(path or RAW_CSV, dtype={"FECHA_CORTE": "string", "UBIGEO": "string"})
    df["timestamp"] = pd.to_datetime(
        dict(
            year=df["year"], month=df["month"], day=df["day"], hour=df["hour"]
        ),
        errors="coerce",
    )
    return df


def write_table(df: pd.DataFrame, name: str) -> Path:
    """Write a contract table to outputs/tables/, creating the folder."""
    TABLES.mkdir(parents=True, exist_ok=True)
    path = TABLES / name
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def write_manifest(payload: dict, name: str = "manifest_index.json") -> Path:
    """Update outputs/manifest_index.json, keeping the declared contract intact."""
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS / name
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data.update(payload)
    data.setdefault("paper", "c20-2026")
    data.setdefault("design_version", "2.0")
    data["status"] = "partial"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def ensure_dirs() -> None:
    for d in (RAW_CSV.parent, PROCESSED, TABLES, FIGURES, LOGS, OUTPUTS / "models"):
        d.mkdir(parents=True, exist_ok=True)


def paths_report() -> str:
    """Human-readable routing summary, printed by the notebook and by stages.

    Makes it obvious which mode is active: `local` writes next to the code,
    `drive` writes into the mounted folder and therefore persists.
    """
    mode = "drive" if os.environ.get("DATA_DIR") else "local"
    return "\n".join([
        f"[{mode}] DATA_DIR  = {DATA_DIR}",
        f"[{mode}] RAW_CSV   = {RAW_CSV} (exists={RAW_CSV.is_file()})",
        f"[{mode}] PROCESSED = {PROCESSED}",
        f"[{mode}] OUTPUTS   = {OUTPUTS}",
    ])
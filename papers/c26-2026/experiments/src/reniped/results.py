# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Single results store (strict JSON), software environment, hardware and SHA-256 manifest."""
import json
import math
import os
import platform
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.metadata as md
from pathlib import Path

import numpy as np
import pandas as pd

from .io_utils import sha256_file

PACKAGES = ["numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "openpyxl",
            "statsmodels", "geopandas", "shapely", "pyproj", "libpysal", "esda"]
EXCLUDE_PARTS = {"__pycache__", ".ipynb_checkpoints"}


def sanitize(o):
    """Convert to strict JSON types: NaN/Inf -> None; numpy/pandas -> native Python types."""
    if isinstance(o, dict):
        return {str(k): sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    if isinstance(o, np.ndarray):
        return [sanitize(v) for v in o.tolist()]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if o is None or isinstance(o, (str, int)):
        return o
    if o is pd.NA or o is pd.NaT:
        return None
    return str(o)


def records(df, decimals=6):
    return sanitize(df.round(decimals).to_dict("records"))


class ResultsStore:
    def __init__(self, root):
        self.root = Path(root)
        self.tables = self.root / "tables"
        self.figures = self.root / "figures"
        for d in (self.root, self.tables, self.figures):
            d.mkdir(parents=True, exist_ok=True)
        self.data = {"generado_utc": datetime.now(timezone.utc).isoformat()}
        self.timings = {}

    def set(self, dotted_key, value):
        node = self.data
        parts = dotted_key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = sanitize(value)

    def table(self, name, df):
        path = self.tables / f"{name}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return path

    @contextmanager
    def timer(self, stage):
        t0 = time.perf_counter()
        yield
        self.timings[stage] = round(time.perf_counter() - t0, 2)
        print(f"  [tiempo] {stage}: {self.timings[stage]:.1f} s")

    def save(self, name="results.json"):
        self.data["tiempos_por_etapa_s"] = self.timings
        path = self.root / name
        txt = json.dumps(sanitize(self.data), indent=2, ensure_ascii=False, allow_nan=False)
        path.write_text(txt, encoding="utf-8")
        return path


def hardware_profile():
    hw = {"python": sys.version.split()[0], "plataforma": platform.platform(),
          "procesador": platform.processor() or None, "cpu_logicos": os.cpu_count()}
    try:
        import psutil
        vm = psutil.virtual_memory()
        hw.update(cpu_fisicos=psutil.cpu_count(logical=False),
                  ram_total_gb=round(vm.total / 1024 ** 3, 2))
    except Exception:
        pass
    gpu = None
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            gpu = r.stdout.strip()
    except Exception:
        pass
    hw["gpu"] = gpu or "sin GPU (no requerida)"
    return hw


def freeze_environment(out_dir):
    """Write requirements.txt and environment.json (package versions and hardware)."""
    out_dir = Path(out_dir)
    versions = {}
    for p in PACKAGES:
        try:
            versions[p] = md.version(p)
        except md.PackageNotFoundError:
            versions[p] = None
    (out_dir / "requirements.txt").write_text(
        "\n".join(f"{k}=={v}" for k, v in versions.items() if v) + "\n", encoding="utf-8")
    env = {"hardware": hardware_profile(), "paquetes": versions}
    (out_dir / "environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    return env


def _included(p, root):
    return p.is_file() and not (set(p.relative_to(root).parts) & EXCLUDE_PARTS) \
        and p.suffix != ".pyc"


def write_manifest(root, name="MANIFEST.sha256"):
    """SHA-256 of every file of the package, so that any later change can be detected."""
    root = Path(root)
    files = [p for p in sorted(root.rglob("*")) if _included(p, root) and p.name != name]
    (root / name).write_text("\n".join(f"{sha256_file(p)}  {p.relative_to(root).as_posix()}"
                                       for p in files) + "\n", encoding="utf-8")
    return len(files)


def bundle_files(root):
    root = Path(root)
    return [p for p in sorted(root.rglob("*")) if _included(p, root)]

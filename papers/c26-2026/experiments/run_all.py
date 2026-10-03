# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Run the full pipeline without a notebook:  python run_all.py

Requires the input files in ../data/raw and ../data/external (included in the repository).
Writes every result to ../outputs/ (results.json, tables, figures), the software and
hardware of this run to ../outputs/environment.json and ../outputs/requirements.txt, and the
SHA-256 of every file to MANIFEST.sha256. The pinned requirements-experiments.txt in this
folder (reference environment) is never overwritten.

Layout: this folder is experiments/ (the package and the frozen analysis plan);
the data and outputs folders live one level up, in the paper folder.
"""
import sys
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parent  # papers/c26-2026/experiments
PAPER = EXPERIMENTS.parent                     # papers/c26-2026
sys.path.insert(0, str(EXPERIMENTS / "src"))

from reniped.pipeline import run_all                           # noqa: E402
from reniped.results import freeze_environment, write_manifest  # noqa: E402

if __name__ == "__main__":
    ctx = run_all(EXPERIMENTS)
    ctx["res"].set("entorno", freeze_environment(PAPER / "outputs"))
    ctx["res"].save()
    write_manifest(PAPER)
    print("Done: outputs/results.json")

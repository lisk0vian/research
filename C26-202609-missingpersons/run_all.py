"""Run the full pipeline without a notebook:  python run_all.py

Requires the input files in data/raw and data/external (included in the repository).
Writes every result to results/ (FINAL_RESULTS.json, tables, figures), the software and
hardware of this run to results/environment.json and results/requirements.txt, and the
SHA-256 of every file to MANIFEST.sha256. The pinned requirements.txt at the repository root
(reference environment) is never overwritten.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from reniped.pipeline import run_all                           # noqa: E402
from reniped.results import freeze_environment, write_manifest  # noqa: E402

if __name__ == "__main__":
    ctx = run_all(ROOT)
    ctx["res"].set("entorno", freeze_environment(ROOT / "results"))
    ctx["res"].save()
    write_manifest(ROOT)
    print("Done: results/FINAL_RESULTS.json")

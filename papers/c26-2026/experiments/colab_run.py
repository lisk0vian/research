"""Run the c26-2026 pipeline under the Colab standard: python colab_run.py [--force]

Adapter between the Colab notebook (COLAB.md at the repo root) and this paper's
reproducibility package. The package runs in one process (`run_all.py`, stage
functions sharing a context), so here the whole pipeline is one stage,
`pipeline`, run through the shared runtime: per-stage log, resume fingerprint,
outputs/logs/errors.log and outputs/logs/status.json. The package itself and
the reader notebook (notebooks/notebook.ipynb) are untouched.

The package reads data/ and writes outputs/ next to experiments/. On Colab the
code is copied to /content while data and outputs live on Drive, so when
DATA_DIR/OUTPUT_DIR are set this links them in before running.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:  # on Colab the runtime sits next to this file (code/_colab_runtime.py)
    import _colab_runtime as rt
except ImportError:  # locally it lives in the repo's scripts/
    sys.path.insert(0, str(HERE.parents[2] / "scripts"))
    import _colab_runtime as rt

INPUTS = ["raw/dataset.csv", "external/population.xlsx", "external/boundaries.geojson"]


def link_drive_folders() -> None:
    """Point <paper>/data and <paper>/outputs at the Drive folders, when on Colab."""
    for name, var in (("data", "DATA_DIR"), ("outputs", "OUTPUT_DIR")):
        target = os.environ.get(var)
        link = HERE.parent / name
        if not target or link.exists():
            continue
        Path(target).mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)


def check_inputs() -> int:
    data = HERE.parent / "data"
    missing = [p for p in INPUTS if not (data / p).is_file()]
    if missing:
        print("missing input files under data/: " + ", ".join(missing))
        print("Upload the paper's data/ folder (raw/ and external/) to the Drive "
              "project folder once; see notebooks/README.md.")
        return 1
    print(f"[ok] {len(INPUTS)} input files present")
    return 0


if __name__ == "__main__":
    link_drive_folders()
    if "--check-data" in sys.argv:
        raise SystemExit(check_inputs())
    raise SystemExit(rt.stages_main(
        HERE, stages=["pipeline"], command=lambda s, force: ["run_all.py"],
        stage_file=lambda s: HERE / "run_all.py"))

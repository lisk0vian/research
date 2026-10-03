"""Run the pipeline stages in order: python run_all.py [--mode smoke] [--only 03] [--force]

Stages are the `NN_name.py` files in this folder (00_..., 01_..., 01b_...), each
run as a subprocess with its own log in outputs/logs/<stage>.log. Unchanged
stages are skipped, every failure goes to outputs/logs/errors.log, and
outputs/logs/status.json records what each stage did. The rules are in COLAB.md
at the repo root; the implementation is the shared scripts/_colab_runtime.py.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:  # on Colab the runtime sits next to this file (code/_colab_runtime.py)
    import _colab_runtime as rt
except ImportError:  # locally it lives in the repo's scripts/
    sys.path.insert(0, str(HERE.parents[2] / "scripts"))
    import _colab_runtime as rt

if __name__ == "__main__":
    raise SystemExit(rt.stages_main(HERE))

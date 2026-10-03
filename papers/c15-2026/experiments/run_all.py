"""Run the c15-2026 stages in order: python run_all.py [--mode smoke] [--only train] [--force]

Adapter between the Colab standard (COLAB.md at the repo root) and this paper's
own orchestrator: every stage runs as `main.py --stage <name>` in a subprocess,
through the shared runtime, which adds the per-stage log, the resume
fingerprints, outputs/logs/errors.log and outputs/logs/status.json. The stages
keep their own `is_done()` checks; `--force` is passed through to them.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:  # on Colab the runtime sits next to this file (code/_colab_runtime.py)
    import _colab_runtime as rt
except ImportError:  # locally it lives in the repo's scripts/
    sys.path.insert(0, str(HERE.parents[2] / "scripts"))
    import _colab_runtime as rt

# Execution order: the import order in src/stages/__init__.py, which is the
# registry order main.py uses for `--stage all`. A test keeps the two equal.
STAGES = ["consolidation", "feature_engineering", "preprocessing",
          "feature_selection", "split", "train"]


def command(stage: str, force: bool) -> list[str]:
    return ["main.py", "--stage", stage, *(["--force"] if force else [])]


if __name__ == "__main__":
    raise SystemExit(rt.stages_main(
        HERE, stages=STAGES, command=command,
        stage_file=lambda s: HERE / "src" / "stages" / f"{s}.py"))

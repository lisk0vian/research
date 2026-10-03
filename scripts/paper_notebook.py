#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_notebook.py — generate a paper's Colab notebook from experiments/colab.yaml.

Every paper's notebook has the same skeleton (COLAB.md, "What each cell does"),
so it is generated, never hand-edited:

    0  how to run (markdown)
    1  load the latest code from Drive   <- re-run after every agent sync
    2  check the runtime                 (GPU, deps, setup commands, probes)
    3  run the pipeline                  <- the only cell that runs it
    4  run one step                      (calls commented out; a no-op under Run all)
    5  results and errors                (report, figures, then errors.log)

It also writes notebooks/README.md, the human page for that notebook.

Usage:
    python scripts/paper_notebook.py --slug c20-2026            # write
    python scripts/paper_notebook.py --slug c20-2026 --check    # exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402

SCRIPT_REPO = Path(__file__).resolve().parents[1]
SPEC_REL = Path("experiments") / "colab.yaml"
NOTEBOOK_REL = Path("notebooks") / "experiments.ipynb"
README_REL = Path("notebooks") / "README.md"

# A top-level (unindented, uncommented) call that launches the pipeline.
RUN_CALL = re.compile(r"^(?!\s|#).*\brun_pipeline\(", re.MULTILINE)
SHELL_RUN = re.compile(r"^\s*(%%bash|!.*run_all|!python)", re.MULTILINE)


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(text)}


def _code(text: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": _lines(text)}


def _lines(text: str) -> list[str]:
    lines = text.strip("\n").split("\n")
    return [ln + "\n" for ln in lines[:-1]] + [lines[-1]]


def build_cells(spec: dict) -> list[dict]:
    folder = spec["drive_folder"]
    gpu = str(spec.get("gpu", "none")).lower()
    gpu_step = {
        "required": "1. **Runtime → Change runtime type → T4 GPU → Save.** The pipeline "
                    "refuses to start without a GPU.\n",
        "optional": "1. A GPU is optional (Runtime → Change runtime type → T4 GPU).\n",
    }.get(gpu, "1. No GPU needed.\n")

    intro = f"""# {spec['title']}

{gpu_step}2. **Runtime → Run all.** The pipeline runs once. Stages that already finished with the same code, config and inputs are skipped; tick `FORCE` in cell 3 to redo them.
3. **If anything fails**, the last cell prints `outputs/logs/errors.log`, the only file to read. `outputs/logs/status.json` says which stage failed.

After the agent syncs new code, re-run cell 1, then cell 3. How to use this notebook and the rules for changing it: `COLAB.md` in the repository. Generated from `experiments/colab.yaml` by `scripts/paper_notebook.py`; do not edit it by hand."""

    load = f'''#@title 1. Load the latest code from Drive (re-run after every agent sync)
import importlib.util
import os
import pathlib
import shutil
import sys
from datetime import datetime

from google.colab import drive

drive.mount("/content/drive")
PROJECT_DIR = pathlib.Path("/content/drive/MyDrive/{folder}")
CODE_DIR = PROJECT_DIR / "code"
WORK_DIR = pathlib.Path("/content/{folder}/experiments")
os.environ["DATA_DIR"] = str(PROJECT_DIR / "data")
os.environ["OUTPUT_DIR"] = str(PROJECT_DIR / "outputs")
if not (CODE_DIR / "_colab_runtime.py").is_file():
    raise RuntimeError(f"{{CODE_DIR}} has no pipeline code: ask the agent to sync it")

# Loaded straight from Drive, so the error hook covers the rest of this cell.
# No bytecode: it would be written into Drive code/ as __pycache__.
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("_colab_runtime", CODE_DIR / "_colab_runtime.py")
rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt)
sys.modules["_colab_runtime"] = rt
LOG = rt.RunLog(PROJECT_DIR / "outputs" / "logs")
LOG.begin_session(note="notebook")
rt.install_cell_error_hook(LOG)

shutil.rmtree(WORK_DIR, ignore_errors=True)
shutil.copytree(CODE_DIR, WORK_DIR, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
for _name, _mod in list(sys.modules.items()):  # forget modules from an older copy
    if str(getattr(_mod, "__file__", "") or "").startswith(str(WORK_DIR)):
        del sys.modules[_name]
if str(WORK_DIR) not in sys.path:
    sys.path.insert(0, str(WORK_DIR))
os.chdir(WORK_DIR)
SPEC = rt.load_spec(WORK_DIR)

_files = sorted(p for p in WORK_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
_newest = max(_files, key=lambda p: p.stat().st_mtime)
print(f"[ok] {{len(_files)}} files copied from {{CODE_DIR}}")
print(f"[ok] newest: {{_newest.name}} "
      f"({{datetime.fromtimestamp(_newest.stat().st_mtime):%Y-%m-%d %H:%M}} UTC)")
print(f"[ok] errors of this session go to {{LOG.errors}}")'''

    check = '''#@title 2. Check the runtime (GPU, dependencies, data, probes)
rt.preflight(SPEC, WORK_DIR, LOG)'''

    run = '''#@title 3. Run the pipeline (the only cell that runs it)
MODE = "full"  #@param ["full", "smoke"]
FORCE = False  #@param {type:"boolean"}

EXIT_CODE = rt.run_pipeline(SPEC, WORK_DIR, LOG, mode=MODE, force=FORCE)'''

    step = '''#@title 4. Run one step (manual: nothing runs under Run all)
def step(*stages, mode="full"):
    """Run only these stages, always re-running them: step("03"), step("07", "07b")."""
    return rt.run_pipeline(SPEC, WORK_DIR, LOG, mode=mode, only=list(stages))


def step_range(first, last, mode="full"):
    """Run an inclusive range, skipping stages that are still current."""
    return rt.run_pipeline(SPEC, WORK_DIR, LOG, mode=mode, extra=["--from", first, "--to", last])


# Uncomment one line, then run this cell:
# step("03")
# step("06b")
# step_range("07", "10")'''

    figures = spec.get("figures")
    show = (f'''from IPython.display import Image, display

for _fig in sorted(PROJECT_DIR.glob("{figures}")):
    print(_fig.name)
    display(Image(filename=str(_fig), width=720))
''' if figures else "")
    results = f'''#@title 5. Results and errors
rt.run_report(SPEC, WORK_DIR, LOG)
{show}rt.raise_if_errors(LOG)'''

    return [_md(intro), _code(load), _code(check), _code(run), _code(step), _code(results)]


def build_notebook(spec: dict) -> dict:
    gpu = str(spec.get("gpu", "none")).lower()
    meta: dict = {
        "colab": {"provenance": [], "toc_visible": False},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
    }
    if gpu in ("required", "optional"):
        # Colab opens the notebook on a GPU runtime when these are set.
        meta["accelerator"] = "GPU"
        meta["colab"]["gpuType"] = "T4"
    return {"cells": build_cells(spec), "metadata": meta, "nbformat": 4, "nbformat_minor": 0}


def notebook_text(spec: dict) -> str:
    return json.dumps(build_notebook(spec), indent=1, ensure_ascii=False) + "\n"


def readme_text(spec: dict, slug: str) -> str:
    folder = spec["drive_folder"]
    gpu = str(spec.get("gpu", "none")).lower()
    rows = "\n".join(f"| `{name}` | `{writes}` |"
                     for name, writes in (spec.get("stages") or {}).items())
    pre = "\n".join(f"- `{' '.join([a] if isinstance(a, str) else a)}` ({kind})"
                    for kind in ("setup", "probes") for a in spec.get(kind) or [])
    notes = "\n".join(f"- {n}" for n in spec.get("notes") or [])
    notes = f"\n## Notes\n\n{notes}\n" if notes else ""
    return f"""# Colab notebook: {spec['title']}

<!-- Generated by scripts/paper_notebook.py from experiments/colab.yaml. Do not edit. -->

- **Notebook:** `MyDrive/{folder}/experiments.ipynb`. Open it from Drive, not from
  Colab's "Recent" list; the agent gives the direct URL after every sync.
- **GPU:** {gpu}.
- **How to run it, what to do when it fails, and the rules for changing it:**
  [COLAB.md](../../../COLAB.md).
- **After a run:** `outputs/logs/errors.log` (empty = no errors) and
  `outputs/logs/status.json`, both in `MyDrive/{folder}/`.

## Before the pipeline (cell 2)

{pre or "- nothing beyond the GPU and dependency checks"}

## Stages (cell 3)

| Stage | Writes |
|---|---|
{rows}
{notes}"""


def load_spec(paper: Path) -> dict:
    path = paper / SPEC_REL
    spec = load_yaml(path)
    for key in ("title", "drive_folder"):
        if not spec.get(key):
            raise SystemExit(f"ERROR: {path}: missing `{key}`")
    return spec


def run_cell_count(nb: dict) -> int:
    """How many code cells launch the pipeline at top level. Must be exactly 1."""
    count = 0
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        count += len(RUN_CALL.findall(src)) + len(SHELL_RUN.findall(src))
    return count


def check(paper: Path, slug: str) -> list[str]:
    """Problems with the committed notebook/README; empty list when in sync."""
    spec = load_spec(paper)
    problems: list[str] = []
    for rel, want in ((NOTEBOOK_REL, notebook_text(spec)), (README_REL, readme_text(spec, slug))):
        path = paper / rel
        if not path.is_file():
            problems.append(f"{rel.as_posix()} missing (run paper_notebook.py --slug {slug})")
        elif path.read_text(encoding="utf-8") != want:
            problems.append(f"{rel.as_posix()} differs from what colab.yaml generates "
                            f"(edit colab.yaml, then run paper_notebook.py --slug {slug})")
    nb_path = paper / NOTEBOOK_REL
    if nb_path.is_file():
        try:
            n = run_cell_count(json.loads(nb_path.read_text(encoding="utf-8")))
        except ValueError:
            problems.append(f"{NOTEBOOK_REL.as_posix()} is not valid JSON")
        else:
            if n != 1:
                problems.append(f"{NOTEBOOK_REL.as_posix()} launches the pipeline {n} times; "
                                "exactly one cell may")
    return problems


def colab_url(paper: Path) -> str | None:
    ids_file = paper / ".drive_ids.json"
    try:
        file_id = json.loads(ids_file.read_text(encoding="utf-8")).get("experiments.ipynb")
    except (OSError, ValueError):
        return None
    return f"https://colab.research.google.com/drive/{file_id}" if file_id else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--root", default=None, help="repo root (default: this repo)")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed notebook or README differs")
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else (
        SCRIPT_REPO if (SCRIPT_REPO / "papers").is_dir() else find_repo_root())
    paper = repo / "papers" / args.slug
    if not (paper / SPEC_REL).is_file():
        print(f"ERROR: {paper / SPEC_REL} not found", file=sys.stderr)
        return 2

    if args.check:
        problems = check(paper, args.slug)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("notebook in sync" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    spec = load_spec(paper)
    for rel, text in ((NOTEBOOK_REL, notebook_text(spec)), (README_REL, readme_text(spec, args.slug))):
        path = paper / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path}")
    url = colab_url(paper)
    if url:
        print(f"Colab: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

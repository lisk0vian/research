# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for scripts/paper_notebook.py: the generated Colab notebook skeleton.

What must hold for "Runtime -> Run all" (COLAB.md): exactly one cell launches the
pipeline, the one-step cell runs nothing unless edited, the refresh cell exists,
every code cell is valid Python, and drift from colab.yaml is detected.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import paper_notebook as pn  # noqa: E402

SPEC = {
    "title": "c99-2026: test",
    "drive_folder": "c99-2026",
    "gpu": "required",
    "setup": [["fetch.py"]],
    "probes": [["06b.py", "--probe"]],
    "figures": "outputs/figures/F*.png",
    "stages": {"00_a": "outputs/a.csv"},
}


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    p = tmp_path / "papers" / "c99-2026"
    (p / "experiments").mkdir(parents=True)
    import yaml

    (p / "experiments" / "colab.yaml").write_text(yaml.safe_dump(SPEC), encoding="utf-8")
    return p


def _code_cells(nb: dict) -> list[str]:
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def test_generation_is_deterministic():
    assert pn.notebook_text(SPEC) == pn.notebook_text(SPEC)


def test_exactly_one_cell_runs_the_pipeline():
    assert pn.run_cell_count(pn.build_notebook(SPEC)) == 1


def test_every_code_cell_compiles():
    for i, src in enumerate(_code_cells(pn.build_notebook(SPEC))):
        compile(src, f"cell{i}", "exec")


def test_refresh_cell_and_commented_step_cell_are_present():
    cells = _code_cells(pn.build_notebook(SPEC))
    assert any("Load the latest code from Drive" in c and "copytree" in c for c in cells)
    step = next(c for c in cells if "Run one step" in c)
    calls = [ln for ln in step.splitlines() if ln.startswith("step(") or ln.startswith("step_range(")]
    assert calls == []  # every example call is commented out
    assert '# step("03")' in step


def test_markdown_is_operational_only():
    md = [("".join(c["source"])) for c in pn.build_notebook(SPEC)["cells"]
          if c["cell_type"] == "markdown"]
    assert len(md) == 1
    for banned in ("fold", "hypothes", "station", "mimeType", "Replica"):
        assert banned not in md[0]


def test_gpu_required_sets_the_colab_accelerator():
    meta = pn.build_notebook(SPEC)["metadata"]
    assert meta["accelerator"] == "GPU" and meta["colab"]["gpuType"] == "T4"
    assert "accelerator" not in pn.build_notebook({**SPEC, "gpu": "none"})["metadata"]


def test_a_second_run_cell_is_detected():
    nb = pn.build_notebook(SPEC)
    nb["cells"].append({"cell_type": "code", "source": ["rc = rt.run_pipeline(SPEC, W, L)\n"]})
    assert pn.run_cell_count(nb) == 2
    nb["cells"][-1] = {"cell_type": "code", "source": ["%%bash\n", "python run_all.py\n"]}
    assert pn.run_cell_count(nb) == 2


def test_check_passes_after_writing_and_fails_on_drift(paper):
    root = str(paper.parents[1])
    run = lambda *a: subprocess.run(  # noqa: E731
        [sys.executable, "scripts/paper_notebook.py", "--slug", "c99-2026", "--root", root, *a],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert run("--check").returncode == 1  # nothing generated yet
    assert run().returncode == 0
    assert run("--check").returncode == 0
    nb_path = paper / "notebooks" / "experiments.ipynb"
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    nb["cells"][0]["source"] = ["# hand edit\n"]
    nb_path.write_text(json.dumps(nb), encoding="utf-8")
    proc = run("--check")
    assert proc.returncode == 1 and "differs" in proc.stderr


def test_readme_links_the_guide_and_lists_stages():
    text = pn.readme_text(SPEC, "c99-2026")
    assert "COLAB.md" in text and "`00_a`" in text and "errors.log" in text


def test_real_papers_with_colab_yaml_are_in_sync():
    for spec in sorted((REPO_ROOT / "papers").glob("*/experiments/colab.yaml")):
        paper = spec.parents[1]
        assert pn.check(paper, paper.name) == [], paper.name


def test_c15_adapter_runs_stages_in_registry_order():
    """run_all.py's list must equal the import order main.py uses for --stage all."""
    import ast
    import re

    paper = REPO_ROOT / "papers" / "c15-2026" / "experiments"
    init = (paper / "src" / "stages" / "__init__.py").read_text(encoding="utf-8")
    registry = re.findall(r"^from src\.stages import (\w+)", init, re.MULTILINE)
    tree = ast.parse((paper / "run_all.py").read_text(encoding="utf-8"))
    stages = next(ast.literal_eval(n.value) for n in tree.body
                  if isinstance(n, ast.Assign) and n.targets[0].id == "STAGES")
    assert stages == registry

def test_pipeline_notebook_loads_the_default_spec():
    load = _code_cells(pn.build_notebook(SPEC))[0]
    assert "rt.load_spec(WORK_DIR)" in load


def test_a_second_spec_generates_its_own_notebook(paper):
    import yaml

    fig_spec = {**SPEC, "title": "c99-2026: figures", "gpu": "none",
                "run": ["run_all.py", "--only", "11_fig"]}
    (paper / "experiments" / "colab_figures.yaml").write_text(yaml.safe_dump(fig_spec),
                                                              encoding="utf-8")
    root = str(paper.parents[1])
    run = lambda *a: subprocess.run(  # noqa: E731
        [sys.executable, "scripts/paper_notebook.py", "--slug", "c99-2026", "--root", root, *a],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert run().returncode == 0
    nb = json.loads((paper / "notebooks" / "figures.ipynb").read_text(encoding="utf-8"))
    assert 'rt.load_spec(WORK_DIR, "colab_figures.yaml")' in _code_cells(nb)[0]
    assert pn.run_cell_count(nb) == 1
    assert "figures.ipynb" in (paper / "notebooks" / "figures.md").read_text(encoding="utf-8")
    assert run("--check").returncode == 0
    (paper / "notebooks" / "figures.md").write_text("hand edit\n", encoding="utf-8")
    proc = run("--check")
    assert proc.returncode == 1 and "colab_figures.yaml" in proc.stderr

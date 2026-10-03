"""Every pipeline source file must at least compile.

A syntax error in a file no test imports (report.py once had an unterminated
string) otherwise reaches Colab and fails there, after the sync. Compiling is
cheap and needs none of the pipeline's dependencies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(
    p for p in REPO_ROOT.glob("papers/*/experiments/**/*.py")
    if "__pycache__" not in p.parts
) + [REPO_ROOT / "scripts" / "_colab_runtime.py"]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_source_compiles(path: Path):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")

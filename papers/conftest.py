# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Mark every per-paper test suite as slow.

A paper's suite synthesises frames and refits climatologies for each case, which
is worth running before a release but not on every push. The gate in CI
therefore runs ``pytest -m "not slow"``: measured, that is 51 tests in ~5 s
against ~66 s for plain ``pytest -q``.

Marking them here rather than decorating a hundred-odd test functions means a
new paper suite is slow by default. The failure mode we care about is a suite
that becomes a bottleneck for everyone because nobody remembered a decorator.

Register the marker in ``pytest.ini`` (``markers = slow: ...``).
"""

from pathlib import Path
from types import ModuleType

import sys

import pytest

_PAPERS = Path(__file__).resolve().parent
_SNAPSHOT: dict[Path, dict[str, ModuleType]] = {}


def _paper_of(path: Path) -> Path | None:
    """The `papers/<slug>/` folder that owns `path`, if any."""
    try:
        path = path.resolve()
    except OSError:
        return None
    for parent in path.parents:
        if parent.parent == _PAPERS:
            return parent
    return None


def pytest_collectstart(collector):
    """Keep each paper's suite on its own modules.

    Every paper ships `experiments/_common.py`, `_figstyle.py`, `run_all.py`,
    ... with the same names, and the test modules import them by bare name. The
    first paper collected wins the `sys.modules` entry, so the second paper
    tests the first paper's module. Snapshot the previous paper's modules and
    drop them before the next paper is imported; its test file re-inserts its
    own `experiments/` at the front of `sys.path`.
    """
    path = getattr(collector, "path", None)
    if path is None:
        return
    current = _paper_of(path)
    if current is None:
        return
    for name, module in list(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        owner = _paper_of(Path(origin))
        if owner is not None and owner != current:
            _SNAPSHOT.setdefault(owner, {})[name] = module
            del sys.modules[name]


@pytest.fixture(autouse=True)
def _own_paper_modules(request):
    """Re-install the test's paper modules for imports done inside tests.

    A test that runs ``import _figstyle`` lazily after collection would find
    whichever paper's `experiments/` sits first in `sys.path`, not its own.
    """
    paper = _paper_of(Path(str(request.path)))
    if paper is not None:
        sys.modules.update(_SNAPSHOT.get(paper, {}))
    yield


def pytest_collection_modifyitems(items):
    """Tag items collected from under papers/.

    The hook is session-scoped: every conftest receives the whole item list, so
    the path filter is required. Without it the repository suite would be
    deselected by ``-m "not slow"`` too, and CI would check nothing at all.
    """
    for item in items:
        path = getattr(item, "path", None) or Path(str(item.fspath))
        if _PAPERS in path.parents:
            item.add_marker(pytest.mark.slow)
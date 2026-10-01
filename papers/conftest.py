"""Mark every per-paper test suite as slow.

A paper's suite synthesises frames and refits climatologies for each case, which
is worth running before a release but not on every push. The structure gate in
CI therefore runs ``pytest -m "not slow"`` and checks a pull request against the
repository contract in seconds; plain ``pytest -q`` still runs everything.

Marking them here rather than decorating a hundred-odd test functions means a
new paper suite is slow by default. The failure mode we care about is a suite
that becomes a bottleneck for everyone because nobody remembered a decorator.

Register the marker in ``pytest.ini`` (``markers = slow: ...``).
"""

from pathlib import Path

import pytest

_PAPERS = Path(__file__).resolve().parent


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
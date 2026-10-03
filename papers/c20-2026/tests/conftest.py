# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Guard rails for the c20-2026 tests.

Two invariants that must hold without anyone having to remember them:

1. Tests never read the real dataset. `data/raw/dataset.csv` and every artefact
   under `data/processed/` and `outputs/` are either gitignored or regenerated,
   and a test that depends on them becomes machine-specific. Fixtures build
   synthetic frames instead.

2. Tests never get expensive. Model stages (`07`, `08`, `09`) are heavy by
   design; their tests must use tiny budgets so the suite stays a fast feedback
   loop rather than a second training run on the author's machine.

The audit hook below enforces (1) at runtime: any attempt to open a real data
path during a test fails loudly instead of silently passing on one machine and
failing on another.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PAPER_ROOT = Path(__file__).resolve().parents[1]
REAL_DATA_DIR = PAPER_ROOT / "data"
REAL_OUTPUTS_DIR = PAPER_ROOT / "outputs"

# Installed once per session; `sys.addaudithook` cannot be removed afterwards.
_audit_hook_installed = False


def _is_real_data(path: object) -> bool:
    try:
        p = Path(str(path)).resolve()
    except (TypeError, ValueError, OSError):
        return False
    for root in (REAL_DATA_DIR, REAL_OUTPUTS_DIR):
        try:
            p.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _install_guard() -> None:
    global _audit_hook_installed
    if _audit_hook_installed:
        return

    def hook(event: str, args: tuple) -> None:
        if event == "open" and args and _is_real_data(args[0]):
            raise AssertionError(
                f"test tried to open real pipeline data: {args[0]!r}. "
                "Use a synthetic fixture instead (see tests/README or conftest)."
            )

    sys.addaudithook(hook)
    _audit_hook_installed = True


_install_guard()


@pytest.fixture(autouse=True)
def _guard_active():
    """Keep the hook active for every test in this folder."""
    _install_guard()
    yield
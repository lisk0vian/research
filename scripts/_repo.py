# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Shared helpers for the repository scripts (repo root discovery, YAML I/O).

Every script in this folder is plain, editable Python: no hidden agent logic.
The agent (skill wrapper) gathers decisions from the user, then calls a script
with explicit arguments. The script is the reproducible source of truth.
"""

from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced with a clear message downstream
    yaml = None


def find_repo_root(start: str | Path | None = None) -> Path:
    """Walk upwards until the repository root (AGENTS.md + papers/) is found."""
    cur = Path(start).resolve() if start else Path.cwd().resolve()
    if cur.is_file():
        cur = cur.parent
    for candidate in [cur, *cur.parents]:
        if (candidate / "AGENTS.md").is_file() and (candidate / "papers").is_dir():
            return candidate
    return cur


def load_yaml(path: str | Path) -> dict:
    """Load a YAML mapping; return {} for empty files or non-mappings."""
    if yaml is None:
        raise RuntimeError("PyYAML is required: pip install pyyaml")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}

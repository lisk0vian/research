#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""link_agents.py — generate tool-specific subagents from neutral canonicals.

Canonical agents live in `.agents/agents/*.md` with neutral front-matter:

    name: peer-plan
    description: ...
    access: read-only

`scripts/link_agents.py` translates the front-matter per tool and keeps the
prompt body identical:

- Claude Code (`.claude/agents/*.md`): `name, description, tools`.
- OpenCode (`.opencode/agents/*.md`): `description, mode: subagent, tools`.

No model is ever pinned: the `model` field is omitted so every subagent
inherits the session model on both tools (free tier included).

Generated files carry a GENERATED header with the canonical sha256; `--check`
regenerates in memory and compares. Both output dirs are gitignored.

Usage:
    python scripts/link_agents.py            # write/refresh generated agents
    python scripts/link_agents.py --check    # verify only; exit 1 if stale
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root  # noqa: E402

CANON_DIR = Path(".agents") / "agents"
CLAUDE_DIR = Path(".claude") / "agents"
OPENCODE_DIR = Path(".opencode") / "agents"

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*(\n|$)", re.DOTALL)


def _parse_front_matter(text: str) -> tuple[dict, str]:
    m = FRONT_MATTER.match(text)
    if not m:
        raise ValueError("missing YAML front-matter block (--- ... ---)")
    fm: dict = {}
    for line in m.group(1).splitlines():
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match:
            fm[match.group(1)] = match.group(2).strip().strip("'\"")
    return fm, text[m.end():]


def _canon_hash(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:16]


def _claude_doc(name: str, desc: str, body: str, src_hash: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        "tools: Read, Grep, Glob\n"
        "---\n"
        f"<!-- GENERATED from .agents/agents/{name}.md ({src_hash}). Do not edit. -->\n"
        f"{body.strip()}\n"
    )


def _opencode_doc(name: str, desc: str, body: str, src_hash: str) -> str:
    return (
        "---\n"
        f"description: {desc}\n"
        "mode: subagent\n"
        "tools:\n"
        "  write: false\n"
        "  edit: false\n"
        "  bash: false\n"
        "permission:\n"
        "  edit: deny\n"
        "  write: deny\n"
        "  bash: deny\n"
        "---\n"
        f"<!-- GENERATED from .agents/agents/{name}.md ({src_hash}). Do not edit. -->\n"
        f"{body.strip()}\n"
    )


def _canonicals(repo: Path) -> dict[str, tuple[str, dict, str]]:
    src = repo / CANON_DIR
    if not src.is_dir():
        return {}
    out: dict[str, tuple[str, dict, str]] = {}
    for path in sorted(src.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm, body = _parse_front_matter(text)
        name = str(fm.get("name") or path.stem)
        out[name] = (text, fm, body)
    return out


def _expected(repo: Path) -> tuple[dict[str, str], dict[str, str], list[str]]:
    canon = _canonicals(repo)
    warnings: list[str] = []
    claude: dict[str, str] = {}
    opencode: dict[str, str] = {}
    for name, (text, fm, body) in canon.items():
        for key in ("name", "description", "access"):
            if not fm.get(key):
                warnings.append(f".agents/agents/{name}.md: missing '{key}'")
        if fm.get("access") != "read-only":
            warnings.append(f".agents/agents/{name}.md: access should be 'read-only'")
        desc = str(fm.get("description") or "").replace("\n", " ").strip()
        src_hash = _canon_hash(text)
        claude[name] = _claude_doc(name, desc, body, src_hash)
        opencode[name] = _opencode_doc(name, desc, body, src_hash)
    return claude, opencode, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate tool agents from neutral canonicals.")
    ap.add_argument("--root", default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    claude, opencode, warnings = _expected(repo)
    if not claude and not opencode:
        print("no canonical agents in .agents/agents/")
        return 0

    if args.check:
        failures = 0
        for name, want in sorted(claude.items()):
            got = repo / CLAUDE_DIR / f"{name}.md"
            if not got.is_file() or got.read_text(encoding="utf-8") != want:
                print(f"stale: .claude/agents/{name}.md")
                failures += 1
        for name, want in sorted(opencode.items()):
            got = repo / OPENCODE_DIR / f"{name}.md"
            if not got.is_file() or got.read_text(encoding="utf-8") != want:
                print(f"stale: .opencode/agents/{name}.md")
                failures += 1
        for w in warnings:
            print(f"warning: {w}")
        if failures:
            print("run: python scripts/link_agents.py")
            return 1
        print(f"OK: {len(claude)} agent(s) in sync")
        return 0

    for w in warnings:
        print(f"warning: {w}")
    (repo / CLAUDE_DIR).mkdir(parents=True, exist_ok=True)
    (repo / OPENCODE_DIR).mkdir(parents=True, exist_ok=True)
    for name, want in sorted(claude.items()):
        (repo / CLAUDE_DIR / f"{name}.md").write_text(want, encoding="utf-8", newline="\n")
        print(f"wrote .claude/agents/{name}.md")
    for name, want in sorted(opencode.items()):
        (repo / OPENCODE_DIR / f"{name}.md").write_text(want, encoding="utf-8", newline="\n")
        print(f"wrote .opencode/agents/{name}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

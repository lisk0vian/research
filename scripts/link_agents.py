#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""link_agents.py — generate tool-specific subagents from neutral canonicals.

Canonical agents live in `.agents/agents/*.md` with neutral front-matter:

    name: rev-methodology
    description: ...
    access: read-only
    model_tier: strong

`scripts/link_agents.py` translates the front-matter per tool and keeps the
prompt body identical:

- Claude Code (`.claude/agents/*.md`): `name, description, tools, model`.
- OpenCode (`.opencode/agents/*.md`): `description, mode: subagent, tools`.

Tier-to-model mapping lives in `.agents/agents/models.yaml`. A tier missing
there inherits the session model locally (with a warning) but fails
`--check`, so a strong reviewer never silently runs on a weak model.

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

from _repo import find_repo_root, load_yaml  # noqa: E402

CANON_DIR = Path(".agents") / "agents"
CLAUDE_DIR = Path(".claude") / "agents"
OPENCODE_DIR = Path(".opencode") / "agents"
MODELS_FILE = "models.yaml"

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*(\n|$)", re.DOTALL)


def _split_front_matter(text: str) -> tuple[dict, str]:
    m = FRONT_MATTER.match(text)
    if not m:
        raise ValueError("missing YAML front-matter block (--- ... ---)")
    return load_yaml_text(m.group(1)), text[m.end():]


def load_yaml_text(text: str) -> dict:
    try:
        import yaml

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        out: dict = {}
        for line in text.splitlines():
            m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("'\"")
        return out


def _canon_hash(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:16]


def _claude_doc(name: str, desc: str, tier: str, models: dict, body: str, src_hash: str) -> str:
    model = ((models.get(tier) or {}) if isinstance(models, dict) else {}).get("claude", "inherit")
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        "tools: Read, Grep, Glob\n"
        f"model: {model}\n"
        "---\n"
        f"<!-- GENERATED from .agents/agents/{name}.md ({src_hash}). Do not edit. -->\n"
        f"{body.strip()}\n"
    )


def _opencode_doc(name: str, desc: str, tier: str, models: dict, body: str, src_hash: str) -> str:
    model = ((models.get(tier) or {}) if isinstance(models, dict) else {}).get("opencode", "inherit")
    model_block = "" if str(model) == "inherit" else f"model: {model}\n"
    return (
        "---\n"
        f"description: {desc}\n"
        "mode: subagent\n"
        f"{model_block}"
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
        fm, body = _split_front_matter(text)
        name = str(fm.get("name") or path.stem)
        out[name] = (text, fm, body)
    return out


def _expected(repo: Path) -> tuple[dict[str, str], dict[str, str], list[str]]:
    canon = _canonicals(repo)
    models_path = repo / CANON_DIR / MODELS_FILE
    models = load_yaml(models_path) if models_path.is_file() else {}
    warnings: list[str] = []
    claude: dict[str, str] = {}
    opencode: dict[str, str] = {}
    for name, (text, fm, body) in canon.items():
        for key in ("name", "description", "access", "model_tier"):
            if not fm.get(key):
                warnings.append(f".agents/agents/{name}.md: missing '{key}'")
        tier = str(fm.get("model_tier") or "")
        desc = str(fm.get("description") or "").replace("\n", " ").strip()
        if tier and tier not in (models or {}):
            warnings.append(f".agents/agents/{name}.md: tier '{tier}' not in models.yaml (inherits session model)")
        src_hash = _canon_hash(text)
        claude[name] = _claude_doc(name, desc, tier, models, body, src_hash)
        opencode[name] = _opencode_doc(name, desc, tier, models, body, src_hash)
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

    models = load_yaml(repo / CANON_DIR / MODELS_FILE) if (repo / CANON_DIR / MODELS_FILE).is_file() else {}
    unmapped = sorted({str(fm.get("model_tier") or "?") for _, fm, _ in _canonicals(repo).values()} - set(models or {}))

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
        if unmapped:
            print(f"unmapped tiers (would inherit silently): {', '.join(unmapped)}")
            failures += 1
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

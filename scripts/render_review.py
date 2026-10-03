#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""render_review.py — render consolidated.md from consolidated.yaml.

The editor writes only consolidated.yaml; this script renders the human
twin and pre-fills triage.yaml with pending entries. CI regenerates the
.md and compares bytes (like link_agents.py --check): a hand-edited .md
fails, because two texts from the same model can tell different stories.

Usage:
    python scripts/render_review.py --slug c20-2026 --round round-1
    python scripts/render_review.py --slug c20-2026 --round round-1 --check
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402
from _structure import REVIEW_SCHEMA_VERSION  # noqa: E402


def _render(paper: str, rnd: str, scope: str, data: dict, src_hash: str) -> str:
    lines = [
        f"<!-- GENERATED from consolidated.yaml ({src_hash}). Do not edit. -->",
        f"# Round {rnd} — consolidated ({scope})",
        "",
    ]
    for f in data.get("findings") or []:
        basis = f.get("basis", "?")
        lines.append(
            f"- [{f.get('severity')}] [{basis}] {f.get('id')} — {f.get('title')}"
        )
        lines.append(f"  `{f.get('location')}` — {f.get('warrant')}")
        lines.append(f"  Fix: {f.get('fix')}")
    discarded = data.get("discarded") or []
    if discarded:
        lines += ["", "## Discarded"]
        for d in discarded:
            lines.append(f"- {d.get('raw_id')}: {d.get('reason')}")
    return "\n".join(lines) + "\n"


def _doc(slug: str, rnd: str, paper: Path) -> tuple[str, dict, str]:
    con = paper / "reviews" / rnd / "consolidated.yaml"
    data = load_yaml(con)
    if data.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise SystemExit(f"ERROR: {con} has no schema_version: 2")
    raw = con.read_bytes().replace(b"\r\n", b"\n")
    src_hash = hashlib.sha256(raw).hexdigest()[:16]
    scope = ""
    packet = paper / "reviews" / rnd / "packet.yaml"
    if packet.is_file():
        try:
            scope = str(load_yaml(packet).get("scope") or "")
        except Exception:
            scope = ""
    return _render(paper.name, rnd, scope or "full", data, src_hash), data, slug


def main() -> int:
    ap = argparse.ArgumentParser(description="Render consolidated.md + pre-fill triage.")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--round", default="round-1")
    ap.add_argument("--root", default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    paper = repo / "papers" / args.slug
    rnd_dir = paper / "reviews" / args.round
    want, data, _ = _doc(args.slug, args.round, paper)
    md_path = rnd_dir / "consolidated.md"

    if args.check:
        if not md_path.is_file() or md_path.read_text(encoding="utf-8") != want:
            print(f"stale: papers/{args.slug}/reviews/{args.round}/consolidated.md")
            print("run: python scripts/render_review.py --slug "
                  f"{args.slug} --round {args.round}")
            return 1
        print("OK: consolidated.md in sync")
        return 0

    md_path.write_text(want, encoding="utf-8", newline="\n")
    print(f"wrote {md_path}")

    tri_path = rnd_dir / "triage.yaml"
    try:
        tri = load_yaml(tri_path) if tri_path.is_file() else {}
    except Exception:
        tri = {}
    if not isinstance(tri, dict):
        tri = {}
    tri.setdefault("schema_version", REVIEW_SCHEMA_VERSION)
    decisions = tri.get("decisions")
    if not isinstance(decisions, list):
        decisions = []
        tri["decisions"] = decisions
    known = {str(d.get("finding_id")) for d in decisions if isinstance(d, dict)}
    for f in data.get("findings") or []:
        if str(f.get("id")) not in known:
            decisions.append({"finding_id": str(f.get("id")), "decision": "pending", "reason": ""})
    try:
        import yaml  # type: ignore

        tri_path.write_text(yaml.safe_dump(tri, sort_keys=False, allow_unicode=True),
                            encoding="utf-8", newline="\n")
    except Exception:
        import json as _json

        tri_path.with_suffix(".json").write_text(
            _json.dumps(tri, indent=2, ensure_ascii=False), encoding="utf-8")
        print("warning: PyYAML missing, triage not written as YAML", file=sys.stderr)
        return 1
    print(f"pre-filled {tri_path} ({len(decisions)} decisions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

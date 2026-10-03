#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_review.py — freeze a review round packet deterministically.

The script does what is deterministic (commits, dirtiness, content hashes,
traceability of run_meta.json); the agents only read. A round packet records
the exact code and manuscript version every finding refers to.

Traceability (Colab/Drive has no git, so git alone is not proof):

- absence: run_meta.json has no code_hashes (old run) -> no failure.
  packet.yaml marks trace "absent" and the editor reports it as a major
  ("results not traceable to code"). This lets the panel run on c15/c21/c26
  and on c20 before re-execution.
- discrepancy: code_hashes (or git_commit, when both ends have it) disagree
  with the local tree -> fail by default. --allow-mismatch records it in
  packet.yaml as trace "mismatch" for the editor to report as a major.

Dirty anchored files (main.qmd, manifest.yaml, config.yaml,
experiments/*.py) fail by default: commit before reviewing. --allow-dirty
records the content hashes anyway; the validator then checks quotes only
when the worktree hash still matches the packet.

Usage:
    python scripts/paper_review.py --slug c20-2026 --round round-1
    python scripts/paper_review.py --slug c20-2026 --round round-1 --scope code-only
    python scripts/paper_review.py --slug c20-2026 --round round-2 --only peer-plan
    python scripts/paper_review.py --slug c20-2026 --round round-2 --allow-mismatch --allow-dirty
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402
from _structure import REVIEW_GROUPS, REVIEW_PRESETS, REVIEW_SCHEMA_VERSION  # noqa: E402

ALL_REVIEW_AGENTS = (
    "rev-design", "rev-refs", "rev-style",
    "peer-plan", "peer-results", "peer-reach", "gate-claims",
)
MERGE_AGENT = "gate-merge"

ANCHORED = [
    Path("paper/main.qmd"),
    Path("manifest.yaml"),
    Path("experiments/config.yaml"),
]


def _git(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _norm_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _rel(posix: str) -> str:
    return posix.replace("\\", "/")


def _anchored_files(paper: Path) -> list[Path]:
    files = [p for p in ANCHORED if (paper / p).is_file()]
    exp = paper / "experiments"
    if exp.is_dir():
        files += sorted(p for p in exp.glob("*.py") if p.is_file())
    return files


def _dirty_anchored(repo: Path, paper: Path) -> list[str]:
    out = _git(repo, "status", "--porcelain", "--", str(paper.relative_to(repo)))
    if out is None:
        return []
    anchored = {_rel(str(p.as_posix())) for p in _anchored_files(paper)}
    dirty: list[str] = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        try:
            rel_to_paper = _rel((repo / path).relative_to(paper).as_posix())
        except ValueError:
            continue
        if rel_to_paper in anchored:
            dirty.append(rel_to_paper)
    return sorted(dirty)


def main() -> int:
    ap = argparse.ArgumentParser(description="Freeze a review round packet.")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--round", default="round-1")
    ap.add_argument("--root", default=None)
    ap.add_argument("--scope", choices=("code-only", "full"), default="full")
    ap.add_argument("--only", default=None,
                    help="comma-separated agents, groups (paper/code/gate) or presets "
                         "(plan/code/manuscript/claims/full); default runs the scope set")
    ap.add_argument("--allow-mismatch", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    paper = repo / "papers" / args.slug
    if not paper.is_dir():
        print(f"ERROR: no papers/{args.slug}/", file=sys.stderr)
        return 2
    if args.scope == "full" and not (paper / "paper" / "main.qmd").is_file():
        print("ERROR: full scope needs paper/main.qmd; use --scope code-only", file=sys.stderr)
        return 2

    agents = _resolve_agents(args.only, args.scope)
    if agents is None:
        return 2
    deferred = _deferred(args.scope, agents)

    dirty = _dirty_anchored(repo, paper)
    if dirty and not args.allow_dirty:
        print("ERROR: anchored files have uncommitted changes; commit before reviewing:", file=sys.stderr)
        for d in dirty:
            print(f"  {d}", file=sys.stderr)
        print("re-run with --allow-dirty to review the worktree anyway (hash-anchored).", file=sys.stderr)
        return 1

    head = _git(repo, "rev-parse", "--short", "HEAD")
    porcelain = _git(repo, "status", "--porcelain")
    repos = [{"path": ".", "commit": head or "unknown", "dirty": bool(porcelain)}]

    files: dict[str, str] = {}
    for rel in _anchored_files(paper):
        abs_path = paper / rel
        files[_rel(rel.as_posix())] = _norm_hash(abs_path)
    agents_dir = repo / ".agents" / "agents"
    if agents_dir.is_dir():
        for p in sorted(agents_dir.glob("*.md")):
            files[_rel(f".agents/agents/{p.name}")] = _norm_hash(p)

    run_meta_path = paper / "outputs" / "run_meta.json"
    trace = "absent"
    trace_reason = "run_meta.json has no code_hashes (run predates traceability; re-run in Colab)"
    mismatch_detail: list[str] = []
    if run_meta_path.is_file():
        try:
            meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        recorded = meta.get("code_hashes") if isinstance(meta, dict) else None
        if isinstance(recorded, dict) and recorded:
            exp = paper / "experiments"
            local = {_rel(f"experiments/{p.name}"): _norm_hash(p) for p in sorted(exp.glob("*.py")) if p.is_file()}
            cfg = paper / "experiments" / "config.yaml"
            if cfg.is_file():
                local["experiments/config.yaml"] = _norm_hash(cfg)
            bad = sorted(k for k, v in recorded.items() if local.get(k) != v)
            extra = sorted(k for k in local if k not in recorded)
            if bad or extra:
                mismatch_detail = bad + [f"{k} (unrecorded)" for k in extra]
                if args.allow_mismatch:
                    trace = "mismatch"
                    trace_reason = f"code_hashes differ from local tree: {', '.join(mismatch_detail)}"
                else:
                    print("ERROR: run_meta code_hashes do not match the local tree:", file=sys.stderr)
                    for k in mismatch_detail:
                        print(f"  {k}", file=sys.stderr)
                    print("re-run with --allow-mismatch to record it as a major.", file=sys.stderr)
                    return 1
            else:
                trace = "ok"
                trace_reason = "code_hashes match the local tree"
                recorded_commit = meta.get("git_commit")
                if recorded_commit and head and str(recorded_commit) != head:
                    if args.allow_mismatch:
                        trace = "mismatch"
                        trace_reason = f"git_commit {recorded_commit} != local {head}"
                    else:
                        print(f"ERROR: run_meta git_commit {recorded_commit} != local {head}", file=sys.stderr)
                        print("re-run with --allow-mismatch to record it as a major.", file=sys.stderr)
                        return 1

    round_dir = paper / "reviews" / args.round
    (round_dir / "raw").mkdir(parents=True, exist_ok=True)
    packet = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "paper": args.slug,
        "round": args.round,
        "scope": args.scope,
        "agents": agents,
        "deferred": deferred,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repos": repos,
        "files": files,
        "trace": trace,
        "trace_reason": trace_reason,
        "mismatch": mismatch_detail,
        "allow": {
            "mismatch": bool(args.allow_mismatch),
            "dirty": bool(args.allow_dirty),
            "dirty_files": dirty,
        },
    }
    text = json.dumps(packet, indent=2, ensure_ascii=False)
    try:
        import yaml  # type: ignore

        as_yaml = yaml.safe_dump(packet, sort_keys=False, allow_unicode=True)
    except Exception:
        as_yaml = None
    out = round_dir / "packet.yaml"
    if as_yaml is not None:
        out.write_text(as_yaml, encoding="utf-8", newline="\n")
    else:
        out.with_suffix(".json").write_text(text, encoding="utf-8", newline="\n")
        print(f"warning: PyYAML missing, wrote {out.with_suffix('.json').name} instead", file=sys.stderr)
        return 1
    print(f"wrote {out} (scope={args.scope} agents={','.join(agents)} trace={trace})")
    if trace in ("absent", "mismatch"):
        print(f"note: {trace_reason}; the editor must report it as a major", file=sys.stderr)
    return 0


def _resolve_agents(only: str | None, scope: str) -> list[str] | None:
    """--only tokens (agents, groups, presets) -> explicit agent list."""
    if scope == "code-only":
        default = ["peer-plan", "peer-results", "peer-reach"]
    else:
        default = list(ALL_REVIEW_AGENTS)
    if not only:
        return default
    out: list[str] = []
    for tok in [t.strip() for t in only.split(",") if t.strip()]:
        if tok in ALL_REVIEW_AGENTS:
            names = [tok]
        elif tok in REVIEW_GROUPS:
            names = list(REVIEW_GROUPS[tok])
        elif tok in REVIEW_PRESETS:
            names = list(REVIEW_PRESETS[tok])
        else:
            print(f"ERROR: unknown agent/group/preset '{tok}'", file=sys.stderr)
            print(f"agents: {', '.join(ALL_REVIEW_AGENTS)}", file=sys.stderr)
            print(f"groups: {', '.join(REVIEW_GROUPS)}", file=sys.stderr)
            print(f"presets: {', '.join(REVIEW_PRESETS)}", file=sys.stderr)
            return None
        for n in names:
            if n not in out:
                out.append(n)
    if scope == "code-only":
        out = [n for n in out if n in ("peer-plan", "peer-results", "peer-reach")]
        if not out:
            out = ["peer-plan", "peer-results", "peer-reach"]
    return out


def _deferred(scope: str, agents: list[str]) -> list[dict]:
    """What this round explicitly does not evaluate, and why."""
    out: list[dict] = []
    if scope == "code-only":
        out.append({"item": "manuscript-checks", "reason": "no main.qmd in code-only scope"})
        if "gate-claims" not in agents:
            out.append({"item": "gate-claims", "reason": "manuscript numbers do not exist yet"})
    skipped = [n for n in ALL_REVIEW_AGENTS if n not in agents]
    if skipped:
        out.append({"item": "agents", "reason": f"not run: {', '.join(skipped)}"})
    return out


if __name__ == "__main__":
    raise SystemExit(main())

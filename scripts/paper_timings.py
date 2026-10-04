#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_timings.py — how long each paper's processes take, in one view.

Each paper records its own timings on Colab: `outputs/timings.json` (the
measured history plus the expectations) and `outputs/timings.md` (the human
view), both written by `_colab_runtime.Timings` after every stage. This script
is the cross-paper side of the same contract:

    python scripts/paper_timings.py                  # every paper, one view
    python scripts/paper_timings.py --slug c20-2026  # one paper in detail
    python scripts/paper_timings.py --seed c20-2026  # harvest past durations
    python scripts/paper_timings.py --write PATH     # write the view to a file

Nothing here computes an expectation of its own: the expected wait is the
median of the *fresh* measurements when there is one, else the a-priori
estimate in `papers/<slug>/experiments/timings.yaml`. `--seed` only moves
durations that already exist somewhere else (state files, stage logs, the run
meta) into the record so a paper does not start from nothing; seeded entries
never claim freshness on their own.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

# The views use the same marks as outputs/timings.md (— and ⚠); a Windows
# console defaults to cp1252 and would die on them mid-print.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _colab_runtime as rt  # noqa: E402  (needs scripts/ on the path)

EXIT_RE = re.compile(r"^# STAGE-EXIT (\S+) exit_code=(-?\d+) elapsed_s=([0-9.]+)",
                     re.MULTILINE)


def papers() -> list[Path]:
    return sorted(p for p in (REPO / "papers").iterdir()
                  if p.is_dir() and (p / "experiments").is_dir())


def timings_for(slug: str, mode: str) -> rt.Timings:
    root = REPO / "papers" / slug
    return rt.Timings(root / "outputs", code_dir=root / "experiments", mode=mode)


# --- seeding ------------------------------------------------------------------

def _entries_from(outputs: Path) -> dict[str, list[dict]]:
    """Durations that already exist elsewhere, one entry per distinct measurement.

    `outputs/_state/<stage>.json` carries the key and the code_sha, which is
    what lets a seeded entry become *fresh* later; a log footer or the run meta
    can only say "it took this long, once". Different sources can describe
    different runs (a local run and a Colab run), so each distinct measurement
    is kept with the source it came from instead of one winner per stage.
    """
    found: dict[str, list[dict]] = {}

    def offer(stage: str, elapsed: float, status: str, source: str,
              run: str | None = None, key: str | None = None,
              code_sha: str | None = None) -> None:
        bucket = found.setdefault(stage, [])
        if any(abs(e["elapsed_s"] - elapsed) < 0.01 and e["status"] == status
               for e in bucket):
            return  # the same measurement seen through two sources
        bucket.append({"elapsed_s": float(elapsed), "status": status, "run": run,
                       "key": key, "code_sha": code_sha, "source": source})

    for path in sorted((outputs / rt.STATE_DIR).glob("*.json")) if (outputs / rt.STATE_DIR).is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("elapsed_s") is not None:
            offer(data.get("stage") or path.stem, float(data["elapsed_s"]), "ok",
                  "state", run=data.get("finished"), key=data.get("key"),
                  code_sha=data.get("code_sha"))

    for log in sorted((outputs / "logs").glob("*.log")) if (outputs / "logs").is_dir() else []:
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for stage, rc, elapsed in EXIT_RE.findall(text):
            offer(stage, float(elapsed), "ok" if int(rc) == 0 else "failed", "log")

    for source, key in (("manifest_index.json", "logs"), ("run_meta.json", "results")):
        path = outputs / source
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        table = ((data.get(key) or {}).get("stages") if key == "logs"
                 else (data.get("results") or {}))
        for stage, info in (table or {}).items():
            if isinstance(info, dict) and info.get("elapsed_s") is not None:
                rc = info.get("exit_code")
                offer(stage, float(info["elapsed_s"]),
                      "ok" if rc in (None, 0) else "failed", source)
    return found


def _state_fingerprints(outputs: Path) -> dict[str, tuple[str | None, str | None]]:
    """What the stage states say is current, for the freshness re-evaluation."""
    out: dict[str, tuple[str | None, str | None]] = {}
    state_dir = outputs / rt.STATE_DIR
    if not state_dir.is_dir():
        return out
    for path in sorted(state_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[data.get("stage") or path.stem] = (data.get("key"), data.get("code_sha"))
    return out


def seed(slug: str, mode: str) -> int:
    root = REPO / "papers" / slug
    outputs = root / "outputs"
    if not outputs.is_dir():
        print(f"{slug}: no outputs/ yet, nothing to seed")
        return 0
    tim = timings_for(slug, mode)
    entries = _entries_from(outputs)
    seeded, stages = 0, set()
    for stage, bucket in sorted(entries.items()):
        est = tim._est_stage(stage)          # same writer, same vocabulary
        units = tim._units_from_file(est["units_from"]) if est.get("units_from") else None
        for e in bucket:
            tim.seed_stage(stage, e["elapsed_s"], e["status"], run=e["run"],
                           key=e["key"], code_sha=e["code_sha"], units=units,
                           source=e["source"])
            seeded += 1
            stages.add(stage)
    # A stage that writes its own per-unit times (c26's reniped) may be the only
    # place its duration exists: the stage total is the sum of its units.
    for stage, est in (tim.estimates().get("stages") or {}).items():
        if entries.get(stage) or not est.get("units_from"):
            continue
        units = tim._units_from_file(est["units_from"])
        if units:
            tim.seed_stage(stage, sum(v for v in units.values() if v is not None),
                           "ok", units=units, source="units_from")
            seeded += 1
            stages.add(stage)
    if not seeded:
        print(f"{slug}: no durations found in _state/, logs/, the run meta "
              "or a units_from file")
        return 0
    fingerprints = _state_fingerprints(outputs)
    if fingerprints:
        tim.sync_fingerprints(fingerprints)
    print(f"{slug}: seeded {seeded} measurement(s) over "
          f"{len(stages)} stage(s) into {tim.path}")
    return seeded


# --- the view -----------------------------------------------------------------

def summary(slug: str, data: dict, mode: str) -> list[str]:
    blocks = (data.get("modes") or {}).get(mode, {})
    expected = [b.get("expected_s") for b in blocks.values() if b.get("expected_s")]
    sources = {b.get("expected_source") for b in blocks.values() if b.get("expected_s")}
    outside = sum(1 for b in blocks.values()
                  for e in (b.get("history") or []) if e.get("outside_estimate"))
    total = rt._fmt_secs(sum(expected)) if expected else "—"
    return [slug, total, "/".join(sorted(s for s in sources if s)) or "—",
            str(len(blocks)), str(outside), str(data.get("updated") or "—")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slug", help="one paper instead of all of them")
    ap.add_argument("--mode", choices=("full", "smoke"), default="full",
                    help="which run mode to show (they are never mixed)")
    ap.add_argument("--seed", nargs="?", const="all", metavar="SLUG",
                    help="harvest durations that exist elsewhere into timings.json "
                         "(one slug, or every paper when given alone)")
    ap.add_argument("--write", type=Path, help="write the view to this file")
    args = ap.parse_args(argv)

    slugs = [args.slug] if args.slug else [p.name for p in papers()]
    if not slugs:
        print("no papers found", file=sys.stderr)
        return 1
    if args.seed:
        targets = slugs if args.seed == "all" else [args.seed]
        for s in targets:
            seed(s, args.mode)
        return 0

    chunks: list[str] = []
    if not args.slug:
        rows = []
        for slug in slugs:
            tim = timings_for(slug, args.mode)
            rows.append(summary(slug, tim.preview(), args.mode))
        head = ["paper", "expected run", "expectation from", "processes",
                "outside estimate", "updated"]
        widths = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
        chunks.append(f"# Timings — all papers ({args.mode} mode)\n")
        chunks.append("Expected wait per paper is the sum of its processes' expectations;\n"
                      "see each paper's section below for the detail.\n")
        chunks.append("| " + " | ".join(h.ljust(w) for h, w in zip(head, widths)) + " |")
        chunks.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
        for r in rows:
            chunks.append("| " + " | ".join(c.ljust(w) for c, w in zip(r, widths)) + " |")
        chunks.append("")
    for slug in slugs:
        chunks.append(timings_for(slug, args.mode).render())
    text = "\n".join(chunks)
    if args.write:
        args.write.write_text(text, encoding="utf-8")
        print(f"wrote {args.write}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

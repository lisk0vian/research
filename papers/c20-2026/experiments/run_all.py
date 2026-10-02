"""Ordered orchestrator for stages 00-10, with per-stage logging.

Runs 00→10 in order, or a named subset. Every stage is launched through
`_common.run_stage`, which is the single writer of `outputs/logs/<stage>.log`:
header, the child's merged output, then a footer carrying the real exit code and
elapsed time. That footer is why this is Python and not a shell `tee` - see the
note in `_common.py`.

Logs are named after the stage and rewritten each run, so one Drive fileId per
stage holds forever. The aggregate `run_all.log` is rewritten at the start of a
full run and appended to per stage.

Enforces the design's §12: per-fold train-only fitting, 28-day embargo, frozen
M* and hyperparameters before opening blind folds B1-B2. A stage that fails
stops the run: the stages after it read its outputs, and running them against
stale or missing files would produce numbers that look valid and are not.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from _common import (
    LOG_SUMMARY,
    OUTPUTS,
    atomic_write_json,
    progress,
    rel_path,
    run_all_log_path,
    run_stage,
    write_logs_manifest,
)

BASE = Path(__file__).resolve().parents[1]


def discover_stages() -> list[str]:
    return [p.stem for p in sorted((BASE / "experiments").glob("[0-9][0-9]_*.py"))]


def resolve_stages(available: list[str], tokens: list[str]) -> tuple[list[str], str]:
    """Map CLI tokens to stage names, accepting an unambiguous numeric prefix.

    `--only 03` is what anyone types, but `03` alone is not a name, and with a
    multi-station layout the numbering stops being contiguous. Full names stay
    canonical; a prefix only works when exactly one stage carries it, so `03`
    and a future `03b` cannot silently resolve to the wrong stage.
    """
    resolved: list[str] = []
    for tok in tokens:
        if tok in available:
            resolved.append(tok)
            continue
        matches = [s for s in available if s.startswith(tok)]
        if len(matches) == 1:
            resolved.append(matches[0])
        elif not matches:
            return [], f"unknown stage: {tok}"
        else:
            return [], (f"ambiguous stage prefix {tok!r}: matches "
                        f"{', '.join(matches)}; use the full name")
    return resolved, ""


def select_range(available: list[str], first: str, last: str) -> tuple[list[str], str]:
    """Inclusive range over the ordered stage list, by prefix or full name."""
    start, err = resolve_stages(available, [first])
    if err:
        return [], err
    stop, err = resolve_stages(available, [last])
    if err:
        return [], err
    i, j = available.index(start[0]), available.index(stop[0])
    if i > j:
        return [], f"--from {start[0]} comes after --to {stop[0]}"
    return available[i:j + 1], ""


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=BASE, capture_output=True,
                           text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _installed_versions() -> dict[str, str]:
    """The versions that actually imported, not the ones the requirements declare.

    A pin in requirements-experiments.txt is a range and Colab's image moves
    under it. Recording what ran is the only version fact that stays true.
    """
    out: dict[str, str] = {}
    for mod in ("pandas", "numpy", "yaml", "sklearn", "lightgbm"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "unknown")
        except Exception:  # noqa: BLE001 - an absent dep is a fact, not an error
            out[mod] = "not installed"
    return out


def write_run_meta(stages: list[str], config: Path | None, entries: dict[str, dict]) -> Path:
    """Write outputs/run_meta.json: what ran, from what, under which versions.

    Fixed name on purpose. The Drive contract requires stable filenames so one
    Drive id per file holds forever, and a timestamped name would mint a new
    Drive file - and a new Colab url - on every run. When run_id directories
    arrive, this file moves to `_runs/<run_id>/run_meta.json` unchanged.
    """
    payload = {
        "finished_at": _now_iso(),
        "stages_run": stages,
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "config": rel_path(config) if config else "experiments/config.yaml",
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "experiments")),
        "versions": _installed_versions(),
        "results": {
            s: {"exit_code": i["exit_code"], "elapsed_s": round(float(i["elapsed_s"]), 2)}
            for s, i in entries.items()
        },
        "note": "Fixed filename by design: a timestamped name would mint a new "
                "Drive file per run, and a new Drive file means a new Colab url.",
    }
    return atomic_write_json(payload, OUTPUTS / "run_meta.json")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the c20-2026 pipeline stages.")
    ap.add_argument("--only", nargs="*", metavar="STAGE",
                    help="run only these; a numeric prefix works when unique "
                         "(e.g. --only 03 05)")
    ap.add_argument("--from", dest="from_", metavar="STAGE",
                    help="run from this stage onward (inclusive)")
    ap.add_argument("--to", dest="to", metavar="STAGE",
                    help="run up to this stage (inclusive)")
    ap.add_argument("--config", metavar="PATH", default=None,
                    help="config.yaml to use; exported to the stages as "
                         "EXP_CONFIG so a subprocess inherits it")
    ap.add_argument("--keep-going", dest="stop_on_error", action="store_false",
                    help="run every stage even after one fails; exit non-zero at the end")
    ap.set_defaults(stop_on_error=True)
    args = ap.parse_args()

    if args.only and (args.from_ or args.to):
        ap.error("pick either --only, or the --from/--to range")

    available = discover_stages()
    if not available:
        print("ERROR: no stages found", file=sys.stderr)
        return 2

    if args.only:
        stages, err = resolve_stages(available, args.only)
    elif args.from_ or args.to:
        stages, err = select_range(
            available, args.from_ or available[0], args.to or available[-1]
        )
    else:
        stages, err = list(available), ""
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        print(f"available: {', '.join(available)}", file=sys.stderr)
        return 2

    config = Path(args.config).resolve() if args.config else None
    if args.config and not config.is_file():
        print(f"ERROR: --config not found: {args.config}", file=sys.stderr)
        return 2
    # A subprocess inherits the environment but not the parent's argv, so this
    # is how `--config` actually reaches the stages.
    if args.config:
        os.environ["EXP_CONFIG"] = str(config)

    aggregate = run_all_log_path()
    if args.only or args.from_ or args.to:
        # A partial run appends to whatever the aggregate already holds.
        aggregate.touch()
    else:
        # A full run rewrites it, so it describes this run only.
        aggregate.write_text("", encoding="utf-8")

    print(f"running {len(stages)} stage(s): {stages[0]} -> {stages[-1]}")
    entries: dict[str, dict] = {}
    failed: list[tuple[str, int]] = []

    for stage in progress(stages, desc="pipeline", unit="stage", level="stage"):
        info = run_stage(stage, aggregate=aggregate)
        entries[stage] = info
        if info["exit_code"] != 0:
            failed.append((stage, info["exit_code"]))
            print(f"[{stage}] FAILED with exit {info['exit_code']}; see {info['log']}",
                  file=sys.stderr)
            if args.stop_on_error:
                break

    write_logs_manifest(entries)
    meta = write_run_meta(stages, config, entries)

    print("\n" + "=" * 58)
    print(f"{'stage':<26}{'exit':>6}{'elapsed_s':>11}")
    print("-" * 58)
    for stage, info in entries.items():
        print(f"{stage:<26}{info['exit_code']:>6}{info['elapsed_s']:>11.2f}")
    print("=" * 58)
    print(f"logs  : {aggregate}")
    print(f"index : {OUTPUTS / 'manifest_index.json'}")
    print(f"meta  : {meta}")

    if failed:
        print(f"\n{LOG_SUMMARY} {len(failed)} stage(s) failed: "
              f"{', '.join(f'{s}({c})' for s, c in failed)}", file=sys.stderr)
        return failed[0][1] or 1
    print(f"\n{LOG_SUMMARY} all {len(entries)} stage(s) ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
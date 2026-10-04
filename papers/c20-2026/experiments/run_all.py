# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
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

Resume and error reporting come from the shared `_colab_runtime` (COLAB.md at
the repo root): a stage whose code, config and upstream are unchanged since it
last succeeded is skipped, every failure is appended to `outputs/logs/errors.log`,
and `outputs/logs/status.json` records what each stage did.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from _common import (
    DATA_DIR,
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


def _load_runtime():
    """The shared runtime: next to this file on Colab, in the repo's scripts/ locally."""
    try:
        import _colab_runtime
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
        import _colab_runtime
    return _colab_runtime


rt = _load_runtime()


# Stages that need torch (and a GPU to be practical); `--skip-dl` drops them.
DL_STAGES = ("07b_deep",)


def discover_stages() -> list[str]:
    """`NN_name.py` and lettered sub-stages `NNx_name.py`, in run order.

    Sorting is by filename, and `_` sorts before any letter, so `07_models`
    runs before `07b_deep`, which runs before `07c_ensemble`.
    """
    return [p.stem for p in sorted((BASE / "experiments").glob("[0-9][0-9]*_*.py"))
            if p.stem[:2].isdigit() and (p.stem[2] == "_" or p.stem[2].isalpha())]


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


def _spec() -> dict:
    """colab.yaml next to the stages, or the runtime's defaults when absent."""
    exp = BASE / "experiments"
    if (exp / rt.SPEC_NAME).is_file():
        return rt.load_spec(exp)
    return rt.load_spec_defaults()


def _resolve_input(path: str) -> Path:
    """`data/...` and `outputs/...` follow DATA_DIR/OUTPUT_DIR, as the stages do."""
    parts = Path(path).parts
    if parts and parts[0] == "data":
        return DATA_DIR.joinpath(*parts[1:])
    if parts and parts[0] == "outputs":
        return OUTPUTS.joinpath(*parts[1:])
    return BASE / path


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

    `code_hashes` maps each experiments/*.py plus config.yaml to its sha256,
    with CRLF normalized to LF so a Windows edit and its Colab copy hash
    equal. On Colab there may be no git checkout, so `git_commit` can be None:
    traceability then rests on `code_hashes`. `splits` is copied from
    manifest_index.json (written where the splits are created, in
    04_make_issuances.py), not reconstructed here.
    """
    payload = {
        "finished_at": _now_iso(),
        "stages_run": stages,
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "config": rel_path(config) if config else "experiments/config.yaml",
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "experiments")),
        "code_hashes": _code_hashes(),
        "splits": _splits_from_manifest(),
        "versions": _installed_versions(),
        "results": {
            s: {"exit_code": i["exit_code"], "elapsed_s": round(float(i["elapsed_s"]), 2)}
            for s, i in entries.items()
        },
        "note": "Fixed filename by design: a timestamped name would mint a new "
                "Drive file per run, and a new Drive file means a new Colab url.",
    }
    return atomic_write_json(payload, OUTPUTS / "run_meta.json")


def _normalized_hash(path: Path) -> str:
    """sha256 of a text file with CRLF normalized to LF."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _code_hashes() -> dict[str, str]:
    """sha256 per experiments/*.py plus config.yaml, keyed by paper-relative path."""
    exp = BASE / "experiments"
    out: dict[str, str] = {}
    if exp.is_dir():
        for p in sorted(exp.glob("*.py")):
            if p.is_file():
                out[rel_path(p)] = _normalized_hash(p)
    cfg = BASE / "experiments" / "config.yaml"
    if cfg.is_file():
        out[rel_path(cfg)] = _normalized_hash(cfg)
    return out


def _splits_from_manifest() -> dict:
    """Split bounds as recorded where the splits were created (04), if present."""
    import json as _json

    idx = OUTPUTS / "manifest_index.json"
    if not idx.is_file():
        return {}
    try:
        data = _json.loads(idx.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    splits = data.get("splits") if isinstance(data, dict) else None
    return dict(splits) if isinstance(splits, dict) else {}


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
    ap.add_argument("--mode", choices=("full", "smoke"), default="full",
                    help="smoke = tiny model budgets (EXP_FAST=1), numbers not citable")
    ap.add_argument("--fast", action="store_true",
                    help="alias of --mode smoke")
    ap.add_argument("--force", action="store_true",
                    help="re-run every selected stage even if its state says it is current")
    ap.add_argument("--skip-dl", action="store_true",
                    help=f"skip the deep-learning stages ({', '.join(DL_STAGES)})")
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

    if args.skip_dl:
        stages = [s for s in stages if s not in DL_STAGES]
    mode = "smoke" if args.fast else args.mode
    if mode == "smoke":
        # Exported, like EXP_CONFIG, because the stages are subprocesses.
        os.environ["EXP_FAST"] = "1"

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

    log = rt.RunLog(OUTPUTS / "logs")
    if not log.in_session():
        log.begin_session(mode=mode, note="run_all outside a notebook", export=False)
    spec = _spec()
    state = rt.StageState(OUTPUTS / rt.STATE_DIR, BASE / "experiments", mode,
                          shared=spec["shared_modules"],
                          inputs=[_resolve_input(p) for p in spec["state_inputs"]],
                          results_version_all=spec.get("results_version", 0))
    fingerprints = state.fingerprints(available, mode_from=spec.get("smoke_from"))
    # Same writer as every other paper: outputs/timings.{json,md}, updated after
    # each stage. The stages record their own units through it, hence the env.
    os.environ[rt.TIMINGS_ENV] = "1"
    timings = rt.Timings.for_outputs(OUTPUTS, code_dir=BASE / "experiments", mode=mode)
    timings.begin_run(stages)
    timings.sync_fingerprints({s: (fingerprints[s], state.code_sha(s)) for s in available})
    # --only names stages the user wants run now, so they never skip.
    force = args.force or bool(args.only)
    log.update_status(state=rt.RUNNING, mode=mode,
                      stages={s: rt.NOT_RUN for s in stages})

    print(f"running {len(stages)} stage(s): {stages[0]} -> {stages[-1]} "
          f"(mode={mode}{', force' if force else ''})")
    entries: dict[str, dict] = {}
    skipped: list[str] = []
    failed: list[tuple[str, int]] = []

    for stage in progress(stages, desc="pipeline", unit="stage", level="stage"):
        if not force and state.is_current(stage, fingerprints[stage]):
            note = state.drift(stage)
            print(f"[{stage}] skipped: done in an earlier {mode} run"
                  + (f" ({note}; results kept, see COLAB.md)" if note else ""))
            skipped.append(stage)
            log.update_status(stages={stage: rt.SKIPPED})
            continue
        log.update_status(stages={stage: rt.RUNNING})
        if force:
            rt.clear_checkpoints(OUTPUTS, stage)
        # The stage's key reaches it through the environment, so its unit
        # checkpoints (rt.Checkpoints) belong to this exact configuration.
        os.environ[rt.STAGE_KEY_ENV] = fingerprints[stage]
        timings.begin_stage(stage)
        info = run_stage(stage, aggregate=aggregate)
        entries[stage] = info
        timings.record_stage(stage, info["elapsed_s"],
                             rt.OK if info["exit_code"] == 0 else rt.FAILED,
                             key=fingerprints[stage], code_sha=state.code_sha(stage))
        if info["exit_code"] != 0:
            failed.append((stage, info["exit_code"]))
            state.invalidate_from(stage, available)
            log.record_error(f"stage {stage}",
                             f"exit {info['exit_code']} after {info['elapsed_s']:.1f}s "
                             f"(full log: {rel_path(Path(info['log']))})",
                             rt.tail(info["log"]))
            log.update_status(stages={stage: rt.FAILED}, failed_stage=stage)
            print(f"[{stage}] FAILED with exit {info['exit_code']}; see {info['log']}",
                  file=sys.stderr)
            if args.stop_on_error:
                break
        else:
            state.mark_done(stage, fingerprints[stage], info["elapsed_s"])
            rt.clear_checkpoints(OUTPUTS, stage)
            log.update_status(stages={stage: rt.OK})
    log.update_status(state=rt.FAILED if failed else rt.OK, finished=rt._now())

    write_logs_manifest(entries)
    meta = write_run_meta(stages, config, entries)

    print("\n" + "=" * 58)
    print(f"{'stage':<26}{'exit':>6}{'elapsed_s':>11}")
    print("-" * 58)
    for stage, info in entries.items():
        print(f"{stage:<26}{info['exit_code']:>6}{info['elapsed_s']:>11.2f}")
    for stage in skipped:
        print(f"{stage:<26}{'skip':>6}{'':>11}")
    print("=" * 58)
    print(f"errors: {log.errors}")
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
"""_colab_runtime.py: the shared Colab runtime every paper's notebook uses.

One implementation, uploaded by `paper_drive_sync.py` to
`Drive/<folder>/code/_colab_runtime.py`, so no paper carries a copy that can
drift. The rules it implements are in COLAB.md at the repo root; read that
first. In short:

- `outputs/logs/errors.log` is the one place to look after a run. It is
  truncated when a session starts, and every failure of that session is appended
  to it: preflight checks, pipeline stages, and exceptions raised by notebook
  cells. An empty file means the last session had no errors.
- `outputs/logs/status.json` says what the last session did, so "never ran" and
  "ran clean" are not the same empty file.
- `outputs/_state/<stage>.json` lets a pipeline skip a stage whose code, config
  and upstream are unchanged since it last succeeded. "Run all" after a crash
  resumes instead of redoing hours of work.
- Progress is rendered as plain text, one line per phase. A widget bar is saved
  in the notebook at 0 %, so a notebook read back from Drive would not show what
  ran; a text line does.

Stdlib only, except `yaml` for the spec, which every pipeline here already
depends on.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ERRORS_LOG = "errors.log"
STATUS_JSON = "status.json"
STATE_DIR = "_state"
SPEC_NAME = "colab.yaml"
SESSION_ENV = "COLAB_SESSION_ID"
PROG_PREFIX = "#PROG "
TAIL_LINES = 80
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Status values a stage can carry in status.json.
OK, SKIPPED, FAILED, NOT_RUN, RUNNING = "ok", "skipped", "failed", "not_run", "running"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a sibling temp file, so a disconnect never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class RecordedError(RuntimeError):
    """An error already written to errors.log; the cell hook must not log it twice."""

    _recorded = True


# --- the spec ------------------------------------------------------------------

def load_spec(code_dir: str | Path) -> dict:
    """Read `colab.yaml` next to the pipeline code. Missing keys get defaults."""
    import yaml  # local: a pipeline dependency, not stdlib

    path = Path(code_dir) / SPEC_NAME
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping")
    data.setdefault("gpu", "none")
    data.setdefault("pip", [])
    data.setdefault("setup", [])
    data.setdefault("probes", [])
    data.setdefault("run", ["run_all.py"])
    data.setdefault("report", [])
    data.setdefault("state_inputs", [])
    data.setdefault("shared_modules", ["_*.py", "config.yaml"])
    data.setdefault("smoke_from", None)
    return data


# --- errors.log and status.json --------------------------------------------------

class RunLog:
    """errors.log + status.json under `logs_dir`.

    Several processes write here in one session (the notebook kernel, run_all,
    each stage), so every write is a short open-append-close or an atomic
    replace, and status.json is re-read before it is updated.
    """

    def __init__(self, logs_dir: str | Path) -> None:
        self.dir = Path(logs_dir)
        self.errors = self.dir / ERRORS_LOG
        self.status_path = self.dir / STATUS_JSON

    # session -------------------------------------------------------------
    def begin_session(self, mode: str = "", note: str = "", export: bool = True) -> str:
        """Start a session: empty errors.log, fresh status.json, export the id.

        The notebook exports the id so the pipeline it launches appends to this
        session instead of starting its own. A pipeline run outside a notebook
        starts a session without exporting it.
        """
        session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.errors.write_text("", encoding="utf-8")
        self.write_status({
            "session": session, "mode": mode, "state": "setup",
            "started": _now(), "finished": None, "failed_stage": None,
            "stages": {}, "note": note,
        })
        if export:
            os.environ[SESSION_ENV] = session
        return session

    def in_session(self) -> bool:
        return bool(os.environ.get(SESSION_ENV))

    # errors --------------------------------------------------------------
    def record_error(self, source: str, title: str, body: str = "") -> None:
        """Append one error block. Never raises: logging must not hide the error."""
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            block = [
                "=" * 78,
                f"[{_now()}] {source}: {title}",
                "-" * 78,
                _ANSI.sub("", body).rstrip(),
                "",
            ]
            with self.errors.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(block) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def error_text(self) -> str:
        return self.errors.read_text(encoding="utf-8") if self.errors.is_file() else ""

    def has_errors(self) -> bool:
        return bool(self.error_text().strip())

    # status --------------------------------------------------------------
    def read_status(self) -> dict:
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def write_status(self, payload: dict) -> None:
        _atomic_write(self.status_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    def update_status(self, **fields) -> dict:
        data = self.read_status()
        stages = fields.pop("stages", None)
        data.update(fields)
        if stages:
            data.setdefault("stages", {}).update(stages)
        self.write_status(data)
        return data


def tail(path: str | Path, n: int = TAIL_LINES) -> str:
    """Last `n` lines of a text file; a traceback lives at the end of a stage log."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])


# --- notebook cell errors --------------------------------------------------------

def install_cell_error_hook(log: RunLog) -> bool:
    """Append every exception a notebook cell raises to errors.log.

    Without this, an error in a cell (not in a stage) exists only in the cell
    output, which is gone once the runtime recycles. Returns False outside
    IPython, where there is nothing to hook.
    """
    try:
        from IPython import get_ipython  # type: ignore
    except ImportError:
        return False
    ip = get_ipython()
    if ip is None:
        return False

    def _handler(shell, etype, evalue, tb, tb_offset=None):
        if not getattr(evalue, "_recorded", False):
            text = "".join(traceback.format_exception(etype, evalue, tb))
            log.record_error("notebook cell", f"{etype.__name__}: {evalue}", text)
            log.update_status(state="failed", finished=_now())
        shell.showtraceback((etype, evalue, tb), tb_offset=tb_offset)

    ip.set_custom_exc((Exception,), _handler)
    return True


# --- running commands with text progress -----------------------------------------

def _parse_prog(line: str) -> dict | None:
    text = line.strip()
    if not text.startswith(PROG_PREFIX):
        return None
    try:
        data = json.loads(text[len(PROG_PREFIX):])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _marker(event: dict, state: dict) -> str | None:
    """A text line on phase change or completion; None for intermediate ticks."""
    level, desc = event.get("level", ""), event.get("desc", "")
    n, total = event.get("n"), event.get("total")
    prev = state.get(level)
    done = total is not None and n is not None and n >= total
    if prev != desc or done:
        state[level] = desc if not done else None
        return f"  .. {desc or level}: {n}/{total if total is not None else '?'}"
    return None


def run_command(argv: list[str], cwd: str | Path | None = None,
                env: dict | None = None, log_path: str | Path | None = None) -> tuple[int, str]:
    """Run a command, printing its output with `#PROG` events as text lines.

    Returns (exit code, last lines of output) so a caller can put the tail,
    which holds the traceback, into errors.log. With `log_path`, everything
    printed is also appended to that file.
    """
    sink = open(log_path, "a", encoding="utf-8") if log_path else None  # noqa: SIM115
    try:
        return _run_command(argv, cwd, env, sink)
    finally:
        if sink is not None:
            sink.close()


def _run_command(argv, cwd, env, sink) -> tuple[int, str]:
    def emit(text: str) -> None:
        print(text, end="", flush=True)
        if sink is not None:
            sink.write(_ANSI.sub("", text))
            sink.flush()

    child_env = dict(os.environ if env is None else env)
    child_env["EXP_PROGRESS_PARENT"] = "1"
    child_env.setdefault("PYTHONUNBUFFERED", "1")
    child_env["PYTHON_COLORS"] = "0"  # colour codes would end up in errors.log
    proc = subprocess.Popen(
        [sys.executable, *argv] if argv and argv[0].endswith(".py") else list(argv),
        cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=child_env,
    )
    keep: list[str] = []
    state: dict = {}
    assert proc.stdout is not None
    for line in proc.stdout:
        event = _parse_prog(line)
        if event is not None:
            mark = _marker(event, state)
            if mark:
                emit(mark + "\n")
            continue
        emit(line)
        keep.append(_ANSI.sub("", line.rstrip("\n")))
        if len(keep) > TAIL_LINES:
            del keep[0]
    proc.wait()
    return proc.returncode, "\n".join(keep)


# --- preflight -------------------------------------------------------------------

def gpu_available() -> bool:
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and "GPU" in r.stdout:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def _fail(log: RunLog, source: str, title: str, body: str = "") -> None:
    log.record_error(source, title, body)
    log.update_status(state="failed", failed_stage=source, finished=_now())
    raise RecordedError(f"{source}: {title} (written to {log.errors})")


def preflight(spec: dict, code_dir: str | Path, log: RunLog,
              marker: str = "/content/.deps_installed") -> None:
    """Hard checks before the pipeline: GPU, dependencies, setup commands, probes.

    Every failure stops the notebook here, in seconds, instead of after the long
    stages have run. Nothing is a warning.
    """
    gpu = str(spec.get("gpu", "none")).lower()
    if gpu == "required" and not gpu_available():
        _fail(log, "preflight", "no GPU in this runtime",
              "This pipeline needs a GPU.\n"
              "Runtime -> Change runtime type -> Hardware accelerator: T4 GPU -> Save,\n"
              "then Runtime -> Run all again.")
    print(f"[ok] GPU: {'yes' if gpu_available() else 'no'} (spec: {gpu})")

    pkgs = list(spec.get("pip") or [])
    if pkgs and not os.path.exists(marker):
        print(f"[..] installing {len(pkgs)} package(s)")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *pkgs],
                           capture_output=True, text=True, cwd=str(code_dir))
        if r.returncode != 0:
            _fail(log, "preflight", f"pip install failed (exit {r.returncode})",
                  (r.stdout + r.stderr)[-6000:])
        Path(marker).write_text("installed\n", encoding="utf-8")
        print("[ok] dependencies installed")
    elif pkgs:
        print("[ok] dependencies already installed in this runtime")

    for kind in ("setup", "probes"):
        for argv in spec.get(kind) or []:
            argv = [argv] if isinstance(argv, str) else list(argv)
            print(f"[..] {kind}: {' '.join(argv)}")
            code, out = run_command(argv, cwd=code_dir)
            if code != 0:
                _fail(log, f"preflight/{kind}", f"{' '.join(argv)} exited {code}", out)
            print(f"[ok] {kind}: {' '.join(argv)}")
    log.update_status(state="ready")


# --- resume ------------------------------------------------------------------------

def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class StageState:
    """Per-stage fingerprints that let a pipeline skip unchanged, finished stages.

    A fingerprint hashes the stage file, the shared modules and config, the
    declared input files, the previous stage's fingerprint and, from the first
    stage whose work depends on it (`mode_from`), the run mode. Chaining means a
    change anywhere upstream re-runs everything after it, and stages before
    `mode_from` are shared by smoke and full runs. A stage's state file is
    written only when it succeeds and removed (with all downstream ones) when it
    fails, so a skip always points at real outputs.
    """

    def __init__(self, state_dir: str | Path, code_dir: str | Path, mode: str,
                 shared: list[str] | None = None, inputs: list[str | Path] | None = None,
                 stage_file=None) -> None:
        self.dir = Path(state_dir)
        self.code = Path(code_dir)
        self.mode = mode
        files: list[Path] = []
        for pattern in shared or []:
            files.extend(sorted(self.code.glob(pattern)))
        self.shared = [p for p in dict.fromkeys(files) if p.is_file()]
        self.inputs = [Path(p) for p in inputs or []]
        self.stage_file = stage_file or (lambda s: self.code / f"{s}.py")

    def _base(self) -> str:
        h = hashlib.sha256(b"stage-state-v2")
        for p in self.shared:
            rel = p.relative_to(self.code).as_posix()
            h.update(f"{rel}:{_sha(p)}".encode())
        for p in self.inputs:
            h.update(f"{p.name}:{_sha(p) if p.is_file() else 'absent'}".encode())
        return h.hexdigest()

    def fingerprints(self, stages: list[str], mode_from: str | None = None) -> dict[str, str]:
        """Chained fingerprint of every stage, in order.

        The mode enters the chain at `mode_from` (or at the first stage when it
        is None or not a stage), so it reaches every stage after it.
        """
        start = mode_from if mode_from in stages else (stages[0] if stages else None)
        prev = self._base()
        out: dict[str, str] = {}
        for stage in stages:
            if stage == start:
                prev = hashlib.sha256(f"{prev}|mode={self.mode}".encode()).hexdigest()
            src = Path(self.stage_file(stage))
            own = _sha(src) if src.is_file() else "absent"
            prev = hashlib.sha256(f"{prev}|{stage}|{own}".encode()).hexdigest()
            out[stage] = prev
        return out

    def path(self, stage: str) -> Path:
        return self.dir / f"{stage}.json"

    def is_current(self, stage: str, fingerprint: str) -> bool:
        try:
            data = json.loads(self.path(stage).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return data.get("fingerprint") == fingerprint

    def mark_done(self, stage: str, fingerprint: str, elapsed_s: float) -> None:
        _atomic_write(self.path(stage), json.dumps({
            "stage": stage, "fingerprint": fingerprint, "mode": self.mode,
            "elapsed_s": round(float(elapsed_s), 2), "finished": _now(),
        }, indent=2) + "\n")

    def invalidate_from(self, stage: str, stages: list[str]) -> None:
        """Drop the state of `stage` and of everything after it."""
        if stage not in stages:
            return
        for s in stages[stages.index(stage):]:
            try:
                self.path(s).unlink()
            except FileNotFoundError:
                pass


# --- the notebook's entry points -----------------------------------------------------

def run_pipeline(spec: dict, code_dir: str | Path, log: RunLog, mode: str = "full",
                 force: bool = False, only: list[str] | None = None,
                 extra: list[str] | None = None) -> int:
    """The single call the notebook's run cell makes. Never raises on a stage failure.

    The run cell must not stop "Run all", so the report cell after it still
    shows errors.log. That cell is the one that raises.
    """
    argv = list(spec.get("run") or ["run_all.py"]) + ["--mode", mode]
    if force:
        argv.append("--force")
    if only:
        argv += ["--only", *only]
    argv += list(extra or [])
    print(f"[..] {' '.join(argv)}")
    log.update_status(state=RUNNING, mode=mode)
    started = time.perf_counter()
    code, out = run_command(argv, cwd=code_dir)
    status = log.read_status()
    if code != 0 and not log.has_errors():
        # run_all itself died (bad argument, import error) before any stage did.
        log.record_error("pipeline", f"{' '.join(argv)} exited {code}", out)
    log.update_status(state=OK if code == 0 else FAILED, finished=_now(),
                      failed_stage=status.get("failed_stage"))
    print(f"\n[{'ok' if code == 0 else 'FAILED'}] pipeline exit={code} "
          f"in {time.perf_counter() - started:.0f}s")
    if code != 0:
        print(f"errors: {log.errors}")
    return code


def run_report(spec: dict, code_dir: str | Path, log: RunLog) -> int:
    """Run the paper's report command; a crash in it goes to errors.log too."""
    argv = list(spec.get("report") or [])
    if not argv:
        return 0
    code, out = run_command(argv, cwd=code_dir)
    if code != 0:
        log.record_error("report", f"{' '.join(argv)} exited {code}", out)
    return code


def raise_if_errors(log: RunLog) -> None:
    """Print errors.log and stop; the last cell calls this so failures are loud."""
    text = log.error_text()
    if text.strip():
        print(text)
        raise RecordedError(f"this session has errors; full text in {log.errors}")
    print(f"[ok] no errors in this session ({log.errors} is empty)")


# --- a generic pipeline runner ---------------------------------------------------------

def discover_stages(code_dir: str | Path) -> list[str]:
    """`NN_name.py` and lettered sub-stages `NNx_name.py`, in filename order."""
    return [p.stem for p in sorted(Path(code_dir).glob("[0-9][0-9]*_*.py"))
            if p.stem[:2].isdigit() and (p.stem[2] == "_" or p.stem[2].isalpha())]


def resolve_stages(available: list[str], tokens: list[str]) -> tuple[list[str], str]:
    """Map names or unambiguous prefixes (`03`) to stage names."""
    out: list[str] = []
    for tok in tokens:
        if tok in available:
            out.append(tok)
            continue
        hits = [s for s in available if s.startswith(tok)]
        if len(hits) != 1:
            return [], (f"unknown stage: {tok}" if not hits else
                        f"ambiguous stage prefix {tok!r}: {', '.join(hits)}")
        out.append(hits[0])
    return out, ""


def _resolve_input(path: str, outputs: Path) -> Path:
    parts = Path(path).parts
    data = Path(os.environ.get("DATA_DIR") or outputs.parent / "data")
    if parts and parts[0] == "data":
        return data.joinpath(*parts[1:])
    if parts and parts[0] == "outputs":
        return outputs.joinpath(*parts[1:])
    return outputs.parent / path


def stages_main(code_dir: str | Path, stages: list[str] | None = None, command=None,
                stage_file=None, argv: list[str] | None = None) -> int:
    """A complete `run_all.py` that follows the pipeline contract (COLAB.md §7).

    `stages` defaults to the `NN_*.py` files in `code_dir`; `command(stage, force)`
    returns the argv of one stage (default: the stage file); `stage_file(stage)`
    is the file whose hash identifies the stage (default: `<stage>.py`). Each
    stage runs as a subprocess with its own log in `outputs/logs/<stage>.log`.
    """
    import argparse

    code = Path(code_dir)
    ap = argparse.ArgumentParser(description="Run the pipeline stages in order.")
    ap.add_argument("--mode", choices=("full", "smoke"), default="full")
    ap.add_argument("--fast", action="store_true", help="alias of --mode smoke")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*", metavar="STAGE")
    ap.add_argument("--from", dest="from_", metavar="STAGE")
    ap.add_argument("--to", dest="to", metavar="STAGE")
    ap.add_argument("--keep-going", dest="stop_on_error", action="store_false")
    args = ap.parse_args(argv)
    if args.only and (args.from_ or args.to):
        ap.error("pick either --only, or the --from/--to range")

    available = list(stages) if stages is not None else discover_stages(code)
    if args.only:
        selected, err = resolve_stages(available, args.only)
    elif args.from_ or args.to:
        bounds, err = resolve_stages(available, [args.from_ or available[0],
                                                 args.to or available[-1]])
        selected = (available[available.index(bounds[0]):available.index(bounds[1]) + 1]
                    if not err else [])
    else:
        selected, err = list(available), ""
    if err:
        print(f"ERROR: {err}\navailable: {', '.join(available)}", file=sys.stderr)
        return 2
    if not selected:
        print("no stages to run")
        return 0

    mode = "smoke" if args.fast else args.mode
    if mode == "smoke":
        os.environ["EXP_FAST"] = "1"
    outputs = Path(os.environ.get("OUTPUT_DIR") or code.parent / "outputs")
    spec = load_spec(code) if (code / SPEC_NAME).is_file() else load_spec_defaults()
    log = RunLog(outputs / "logs")
    if not log.in_session():
        log.begin_session(mode=mode, note="run_all outside a notebook", export=False)
    state = StageState(outputs / STATE_DIR, code, mode, shared=spec["shared_modules"],
                       inputs=[_resolve_input(p, outputs) for p in spec["state_inputs"]],
                       stage_file=stage_file)
    prints = state.fingerprints(available, mode_from=spec.get("smoke_from"))
    force = args.force or bool(args.only)
    command = command or (lambda s, f: [f"{s}.py"])
    log.update_status(state=RUNNING, mode=mode, stages={s: NOT_RUN for s in selected})

    print(f"running {len(selected)} stage(s): {selected[0]} -> {selected[-1]} (mode={mode})")
    failed: list[str] = []
    for i, stage in enumerate(selected, 1):
        if os.environ.get("EXP_PROGRESS_PARENT") == "1":
            print(f"{PROG_PREFIX}" + json.dumps({"level": "stage", "n": i, "total": len(selected),
                                                 "desc": stage, "unit": "stage"}), flush=True)
        if not force and state.is_current(stage, prints[stage]):
            print(f"[{stage}] skipped: unchanged since its last successful {mode} run")
            log.update_status(stages={stage: SKIPPED})
            continue
        log.update_status(stages={stage: RUNNING})
        stage_log = outputs / "logs" / f"{stage}.log"
        stage_log.parent.mkdir(parents=True, exist_ok=True)
        stage_log.write_text(f"# STAGE-START {stage}\n# started : {_now()}\n", encoding="utf-8")
        started = time.perf_counter()
        rc, out = run_command(command(stage, force), cwd=code, log_path=stage_log)
        elapsed = time.perf_counter() - started
        with stage_log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n# STAGE-EXIT {stage} exit_code={rc} elapsed_s={elapsed:.2f}\n")
        print(f"[{stage}] exit={rc} elapsed={elapsed:.1f}s")
        if rc != 0:
            failed.append(stage)
            state.invalidate_from(stage, available)
            log.record_error(f"stage {stage}", f"exit {rc} after {elapsed:.1f}s "
                             f"(full log: outputs/logs/{stage}.log)", out)
            log.update_status(stages={stage: FAILED}, failed_stage=stage)
            if args.stop_on_error:
                break
        else:
            state.mark_done(stage, prints[stage], elapsed)
            log.update_status(stages={stage: OK})
    log.update_status(state=FAILED if failed else OK, finished=_now())
    print(f"\n{'FAILED: ' + ', '.join(failed) if failed else 'all stages ok'} | errors: {log.errors}")
    return 1 if failed else 0


def load_spec_defaults() -> dict:
    """The spec defaults, for a pipeline without a colab.yaml."""
    return {"shared_modules": ["_*.py", "config.yaml"], "state_inputs": [], "smoke_from": None}

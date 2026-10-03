# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Progress protocol: children emit, readers draw.

Why this exists
--------------
Every stage runs as a subprocess, and a pipe is not a TTY. tqdm redraws in
place with a bare `\\r`, which Colab's captured `%%bash`/subprocess output does
not honour as a carriage return, so each refresh lands as its own line. Tuning
`tqdm` arguments cannot fix that: the bytes are fine, the renderer is not.

So the child never draws. It emits machine-readable progress lines on stdout::

    #PROG {"level": "fold", "n": 3, "total": 5, "desc": "D2 W3_4", "unit": "fold"}

and whoever reads draws: the notebook cell with `tqdm.notebook` (fixed widgets),
a local terminal with `tqdm.std`, the log file with plain phase markers. One
protocol, three backends. `tqdm` is only a drawing library here, never the
source of truth.

Levels are `stage` (run_all over stages), `fold` (a stage over folds) and `step`
(sub-fold work such as a per-model fit loop). A reader keeps one widget per
level, reused across phases with a live `desc`, so many short bars become
one bar whose description says where it is.

Silencing
---------
`EXP_PROGRESS=off` disables the whole protocol: no events, no bars. Tests and CI
set it (or simply run without a TTY and without a parent, which is silent by
construction). `TQDM_*` stays as the fine aesthetic override below it; `EXP_*`
is the family this pipeline already uses (`EXP_ENV`, `EXP_CONFIG`).

Throttling
----------
`05` iterates over thousands of rows. Emitting per iteration would drown the
pipe, so the emitter throttles like `tqdm`'s `mininterval`: first event, phase
changes (`desc` differs) and the final event always go through; the rest go
through at most every `mininterval_s` seconds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROG_PREFIX = "#PROG "
OFF_VALUES = {"off", "0", "false", "no", "disabled", "none"}
PARENT_FLAG = "EXP_PROGRESS_PARENT"
LEVEL_ORDER = {"stage": 0, "fold": 1, "step": 2}

# Last emission per level: level -> (monotonic time, desc). Module state so the
# throttle survives across calls within one process; reset in tests.
_last_emit: dict[str, tuple[float, str]] = {}
_cfg_cache: dict | None = None


def reset_state() -> None:
    """Clear throttle state and the cached progress config. Tests only."""
    global _cfg_cache
    _last_emit.clear()
    _cfg_cache = None


def is_enabled() -> bool:
    """False when the protocol is switched off; nothing emits, nothing draws."""
    return os.environ.get("EXP_PROGRESS", "").strip().lower() not in OFF_VALUES


def parent_present() -> bool:
    """True when a rendering parent spawned this process and parses our events."""
    return os.environ.get(PARENT_FLAG) == "1"


def _progress_config() -> dict:
    """The `progress:` block of the active config, or {} when unreadable.

    Read straight from the file so this module never imports `_common`
    (which imports this module). A broken config must not take progress down,
    so every failure degrades to defaults.
    """
    global _cfg_cache
    if _cfg_cache is not None:
        return _cfg_cache
    _cfg_cache = {}
    try:
        base = Path(__file__).resolve().parents[1]
        cfg_path = Path(os.environ.get("EXP_CONFIG") or base / "experiments" / "config.yaml")
        if cfg_path.is_file():
            import yaml  # local: yaml is a pipeline dep, not a stdlib guarantee

            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            block = data.get("progress") or {}
            if isinstance(block, dict):
                _cfg_cache = block
    except Exception:  # noqa: BLE001 - progress must never break a stage
        _cfg_cache = {}
    return _cfg_cache


def mininterval_s() -> float:
    """Slowest of env override, config, default. Never negative."""
    for var in ("EXP_PROGRESS_MININTERVAL", "TQDM_MININTERVAL"):
        raw = os.environ.get(var)
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
    try:
        return max(0.0, float(_progress_config().get("mininterval_s", 0.1)))
    except (TypeError, ValueError):
        return 0.1


def level_shown(level: str) -> bool:
    """Whether `config.progress` wants a bar for this level. Markers still log."""
    key = {"stage": "show_stage_bar", "fold": "show_fold_bar",
           "step": "show_step_bar"}.get(level)
    if key is None:
        return True
    return bool(_progress_config().get(key, True))


def emit(level: str, n: int, total: int | None, desc: str = "",
         unit: str = "it", mininterval: float | None = None,
         force: bool = False) -> bool:
    """Print one `#PROG` event line. Returns True when it went through.

    First event, `desc` changes and the final event always pass; the rest are
    throttled to `mininterval` seconds, like `tqdm` itself. Callers emit per
    iteration without worrying about flooding the pipe.
    """
    if not is_enabled():
        return False
    interval = mininterval if mininterval is not None else mininterval_s()
    now = time.monotonic()
    prev = _last_emit.get(level)
    final = total is not None and n >= total
    first = n <= 1
    changed = prev is None or prev[1] != desc
    if not (force or first or final or changed):
        if prev is not None and now - prev[0] < interval:
            return False
    _last_emit[level] = (now, desc)
    payload = {"level": level, "n": int(n),
               "total": None if total is None else int(total),
               "desc": desc, "unit": unit}
    print(f"{PROG_PREFIX}{json.dumps(payload, ensure_ascii=False)}", flush=True)
    return True


def parse_line(line: str) -> dict | None:
    """Parse one output line into a progress event, or None when it is not one.

    Never raises: a stage printing something that *looks like* a prefix but is
    not JSON must not take the reader down.
    """
    text = line.strip()
    if not text.startswith(PROG_PREFIX):
        return None
    try:
        data = json.loads(text[len(PROG_PREFIX):])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("n"), int) or not isinstance(data.get("level"), str):
        return None
    total = data.get("total")
    if total is not None and not isinstance(total, int):
        return None
    data.setdefault("desc", "")
    data.setdefault("unit", "it")
    return data


def format_marker(event: dict) -> str:
    """One plain-text progress line for logs and non-bar consoles.

    Logs are read to diagnose, and there what matters is which phase was
    running, not a redrawn bar. The marker carries the same numbers the bar
    would show.
    """
    desc = event.get("desc") or event.get("level", "")
    return f"# progress {desc}: {event.get('n')}/{event.get('total')}"


def is_phase_change(event: dict, state: dict) -> bool:
    """True on first sight of a level, on `desc` change, and on completion.

    `state` maps level -> (desc, n) and is owned by the caller, so the log and
    the console can track phases independently.
    """
    level = event.get("level", "")
    desc = event.get("desc", "")
    prev = state.get(level)
    if prev is None or prev[0] != desc:
        state[level] = (desc, event.get("n"))
        return True
    n, total = event.get("n"), event.get("total")
    if total is not None and n is not None and n >= total:
        state[level] = (desc, n)
        return True
    return False


def iter_progress(iterable, level: str = "fold", desc: str = "",
                  unit: str = "it", total: int | None = None,
                  mininterval: float | None = None):
    """Yield items, emitting progress events when someone listens.

    Three cases, and only the first two do anything visible:

    - a rendering parent spawned us (`EXP_PROGRESS_PARENT=1`): emit throttled
      `#PROG` events on stdout. Never draw locally: the parent owns the bars,
      and a local bar would fight it for the same stderr.
    - no parent but an interactive stderr: draw a local `tqdm.std` bar. This is
      `python 03_climatology.py` in a terminal. Nothing is emitted, because
      nobody parses stdout here and the JSON would be noise.
    - otherwise (piped, CI, tests): yield silently.

    `EXP_PROGRESS=off` forces the third case everywhere.
    """
    if total is None:
        try:
            total = len(iterable)  # type: ignore[arg-type]
        except TypeError:
            total = None
    if not is_enabled():
        yield from iterable
        return
    if parent_present():
        n = 0
        for item in iterable:
            n += 1
            if level_shown(level):
                emit(level, n, total, desc, unit, mininterval)
            yield item
        if total is None:
            emit(level, n, n, desc, unit, mininterval, force=True)
        return
    if sys.stderr.isatty():
        try:
            from tqdm.std import tqdm as std_tqdm
        except ImportError:
            yield from iterable
            return
        for item in std_tqdm(iterable, desc=desc, unit=unit,
                             total=total, leave=False):
            yield item
        return
    yield from iterable


# --- drawing backends -------------------------------------------------------

def has_tqdm() -> bool:
    """Whether any tqdm bar can be drawn in this process."""
    try:
        from tqdm.std import tqdm  # noqa: F401
        return True
    except ImportError:
        return False


def _in_notebook_kernel() -> bool:
    try:
        from IPython import get_ipython  # type: ignore

        ip = get_ipython()
        return ip is not None and getattr(ip, "kernel", None) is not None
    except Exception:  # noqa: BLE001
        return False


def backend_for_current_process() -> str:
    """`"notebook"`, `"std"` or `"text"`, by capability, not by preference."""
    if _in_notebook_kernel():
        try:
            from tqdm.notebook import tqdm  # noqa: F401

            return "notebook"
        except ImportError:
            pass
    if sys.stderr.isatty() and has_tqdm():
        return "std"
    return "text"


class TqdmDisplay:
    """One reused widget per level. Sequential phases reset the same bar.

    Many short phases become one step widget whose `desc` says which
    fold and horizon it is on. A new (`desc`, `total`) pair closes the old bar
    and opens a fresh one at the same position, so phases never stack.
    """

    def __init__(self, tqdm_cls=None, leave: bool = False) -> None:
        if tqdm_cls is None:
            try:
                from tqdm.std import tqdm as std_tqdm

                tqdm_cls = std_tqdm
            except ImportError:
                tqdm_cls = None
        self._cls = tqdm_cls
        self._leave = leave
        self._bars: dict[str, object] = {}
        self._meta: dict[str, tuple[str, int | None, str]] = {}

    @property
    def available(self) -> bool:
        return self._cls is not None

    def update(self, event: dict) -> None:
        """Advance the bar for `event["level"]`, recreating it on phase change."""
        if self._cls is None or not level_shown(event.get("level", "")):
            return
        level = event.get("level", "")
        desc, total, unit = (event.get("desc", ""), event.get("total"),
                             event.get("unit", "it"))
        n = event.get("n", 0)
        key = (desc, total, unit)
        if self._meta.get(level) != key:
            old = self._bars.pop(level, None)
            if old is not None:
                old.close()
            pos = LEVEL_ORDER.get(level, 3)
            self._bars[level] = self._cls(total=total, desc=desc, unit=unit,
                                          position=pos, leave=self._leave)
            self._meta[level] = key
        bar = self._bars[level]
        try:
            bar.n = max(0, int(n))
            if hasattr(bar, "set_description_str"):
                bar.set_description_str(desc)
            bar.refresh()
        except Exception:  # noqa: BLE001 - a bar must never break a run
            pass

    def close(self) -> None:
        for bar in self._bars.values():
            try:
                bar.close()
            except Exception:  # noqa: BLE001
                pass
        self._bars.clear()
        self._meta.clear()


def run_and_render(argv: list[str], cwd: str | Path | None = None,
                   backend: str = "auto") -> int:
    """Run a pipeline command, drawing its `#PROG` events as fixed bars.

    This is what the notebook cells call instead of `subprocess.call` or
    `%%bash`: the child emits, this function draws, and the bars stay put
    because they are rendered by the kernel, not by redrawing `\\r` in captured
    output. Anything that is not a `#PROG` line passes through to the cell
    output unchanged.

    Returns the child's exit code. The child's own `#PROG` lines never reach the
    cell output; the log markers live in the stage logs on Drive instead.
    """
    import pathlib

    if backend == "auto":
        try:
            from tqdm.notebook import tqdm as nb_tqdm

            backend_cls: object = nb_tqdm if _in_notebook_kernel() else None
        except ImportError:
            backend_cls = None
        if backend_cls is None:
            try:
                from tqdm.std import tqdm as std_tqdm

                backend_cls = std_tqdm
            except ImportError:
                backend_cls = None
    elif backend == "notebook":
        from tqdm.notebook import tqdm as backend_cls  # type: ignore[no-redef]
    elif backend == "std":
        from tqdm.std import tqdm as backend_cls  # type: ignore[no-redef]
    else:
        backend_cls = None

    display = TqdmDisplay(backend_cls) if backend_cls is not None else None
    env = dict(os.environ)
    env[PARENT_FLAG] = "1"
    proc = subprocess.Popen(
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            event = parse_line(line)
            if event is None:
                print(line, end="", flush=True)
            elif display is not None:
                display.update(event)
        proc.wait()
    finally:
        if display is not None:
            display.close()
        if proc.stdout is not None:
            proc.stdout.close()
    code = proc.returncode if proc.returncode is not None else 1
    where = pathlib.Path(cwd) if cwd is not None else pathlib.Path.cwd()
    print(f"[exit={code}] {' '.join(argv[1:] if len(argv) > 1 else argv)} (cwd={where})",
          flush=True)
    return code

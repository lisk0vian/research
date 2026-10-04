# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Shared helpers for the c20-2026 pipeline: paths, config, IO.

Kept dependency-light on purpose (pandas + pyyaml only) so the early stages
run in a Colab cell before any modelling dependency is installed.

Every module reads `config.yaml`; nothing hardcodes a threshold.

Paths resolve in two modes, mirroring `papers/c15-2026/experiments/src/paths.py`:

- Local: no env vars set, so DATA_DIR/OUTPUT_DIR fall back to `../data` and
  `../outputs` relative to the paper root (`parents[1]` of this file).
- Drive (Colab): the notebook exports DATA_DIR and OUTPUT_DIR pointing into
  the mounted Drive before importing anything, so `data/` and `outputs/` land
  on Drive and survive a runtime recycle instead of vanishing with `/content`.

The env vars are read once at import time, so the notebook must set them before
running any stage.

`EXP_CONFIG` optionally overrides which `config.yaml` is read; `run_all.py`
exports it so a `--config` on the orchestrator reaches the stages it spawns,
since a subprocess inherits the environment but not the parent's argv.

`EXP_ENV` is a check, never a switch. The notebook keeps exporting the paths
explicitly; `EXP_ENV` only asserts that what those paths resolved to matches
what the caller believes, so a misconfigured run fails at import instead of
writing to the runtime's ephemeral disk and disappearing on recycle.

Every artefact write goes through `_atomic_write`: a temporary sibling plus
`os.replace`. A disconnect or crash mid-write then leaves the previous file or
nothing, never half a CSV that the next stage would read as complete.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

BASE = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("EXP_CONFIG") or BASE / "experiments" / "config.yaml")

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE / "data"))
OUTPUTS = Path(os.environ.get("OUTPUT_DIR", BASE / "outputs"))


def _declared_raw_name() -> str:
    """The raw filename the config declares, defaulting to the old fixed one.

    Hardcoding `dataset.csv` here while `fetch_source.py` writes whatever
    `source.file` says is the worst kind of mismatch: the fetch succeeds, the
    stages run, every log looks healthy, and stages 00-05 read a completely
    different file than the one just downloaded. Both names come from config now,
    so the fetch and the readers cannot drift apart.

    Config is read defensively rather than through `load_config`, which is
    defined further down and would make this a forward reference.
    """
    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return "dataset.csv"
    name = (cfg.get("source") or {}).get("file")
    if name is None:
        return "dataset.csv"
    return str(name).strip() or "dataset.csv"


RAW_CSV = DATA_DIR / "raw" / _declared_raw_name()
PROCESSED = DATA_DIR / "processed"
TABLES = OUTPUTS / "tables"
FIGURES = OUTPUTS / "figures"
LOGS = OUTPUTS / "logs"
INSPECT = OUTPUTS / "_inspect"


def checkpoints(stage: str):
    """Unit checkpoints of a long stage, on Drive next to its outputs.

    The shared runtime (COLAB.md) sits next to this file on Colab and in the
    repo's scripts/ locally; the stage's key arrives from run_all as $STAGE_KEY.
    """
    try:
        import _colab_runtime as rt
    except ImportError:
        sys.path.insert(0, str(BASE.parents[1] / "scripts"))
        import _colab_runtime as rt
    return rt.Checkpoints(stage, root=OUTPUTS / rt.CHECKPOINT_DIR)

# The previous provider's vocabulary, kept only as the fallback for a config
# with no `variables` map (pre-v3 configs and the legacy test fixtures).
LEGACY_NUMERIC_VARS = ("TT", "HR", "RR", "PP", "FF", "DD")


def variable_map(cfg: dict) -> dict[str, str]:
    """Source column -> internal name, from `config.variables`."""
    return {str(k): str(v) for k, v in (cfg.get("variables") or {}).items()}


def numeric_vars(cfg: dict) -> tuple[str, ...]:
    """Internal numeric variables, derived from the map rather than restated.

    Restating them is how `PP` came to mean pressure in one place and
    precipitation in another: the config moved to a new provider and this
    tuple did not.
    """
    mapped = tuple(variable_map(cfg).values())
    return mapped or LEGACY_NUMERIC_VARS


def _declared_numeric_vars() -> tuple[str, ...]:
    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return LEGACY_NUMERIC_VARS
    return numeric_vars(cfg)


NUMERIC_VARS = _declared_numeric_vars()

# Environment names this pipeline knows. EXP_ENV is a *check*, not a switch:
# the notebook still exports DATA_DIR/OUTPUT_DIR explicitly, and EXP_ENV only
# asserts that what they resolved to matches what the caller believes.
KNOWN_ENVS = ("local", "colab")


def _validate_environment() -> None:
    """Fail loudly if EXP_ENV disagrees with where the paths actually point.

    The failure this prevents is quiet and expensive: with EXP_ENV=colab and
    paths under /content, a Colab recycle deletes the run's outputs and nothing
    says so until someone goes looking for them.
    """
    declared = os.environ.get("EXP_ENV")
    if declared is None:
        return
    if declared not in KNOWN_ENVS:
        raise SystemExit(
            f"ERROR: EXP_ENV={declared!r} is not one of {KNOWN_ENVS}"
        )
    on_drive = "drive" in str(OUTPUTS).replace("\\", "/").lower()
    if declared == "colab" and not on_drive:
        raise SystemExit(
            f"ERROR: EXP_ENV=colab but OUTPUTS={OUTPUTS} is not on Drive.\n"
            "Outputs would be written to the runtime's ephemeral disk and lost on "
            "recycle. Export OUTPUT_DIR (and DATA_DIR) pointing into the mounted "
            "Drive before running a stage, or set EXP_ENV=local."
        )
    if declared == "local" and on_drive:
        raise SystemExit(
            f"ERROR: EXP_ENV=local but OUTPUTS={OUTPUTS} is on Drive.\n"
            "Refusing to write: unset the exported OUTPUT_DIR, or set EXP_ENV=colab."
        )


_validate_environment()


def _atomic_write(path: Path, write_fn) -> Path:
    """Write through a temp sibling, then `os.replace` onto the target.

    `os.replace` is only atomic within a filesystem, so the temporary file has
    to be a sibling of the target rather than in the system temp dir. A Colab
    disconnect or a crash mid-write then leaves either the previous file or
    nothing - never half a CSV that the next stage reads as complete, which is
    the failure mode that costs a full re-run.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        write_fn(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    """Atomically write text. For JSON payloads prefer `atomic_write_json`."""
    return _atomic_write(path, lambda p: p.write_text(text, encoding=encoding))


def atomic_write_csv(df: pd.DataFrame, path: Path, index: bool = False) -> Path:
    """Atomically write a DataFrame to CSV."""
    return _atomic_write(path, lambda p: df.to_csv(p, index=index, encoding="utf-8"))


def atomic_write_json(payload: dict, path: Path) -> Path:
    """Atomically write a JSON object with the repo's usual formatting."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    return _atomic_write(path, lambda p: p.write_text(text, encoding="utf-8"))


def rel_path(path: Path) -> str:
    """Path relative to the paper root, with forward slashes.

    Manifests record paths, and the repo convention is forward slashes so a
    manifest written on Windows cites the same string a reader on Linux sees.
    A path outside the paper root (a temp dir in a test, say) is returned
    absolute rather than mangled by a failed relativisation.
    """
    try:
        return str(Path(path).resolve().relative_to(BASE)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def inspect_write(name: str, df: pd.DataFrame) -> Path:
    """Persist a DataFrame for notebook exploration only. Not a pipeline output.

    Most things worth exploring are already a stage output and should be read
    from there. This exists for the intermediates that are useful to look at and
    do not deserve to be a declared output - the anomaly panels, a joined frame
    kept only for a diagnostic.

    Opt-in per call, and the name records which stage asked for it, so this
    cannot silently become a second, undocumented `outputs/` tree. Written under
    `outputs/_inspect/`, which the Drive sync does not pick up: it is a local
    cache that is cheap to rebuild.
    """
    return atomic_write_csv(df, INSPECT / f"{name}.csv")


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}


def primary_target(cfg: dict | None = None) -> str:
    """The primary target's name, from `data.target_variable`.

    Every stage used to carry `TARGET = "TT_mean"` next to a config that
    declares `data.target_variable`, so editing the config changed nothing.
    One reader, used by the stages, closes that gap. Config is read
    defensively, like `_declared_raw_name`: an unreadable config is a fact,
    not an import error, and the fallback is the name the pipeline has always
    used.
    """
    try:
        name = ((cfg if cfg is not None else load_config()).get("data") or {}).get(
            "target_variable")
    except (OSError, yaml.YAMLError):
        name = None
    return str(name).strip() if name else "TT_mean"


def secondary_targets(cfg: dict | None = None) -> tuple[str, ...]:
    """The secondary targets, from `data.secondary_targets`.

    Stages 03 and 04 used to hardcode `("TT_min", "TT_max")` while 07 read the
    config, so the three stages could silently disagree about which targets
    carry their own climatology. Same reader as `primary_target`, same rule.
    """
    try:
        names = ((cfg if cfg is not None else load_config()).get("data") or {}).get(
            "secondary_targets")
    except (OSError, yaml.YAMLError):
        names = None
    return tuple(str(n).strip() for n in (names or ("TT_min", "TT_max")))


def design_version() -> str:
    """The design version of the config that ran, for the manifest stamp.

    It used to be a hardcoded `"2.0"` default, which labelled the v3.0
    multi-station outputs as the superseded single-station design. The
    manifest is the provenance record every manuscript number traces
    through, so it must carry the version that actually executed.
    """
    try:
        return str(load_config().get("design_version") or "unknown")
    except (OSError, yaml.YAMLError):
        return "unknown"


def normalize_ubigeo(value) -> str:
    """Canonical six-digit station code from whatever the source served.

    The portal hands UBIGEO over as a float, so codes below 100000 arrive as
    40514.0 and pandas types the whole column float64. The leading zero is gone
    before any stage can see it and no later comparison recovers it, so this
    runs at the read boundary and nowhere else. NaN passes through as "" rather
    than becoming the string "nan", which would look like a real code.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return ""
    if "." in text:
        text = text.split(".")[0]
    return text.zfill(6)


def read_station_keyed(path: Path, **kwargs) -> pd.DataFrame:
    """Read a CSV that carries a station key, in canonical six-digit form.

    Both `UBIGEO` (hourly) and `station` (daily) are read as strings and
    normalised on the way in. Reading them without a dtype is how the padding
    comes off: pandas infers int64 from 040514, the leading zero is gone, and
    a station configured as "040514" stops matching the data with no error
    anywhere. Normalising at every read boundary costs nothing and makes the
    key stable regardless of what wrote the file.
    """
    dtype = {"UBIGEO": "string", "station": "string", **kwargs.pop("dtype", {})}
    df = pd.read_csv(path, dtype=dtype, **kwargs)
    for col in ("UBIGEO", "station"):
        if col in df.columns:
            df[col] = df[col].map(normalize_ubigeo)
    return df


def build_timestamp(dates: pd.Series, times: pd.Series) -> pd.Series:
    """Timestamp from integer `yyyymmdd` and `hhmmss` columns.

    HORA arrives as an integer, so 01:00:00 is 10000 and midnight is 0; the
    zero-padding to six digits is what makes those parse as times at all.
    """
    d = dates.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(8)
    t = times.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(6)
    return pd.to_datetime(d + t, format="%Y%m%d%H%M%S", errors="coerce")


def read_hourly(path: Path | None = None, cfg: dict | None = None) -> pd.DataFrame:
    """Read the raw CSV with local civil timestamps, internal variable names and
    canonical station codes.

    Two schemas are recognised. When the file carries the config's timestamp
    columns (`FECHA`+`HORA` for SENAMHI) it is the provider of record: the
    timestamp is built from them and `config.variables` renames the source
    columns to internal names (`TEMP`->`TT`, `PP`->`RR`). Otherwise it is the
    legacy `year/month/day/hour` contract, read verbatim. The rename is tied to
    the schema on purpose: applying a SENAMHI map to a file where `PP` is
    pressure would silently relabel pressure as rain.

    `FECHA_CORTE` is a snapshot date, not a per-row timestamp (it is in
    `config.data.non_predictors`). UBIGEO is normalised here because this is the
    last point at which the raw value is still visible.
    """
    cfg = load_config() if cfg is None else cfg
    df = pd.read_csv(path or RAW_CSV, dtype={"FECHA_CORTE": "string", "UBIGEO": "string"})
    ts_cfg = cfg.get("timestamp") or {}
    date_col, time_col = ts_cfg.get("date_col"), ts_cfg.get("time_col")
    if date_col and time_col and {date_col, time_col} <= set(df.columns):
        df["timestamp"] = build_timestamp(df[date_col], df[time_col])
        mapping = variable_map(cfg)
        missing = [src for src in mapping if src not in df.columns]
        if missing:
            raise SystemExit(f"ERROR: config.variables names source columns absent "
                             f"from the file: {missing}")
        clash = [dst for src, dst in mapping.items()
                 if dst != src and dst in df.columns and dst not in mapping]
        if clash:
            raise SystemExit(f"ERROR: renaming would overwrite existing columns {clash}")
        df = df.rename(columns=mapping)
    else:
        df["timestamp"] = pd.to_datetime(
            dict(
                year=df["year"], month=df["month"], day=df["day"], hour=df["hour"]
            ),
            errors="coerce",
        )
    if "UBIGEO" in df.columns:
        df["UBIGEO"] = df["UBIGEO"].map(normalize_ubigeo)
    return df


def fold_windows(fold: dict, cfg: dict | None = None
                 ) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """(train_start, train_end, test_start, test_end) for one fold, inclusive.

    Design v3 folds give the test window as dates (`test: [start, end]`) and
    train from `validation.train_start` to the day before the test window. The
    legacy form (`train: [y0, y1]`, `test: year`) is still read so the older
    fixtures keep meaning what they meant. The embargo is not applied here: it
    belongs to training *issuances* (04), not to the climatology fit, whose
    inputs all predate the test window anyway.
    """
    test = fold["test"]
    if isinstance(test, (list, tuple)):
        test_start, test_end = pd.Timestamp(test[0]), pd.Timestamp(test[1])
        start = fold.get("train_start") or ((cfg or {}).get("validation") or {}).get("train_start")
        if start is None:
            raise SystemExit(f"ERROR: fold {fold.get('id')} has no train_start "
                             "(set validation.train_start)")
        return (pd.Timestamp(start), test_start - pd.Timedelta(days=1),
                test_start, test_end)
    y0, y1 = fold["train"]
    return (pd.Timestamp(y0, 1, 1), pd.Timestamp(y1, 12, 31),
            pd.Timestamp(int(test), 1, 1), pd.Timestamp(int(test), 12, 31))


def write_table(df: pd.DataFrame, name: str) -> Path:
    """Write a contract table to outputs/tables/, creating the folder."""
    return atomic_write_csv(df, TABLES / name)


def station_codes(cfg: dict) -> list[str]:
    """Station codes declared in config, in order, padded to six digits.

    The padding belongs here and nowhere else. The portal serves UBIGEO as a
    float, so codes below 100000 arrive as 40514.0 and pandas types the whole
    column float64; by the time a stage sees the value the leading zero is
    already gone and no later comparison can recover it. Normalising at the one
    boundary where the raw value is still visible is the only place it is safe.

    Empty when `stations` is absent, so single-station data still runs.
    """
    out: list[str] = []
    for entry in cfg.get("stations") or []:
        raw = entry.get("ubigeo")
        if raw is None:
            continue
        code = normalize_ubigeo(raw)
        if code:
            out.append(code)
    return out


def deep_merge(base: dict, payload: dict, replace: frozenset[str] = frozenset()) -> dict:
    """Merge `payload` into `base`, recursing into nested dicts.

    The manifest is written once per (station, fold, target), so a shallow
    `update` means the second station silently overwrites the first: no
    exception, no warning, just one station's numbers where there should be
    five. Recursing is what makes the per-unit writes accumulate.

    `replace` names top-level keys to overwrite outright instead. Deep merge
    never forgets, which is the other half of the problem: a station removed
    from config keeps its last entry on disk. A stage that writes a complete
    set of units in one call passes `replace` for that key, so the block
    reflects the config that ran rather than the union of every config that
    ever ran.
    """
    out = dict(base)
    for key, value in payload.items():
        if key in replace:
            out[key] = value
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def write_manifest(payload: dict, name: str = "manifest_index.json",
                   replace: frozenset[str] | Iterable[str] = frozenset()) -> Path:
    """Update outputs/manifest_index.json, keeping the declared contract intact."""
    path = OUTPUTS / name
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data = deep_merge(data, payload, frozenset(replace))
    data.setdefault("paper", "c20-2026")
    data.setdefault("design_version", design_version())
    data["status"] = "partial"
    return atomic_write_json(data, path)


def ensure_dirs() -> None:
    for d in (RAW_CSV.parent, PROCESSED, TABLES, FIGURES, LOGS, OUTPUTS / "models"):
        d.mkdir(parents=True, exist_ok=True)


def paths_report() -> str:
    """Human-readable routing summary, printed by the notebook and by stages.

    Makes it obvious which mode is active: `local` writes next to the code,
    `drive` writes into the mounted folder and therefore persists.
    """
    mode = "drive" if os.environ.get("DATA_DIR") else "local"
    return "\n".join([
        f"[{mode}] DATA_DIR  = {DATA_DIR}",
        f"[{mode}] RAW_CSV   = {RAW_CSV} (exists={RAW_CSV.is_file()})",
        f"[{mode}] PROCESSED = {PROCESSED}",
        f"[{mode}] OUTPUTS   = {OUTPUTS}",
    ])


# --- progress ---------------------------------------------------------------
# The child never draws a bar: it emits `#PROG` event lines (see
# `_progress.py`) and whoever reads draws. `tqdm` stays optional and is only
# ever used by a *reader* (this module's `run_stage`, the notebook runner, or
# a direct terminal run), so a missing bar can never take a stage down.
#
# `has_tqdm` reports whether any bar can be drawn here; it is what the stage
# log header records.

try:  # pragma: no cover - exercised by whichever branch the env provides
    from tqdm.auto import tqdm as _tqdm
except ImportError:  # pragma: no cover
    _tqdm = None


def progress(iterable, desc: str = "", unit: str = "it",
               total: int | None = None, level: str = "fold",
               mininterval: float | None = None, **_ignored) -> object:
    """Yield items, emitting `#PROG` events when a rendering parent listens.

    The child never draws: whoever reads draws (notebook widgets, terminal
    bars, log markers). See `_progress.iter_progress` for the three cases
    (parent present, interactive terminal, silent). Extra keywords are ignored
    so older call sites keep working.
    """
    import _progress

    return _progress.iter_progress(iterable, level=level, desc=desc,
                                   unit=unit, total=total,
                                   mininterval=mininterval)


def has_tqdm() -> bool:
    import _progress

    return _progress.has_tqdm()


# --- stage logging ----------------------------------------------------------
# Why the runner is Python and not a shell `tee`
# ---------------------------------------------
# The obvious design is `python stage.py | tee outputs/logs/stage.log` and then
# an `echo "exit=$?"` footer. That does not work: the footer is written to the
# shell's stdout, which is downstream of `tee`, so it never reaches the file. A
# footer written before the pipeline runs cannot know the exit code, and bash
# only reports the *last* command in a pipe unless `pipefail` is set.
#
# So the runner owns the whole file. It streams the child's merged output,
# passing it through to the terminal verbatim and to the log with carriage
# returns collapsed and ANSI stripped. That is what lets a tqdm bar animate in
# the notebook while the file on Drive stays clean text.
#
# Logs are named after the stage, fixed, and rewritten every run: one Drive
# fileId per stage that never changes. A timestamped filename would mint a new
# file per run, and each new Drive file needs a new Colab URL and a new runtime
# session, which the account caps.

LOG_START = "STAGE-START"
LOG_EXIT = "STAGE-EXIT"
LOG_SUMMARY = "STAGE-SUMMARY"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def log_dir() -> Path:
    """outputs/logs, created on demand."""
    LOGS.mkdir(parents=True, exist_ok=True)
    return LOGS


def stage_log_path(stage: str) -> Path:
    return log_dir() / f"{stage}.log"


def run_all_log_path() -> Path:
    return log_dir() / "run_all.log"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_stage_log_header(stage: str, argv: list[str], extra: dict | None = None,
                           log_path: Path | None = None) -> Path:
    """Open a fresh log for `stage` and write its header.

    Truncating here (rather than appending at the end) means a crash still
    leaves a readable log on Drive: the header and whatever the child managed to
    print are already there.
    """
    path = log_path or stage_log_path(stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {LOG_START} {stage}",
        f"# started        : {_now()}",
        f"# command        : {' '.join(argv)}",
        f"# cwd            : {Path.cwd()}",
        f"# python         : {sys.version.split()[0]} ({sys.executable})",
        f"# tqdm available : {has_tqdm()}",
        f"# log            : {path}",
        "#",
        *paths_report().splitlines(),
    ]
    for key, value in (extra or {}).items():
        lines.append(f"# {key:<16}: {value}")
    lines.append("#" + "-" * 78)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def append_stage_log(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def write_stage_log_footer(stage: str, exit_code: int, elapsed_s: float,
                           log_path: Path, extra: dict | None = None) -> None:
    """Close the log with the exit code and elapsed time.

    These two lines are what make a log self-describing: read off Drive
    through the MCP, with no notebook and no stdout, you can tell which stage
    failed, why it failed, and whether it was slow or fast.
    """
    status = "ok" if exit_code == 0 else "FAILED"
    lines = [
        "",
        "#" + "-" * 78,
        f"# {LOG_SUMMARY} {stage}: {status}",
        f"# {LOG_EXIT} {stage} exit_code={exit_code} elapsed_s={elapsed_s:.2f}",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"# {key:<16}: {value}")
    lines.append(f"# finished       : {_now()}")
    lines.append(f"# row counts, if any, are in outputs/manifest_index.json")
    append_stage_log(log_path, "\n".join(lines) + "\n")


class _TerminalLineSplitter:
    """Collapse carriage-return redraws into plain lines.

    tqdm redraws a bar in place with a bare `\\r`. Forwarding that raw gives a
    correct terminal but a log full of redraw fragments, so the file keeps only
    the state before each newline.

    The trap is that a bare `\\r` and a CRLF pair look alike until you look at
    the next byte. On Windows the child's stdout is in text mode, so every
    newline it writes arrives as `\\r\\n`; treating those as redraw-then-newline
    discards the whole line and silently empties the log.
    """

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        self._pending += chunk
        while True:
            nl = self._pending.find("\n")
            cr = self._pending.find("\r")
            if nl == -1 and cr == -1:
                break
            if cr != -1 and (nl == -1 or cr < nl):
                if cr + 1 == len(self._pending):
                    # A trailing \r cannot be classified yet: the next chunk may
                    # start with \n and make this a CRLF. Wait for it.
                    break
                if self._pending[cr + 1] == "\n":
                    out.append(_ANSI.sub("", self._pending[:cr]))
                    self._pending = self._pending[cr + 2:]
                else:
                    self._pending = self._pending[cr + 1:]  # redraw: discard
                continue
            out.append(_ANSI.sub("", self._pending[:nl]))
            self._pending = self._pending[nl + 1:]
        return "".join(line + "\n" for line in out)

    def flush(self) -> str:
        if not self._pending:
            return ""
        tail = _ANSI.sub("", self._pending)
        self._pending = ""
        return tail + "\n" if tail.strip() else ""


def run_stage(stage: str, argv: list[str] | None = None, cwd: Path | None = None,
              log_path: Path | None = None, header_extra: dict | None = None,
              footer_extra: dict | None = None,
              aggregate: Path | None = None) -> dict:
    """Run one stage as a subprocess, logging it.

    Returns {"stage", "exit_code", "elapsed_s", "log"} so the caller never has
    to parse its own log back. The child inherits stdout and stderr merged, so a
    tqdm bar on stderr still reaches the notebook. This wrapper is the single
    writer of the log, which is why the footer can carry a real exit code (see
    the note above).
    """
    argv = list(argv or [f"{stage}.py"])
    work = Path(cwd) if cwd else Path(__file__).resolve().parent
    LOGS.mkdir(parents=True, exist_ok=True)
    path = write_stage_log_header(stage, argv, header_extra, log_path)
    append_stage_log(path, f"$ {' '.join(argv)}\n")
    if aggregate is not None:
        aggregate.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    import _progress as _prog

    # The child always sees a rendering parent (us), so it emits `#PROG`
    # events instead of drawing its own bar. What we do with them depends on
    # where *we* are: under a notebook runner we forward them raw so the
    # kernel draws; in a terminal we draw fixed bars here; otherwise the log
    # and the console get plain phase markers.
    child_env = dict(os.environ)
    child_env[_prog.PARENT_FLAG] = "1"
    proc = subprocess.Popen(
        [sys.executable, *argv],
        cwd=str(work),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env=child_env,
    )
    splitter = _TerminalLineSplitter()
    # Read raw bytes, not text. With text=True the pipe runs in universal
    # newlines mode, which rewrites \r as \n before the splitter can see it -
    # so every tqdm redraw would land in the log as its own line. Binary reads
    # keep \r intact and let the splitter collapse it. The incremental decoder
    # handles a multi-byte character split across two reads.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    out = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else None

    def _console_write(text: str) -> None:
        if out is not None:
            out.write(text.encode("utf-8", errors="replace"))
            out.flush()
        else:  # pragma: no cover - a stdout without a buffer
            sys.stdout.write(text)
            sys.stdout.flush()

    forward_prog = _prog.parent_present() and _prog.is_enabled()
    display = None
    if _prog.is_enabled() and not forward_prog:
        if sys.stderr.isatty() and _prog.has_tqdm():
            from tqdm.std import tqdm as _std_tqdm

            display = _prog.TqdmDisplay(_std_tqdm)
    mark_state: dict = {}

    def _handle_line(line: str) -> None:
        """Route one complete output line to console and/or log."""
        event = _prog.parse_line(line) if _prog.is_enabled() else None
        if event is None:
            _console_write(line)
            append_stage_log(path, line)
            return
        # A progress event: the raw JSON never reaches the log. The log keeps
        # a phase marker (`# progress <desc>: n/total`), which says which
        # phase was running without burying the diagnosis in redraws.
        phase = _prog.is_phase_change(event, mark_state)
        marker = _prog.format_marker(event) + "\n"
        if phase:
            append_stage_log(path, marker)
        if forward_prog:
            # Our own reader draws; hand it the untouched event line.
            _console_write(line if line.endswith("\n") else line + "\n")
        elif display is not None:
            display.update(event)
        elif phase:
            # No bars here (piped output, CI): the marker is the display.
            _console_write(marker)

    try:
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            text = decoder.decode(chunk)
            for cooked in splitter.feed(text).splitlines(keepends=True):
                _handle_line(cooked)
        for cooked in splitter.feed(decoder.decode(b"", True)).splitlines(keepends=True):
            _handle_line(cooked)
        tail = splitter.flush()
        if tail:
            _handle_line(tail)
        proc.wait()
    finally:
        if display is not None:
            display.close()
        if proc.stdout is not None:
            proc.stdout.close()

    exit_code = proc.returncode
    elapsed = time.perf_counter() - started
    write_stage_log_footer(stage, exit_code, elapsed, path, footer_extra)
    if aggregate is not None:
        with aggregate.open("a", encoding="utf-8") as fh:
            fh.write(f"\n{'=' * 80}\n== {stage}  exit={exit_code}  {elapsed:.2f}s\n{'=' * 80}\n")
            fh.write(path.read_text(encoding="utf-8", errors="replace"))
            fh.write("\n")
    print(f"[{stage}] exit={exit_code} elapsed={elapsed:.2f}s -> {path}")
    return {
        "stage": stage,
        "exit_code": exit_code,
        "elapsed_s": elapsed,
        "log": str(path),
    }


def write_logs_manifest(entries: dict[str, dict], name: str = "manifest_index.json") -> Path:
    """Publish the log index so a reader can find each log without listing Drive.

    `entries` maps stage -> {"exit_code", "elapsed_s", "log"}. The log files live
    on Drive, so without an index there is no way to locate them from a
    manifest read; with one, `manifest_index.json` names every path and every
    exit code.
    """
    stages = {}
    for stage, info in entries.items():
        stages[stage] = {
            "log": rel_path(info["log"]),
            "exit_code": info.get("exit_code"),
            "elapsed_s": round(float(info.get("elapsed_s", 0.0)), 2),
        }
    return write_manifest({
        "logs": {
            "dir": rel_path(LOGS),
            "run_all": rel_path(LOGS / "run_all.log"),
            "stages": stages,
        }
    }, name=name)
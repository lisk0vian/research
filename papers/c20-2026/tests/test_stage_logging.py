"""Tests for the stage-logging runner.

The runner is what makes a Colab run inspectable from outside: the Colab runtime
is disposable, so `outputs/logs/<stage>.log` on Drive is the only durable record
of what a run did. These tests exercise it against throwaway stage scripts in
`tmp_path`, never against the real dataset.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import _common  # noqa: E402


@pytest.fixture
def routed(tmp_path, monkeypatch):
    """Point DATA_DIR/OUTPUT_DIR at a tmp tree and reload _common's paths."""
    data = tmp_path / "data"
    outs = tmp_path / "outputs"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("OUTPUT_DIR", str(outs))
    yield data, outs
    # _common reads these at import time; drop it so the next test re-imports.
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)


def _stage(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / "experiments"
    p.mkdir(parents=True, exist_ok=True)
    f = p / name
    f.write_text(body, encoding="utf-8")
    return f


def test_successful_stage_logs_header_footer_and_exit_zero(routed, tmp_path, capsys):
    data, outs = routed
    _stage(tmp_path, "00_ok.py", "print('hello from stage')\n")
    common = _common
    common.DATA_DIR, common.OUTPUTS = data, outs
    common.LOGS = outs / "logs"

    info = common.run_stage("00_ok", cwd=tmp_path / "experiments")

    assert info["exit_code"] == 0
    log = Path(info["log"])
    assert log.is_file()
    text = log.read_text(encoding="utf-8")

    assert common.LOG_START in text
    assert common.LOG_EXIT in text
    assert "exit_code=0" in text
    assert "hello from stage" in text, "stdout must reach the log"
    assert info["elapsed_s"] >= 0
    # The footer must be inside the file, which a shell `tee` could not do.
    assert text.index("hello from stage") < text.index(common.LOG_EXIT)


def test_failing_stage_records_nonzero_exit_and_traceback(routed, tmp_path):
    data, outs = routed
    _stage(tmp_path, "00_bad.py", "raise RuntimeError('boom')\n")
    common = _common
    common.DATA_DIR, common.OUTPUTS = data, outs
    common.LOGS = outs / "logs"

    info = common.run_stage("00_bad", cwd=tmp_path / "experiments")

    assert info["exit_code"] != 0
    text = Path(info["log"]).read_text(encoding="utf-8")
    assert f"exit_code={info['exit_code']}" in text
    assert "Traceback" in text
    assert "boom" in text, "stderr must reach the log"
    assert "FAILED" in text


def test_header_truncates_so_a_crash_still_leaves_a_readable_log(routed, tmp_path):
    data, outs = routed
    _stage(tmp_path, "00_twice.py", "print('marker')\n")
    common = _common
    common.DATA_DIR, common.OUTPUTS = data, outs
    common.LOGS = outs / "logs"

    common.run_stage("00_twice", cwd=tmp_path / "experiments")
    first = Path(common.stage_log_path("00_twice")).read_text(encoding="utf-8")

    common.run_stage("00_twice", cwd=tmp_path / "experiments")
    second = Path(common.stage_log_path("00_twice")).read_text(encoding="utf-8")

    assert first.count("marker") == second.count("marker") == 1, \
        "a re-run must overwrite, not append"


def test_carriage_returns_collapse_and_ansi_is_stripped(routed, tmp_path):
    """A redrawn bar must not leave fragments in the file."""
    data, outs = routed
    body = (
        "import sys\n"
        "sys.stdout.write('\\x1b[2Kloading 10%\\r')\n"
        "sys.stdout.write('\\x1b[2Kloading 100%\\n')\n"
    )
    _stage(tmp_path, "00_bar.py", body)
    common = _common
    common.DATA_DIR, common.OUTPUTS = data, outs
    common.LOGS = outs / "logs"

    info = common.run_stage("00_bar", cwd=tmp_path / "experiments")
    text = Path(info["log"]).read_text(encoding="utf-8")

    assert "\r" not in text
    assert "\x1b" not in text
    assert "loading 100%" in text
    assert "loading 10%" not in text, "superseded redraws must be dropped"


def test_splitter_keeps_newline_terminated_lines():
    sp = _common._TerminalLineSplitter()
    assert sp.feed("alpha\nbeta\n") == "alpha\nbeta\n"
    assert sp.feed("no newline yet") == ""
    assert sp.flush() == "no newline yet\n"


def test_splitter_treats_crlf_as_one_terminator():
    """Windows text-mode stdout sends \\r\\n for every newline.

    Reading a CRLF as redraw-then-newline drops the line, which is how the log
    ended up empty on this platform while the terminal looked fine.
    """
    sp = _common._TerminalLineSplitter()
    assert sp.feed("alpha\r\nbeta\r\n") == "alpha\nbeta\n"


def test_splitter_waits_when_crlf_is_split_across_chunks():
    sp = _common._TerminalLineSplitter()
    assert sp.feed("alpha\r") == "", "an unclassifiable trailing \\r must be held"
    assert sp.feed("\nbeta\n") == "alpha\nbeta\n"


def test_splitter_distinguishes_redraw_from_crlf():
    sp = _common._TerminalLineSplitter()
    assert sp.feed("10%\r100%\n") == "100%\n"
    assert sp.feed("keep\r\n") == "keep\n"


def test_splitter_drops_blank_carryover_on_flush():
    sp = _common._TerminalLineSplitter()
    sp.feed("   \r")
    assert sp.flush() == ""


def test_aggregate_accumulates_every_stage(routed, tmp_path):
    data, outs = routed
    _stage(tmp_path, "00_a.py", "print('A')\n")
    _stage(tmp_path, "00_b.py", "print('B')\n")
    common = _common
    common.DATA_DIR, common.OUTPUTS = data, outs
    common.LOGS = outs / "logs"

    agg = outs / "logs" / "run_all.log"
    agg.parent.mkdir(parents=True, exist_ok=True)
    agg.write_text("", encoding="utf-8")
    common.run_stage("00_a", cwd=tmp_path / "experiments", aggregate=agg)
    common.run_stage("00_b", cwd=tmp_path / "experiments", aggregate=agg)

    text = agg.read_text(encoding="utf-8")
    assert "A" in text and "B" in text
    assert text.count("STAGE-EXIT") == 2
    assert "exit=0" in text


def test_logs_manifest_names_every_path_and_exit_code(routed, tmp_path):
    data, outs = routed
    common = _common
    common.DATA_DIR, common.OUTPUTS = data, outs
    common.LOGS = outs / "logs"
    common.BASE = data.parent

    info = {"log": str(outs / "logs" / "00_ok.log"), "exit_code": 1, "elapsed_s": 0.5}
    path = common.write_logs_manifest({"00_ok": info})
    payload = __import__("json").loads(path.read_text(encoding="utf-8"))

    assert payload["logs"]["dir"] == "outputs/logs"
    assert payload["logs"]["run_all"] == "outputs/logs/run_all.log"
    entry = payload["logs"]["stages"]["00_ok"]
    assert entry["exit_code"] == 1
    assert entry["elapsed_s"] == 0.5
    assert entry["log"].endswith("00_ok.log")


def test_progress_is_silent_when_switched_off(monkeypatch, capsys):
    """EXP_PROGRESS=off: no events, no bars, just the items."""
    import _progress

    monkeypatch.setenv("EXP_PROGRESS", "off")
    monkeypatch.setenv("EXP_PROGRESS_PARENT", "1")
    _progress.reset_state()
    assert list(_common.progress([1, 2, 3], desc="stage", level="stage")) == [1, 2, 3]
    assert capsys.readouterr().out == ""


def test_progress_emits_parseable_events_for_a_parent(monkeypatch, capsys):
    """Under a rendering parent the child emits `#PROG` JSON lines."""
    import _progress
    import json

    monkeypatch.delenv("EXP_PROGRESS", raising=False)
    monkeypatch.setenv("EXP_PROGRESS_PARENT", "1")
    _progress.reset_state()
    assert list(_common.progress([1, 2], desc="stage", unit="st",
                                 level="stage")) == [1, 2]
    out = capsys.readouterr().out
    events = [_progress.parse_line(l) for l in out.splitlines()]
    events = [e for e in events if e is not None]
    assert len(events) == 2, out
    assert events[0]["level"] == "stage" and events[-1]["n"] == 2
    assert events[-1]["total"] == 2
    # The raw line round-trips through json, so any reader can parse it.
    json.loads(out.splitlines()[0].removeprefix(_progress.PROG_PREFIX))


def test_progress_is_silent_without_parent_or_tty(monkeypatch, capsys):
    """Piped output with no parent: no JSON noise on stdout."""
    import _progress

    monkeypatch.delenv("EXP_PROGRESS", raising=False)
    monkeypatch.delenv("EXP_PROGRESS_PARENT", raising=False)
    _progress.reset_state()
    assert list(_common.progress([1, 2, 3], desc="x")) == [1, 2, 3]
    assert capsys.readouterr().out == ""


def test_header_reports_drive_mode_from_env(routed, tmp_path):
    data, outs = routed
    _stage(tmp_path, "00_mode.py", "print('x')\n")
    common = _common
    common.DATA_DIR, common.OUTPUTS = data, outs
    common.LOGS = outs / "logs"

    info = common.run_stage("00_mode", cwd=tmp_path / "experiments")
    text = Path(info["log"]).read_text(encoding="utf-8")
    assert "[drive]" in text, "log must state which routing mode produced it"


def test_log_filename_is_fixed_so_drive_fileid_is_stable(routed, tmp_path):
    data, outs = routed
    common = _common
    common.DATA_DIR, common.OUTPUTS = data, outs
    common.LOGS = outs / "logs"
    name = common.stage_log_path("05_features_local").name
    assert name == "05_features_local.log"
    assert re.match(r"^\d\d_[a-z_]+\.log$", name), "no timestamp may enter the filename"
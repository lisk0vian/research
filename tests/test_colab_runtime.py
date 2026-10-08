# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for scripts/_colab_runtime.py: errors.log, status.json, resume, preflight.

The contract (COLAB.md): one errors.log per session that holds every failure and
nothing else, a status.json that tells "never ran" from "ran clean", and stage
states that only ever skip work whose code, config and upstream are unchanged.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _colab_runtime as rt  # noqa: E402


@pytest.fixture(autouse=True)
def _no_session(monkeypatch):
    monkeypatch.delenv(rt.SESSION_ENV, raising=False)


@pytest.fixture
def log(tmp_path: Path) -> rt.RunLog:
    return rt.RunLog(tmp_path / "outputs" / "logs")


# --- errors.log and status.json ---------------------------------------------------

def test_session_starts_with_an_empty_errors_log(log):
    log.dir.mkdir(parents=True)
    log.errors.write_text("old failure\n", encoding="utf-8")
    log.begin_session(mode="full")
    assert log.errors.read_text(encoding="utf-8") == ""
    assert not log.has_errors()
    assert log.read_status()["state"] == "setup"


def test_begin_session_exports_the_id_only_when_asked(log):
    import os

    log.begin_session(export=False)
    assert rt.SESSION_ENV not in os.environ
    sid = log.begin_session()
    assert os.environ[rt.SESSION_ENV] == sid


def test_errors_accumulate_in_one_file(log):
    log.begin_session()
    log.record_error("stage 03", "exit 1", "Traceback...\nValueError: x")
    log.record_error("notebook cell", "KeyError: 'a'")
    text = log.error_text()
    assert "stage 03: exit 1" in text and "ValueError: x" in text
    assert "notebook cell: KeyError" in text


def test_status_updates_merge_stages(log):
    log.begin_session()
    log.update_status(stages={"00": rt.OK})
    log.update_status(stages={"01": rt.FAILED}, failed_stage="01")
    st = log.read_status()
    assert st["stages"] == {"00": "ok", "01": "failed"}
    assert st["failed_stage"] == "01"


def test_tail_keeps_the_end_of_a_log(tmp_path):
    p = tmp_path / "s.log"
    p.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
    out = rt.tail(p, 5)
    assert out.splitlines() == [f"line {i}" for i in range(195, 200)]


def test_raise_if_errors_is_quiet_on_a_finished_clean_session(log, capsys):
    log.begin_session()
    log.update_status(state=rt.OK)
    rt.raise_if_errors(log)
    assert "no errors" in capsys.readouterr().out


def test_a_session_whose_pipeline_never_ran_is_not_reported_ok(log):
    """The run cell was missing once and the report still said 'no errors'."""
    log.begin_session()
    log.update_status(state="ready")  # preflight passed, pipeline never started
    with pytest.raises(rt.RecordedError, match="did not finish"):
        rt.raise_if_errors(log)
    assert "did not finish" in log.error_text()


def test_raise_if_errors_raises_an_already_recorded_error(log):
    log.begin_session()
    log.record_error("stage 06b", "exit 1")
    with pytest.raises(rt.RecordedError) as exc:
        rt.raise_if_errors(log)
    assert exc.value._recorded


# --- notebook cell hook -------------------------------------------------------------

class _FakeShell:
    def __init__(self):
        self.handler = None
        self.shown = []

    def set_custom_exc(self, types_, handler):
        self.handler = handler

    def showtraceback(self, exc_tuple, tb_offset=None):
        self.shown.append(exc_tuple[0])


def _fake_ipython(monkeypatch, shell):
    mod = types.ModuleType("IPython")
    mod.get_ipython = lambda: shell
    monkeypatch.setitem(sys.modules, "IPython", mod)


def test_cell_exception_lands_in_errors_log(log, monkeypatch):
    shell = _FakeShell()
    _fake_ipython(monkeypatch, shell)
    log.begin_session()
    assert rt.install_cell_error_hook(log)
    try:
        raise FileNotFoundError("metrics_long.csv")
    except FileNotFoundError as e:
        shell.handler(shell, type(e), e, e.__traceback__)
    assert "FileNotFoundError" in log.error_text()
    assert shell.shown == [FileNotFoundError]  # still shown in the cell
    assert log.read_status()["state"] == "failed"


def test_recorded_error_is_not_logged_twice(log, monkeypatch):
    shell = _FakeShell()
    _fake_ipython(monkeypatch, shell)
    log.begin_session()
    rt.install_cell_error_hook(log)
    log.record_error("preflight", "no GPU")
    err = rt.RecordedError("preflight: no GPU")
    shell.handler(shell, type(err), err, None)
    assert log.error_text().count("no GPU") == 1


# --- running commands ---------------------------------------------------------------

def _script(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_run_command_turns_progress_events_into_text(tmp_path, capsys):
    _script(tmp_path / "s.py",
            "import json\n"
            "for n in range(1, 4):\n"
            "    print('#PROG ' + json.dumps({'level': 'fold', 'n': n, 'total': 3, 'desc': 'D1'}))\n"
            "print('done')\n")
    log = tmp_path / "stage.log"
    code, out = rt.run_command(["s.py"], cwd=tmp_path, log_path=log)
    printed = capsys.readouterr().out
    assert code == 0
    assert "#PROG" not in printed
    assert " 1/3 " in printed and " 3/3 " in printed and "100%" in printed
    assert " 2/3 " not in printed  # within 30 s, intermediate ticks are not lines
    assert out.strip() == "done"
    assert "D1: 1/3" in log.read_text(encoding="utf-8")  # phase markers in the log


def test_run_command_forwards_events_to_a_rendering_parent(tmp_path, capsys, monkeypatch):
    """Nested runners (stages_main under the notebook) pass events up, raw."""
    monkeypatch.setenv("EXP_PROGRESS_PARENT", "1")
    _script(tmp_path / "s.py",
            "import json\nprint('#PROG ' + json.dumps({'level': 'step', 'n': 1, 'total': 9}))\n")
    rt.run_command(["s.py"], cwd=tmp_path)
    assert '#PROG {"level": "step"' in capsys.readouterr().out


def test_bar_text_shows_count_percent_rate_and_time_left():
    text = rt.bar_text("06b CFSv2", 216, 864, 60.0)
    assert "216/864" in text and "25%" in text and "3.6/s" in text
    assert "elapsed 01:00" in text and "left 03:00" in text


class _FakeHandle:
    def __init__(self, store):
        self.store = store

    def update(self, obj, raw=False):
        self.store.append(obj["text/plain"])


def test_notebook_bar_updates_in_place(monkeypatch):
    shown: list[str] = []
    display_mod = types.ModuleType("IPython.display")
    display_mod.display = lambda obj, raw=False, display_id=False: (
        shown.append(obj["text/plain"]), _FakeHandle(shown))[1]
    monkeypatch.setitem(sys.modules, "IPython.display", display_mod)
    monkeypatch.delenv("EXP_PROGRESS_PARENT", raising=False)
    monkeypatch.setattr(rt, "_in_kernel", lambda: True)
    p = rt._Progress(lambda t: None, None)
    assert p.mode == "live"
    p.LIVE_EVERY_S = 0.0
    for n in (1, 2, 3):
        p.event("", {"level": "step", "n": n, "total": 3, "desc": "06b CFSv2"})
    assert len(shown) == 3 and "3/3" in shown[-1] and "100%" in shown[-1]


def test_run_command_returns_the_traceback_tail(tmp_path):
    _script(tmp_path / "bad.py", "raise ValueError('boom')\n")
    code, out = rt.run_command(["bad.py"], cwd=tmp_path)
    assert code != 0 and "ValueError: boom" in out


# --- preflight ------------------------------------------------------------------------

def test_missing_gpu_fails_hard(log, monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "gpu_available", lambda: False)
    log.begin_session()
    with pytest.raises(rt.RecordedError):
        rt.preflight({"gpu": "required"}, tmp_path, log)
    assert "no GPU" in log.error_text()
    assert "Change runtime type" in log.error_text()
    assert log.read_status()["failed_stage"] == "preflight"


def test_failing_probe_stops_before_the_pipeline(log, monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "gpu_available", lambda: True)
    _script(tmp_path / "probe.py", "raise SystemExit('KeyValueNotFoundError')\n")
    log.begin_session()
    with pytest.raises(rt.RecordedError):
        rt.preflight({"gpu": "required", "probes": [["probe.py"]]}, tmp_path, log)
    assert "preflight/probes" in log.error_text()
    assert "KeyValueNotFoundError" in log.error_text()


def test_passing_preflight_marks_the_session_ready(log, monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "gpu_available", lambda: False)
    _script(tmp_path / "setup.py", "print('ok')\n")
    log.begin_session()
    rt.preflight({"gpu": "none", "setup": [["setup.py"]]}, tmp_path, log)
    assert not log.has_errors()
    assert log.read_status()["state"] == "ready"


# --- run_pipeline ------------------------------------------------------------------

def test_pipeline_failure_does_not_raise_and_is_recorded(log, tmp_path):
    _script(tmp_path / "run_all.py", "import sys\nprint('bad arg')\nsys.exit(2)\n")
    log.begin_session()
    code = rt.run_pipeline({"run": ["run_all.py"]}, tmp_path, log)
    assert code == 2
    assert "run_all.py --mode full exited 2" in log.error_text()
    assert log.read_status()["state"] == "failed"


def test_pipeline_args_carry_mode_force_and_only(log, tmp_path):
    _script(tmp_path / "run_all.py", "import sys\nprint(' '.join(sys.argv[1:]))\n")
    log.begin_session()
    rt.run_pipeline({"run": ["run_all.py"]}, tmp_path, log, mode="smoke", force=True,
                    only=["03"])
    assert log.read_status()["state"] == "ok"


# --- resume ---------------------------------------------------------------------

STAGES = ["00_a", "01_b", "02_c"]


@pytest.fixture
def code(tmp_path: Path) -> Path:
    d = tmp_path / "code"
    d.mkdir()
    for s in STAGES:
        (d / f"{s}.py").write_text(f"# {s}\n", encoding="utf-8")
    (d / "_common.py").write_text("# shared\n", encoding="utf-8")
    (d / "config.yaml").write_text("a: 1\n", encoding="utf-8")
    return d


def _state(tmp_path, code, mode="full", inputs=None):
    return rt.StageState(tmp_path / "state", code, mode,
                         shared=["_*.py", "config.yaml"], inputs=inputs)


def _done_all(st):
    fps = st.fingerprints(STAGES)
    for s in STAGES:
        st.mark_done(s, fps[s], 1.0)
    return fps


def test_unchanged_stages_are_current(tmp_path, code):
    st = _state(tmp_path, code)
    _done_all(st)
    fps = _state(tmp_path, code).fingerprints(STAGES)
    assert all(st.is_current(s, fps[s]) for s in STAGES)


def test_a_code_edit_keeps_the_stage_but_reports_drift(tmp_path, code):
    """A fix that leaves the results alone must not re-run an hour of work."""
    st = _state(tmp_path, code)
    _done_all(st)
    (code / "01_b.py").write_text("# silenced a warning\n", encoding="utf-8")
    st2 = _state(tmp_path, code)
    fps = st2.fingerprints(STAGES)
    assert all(st2.is_current(s, fps[s]) for s in STAGES)
    assert st2.drift("01_b") == "code changed since it ran"
    assert st2.drift("00_a") is None


def test_bumping_results_version_reruns_the_stage_and_everything_after(tmp_path, code):
    st = _state(tmp_path, code)
    _done_all(st)
    (code / "01_b.py").write_text("RESULTS_VERSION = 2  # new QC rule\n", encoding="utf-8")
    st2 = _state(tmp_path, code)
    fps = st2.fingerprints(STAGES)
    assert [s for s in STAGES if st2.is_current(s, fps[s])] == ["00_a"]


def test_spec_results_version_reruns_everything(tmp_path, code):
    _done_all(_state(tmp_path, code))
    st2 = rt.StageState(tmp_path / "state", code, "full", shared=["_*.py", "config.yaml"],
                        results_version_all=1)
    fps = st2.fingerprints(STAGES)
    assert not any(st2.is_current(s, fps[s]) for s in STAGES)


def test_a_state_from_before_keys_is_adopted_once(tmp_path, code):
    """The 00-07 states on Drive predate keys; they must not force a re-run."""
    st = _state(tmp_path, code)
    st.dir.mkdir(parents=True)
    for s in STAGES:
        st.path(s).write_text(json.dumps({"stage": s, "fingerprint": "old", "mode": "full",
                                          "elapsed_s": 5.0}), encoding="utf-8")
    fps = st.fingerprints(STAGES)
    assert all(st.is_current(s, fps[s]) for s in STAGES)
    data = json.loads(st.path("01_b").read_text(encoding="utf-8"))
    assert data["scheme"] == rt.StageState.SCHEME and data["adopted_from_older_state"]
    assert st.drift("01_b") == "ran before its code was recorded"


def test_an_old_smoke_state_is_not_adopted_by_a_full_run(tmp_path, code):
    st = _state(tmp_path, code)
    st.dir.mkdir(parents=True)
    st.path("00_a").write_text(json.dumps({"fingerprint": "x", "mode": "smoke"}), encoding="utf-8")
    fps = st.fingerprints(STAGES)
    assert not st.is_current("00_a", fps["00_a"])


def test_editing_config_or_a_shared_module_reruns_everything(tmp_path, code):
    st = _state(tmp_path, code)
    _done_all(st)
    (code / "config.yaml").write_text("a: 2\n", encoding="utf-8")
    fps = _state(tmp_path, code).fingerprints(STAGES)
    assert not any(st.is_current(s, fps[s]) for s in STAGES)


def test_a_new_input_file_reruns_everything(tmp_path, code):
    src = tmp_path / "SOURCE.json"
    src.write_text('{"sha": 1}', encoding="utf-8")
    st = _state(tmp_path, code, inputs=[src])
    _done_all(st)
    src.write_text('{"sha": 2}', encoding="utf-8")
    fps = _state(tmp_path, code, inputs=[src]).fingerprints(STAGES)
    assert not any(st.is_current(s, fps[s]) for s in STAGES)


def test_smoke_state_never_satisfies_a_full_run(tmp_path, code):
    _done_all(_state(tmp_path, code, mode="smoke"))
    full = _state(tmp_path, code, mode="full")
    fps = full.fingerprints(STAGES)
    assert not any(full.is_current(s, fps[s]) for s in STAGES)


def test_failure_invalidates_the_stage_and_downstream(tmp_path, code):
    st = _state(tmp_path, code)
    fps = _done_all(st)
    st.invalidate_from("01_b", STAGES)
    assert st.is_current("00_a", fps["00_a"])
    assert not st.is_current("01_b", fps["01_b"])
    assert not st.is_current("02_c", fps["02_c"])


def test_state_file_records_key_mode_version_and_code(tmp_path, code):
    st = _state(tmp_path, code)
    fps = _done_all(st)
    data = json.loads(st.path("00_a").read_text(encoding="utf-8"))
    assert data["key"] == fps["00_a"] and data["mode"] == "full"
    assert data["results_version"] == 0 and data["code_sha"] == st.code_sha("00_a")


# --- spec ---------------------------------------------------------------------

def test_load_spec_fills_defaults(tmp_path):
    (tmp_path / "colab.yaml").write_text("title: T\ndrive_folder: x\n", encoding="utf-8")
    spec = rt.load_spec(tmp_path)
    assert spec["gpu"] == "none" and spec["run"] == ["run_all.py"] and spec["probes"] == []


def test_mode_enters_the_chain_at_smoke_from(tmp_path, code):
    _done_all(_state(tmp_path, code, mode="smoke"))
    full = _state(tmp_path, code, mode="full")
    fps = full.fingerprints(STAGES, mode_from="01_b")
    smoke_fps = _state(tmp_path, code, mode="smoke").fingerprints(STAGES, mode_from="01_b")
    assert fps["00_a"] == smoke_fps["00_a"]  # shared by smoke and full
    assert fps["01_b"] != smoke_fps["01_b"] and fps["02_c"] != smoke_fps["02_c"]


def test_custom_stage_file_carries_the_results_version(tmp_path, code):
    other = tmp_path / "src"
    other.mkdir()
    (other / "a.py").write_text("x = 1\n", encoding="utf-8")
    st = rt.StageState(tmp_path / "s", code, "full", stage_file=lambda s: other / "a.py")
    before = st.fingerprints(["a"])["a"]
    (other / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert st.fingerprints(["a"])["a"] == before
    (other / "a.py").write_text("RESULTS_VERSION = 1\nx = 2\n", encoding="utf-8")
    assert st.fingerprints(["a"])["a"] != before


# --- unit checkpoints inside a stage --------------------------------------------------

def test_checkpoints_survive_a_crash_and_reload(tmp_path):
    ck = rt.Checkpoints("07_models", root=tmp_path, key="K1")
    ck.save("temporal_TT_mean_D1", {"rows": [1, 2, 3]})
    again = rt.Checkpoints("07_models", root=tmp_path, key="K1")
    assert again.has("temporal_TT_mean_D1")
    assert again.load("temporal_TT_mean_D1") == {"rows": [1, 2, 3]}
    assert again.units() == ["temporal_TT_mean_D1"]


def test_checkpoints_from_another_key_are_dropped(tmp_path):
    rt.Checkpoints("07_models", root=tmp_path, key="K1").save("u", 1)
    ck = rt.Checkpoints("07_models", root=tmp_path, key="K2")
    assert not ck.has("u")


def test_checkpoint_key_defaults_to_the_runner_env(tmp_path, monkeypatch):
    monkeypatch.setenv(rt.STAGE_KEY_ENV, "FROM_ENV")
    rt.Checkpoints("s", root=tmp_path).save("u", 1)
    assert rt.Checkpoints("s", root=tmp_path, key="FROM_ENV").has("u")


def test_clear_checkpoints_removes_the_stage_folder(tmp_path):
    rt.Checkpoints("s", root=tmp_path / rt.CHECKPOINT_DIR, key="K").save("u", 1)
    rt.clear_checkpoints(tmp_path, "s")
    assert not (tmp_path / rt.CHECKPOINT_DIR / "s").exists()


# --- the generic runner (templates/paper/run_all.py.template) ------------------------

@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    exp = tmp_path / "experiments"
    exp.mkdir()
    (exp / "00_load.py").write_text("print('load')\n", encoding="utf-8")
    (exp / "01_fit.py").write_text("print('fit')\n", encoding="utf-8")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.delenv("EXP_FAST", raising=False)
    return exp


def _logs(tmp_path):
    return tmp_path / "outputs" / "logs"


def test_generic_runner_runs_discovered_stages_and_resumes(pipeline, tmp_path, capsys):
    assert rt.stages_main(pipeline, argv=[]) == 0
    assert (_logs(tmp_path) / "00_load.log").read_text(encoding="utf-8").count("load") >= 1
    capsys.readouterr()
    assert rt.stages_main(pipeline, argv=[]) == 0
    assert capsys.readouterr().out.count("skipped") == 2


def test_generic_runner_records_a_failed_stage(pipeline, tmp_path):
    (pipeline / "01_fit.py").write_text("raise RuntimeError('diverged')\n", encoding="utf-8")
    assert rt.stages_main(pipeline, argv=[]) == 1
    errors = (_logs(tmp_path) / "errors.log").read_text(encoding="utf-8")
    assert "stage 01_fit" in errors and "RuntimeError: diverged" in errors
    status = json.loads((_logs(tmp_path) / "status.json").read_text(encoding="utf-8"))
    assert status["stages"] == {"00_load": "ok", "01_fit": "failed"}


def test_generic_runner_only_forces_the_named_stage(pipeline, tmp_path, capsys):
    rt.stages_main(pipeline, argv=[])
    capsys.readouterr()
    rt.stages_main(pipeline, argv=["--only", "01"])
    out = capsys.readouterr().out
    assert "[01_fit] exit=0" in out and "[00_load]" not in out


def test_generic_runner_with_no_stages_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    (tmp_path / "experiments").mkdir()
    assert rt.stages_main(tmp_path / "experiments", argv=[]) == 0


def test_generic_runner_uses_a_custom_command(pipeline, tmp_path):
    (pipeline / "main.py").write_text(
        "import sys\nprint('stage', sys.argv[2])\n", encoding="utf-8")
    rc = rt.stages_main(pipeline, stages=["prep", "train"],
                        command=lambda s, f: ["main.py", "--stage", s],
                        stage_file=lambda s: pipeline / "main.py", argv=[])
    assert rc == 0
    assert "stage train" in (_logs(tmp_path) / "train.log").read_text(encoding="utf-8")


def test_the_runtime_itself_is_not_part_of_the_fingerprint(tmp_path, code):
    st = _state(tmp_path, code)
    (code / "_colab_runtime.py").write_text("# v1\n", encoding="utf-8")
    before = st.fingerprints(STAGES)
    (code / "_colab_runtime.py").write_text("# v2\n", encoding="utf-8")
    assert _state(tmp_path, code).fingerprints(STAGES) == before


def test_tail_keeps_the_top_of_a_long_traceback(tmp_path):
    """A torch/transformers traceback pushed 07b's own frame out of errors.log."""
    lines = ["stage output"] * 5 + ["Traceback (most recent call last):",
                                    '  File "07b_deep.py", line 328, in run_chronos']
    lines += [f'  File "torch/module.py", line {i}' for i in range(200)]
    lines += ["torch.OutOfMemoryError: CUDA out of memory."]
    p = tmp_path / "s.log"
    p.write_text("\n".join(lines), encoding="utf-8")
    out = rt.tail(p, 30)
    assert "07b_deep.py" in out and "OutOfMemoryError" in out and "omitted" in out
    assert len(out.splitlines()) <= 31

def test_load_spec_reads_a_named_spec(tmp_path):
    (tmp_path / "colab.yaml").write_text("title: main\n", encoding="utf-8")
    (tmp_path / "colab_figures.yaml").write_text(
        "title: figures\nrun: [run_all.py, --only, 11]\n", encoding="utf-8")
    assert rt.load_spec(tmp_path)["title"] == "main"
    spec = rt.load_spec(tmp_path, "colab_figures.yaml")
    assert spec["title"] == "figures" and spec["run"][-1] == 11 and spec["gpu"] == "none"

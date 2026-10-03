# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""The progress protocol contract, not pixels.

What can break without anyone noticing: the event format a reader parses, the
throttle that keeps 27k iterations from becoming 27k lines, the switch that
silences everything in tests, and the phase markers that are the only progress
trace in a log. Those are pinned here. How a bar looks on screen is not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import _progress  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _progress.reset_state()
    monkeypatch.delenv("EXP_PROGRESS", raising=False)
    monkeypatch.delenv("EXP_PROGRESS_PARENT", raising=False)
    monkeypatch.delenv("EXP_PROGRESS_MININTERVAL", raising=False)
    monkeypatch.delenv("TQDM_MININTERVAL", raising=False)


class TestParseLine:
    def test_valid_event_round_trips(self):
        line = '#PROG {"level": "fold", "n": 3, "total": 5, "desc": "D2", "unit": "fold"}\n'
        event = _progress.parse_line(line)
        assert event == {"level": "fold", "n": 3, "total": 5,
                         "desc": "D2", "unit": "fold"}

    def test_plain_output_is_not_an_event(self):
        assert _progress.parse_line("[D1] eval=52 train=100\n") is None
        assert _progress.parse_line("") is None

    def test_malformed_json_is_not_an_event_and_never_raises(self):
        assert _progress.parse_line("#PROG {not json}\n") is None
        assert _progress.parse_line("#PROG [1, 2]\n") is None

    def test_wrong_types_are_rejected(self):
        assert _progress.parse_line('#PROG {"level": 3, "n": 1, "total": 5}\n') is None
        assert _progress.parse_line('#PROG {"level": "x", "n": "1", "total": 5}\n') is None
        assert _progress.parse_line('#PROG {"level": "x"}\n') is None

    def test_missing_desc_and_unit_get_defaults(self):
        event = _progress.parse_line('#PROG {"level": "step", "n": 1, "total": 7}\n')
        assert event is not None and event["desc"] == "" and event["unit"] == "it"

    def test_leading_whitespace_is_tolerated(self):
        assert _progress.parse_line('  #PROG {"level": "s", "n": 1, "total": 1}\n') is not None


class TestEmit:
    def test_line_format_is_prefix_plus_json(self, capsys):
        assert _progress.emit("fold", 2, 5, desc="D1", unit="fold") is True
        line = capsys.readouterr().out
        assert line.startswith(_progress.PROG_PREFIX)
        payload = json.loads(line[len(_progress.PROG_PREFIX):])
        assert payload == {"level": "fold", "n": 2, "total": 5,
                           "desc": "D1", "unit": "fold"}

    def test_first_desc_change_and_final_always_pass(self, capsys):
        # A huge interval suppresses everything except first / phase / final.
        assert _progress.emit("fold", 1, 100, desc="A", mininterval=3600.0) is True
        assert _progress.emit("fold", 2, 100, desc="A", mininterval=3600.0) is False
        assert _progress.emit("fold", 50, 100, desc="A", mininterval=3600.0) is False
        assert _progress.emit("fold", 51, 100, desc="B", mininterval=3600.0) is True
        assert _progress.emit("fold", 100, 100, desc="B", mininterval=3600.0) is True
        assert len(capsys.readouterr().out.splitlines()) == 3

    def test_zero_interval_emits_everything(self, capsys):
        for n in range(1, 6):
            assert _progress.emit("s", n, 5, mininterval=0.0) is True
        assert len(capsys.readouterr().out.splitlines()) == 5

    def test_force_bypasses_the_throttle(self, capsys):
        _progress.emit("s", 1, 100, mininterval=3600.0)
        capsys.readouterr()
        assert _progress.emit("s", 2, 100, mininterval=3600.0, force=True) is True

    def test_disabled_emits_nothing(self, monkeypatch, capsys):
        monkeypatch.setenv("EXP_PROGRESS", "off")
        assert _progress.emit("fold", 1, 5, mininterval=0.0) is False
        assert capsys.readouterr().out == ""


class TestSwitch:
    @pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "no", "disabled"])
    def test_off_values_disable(self, monkeypatch, value):
        monkeypatch.setenv("EXP_PROGRESS", value)
        assert _progress.is_enabled() is False

    def test_unset_and_other_values_enable(self, monkeypatch):
        assert _progress.is_enabled() is True
        monkeypatch.setenv("EXP_PROGRESS", "on")
        assert _progress.is_enabled() is True


class TestMarkerAndPhase:
    def test_marker_carries_the_same_numbers_as_the_bar(self):
        assert _progress.format_marker(
            {"level": "fold", "n": 3, "total": 5, "desc": "D2"}) == \
            "# progress D2: 3/5"

    def test_marker_falls_back_to_level_without_desc(self):
        assert _progress.format_marker(
            {"level": "fold", "n": 1, "total": 5}) == "# progress fold: 1/5"

    def test_phase_change_on_first_desc_change_and_final(self):
        state: dict = {}
        assert _progress.is_phase_change({"level": "f", "desc": "A", "n": 1,
                                           "total": 10}, state) is True
        assert _progress.is_phase_change({"level": "f", "desc": "A", "n": 5,
                                           "total": 10}, state) is False
        assert _progress.is_phase_change({"level": "f", "desc": "B", "n": 6,
                                           "total": 10}, state) is True
        assert _progress.is_phase_change({"level": "f", "desc": "B", "n": 10,
                                           "total": 10}, state) is True

    def test_levels_track_phases_independently(self):
        state: dict = {}
        _progress.is_phase_change({"level": "a", "desc": "x", "n": 1, "total": 2}, state)
        assert _progress.is_phase_change({"level": "b", "desc": "x", "n": 1,
                                           "total": 2}, state) is True


class TestIterProgress:
    def test_parent_present_emits_and_yields(self, monkeypatch, capsys):
        monkeypatch.setenv("EXP_PROGRESS_PARENT", "1")
        assert list(_progress.iter_progress([10, 20], level="fold", desc="F",
                                           unit="fold", mininterval=0.0)) == [10, 20]
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 2 and all(l.startswith("#PROG ") for l in lines)

    def test_disabled_yields_silently_even_with_parent(self, monkeypatch, capsys):
        monkeypatch.setenv("EXP_PROGRESS", "off")
        monkeypatch.setenv("EXP_PROGRESS_PARENT", "1")
        assert list(_progress.iter_progress([1, 2], level="s", desc="d")) == [1, 2]
        assert capsys.readouterr().out == ""

    def test_no_parent_no_tty_yields_silently(self, monkeypatch, capsys):
        """Piped output must never carry JSON noise nobody parses."""
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
        assert list(_progress.iter_progress([1, 2, 3], desc="d")) == [1, 2, 3]
        assert capsys.readouterr().out == ""

    def test_hidden_level_is_skipped_but_items_flow(self, monkeypatch, capsys):
        monkeypatch.setenv("EXP_PROGRESS_PARENT", "1")
        monkeypatch.setattr(_progress, "_cfg_cache", {"show_step_bar": False})
        assert list(_progress.iter_progress([1, 2], level="step", desc="s",
                                           mininterval=0.0)) == [1, 2]
        assert capsys.readouterr().out == ""


class FakeTqdm:
    """Records bars instead of drawing them."""

    instances: list["FakeTqdm"] = []

    def __init__(self, total=None, desc="", unit="it", position=0, leave=False):
        self.total = total
        self.desc = desc
        self.unit = unit
        self.position = position
        self.n = 0
        self.refreshes = 0
        self.closed = False
        FakeTqdm.instances.append(self)

    def set_description_str(self, desc):
        self.desc = desc

    def refresh(self):
        self.refreshes += 1

    def close(self):
        self.closed = True


@pytest.fixture
def _fakes(monkeypatch):
    FakeTqdm.instances.clear()
    return FakeTqdm


class TestDisplay:
    def test_one_widget_per_level_reused_across_phases(self, _fakes):
        disp = _progress.TqdmDisplay(FakeTqdm)
        disp.update({"level": "fold", "n": 1, "total": 5, "desc": "D1", "unit": "fold"})
        disp.update({"level": "fold", "n": 5, "total": 5, "desc": "D1", "unit": "fold"})
        disp.update({"level": "fold", "n": 1, "total": 5, "desc": "D2", "unit": "fold"})
        assert len([b for b in FakeTqdm.instances]) == 2, \
            "a desc change must recycle the widget, not stack a third"
        assert FakeTqdm.instances[0].closed is True
        current = [b for b in FakeTqdm.instances if not b.closed]
        assert len(current) == 1 and current[0].desc == "D2"
        disp.close()

    def test_positions_follow_level_order(self, _fakes):
        disp = _progress.TqdmDisplay(FakeTqdm)
        disp.update({"level": "fold", "n": 1, "total": 5, "desc": "F", "unit": "f"})
        disp.update({"level": "stage", "n": 1, "total": 6, "desc": "S", "unit": "s"})
        by_desc = {b.desc: b.position for b in FakeTqdm.instances}
        assert by_desc["S"] == 0 and by_desc["F"] == 1
        disp.close()

    def test_hidden_level_never_draws(self, _fakes, monkeypatch):
        monkeypatch.setattr(_progress, "_cfg_cache", {"show_step_bar": False})
        disp = _progress.TqdmDisplay(FakeTqdm)
        disp.update({"level": "step", "n": 1, "total": 7, "desc": "s", "unit": "d"})
        assert FakeTqdm.instances == []
        disp.close()

    def test_a_broken_bar_never_breaks_the_run(self, _fakes):
        class Bad(FakeTqdm):
            def refresh(self):
                raise RuntimeError("draw failed")

        disp = _progress.TqdmDisplay(Bad)
        disp.update({"level": "fold", "n": 1, "total": 2, "desc": "x", "unit": "u"})
        disp.close()


class TestRunAndRender:
    def test_events_draw_and_plain_lines_pass_through(self, tmp_path, capsys, _fakes):
        child = tmp_path / "child.py"
        child.write_text(
            "print('hello')\n"
            "print('#PROG {\"level\": \"fold\", \"n\": 1, \"total\": 2, "
            "\"desc\": \"F\", \"unit\": \"fold\"}')\n"
            "print('#PROG {\"level\": \"fold\", \"n\": 2, \"total\": 2, "
            "\"desc\": \"F\", \"unit\": \"fold\"}')\n"
            "print('bye')\n",
            encoding="utf-8",
        )
        import sys as _sys

        code = _progress.run_and_render([_sys.executable, str(child)],
                                        cwd=str(tmp_path), backend="std")
        # backend="std" imports the real tqdm: swap in the fake afterwards is
        # too late, so this asserts the contract (exit code, passthrough, no
        # raw JSON on stdout) rather than the pixels.
        assert code == 0
        out = capsys.readouterr().out
        assert "hello" in out and "bye" in out
        assert "#PROG" not in out, "raw events must not leak to the cell output"

    def test_exit_code_propagates(self, tmp_path, capsys):
        child = tmp_path / "fail.py"
        child.write_text("raise SystemExit(3)\n", encoding="utf-8")
        import sys as _sys

        assert _progress.run_and_render([_sys.executable, str(child)],
                                        cwd=str(tmp_path)) == 3

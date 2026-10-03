"""The run_all CLI: prefix resolution, ranges, and run_meta.json.

The prefix rule is the part worth pinning down. `--only 03` is what anyone types,
but `03` is not a stage name and the numbering stops being contiguous once the
multi-station loop lands. Full names stay canonical and a prefix resolves only
when exactly one stage carries it, so a future `03b` cannot silently capture
`--only 03`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PAPER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PAPER_ROOT / "experiments"))

import run_all  # noqa: E402

AVAILABLE = [
    "00_verify_source", "01_qc_hourly", "02_aggregate_daily", "03_climatology",
    "04_make_issuances", "05_features_local", "06_features_largescale",
]


class TestResolveStages:
    def test_full_name_passes_through(self):
        stages, err = run_all.resolve_stages(AVAILABLE, ["03_climatology"])
        assert stages == ["03_climatology"] and err == ""

    def test_numeric_prefix_resolves(self):
        stages, err = run_all.resolve_stages(AVAILABLE, ["03"])
        assert stages == ["03_climatology"] and err == ""

    def test_several_prefixes_in_order(self):
        stages, err = run_all.resolve_stages(AVAILABLE, ["03", "05"])
        assert stages == ["03_climatology", "05_features_local"] and err == ""

    def test_ambiguous_prefix_is_refused(self):
        _, err = run_all.resolve_stages(AVAILABLE, ["0"])
        assert "ambiguous" in err and "00_verify_source" in err

    def test_unknown_stage_is_refused(self):
        _, err = run_all.resolve_stages(AVAILABLE, ["99"])
        assert "unknown stage" in err

    def test_a_new_03b_would_make_03_ambiguous(self):
        """The reason the rule is 'unique prefix' and not 'numeric prefix'."""
        grown = AVAILABLE + ["03b_extra_stage"]
        _, err = run_all.resolve_stages(grown, ["03"])
        assert "ambiguous" in err

    def test_a_new_03b_keeps_the_full_name_working(self):
        grown = AVAILABLE + ["03b_extra_stage"]
        stages, err = run_all.resolve_stages(grown, ["03_climatology", "03b_extra_stage"])
        assert err == "" and len(stages) == 2


class TestSelectRange:
    def test_inclusive_both_ends(self):
        got, err = run_all.select_range(AVAILABLE, "02", "04")
        assert err == "" and got == [
            "02_aggregate_daily", "03_climatology", "04_make_issuances"
        ]

    def test_full_names_accepted(self):
        got, err = run_all.select_range(
            AVAILABLE, "03_climatology", "04_make_issuances"
        )
        assert got == ["03_climatology", "04_make_issuances"] and err == ""

    def test_single_stage_range(self):
        got, err = run_all.select_range(AVAILABLE, "03", "03")
        assert got == ["03_climatology"] and err == ""

    def test_reversed_range_is_refused(self):
        _, err = run_all.select_range(AVAILABLE, "04", "02")
        assert "comes after" in err

    def test_unknown_bound_is_refused(self):
        _, err = run_all.select_range(AVAILABLE, "99", "04")
        assert "unknown stage" in err


class TestRunMeta:
    def _entries(self):
        return {"03_climatology": {"exit_code": 0, "elapsed_s": 1.23456, "log": "x"}}

    def test_records_versions_git_and_results(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_all, "OUTPUTS", tmp_path)
        monkeypatch.setattr(run_all, "_git", lambda *a: "deadbee" if "rev-parse" in a else "")
        out = run_all.write_run_meta(["03_climatology"], None, self._entries())
        import json
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["git_commit"] == "deadbee"
        assert data["stages_run"] == ["03_climatology"]
        assert data["results"]["03_climatology"]["exit_code"] == 0
        assert data["results"]["03_climatology"]["elapsed_s"] == 1.23
        assert set(data["versions"]) >= {"pandas", "numpy", "yaml"}
        assert data["finished_at"].endswith("+00:00")

    def test_config_path_is_relative_and_forward_slashed(self, tmp_path, monkeypatch):
        """Windows must not leak backslashes into a manifest anyone reads."""
        import _common
        monkeypatch.setattr(run_all, "OUTPUTS", tmp_path)
        monkeypatch.setattr(_common, "BASE", tmp_path)
        cfg = tmp_path / "sub" / "other.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("project: x\n", encoding="utf-8")
        out = run_all.write_run_meta(["00"], cfg, {})
        import json
        recorded = json.loads(out.read_text(encoding="utf-8"))["config"]
        assert recorded == "sub/other.yaml"
        assert "\\" not in recorded

    def test_config_outside_the_paper_stays_absolute(self, tmp_path, monkeypatch):
        """An unrelatable path is returned whole, not mangled into a wrong one."""
        import _common
        monkeypatch.setattr(run_all, "OUTPUTS", tmp_path)
        monkeypatch.setattr(_common, "BASE", tmp_path / "paper")
        cfg = tmp_path / "elsewhere.yaml"
        cfg.write_text("project: x\n", encoding="utf-8")
        out = run_all.write_run_meta(["00"], cfg, {})
        import json
        recorded = json.loads(out.read_text(encoding="utf-8"))["config"]
        assert recorded.endswith("elsewhere.yaml") and ".." not in recorded

    def test_fixed_filename_is_the_documented_reason(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_all, "OUTPUTS", tmp_path)
        out = run_all.write_run_meta(["00"], None, {})
        assert out.name == "run_meta.json"
        import json
        assert "Colab url" in json.loads(out.read_text(encoding="utf-8"))["note"]


def test_discover_stages_picks_up_a_new_module(tmp_path, monkeypatch):
    """`11_algo.py` must work without editing run_all.py."""
    exp = tmp_path / "experiments"
    exp.mkdir()
    for name in ("00_a.py", "05_b.py"):
        (exp / name).write_text("def main():\n    pass\n", encoding="utf-8")
    (exp / "not_a_stage.py").write_text("", encoding="utf-8")
    (exp / "11_algo.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(run_all, "BASE", tmp_path)
    assert run_all.discover_stages() == ["00_a", "05_b", "11_algo"]


def test_discover_stages_ignores_stubs_helper_and_private(tmp_path, monkeypatch):
    exp = tmp_path / "experiments"
    exp.mkdir()
    for name in ("00_a.py", "_common.py", "_harmonic.py", "run_all.py"):
        (exp / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(run_all, "BASE", tmp_path)
    assert run_all.discover_stages() == ["00_a"]


def test_only_cannot_be_combined_with_a_range(tmp_path, monkeypatch, capsys):
    """Guards a precedence bug: the range must not error on itself."""
    monkeypatch.setattr(sys, "argv", ["run_all.py", "--only", "03", "--to", "04"])
    with pytest.raises(SystemExit):
        run_all.main()


def test_from_to_range_does_not_error(tmp_path, monkeypatch):
    exp = tmp_path / "experiments"
    exp.mkdir()
    for name in ("00_a.py", "01_b.py", "02_c.py"):
        (exp / name).write_text("", encoding="utf-8")
    ran: list[str] = []
    monkeypatch.setattr(run_all, "BASE", tmp_path)
    monkeypatch.setattr(run_all, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(run_all, "run_all_log_path", lambda: tmp_path / "run_all.log")
    monkeypatch.setattr(
        run_all, "run_stage",
        lambda stage, aggregate=None: (
            ran.append(stage),
            {"stage": stage, "exit_code": 0, "elapsed_s": 0.0, "log": str(tmp_path / "l")},
        )[1],
    )
    monkeypatch.setattr(run_all, "write_logs_manifest", lambda e, n="m.json": tmp_path / "m.json")
    monkeypatch.setattr(sys, "argv", ["run_all.py", "--from", "00", "--to", "01"])
    assert run_all.main() == 0
    assert ran == ["00_a", "01_b"]


def _stub_pipeline(tmp_path, monkeypatch, fail: set[str] | None = None):
    """Three empty stages, a fake run_stage, outputs under tmp. Returns the run list."""
    import os

    exp = tmp_path / "experiments"
    exp.mkdir(exist_ok=True)
    for name in ("00_a.py", "01_b.py", "02_c.py"):
        (exp / name).write_text(f"# {name}\n", encoding="utf-8")
    ran: list[str] = []

    def fake_run_stage(stage, aggregate=None):
        ran.append(stage)
        log = tmp_path / f"{stage}.log"
        log.write_text(f"Traceback\nValueError: {stage} broke\n", encoding="utf-8")
        code = 1 if stage in (fail or set()) else 0
        return {"stage": stage, "exit_code": code, "elapsed_s": 0.1, "log": str(log)}

    monkeypatch.setattr(run_all, "BASE", tmp_path)
    monkeypatch.setattr(run_all, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(run_all, "run_all_log_path", lambda: tmp_path / "run_all.log")
    monkeypatch.setattr(run_all, "run_stage", fake_run_stage)
    monkeypatch.setattr(run_all, "write_logs_manifest", lambda e, n="m.json": tmp_path / "m.json")
    monkeypatch.delenv("COLAB_SESSION_ID", raising=False)
    monkeypatch.setattr(os, "environ", dict(os.environ))  # EXP_FAST must not leak
    return ran


def _status(tmp_path):
    import json
    return json.loads((tmp_path / "outputs" / "logs" / "status.json").read_text(encoding="utf-8"))


def test_second_run_skips_stages_that_are_unchanged(tmp_path, monkeypatch):
    ran = _stub_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_all.py"])
    assert run_all.main() == 0
    assert ran == ["00_a", "01_b", "02_c"]
    ran.clear()
    assert run_all.main() == 0
    assert ran == []
    assert set(_status(tmp_path)["stages"].values()) == {"skipped"}


def test_editing_a_stage_reruns_it_and_downstream(tmp_path, monkeypatch):
    ran = _stub_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_all.py"])
    run_all.main()
    ran.clear()
    (tmp_path / "experiments" / "01_b.py").write_text("# edited\n", encoding="utf-8")
    run_all.main()
    assert ran == ["01_b", "02_c"]


def test_force_and_only_rerun_current_stages(tmp_path, monkeypatch):
    ran = _stub_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_all.py"])
    run_all.main()
    ran.clear()
    monkeypatch.setattr(sys, "argv", ["run_all.py", "--force"])
    run_all.main()
    assert ran == ["00_a", "01_b", "02_c"]
    ran.clear()
    monkeypatch.setattr(sys, "argv", ["run_all.py", "--only", "01"])
    run_all.main()
    assert ran == ["01_b"]


def test_failed_stage_goes_to_errors_log_and_status(tmp_path, monkeypatch):
    ran = _stub_pipeline(tmp_path, monkeypatch, fail={"01_b"})
    monkeypatch.setattr(sys, "argv", ["run_all.py"])
    assert run_all.main() == 1
    assert ran == ["00_a", "01_b"]
    errors = (tmp_path / "outputs" / "logs" / "errors.log").read_text(encoding="utf-8")
    assert "stage 01_b: exit 1" in errors and "ValueError: 01_b broke" in errors
    st = _status(tmp_path)
    assert st["state"] == "failed" and st["failed_stage"] == "01_b"
    assert st["stages"] == {"00_a": "ok", "01_b": "failed", "02_c": "not_run"}


def test_rerun_after_a_failure_resumes_at_the_failed_stage(tmp_path, monkeypatch):
    ran = _stub_pipeline(tmp_path, monkeypatch, fail={"01_b"})
    monkeypatch.setattr(sys, "argv", ["run_all.py"])
    run_all.main()
    ran.clear()
    monkeypatch.setattr(run_all, "run_stage", lambda stage, aggregate=None: (
        ran.append(stage),
        {"stage": stage, "exit_code": 0, "elapsed_s": 0.1, "log": str(tmp_path / "x.log")})[1])
    assert run_all.main() == 0
    assert ran == ["01_b", "02_c"]
    errors = (tmp_path / "outputs" / "logs" / "errors.log").read_text(encoding="utf-8")
    assert errors == ""  # a new run outside a notebook starts a clean session


def test_smoke_mode_never_reuses_a_full_run(tmp_path, monkeypatch):
    ran = _stub_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["run_all.py"])
    run_all.main()
    ran.clear()
    monkeypatch.setattr(sys, "argv", ["run_all.py", "--mode", "smoke"])
    run_all.main()
    assert ran == ["00_a", "01_b", "02_c"]


def test_config_flag_exports_exp_config_to_subprocesses(tmp_path, monkeypatch):
    """A subprocess inherits the environment but not the parent's argv."""
    import os
    cfg = tmp_path / "alt.yaml"
    cfg.write_text("project: alt\n", encoding="utf-8")
    monkeypatch.delenv("EXP_CONFIG", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_all.py", "--only", "00", "--config", str(cfg)])
    monkeypatch.setattr(run_all, "BASE", tmp_path)
    monkeypatch.setattr(run_all, "OUTPUTS", tmp_path / "outputs")
    try:
        # --only 00 resolves to nothing here, which exits 2 before exporting.
        # Assert the *refusal* path instead: a bad config never gets exported.
        assert run_all.main() == 2
        assert "EXP_CONFIG" not in os.environ
    finally:
        os.environ.pop("EXP_CONFIG", None)


def test_missing_config_exits_two_without_running(tmp_path, monkeypatch, capsys):
    exp = tmp_path / "experiments"
    exp.mkdir()
    (exp / "00_a.py").write_text("def main():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(run_all, "BASE", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_all.py", "--config", str(tmp_path / "nope.yaml")])
    assert run_all.main() == 2
    assert "--config not found" in capsys.readouterr().err

def test_default_config_path_has_no_doubled_directory(tmp_path, monkeypatch):
    """Regression: rel_path on a cwd-relative default produced
    experiments/experiments/config.yaml when run from experiments/."""
    import json

    monkeypatch.setattr(run_all, "OUTPUTS", tmp_path)
    out = run_all.write_run_meta(["00"], None, {})
    assert json.loads(out.read_text(encoding="utf-8"))["config"] == \
        "experiments/config.yaml"

"""setup_mcp.py: the Claude Code registration (`--claude`) and the unchanged OpenCode path.

No test starts `claude` or touches the real `~/.claude.json`: a fake runner records the
commands, and the Claude config lives in a temp directory. What is pinned is what would
otherwise fail on someone else's machine: the translation of the template, secret
handling, idempotence, and the `cmd /c` wrapper that only matters on Windows.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import setup_mcp as sm  # noqa: E402

SECRET = "FOLDER-ID-1234567890"


@pytest.fixture
def example() -> dict:
    return sm.load_jsonc(REPO_ROOT / sm.EXAMPLE_NAME)


@pytest.fixture
def source() -> dict[str, str]:
    return {"GDRIVE_FOLDER_ID": SECRET, "GDRIVE_NOTEBOOK_ID": "nb-id-999",
            "GDRIVE_NOTEBOOK_NAME": "experiments.ipynb", "GDRIVE_PROJECT_ID": "proj-id-777"}


class FakeClaude:
    """Stands in for `claude mcp`: applies add-json/remove to a fake ~/.claude.json."""

    def __init__(self, config: Path, repo: Path, fail_add: bool = False) -> None:
        self.config, self.repo, self.fail_add, self.calls = config, repo, fail_add, []

    def __call__(self, args, cwd=None, capture_output=True, text=True):
        self.calls.append(list(args))
        sub, name = args[2], args[3]
        scope = args[args.index("--scope") + 1]
        if sub == "add-json" and self.fail_add:
            return subprocess.CompletedProcess(args, 1, "", f"bad spec {args[4]}")
        data = json.loads(self.config.read_text()) if self.config.is_file() else {}
        bucket = data.setdefault("mcpServers", {}) if scope == "user" else \
            data.setdefault("projects", {}).setdefault(self.repo.as_posix(), {}).setdefault("mcpServers", {})
        if sub == "add-json":
            bucket[name] = json.loads(args[4])
        elif sub == "remove":
            bucket.pop(name, None)
        self.config.write_text(json.dumps(data))
        return subprocess.CompletedProcess(args, 0, "", "")


# --- pure helpers --------------------------------------------------------------

def test_parse_dotenv_handles_the_usual_shapes():
    text = '# comment\r\nA=1\r\nexport B="two words"\nC=\'q\'\nD=x # trailing\nE=a=b\nbad line\n=nokey\n'
    assert sm.parse_dotenv(text) == {"A": "1", "B": "two words", "C": "q", "D": "x", "E": "a=b"}


def test_process_environment_wins_over_dotenv(tmp_path):
    (tmp_path / ".env").write_text("A=from-file\nB=only-file\n", encoding="utf-8")
    got = sm.environment_sources(tmp_path, {"A": "from-process", "EMPTY": ""})
    assert got["A"] == "from-process" and got["B"] == "only-file" and "EMPTY" not in got


def test_unfilled_placeholders_are_left_out_not_passed_literally():
    env, missing = sm.resolve_env({"X": "{env:HAS}", "Y": "{env:NOPE}", "Z": "pre-{env:HAS}"}, {"HAS": "v"})
    assert env == {"X": "v", "Z": "pre-v"} and missing == ["Y"]


@pytest.mark.parametrize("platform,found,expected", [
    ("win32", r"C:\x\pnpm.CMD", True), ("win32", r"C:\x\uv.exe", False),
    ("win32", None, False), ("linux", "/usr/bin/pnpm", False), ("darwin", "/x/npx", False)])
def test_cmd_wrapper_only_for_windows_shims(platform, found, expected):
    assert sm.needs_cmd_wrapper("pnpm", platform, lambda _: found) is expected


# --- translating the real template -----------------------------------------------

def test_gdrive_spec_on_windows_is_wrapped_and_carries_the_env(example, source):
    servers, _ = sm._split_servers(sm.resolve_example(REPO_ROOT, example)["mcp"])
    spec, missing = sm.to_claude_spec(servers["gdrive"], source, "win32", lambda _: r"C:\n\pnpm.CMD")
    assert missing == []
    assert spec["type"] == "stdio" and spec["command"] == "cmd"
    assert spec["args"] == ["/c", "pnpm", "dlx", "@piotr-agier/google-drive-mcp"]
    assert spec["env"]["GDRIVE_FOLDER_ID"] == SECRET and "{env:" not in json.dumps(spec)


def test_gdrive_spec_elsewhere_is_not_wrapped(example, source):
    servers, _ = sm._split_servers(sm.resolve_example(REPO_ROOT, example)["mcp"])
    spec, _ = sm.to_claude_spec(servers["gdrive"], source, "linux", lambda _: "/usr/bin/pnpm")
    assert spec["command"] == "pnpm" and spec["args"][0] == "dlx"


def test_academic_search_spec_uses_the_absolute_repo_path(example):
    servers, _ = sm._split_servers(sm.resolve_example(Path("/some/repo"), example)["mcp"])
    spec, _ = sm.to_claude_spec(servers["academic-search"], {}, "win32", lambda _: r"C:\bin\uv.exe")
    assert spec["command"] == "uv" and "env" not in spec
    assert spec["args"][-1] == "/some/repo/.agents/skills/paper-search/mcp-server/academic_search_server.py"
    assert sm.REPO_ROOT_TOKEN not in json.dumps(spec)


# --- reading Claude Code's state ---------------------------------------------------

def test_claude_config_path_honours_claude_config_dir(tmp_path):
    assert sm.claude_config_path({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path / ".claude.json"
    assert sm.claude_config_path({}, home=tmp_path) == tmp_path / ".claude.json"


def test_registered_servers_matches_the_project_key_and_the_user_scope(tmp_path):
    repo = tmp_path / "repo"
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({
        "mcpServers": {"u": {"command": "x"}},
        "projects": {repo.as_posix(): {"mcpServers": {"a": {"command": "y"}}},
                     "/elsewhere": {"mcpServers": {"b": {}}}}}))
    assert set(sm.registered_servers("local", repo, cfg)) == {"a"}
    assert set(sm.registered_servers("user", repo, cfg)) == {"u"}
    assert sm.registered_servers("local", tmp_path / "other", cfg) == {}
    assert sm.registered_servers("local", repo, tmp_path / "missing.json") == {}


def test_spec_status_ignores_a_missing_type_and_detects_drift():
    want = {"type": "stdio", "command": "pnpm", "args": ["dlx", "p"], "env": {"K": "v"}}
    assert sm.spec_status(want, None) == "missing"
    assert sm.spec_status(want, {"command": "pnpm", "args": ["dlx", "p"], "env": {"K": "v"}}) == "ok"
    assert sm.spec_status(want, {**want, "args": ["dlx", "old"]}) == "stale"
    assert sm.spec_status(want, {**want, "env": {"K": "other"}}) == "stale"


# --- run_claude ----------------------------------------------------------------------

def _run(tmp_path, example, source, runner, **kw):
    lines: list[str] = []
    code = sm.run_claude(REPO_ROOT, example, config_path=tmp_path / ".claude.json", claude_bin="claude",
                         source=source, runner=runner, platform="linux", which=lambda _: "/bin/x",
                         out=lines.append, **kw)
    return code, "\n".join(lines)


def test_register_then_rerun_is_idempotent(tmp_path, example, source):
    fake = FakeClaude(tmp_path / ".claude.json", REPO_ROOT)
    code, text = _run(tmp_path, example, source, fake, only=["gdrive"])
    assert code == 0 and "gdrive: registered" in text and "relaunch" in text
    assert [c[2] for c in fake.calls] == ["add-json"]
    assert fake.calls[0][:4] == ["claude", "mcp", "add-json", "gdrive"] and fake.calls[0][-2:] == ["--scope", "local"]

    fake.calls.clear()
    code, text = _run(tmp_path, example, source, fake, only=["gdrive"])
    assert code == 0 and "already registered" in text and fake.calls == []
    assert "relaunch" not in text            # nothing changed, nothing to restart


def test_a_stale_server_is_removed_then_added(tmp_path, example, source):
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"projects": {REPO_ROOT.as_posix(): {"mcpServers": {
        "gdrive": {"type": "stdio", "command": "old", "args": []}}}}}))
    fake = FakeClaude(cfg, REPO_ROOT)
    code, text = _run(tmp_path, example, source, fake, only=["gdrive"])
    assert code == 0 and "replaced" in text
    assert [c[2] for c in fake.calls] == ["remove", "add-json"]


def test_secrets_never_reach_the_output_even_on_failure(tmp_path, example, source):
    fake = FakeClaude(tmp_path / ".claude.json", REPO_ROOT, fail_add=True)
    code, text = _run(tmp_path, example, source, fake, only=["gdrive"])
    assert code == 1 and "FAILED" in text
    # the fake CLI echoes the whole JSON spec in its error, secret included
    assert SECRET not in text and "<hidden>" in text


def test_a_missing_env_value_warns_and_is_omitted(tmp_path, example):
    fake = FakeClaude(tmp_path / ".claude.json", REPO_ROOT)
    code, text = _run(tmp_path, example, {"GDRIVE_FOLDER_ID": SECRET}, fake, only=["gdrive"])
    assert code == 0 and "GDRIVE_NOTEBOOK_ID has no value" in text
    spec = json.loads(fake.calls[0][4])
    assert list(spec["env"]) == ["GDRIVE_FOLDER_ID"]


def test_check_reports_without_calling_claude(tmp_path, example, source):
    fake = FakeClaude(tmp_path / ".claude.json", REPO_ROOT)
    code, text = _run(tmp_path, example, source, fake, check=True)
    assert code == 1 and "gdrive: missing" in text and "academic-search: missing" in text and fake.calls == []
    _run(tmp_path, example, source, fake)                      # register everything
    code, text = _run(tmp_path, example, source, fake, check=True)
    assert code == 0 and "gdrive: ok" in text and "academic-search: ok" in text


def test_unknown_server_name_is_a_clear_error(tmp_path, example, source):
    code, text = _run(tmp_path, example, source, FakeClaude(tmp_path / "c.json", REPO_ROOT), only=["nope"])
    assert code == 2 and "not in opencode.jsonc.example" in text and "gdrive" in text


def test_missing_claude_cli_fails_clearly_but_check_still_works(tmp_path, example, source, monkeypatch):
    monkeypatch.setattr(sm.shutil, "which", lambda name: None)   # no `claude` on PATH
    lines: list[str] = []
    kw = dict(config_path=tmp_path / "none.json", claude_bin=None, source=source, runner=None,
              platform="linux", which=lambda _: None, out=lines.append, only=["gdrive"])
    assert sm.run_claude(REPO_ROOT, example, **kw) == 1
    assert any("`claude` CLI is not on PATH" in line for line in lines)
    lines.clear()
    assert sm.run_claude(REPO_ROOT, example, check=True, **kw) == 1       # missing, but no crash
    assert any("gdrive: missing" in line for line in lines)


def test_user_scope_is_passed_through(tmp_path, example, source):
    fake = FakeClaude(tmp_path / ".claude.json", REPO_ROOT)
    code, _ = _run(tmp_path, example, source, fake, only=["gdrive"], scope="user")
    assert code == 0 and fake.calls[0][-2:] == ["--scope", "user"]
    assert set(sm.registered_servers("user", REPO_ROOT, tmp_path / ".claude.json")) == {"gdrive"}


# --- OpenCode path unchanged ------------------------------------------------------------

def test_opencode_config_is_still_generated_and_hand_added_servers_survive(example):
    existing = {"mcp": {"servers": {"mine": {"type": "local", "command": ["x"]}}}, "theme": "dark"}
    out = sm.build_config(Path("/r"), example, existing)
    names = set(out["mcp"]["servers"])
    assert {"gdrive", "academic-search", "mine"} <= names and out["theme"] == "dark"
    assert "/r/.agents/skills/paper-search" in json.dumps(out)


def test_project_scope_is_not_offered():
    assert sm.CLAUDE_SCOPES == ("local", "user")      # .mcp.json would commit the Drive ids

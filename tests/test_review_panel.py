# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Review panel v2 contract: strict YAML checks fail loudly, legacy stays silent."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import paper_validate  # noqa: E402


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _write_min_paper_with_qmd(repo: Path, slug: str = "c99-2026") -> Path:
    root = repo / "papers" / slug
    for d in ("paper/media", "data", "experiments", "notebooks", "build", "reviews/round-1"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "manifest.yaml").write_text(
        f"paper: {slug}\njournal: test-journal\nauthors:\n"
        "  - id: moises\n    role: corresponding\n    order: 1\n",
        encoding="utf-8",
    )
    (root / "paper" / "references.bib").write_text("@article{x, title={x}}\n", encoding="utf-8")
    (root / "paper" / "main.qmd").write_text(
        '---\ntitle: "T"\nformat:\n  pdf: default\n---\n\n# Intro\n\nReal sentence here.\n',
        encoding="utf-8",
    )
    (root / "experiments" / "config.yaml").write_text("project: x\n", encoding="utf-8")
    (root / "reviews" / "round-1" / "comments.yaml").write_text("comments: []\n", encoding="utf-8")
    (root / "reviews" / "round-1" / "responses.yaml").write_text("responses: []\n", encoding="utf-8")
    return root


def _files_block(root: Path) -> str:
    files = {
        "paper/main.qmd": _hash(root / "paper" / "main.qmd"),
        "manifest.yaml": _hash(root / "manifest.yaml"),
        "experiments/config.yaml": _hash(root / "experiments" / "config.yaml"),
    }
    return "\n".join(f'    {k}: "{v}"' for k, v in files.items())


def _write_v2_round(root: Path, quote: str = "Real sentence here.",
                    location: str = "paper/main.qmd:9") -> Path:
    rnd = root / "reviews" / "round-1"
    (rnd / "packet.yaml").write_text(
        "schema_version: 2\npaper: c99-2026\nround: round-1\nscope: full\n"
        "agents: [peer-plan, gate-merge]\ndeferred: []\n"
        'repos:\n  - path: "."\n    commit: "abc1234"\n    dirty: false\n'
        f"files:\n{_files_block(root)}\n",
        encoding="utf-8",
    )
    raw_dir = rnd / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "peer-plan.yaml").write_text(
        "schema_version: 2\nagent: peer-plan\nomitted_count: 0\nfindings:\n"
        "  - id: r1-plan-01\n    severity: major\n    kind: presence\n"
        "    basis: demonstrable\n    title: Something matters\n"
        f'    location: "{location}"\n'
        f'    evidence:\n      - path: "{location.split(":")[0]}"\n        quote: "{quote}"\n'
        '    warrant: "Why it matters."\n    fix: "Fix it."\n',
        encoding="utf-8",
    )
    (rnd / "consolidated.yaml").write_text(
        "schema_version: 2\nfindings:\n"
        "  - id: r1-plan-01\n    severity: major\n    kind: presence\n"
        "    basis: demonstrable\n    title: Something matters\n"
        f'    location: "{location}"\n'
        f'    evidence:\n      - path: "{location.split(":")[0]}"\n        quote: "{quote}"\n'
        '    warrant: "Why it matters."\n    fix: "Fix it."\n'
        "    merged_from: [r1-plan-01]\n"
        "discarded: []\n",
        encoding="utf-8",
    )
    (rnd / "consolidated.md").write_text(
        "<!-- GENERATED from consolidated.yaml (test). Do not edit. -->\n"
        "# Round round-1 — consolidated (full)\n\n"
        "- [major] [demonstrable] r1-plan-01 — Something matters\n"
        f'  `{location}` — Why it matters.\n'
        "  Fix: Fix it.\n",
        encoding="utf-8",
    )
    (rnd / "triage.yaml").write_text(
        "schema_version: 2\ndecisions:\n"
        '  - finding_id: r1-plan-01\n    decision: accept\n    reason: "agreed"\n'
        '    commit: "deadbee"\n',
        encoding="utf-8",
    )
    return rnd


def test_v2_happy_path_passes(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    _write_v2_round(root)
    report = paper_validate.validate_repo(mini_repo)
    assert report.ok, report.errors


def test_v2_invented_quote_fails(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    _write_v2_round(root, quote="This sentence was invented by the model.")
    report = paper_validate.validate_repo(mini_repo)
    assert any("not found verbatim" in e for e in report.errors), report.errors


def test_v2_quote_outside_cited_lines_fails(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    _write_v2_round(root, location="paper/main.qmd:1")
    report = paper_validate.validate_repo(mini_repo)
    assert any("not inside cited lines" in e for e in report.errors), report.errors


def test_v2_lost_raw_id_fails(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    rnd = _write_v2_round(root)
    (rnd / "consolidated.yaml").write_text(
        "schema_version: 2\nfindings: []\ndiscarded: []\n", encoding="utf-8"
    )
    (rnd / "consolidated.md").write_text("<!-- GENERATED -->\n", encoding="utf-8")
    report = paper_validate.validate_repo(mini_repo)
    assert any("neither merged nor discarded" in e for e in report.errors), report.errors


def test_v2_major_without_triage_fails(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    rnd = _write_v2_round(root)
    (rnd / "triage.yaml").write_text("schema_version: 2\ndecisions: []\n", encoding="utf-8")
    report = paper_validate.validate_repo(mini_repo)
    assert any("no triage decision" in e for e in report.errors), report.errors


def test_v2_pending_major_fails(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    rnd = _write_v2_round(root)
    (rnd / "triage.yaml").write_text(
        "schema_version: 2\ndecisions:\n"
        "  - finding_id: r1-plan-01\n    decision: pending\n    reason: ''\n",
        encoding="utf-8",
    )
    report = paper_validate.validate_repo(mini_repo)
    assert any("still 'pending'" in e for e in report.errors), report.errors


def test_v2_legacy_ai_review_is_error(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    rnd = _write_v2_round(root)
    (rnd / "ai-review.yaml").write_text("schema_version: 2\nreviews: []\n", encoding="utf-8")
    report = paper_validate.validate_repo(mini_repo)
    assert any("must not coexist" in e for e in report.errors), report.errors


def test_v2_normative_major_fails(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    rnd = _write_v2_round(root)
    text = (rnd / "raw" / "peer-plan.yaml").read_text(encoding="utf-8")
    (rnd / "raw" / "peer-plan.yaml").write_text(
        text.replace("basis: demonstrable", "basis: normative"), encoding="utf-8"
    )
    text = (rnd / "consolidated.yaml").read_text(encoding="utf-8")
    (rnd / "consolidated.yaml").write_text(
        text.replace("basis: demonstrable", "basis: normative"), encoding="utf-8"
    )
    report = paper_validate.validate_repo(mini_repo)
    assert any("major requires basis: demonstrable" in e for e in report.errors), report.errors


def test_v2_too_many_findings_fails(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    rnd = _write_v2_round(root)
    many = "\n".join(
        f"  - id: r1-plan-{i:02d}\n    severity: minor\n    kind: absence\n"
        "    basis: demonstrable\n    title: T\n    location: \"paper/main.qmd:9\"\n"
        "    searched: [\"paper/main.qmd\"]\n    expected: \"x\"\n"
        "    warrant: \"w\"\n    fix: \"f\""
        for i in range(1, 17)
    )
    (rnd / "raw" / "peer-plan.yaml").write_text(
        "schema_version: 2\nagent: peer-plan\nomitted_count: 0\nfindings:\n" + many + "\n",
        encoding="utf-8",
    )
    report = paper_validate.validate_repo(mini_repo)
    assert any("exceeds 15" in e for e in report.errors), report.errors


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=REPO_ROOT,
                          capture_output=True, text=True)


def test_paper_review_scope_code_only(mini_repo: Path):
    _write_min_paper_with_qmd(mini_repo)
    proc = _run("scripts/paper_review.py", "--root", str(mini_repo),
                "--slug", "c99-2026", "--round", "round-1", "--scope", "code-only")
    assert proc.returncode == 0, proc.stderr
    import yaml

    packet = yaml.safe_load((mini_repo / "papers" / "c99-2026" / "reviews"
                             / "round-1" / "packet.yaml").read_text(encoding="utf-8"))
    assert packet["scope"] == "code-only"
    assert packet["agents"] == ["peer-plan", "peer-results", "peer-reach"]
    assert any(d["item"] == "manuscript-checks" for d in packet["deferred"])


def test_paper_review_full_needs_qmd(mini_repo: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    (root / "paper" / "main.qmd").unlink()
    proc = _run("scripts/paper_review.py", "--root", str(mini_repo),
                "--slug", "c99-2026", "--round", "round-1", "--scope", "full")
    assert proc.returncode != 0
    assert "code-only" in (proc.stderr + proc.stdout)


def test_paper_review_only_selector(mini_repo: Path):
    _write_min_paper_with_qmd(mini_repo)
    proc = _run("scripts/paper_review.py", "--root", str(mini_repo),
                "--slug", "c99-2026", "--round", "round-1", "--only", "peer-plan")
    assert proc.returncode == 0, proc.stderr
    import yaml

    packet = yaml.safe_load((mini_repo / "papers" / "c99-2026" / "reviews"
                             / "round-1" / "packet.yaml").read_text(encoding="utf-8"))
    assert packet["agents"] == ["peer-plan"]


def test_paper_review_rejects_unknown_selector(mini_repo: Path):
    _write_min_paper_with_qmd(mini_repo)
    proc = _run("scripts/paper_review.py", "--root", str(mini_repo),
                "--slug", "c99-2026", "--round", "round-1", "--only", "nope-agent")
    assert proc.returncode != 0


def test_render_review_roundtrip(mini_repo: Path, tmp_path: Path):
    root = _write_min_paper_with_qmd(mini_repo)
    rnd = _write_v2_round(root)
    (rnd / "consolidated.md").unlink()
    proc = _run("scripts/render_review.py", "--root", str(mini_repo),
                "--slug", "c99-2026", "--round", "round-1")
    assert proc.returncode == 0, proc.stderr
    assert "r1-plan-01" in (rnd / "consolidated.md").read_text(encoding="utf-8")
    proc = _run("scripts/render_review.py", "--root", str(mini_repo),
                "--slug", "c99-2026", "--round", "round-1", "--check")
    assert proc.returncode == 0, proc.stdout


def test_review_command_twins_match():
    opencode = (REPO_ROOT / ".opencode" / "commands" / "review.md").read_text(encoding="utf-8")
    claude = (REPO_ROOT / ".claude" / "commands" / "review.md").read_text(encoding="utf-8")

    def body(text: str) -> str:
        core = text.split("---\n", 2)[2]
        for n in ("rev-design", "rev-refs", "rev-style", "peer-plan",
                  "peer-results", "peer-reach", "gate-claims", "gate-merge"):
            core = core.replace(f"Task(subagent_type={n})", f"@{n}")
        return core

    assert body(opencode) == body(claude)


def test_link_agents_check_passes(tmp_path: Path):
    repo = tmp_path / "repo"
    canon = repo / ".agents" / "agents"
    canon.mkdir(parents=True)
    (canon / "models.yaml").write_text(
        "strong:\n  claude: opus\n  opencode: inherit\n", encoding="utf-8"
    )
    (canon / "peer-plan.md").write_text(
        "---\nname: peer-plan\ndescription: Test colleague.\n"
        "access: read-only\nmodel_tier: strong\n---\n\n# peer-plan\n",
        encoding="utf-8",
    )
    proc = _run("scripts/link_agents.py", "--root", str(repo))
    assert proc.returncode == 0, proc.stdout
    assert (repo / ".claude" / "agents" / "peer-plan.md").is_file()
    assert (repo / ".opencode" / "agents" / "peer-plan.md").is_file()
    proc = _run("scripts/link_agents.py", "--root", str(repo), "--check")
    assert proc.returncode == 0, proc.stdout


def test_link_agents_check_catches_stale(tmp_path: Path):
    repo = tmp_path / "repo"
    canon = repo / ".agents" / "agents"
    canon.mkdir(parents=True)
    (canon / "models.yaml").write_text(
        "strong:\n  claude: opus\n  opencode: inherit\n", encoding="utf-8"
    )
    (canon / "peer-plan.md").write_text(
        "---\nname: peer-plan\ndescription: Test colleague.\n"
        "access: read-only\nmodel_tier: strong\n---\n\n# peer-plan\n",
        encoding="utf-8",
    )
    assert _run("scripts/link_agents.py", "--root", str(repo)).returncode == 0
    (repo / ".claude" / "agents" / "peer-plan.md").write_text("tampered\n", encoding="utf-8")
    proc = _run("scripts/link_agents.py", "--root", str(repo), "--check")
    assert proc.returncode != 0
    assert "stale" in proc.stdout


def test_link_agents_check_fails_on_unmapped_tier(tmp_path: Path):
    repo = tmp_path / "repo"
    canon = repo / ".agents" / "agents"
    canon.mkdir(parents=True)
    (canon / "models.yaml").write_text("light:\n  claude: haiku\n", encoding="utf-8")
    (canon / "peer-plan.md").write_text(
        "---\nname: peer-plan\ndescription: Test colleague.\n"
        "access: read-only\nmodel_tier: strong\n---\n\n# peer-plan\n",
        encoding="utf-8",
    )
    proc = _run("scripts/link_agents.py", "--root", str(repo), "--check")
    assert proc.returncode != 0
    assert "unmapped" in proc.stdout

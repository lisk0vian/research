#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""paper_validate.py — enforce the repository structure contract.

Runs standalone (`python scripts/paper_validate.py`) and is imported by the test
suite so the same rules gate every pull request in CI. Exit code 0 = valid,
1 = at least one error.

Usage:
    python scripts/paper_validate.py [--root .] [--json] [--quiet]
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402
import journal_guide  # noqa: E402
from _structure import (  # noqa: E402
    ARTEFACT_SCOPE_DIRS,
    FORBIDDEN_ARTEFACT_EXTENSIONS,
    MIGRATION_MARKER,
    REQUIRED_DIRS,
    REQUIRED_PAPER_FILES,
    REVIEW_BASES,
    REVIEW_CONSOLIDATED_MD,
    REVIEW_CONSOLIDATED_YAML,
    REVIEW_DECISIONS,
    REVIEW_EVIDENCE_MAX,
    REVIEW_FILES,
    REVIEW_FIX_MAX,
    REVIEW_KINDS,
    REVIEW_LEGACY_AI_REVIEW,
    REVIEW_MAX_FINDINGS,
    REVIEW_OBJECTS,
    REVIEW_PACKET_FILE,
    REVIEW_PENDING,
    REVIEW_QUOTE_MAX,
    REVIEW_RAW_DIR,
    REVIEW_REJECTED_DIR,
    REVIEW_SCHEMA_VERSION,
    REVIEW_SCOPES,
    REVIEW_SEVERITIES,
    REVIEW_TITLE_MAX,
    REVIEW_TRIAGE_FILE,
    REVIEW_WARRANT_MAX,
    SECRET_PATTERNS,
    SKILL_REGISTRY,
    SLUG_PATTERN,
)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}" if where else msg)

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}" if where else msg)

    def add(self, level: str, where: str, msg: str) -> None:
        """Record an issue whose severity comes from elsewhere (journal_guide)."""
        (self.error if level == "error" else self.warn)(where, msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def _front_matter(text: str) -> str | None:
    """Return the YAML front-matter block of a .qmd/.md file, or None."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.DOTALL)
    return m.group(1) if m else None


def _parse_simple_yaml(text: str) -> dict:
    """Parse a tiny YAML mapping without requiring PyYAML at import time."""
    try:
        import yaml

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        # Fallback: only top-level "key:" lines (enough for a front-matter gate).
        out = {}
        for line in text.splitlines():
            m = re.match(r"^([A-Za-z_][\w-]*):", line)
            if m:
                out[m.group(1)] = True
        return out


# --------------------------------------------------------------------------- #
# Repo-level catalogs
# --------------------------------------------------------------------------- #
def check_authors(repo: Path, rep: Report) -> None:
    authors_dir = repo / "authors"
    if not authors_dir.is_dir():
        rep.error("authors/", "missing (shared author catalog)")
        return
    for f in sorted(authors_dir.glob("*.yaml")):
        data = load_yaml(f)
        where = f"authors/{f.name}"
        if data.get("id") != f.stem:
            rep.error(where, f"id '{data.get('id')}' must equal filename '{f.stem}'")
        if not data.get("name"):
            rep.error(where, "missing 'name'")


def check_journals(repo: Path, rep: Report) -> None:
    journals_dir = repo / "templates" / "journals"
    if not journals_dir.is_dir():
        rep.error("templates/journals/", "missing (shared journal catalog)")
        return
    for d in sorted(p for p in journals_dir.iterdir() if p.is_dir()):
        # `_shared/` holds pages mirrored once for every journal, not a journal,
        # so it has no type.yaml. Underscore-prefixed folders opt out of the
        # per-journal contract the same way.
        if d.name.startswith("_"):
            continue
        type_yaml = d / "type.yaml"
        if not type_yaml.is_file():
            rep.error(f"templates/journals/{d.name}/", "missing type.yaml")
            continue
        data = load_yaml(type_yaml)
        if not data.get("journal"):
            rep.error(f"templates/journals/{d.name}/type.yaml", "missing 'journal' name")
        # A journal that declares `guide:` is auditable; one that does not is
        # simply opt-in and reports nothing.
        for issue in journal_guide.check_guide(repo, d.name).issues:
            rep.add(issue.level, issue.where, issue.message)
    # Cross-guide checks run once, not per journal: duplicates and shared-file
    # integrity are, by definition, never visible from a single journal.
    for issue in journal_guide.check_duplicates(repo).issues:
        rep.add(issue.level, issue.where, issue.message)
    for issue in journal_guide.check_shared_files(repo).issues:
        rep.add(issue.level, issue.where, issue.message)


def check_skills(repo: Path, rep: Report) -> None:
    skills_dir = repo / ".agents" / "skills"
    if not skills_dir.is_dir():
        rep.warn(".agents/skills/", "missing")
        return
    for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            rep.error(f".agents/skills/{d.name}/", "missing SKILL.md")
            continue
        fm = _front_matter(skill_md.read_text(encoding="utf-8")) or ""
        name = _parse_simple_yaml(fm).get("name")
        if name != d.name:
            rep.error(
                f".agents/skills/{d.name}/SKILL.md",
                f"front-matter name '{name}' must equal folder name '{d.name}'",
            )
        if d.name not in SKILL_REGISTRY:
            rep.warn(f".agents/skills/{d.name}/", "not in the documented skill registry")


def check_claude_links(repo: Path, rep: Report) -> None:
    """Claude Code reads `.claude/skills/`; OpenCode reads `.agents/skills/` directly.

    The canonical skills are `.agents/skills/`, and `scripts/link_skills.py`
    mirrors them into `.claude/skills/` (a SessionStart hook keeps them fresh).
    Warn when that mirror is missing or out of date. Skipped on CI, where the
    links are machine-local and intentionally absent.
    """
    canonical = repo / ".agents" / "skills"
    link_dir = repo / ".claude" / "skills"
    if not canonical.is_dir():
        return
    skills = sorted(p.name for p in canonical.iterdir() if p.is_dir())

    if not link_dir.exists():
        if not os.environ.get("CI"):
            rep.warn(
                ".claude/skills/",
                "not set up — Claude Code reads .claude/skills (OpenCode reads "
                ".agents/skills directly); run `python scripts/link_skills.py`",
            )
        return

    missing = [s for s in skills if not (link_dir / s / "SKILL.md").is_file()]
    if missing:
        rep.warn(
            ".claude/skills/",
            f"missing links for: {', '.join(missing)} — run `python scripts/link_skills.py`",
        )
    stale = sorted(p.name for p in link_dir.iterdir() if p.name not in skills and os.path.lexists(p))
    if stale:
        rep.warn(
            ".claude/skills/",
            f"stale links: {', '.join(stale)} — run `python scripts/link_skills.py`",
        )


def check_agent_links(repo: Path, rep: Report) -> None:
    """Generated subagents for both tools; warn when out of sync. Skip on CI."""
    canon = repo / ".agents" / "agents"
    if not canon.is_dir():
        return
    names = sorted(p.stem for p in canon.glob("*.md"))
    if os.environ.get("CI"):
        return
    for label, directory, suffix in (
        ("claude", repo / ".claude" / "agents", ".md"),
        ("opencode", repo / ".opencode" / "agents", ".md"),
    ):
        if not directory.is_dir():
            rep.warn(
                f".{label}/agents/",
                f"not generated — run `python scripts/link_agents.py`",
            )
            continue
        missing = [n for n in names if not (directory / f"{n}{suffix}").is_file()]
        if missing:
            rep.warn(
                f".{label}/agents/",
                f"missing generated agents: {', '.join(missing)} — run `python scripts/link_agents.py`",
            )


def check_no_tracked_secrets(repo: Path, rep: Report) -> None:
    if not (repo / ".git").exists():
        return
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=repo, capture_output=True, text=True, timeout=30
        )
    except Exception as exc:  # pragma: no cover
        rep.warn("git", f"could not list tracked files: {exc}")
        return
    for line in out.stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        base = path.lower()
        if base.endswith(".env.example"):
            continue
        names = [path, Path(path).name]
        if any(fnmatch.fnmatch(n.lower(), pat) for pat in SECRET_PATTERNS for n in names):
            rep.error(path, "looks like a secret/credential and must not be tracked")
        if Path(path).name == ".env":
            rep.error(path, ".env must not be committed (use .env.example)")


# --------------------------------------------------------------------------- #
# Per-paper checks
# --------------------------------------------------------------------------- #
def check_paper(repo: Path, root: Path, rep: Report) -> None:
    slug = root.name
    where = f"papers/{slug}"

    if not re.match(SLUG_PATTERN, slug):
        rep.error(where, f"folder name '{slug}' must be lowercase kebab/code (regex {SLUG_PATTERN})")

    for d in REQUIRED_DIRS:
        if not (root / d).is_dir():
            rep.error(where, f"missing required directory '{d}/'")

    if not (root / "paper" / "media").is_dir():
        rep.warn(where, "missing 'paper/media/' (figures folder)")

    for f in REQUIRED_PAPER_FILES:
        if not (root / f).is_file():
            rep.error(where, f"missing required file '{f}'")

    has_qmd = (root / "paper" / "main.qmd").is_file()
    has_marker = (root / MIGRATION_MARKER).is_file()
    if not has_qmd and not has_marker:
        rep.error(where, "need paper/main.qmd (or MIGRATION_PENDING.txt while migrating)")

    check_manifest(repo, root, rep)
    if has_qmd:
        check_qmd(root, rep)
    check_artefacts(root, rep)
    check_reviews(root, rep)
    check_colab(root, rep)
    rep.checked.append(where)


# Agent instructions that must not sit in experiments/ of a Colab paper:
# everything there is synced to Drive code/ and copied into the runtime
# (COLAB.md). Local config (.env, opencode.jsonc) is fine: the sync skips it.
COLAB_FORBIDDEN_IN_EXPERIMENTS = ("AGENTS.md", "CLAUDE.md")


def check_colab(root: Path, rep: Report) -> None:
    """A paper with experiments/colab.yaml follows the Colab standard (COLAB.md)."""
    slug = root.name
    if not (root / "experiments" / "colab.yaml").is_file():
        rep.warn(f"papers/{slug}", "no experiments/colab.yaml: not on the Colab standard "
                 "(COLAB.md); paper_new.py adds it")
        return
    where = f"papers/{slug}/notebooks"
    try:
        from paper_notebook import check as notebook_check
    except Exception as exc:  # noqa: BLE001
        rep.error(where, f"cannot load scripts/paper_notebook.py: {exc}")
        return
    try:
        problems = notebook_check(root, slug)
    except BaseException as exc:  # noqa: BLE001 - load_spec exits on a bad spec
        problems = [f"experiments/colab.yaml unreadable: {exc}"]
    for p in problems:
        rep.error(where, p)
    for name in COLAB_FORBIDDEN_IN_EXPERIMENTS:
        if (root / "experiments" / name).exists():
            rep.error(f"papers/{slug}/experiments/{name}",
                      "agent instructions would be synced to Drive code/; "
                      "keep them in the paper folder, outside experiments/")


def check_manifest(repo: Path, root: Path, rep: Report) -> None:
    slug = root.name
    where = f"papers/{slug}/manifest.yaml"
    mp = root / "manifest.yaml"
    if not mp.is_file():
        return
    try:
        data = load_yaml(mp)
    except Exception as exc:
        rep.error(where, f"unparseable YAML: {exc}")
        return

    if data.get("paper") != slug:
        rep.error(where, f"'paper' must be '{slug}', found '{data.get('paper')}'")

    journal = data.get("journal")
    if not journal:
        rep.error(where, "missing 'journal'")
    elif not (repo / "templates" / "journals" / str(journal) / "type.yaml").is_file():
        rep.error(where, f"journal '{journal}' not found in templates/journals/")

    authors = data.get("authors")
    if not isinstance(authors, list) or not authors:
        rep.error(where, "'authors' must be a non-empty list")
        return
    seen_orders = set()
    for i, a in enumerate(authors):
        tag = f"{where} authors[{i}]"
        if not isinstance(a, dict):
            rep.error(tag, "must be a mapping with id/role/order")
            continue
        for key in ("id", "role", "order"):
            if a.get(key) in (None, ""):
                rep.error(tag, f"missing '{key}'")
        aid = a.get("id")
        if aid and not (repo / "authors" / f"{aid}.yaml").is_file():
            rep.error(tag, f"author id '{aid}' has no authors/{aid}.yaml")
        order = a.get("order")
        if order in seen_orders:
            rep.error(tag, f"duplicate author order {order}")
        seen_orders.add(order)


def check_qmd(root: Path, rep: Report) -> None:
    slug = root.name
    qmd = root / "paper" / "main.qmd"
    where = f"papers/{slug}/paper/main.qmd"
    fm = _front_matter(qmd.read_text(encoding="utf-8"))
    if fm is None:
        rep.error(where, "missing YAML front-matter block (--- ... ---)")
        return
    data = _parse_simple_yaml(fm)
    if not data.get("title"):
        rep.error(where, "front-matter missing 'title'")
    if not data.get("format"):
        rep.error(where, "front-matter missing 'format'")


def check_artefacts(root: Path, rep: Report) -> None:
    slug = root.name
    for scope in ARTEFACT_SCOPE_DIRS:
        base = root / scope
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if f.is_file() and f.suffix.lower() in FORBIDDEN_ARTEFACT_EXTENSIONS:
                rep.error(
                    f"papers/{slug}/{f.relative_to(root).as_posix()}",
                    f"{f.suffix} is banned in {scope}/ "
                    "(numbers must live in CSV/JSON, not spreadsheets)",
                )


def check_reviews(root: Path, rep: Report) -> None:
    slug = root.name
    reviews = root / "reviews"
    if not reviews.is_dir():
        return
    round_dirs = sorted(p for p in reviews.iterdir() if p.is_dir())
    if len(round_dirs) > 3:
        rep.warn(
            f"papers/{slug}/reviews/",
            f"{len(round_dirs)} rounds found; panel limit is 3 "
            "(a justified 4th round warns but does not fail)",
        )
    for round_dir in round_dirs:
        if _round_is_v2(round_dir):
            _check_review_round_v2(root, round_dir, rep)
        else:
            for fname in REVIEW_FILES:
                f = round_dir / fname
                if not f.is_file():
                    rep.warn(
                        f"papers/{slug}/reviews/{round_dir.name}/",
                        f"missing '{fname}'",
                    )


def _round_is_v2(round_dir: Path) -> bool:
    """Strict checks apply only when schema_version == 2 is present."""
    for fname in (REVIEW_PACKET_FILE, REVIEW_TRIAGE_FILE, REVIEW_CONSOLIDATED_YAML):
        f = round_dir / fname
        if not f.is_file():
            continue
        try:
            data = load_yaml(f)
        except Exception:
            continue
        if data.get("schema_version") == REVIEW_SCHEMA_VERSION:
            return True
    return False


def _normalize_text(text: str) -> str:
    """NFKC + collapsed whitespace. No fuzzy matching: a paraphrase must fail."""
    import re as _re
    import unicodedata as _ud

    norm = _ud.normalize("NFKC", text)
    return _re.sub(r"\s+", " ", norm).strip()


def _sha256_normalized(path: Path) -> str:
    import hashlib as _hl

    return _hl.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _parse_location(loc: str) -> tuple[str, int, int] | None:
    """'paper/main.qmd:12' or 'paper/main.qmd:12-18' -> (path, first, last)."""
    import re as _re

    m = _re.match(r"^(.+?):(\d+)(?:-(\d+))?$", str(loc or "").strip())
    if not m:
        return None
    rel, first, last = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
    if first < 1 or last < first:
        return None
    return rel, first, last


def _finding_id_ok(fid: str) -> bool:
    """Word-based ids: r<round>-<object>-<nn>, objects from REVIEW_OBJECTS."""
    import re as _re

    m = _re.match(r"^r\d+-([a-z]+)-\d+$", str(fid or ""))
    return bool(m) and m.group(1) in REVIEW_OBJECTS


def _check_lengths(f: dict, tag: str, rep: Report) -> None:
    for key, limit in (("title", REVIEW_TITLE_MAX), ("warrant", REVIEW_WARRANT_MAX),
                       ("fix", REVIEW_FIX_MAX)):
        value = f.get(key)
        if isinstance(value, str) and len(value) > limit:
            rep.error(tag, f"'{key}' exceeds {limit} chars ({len(value)})")


def _check_review_round_v2(root: Path, round_dir: Path, rep: Report) -> None:
    slug = root.name
    where = f"papers/{slug}/reviews/{round_dir.name}"

    if (round_dir / REVIEW_LEGACY_AI_REVIEW).is_file():
        try:
            legacy = load_yaml(round_dir / REVIEW_LEGACY_AI_REVIEW)
        except Exception:
            legacy = {}
        if legacy.get("schema_version") == REVIEW_SCHEMA_VERSION or (
            round_dir / REVIEW_PACKET_FILE
        ).is_file():
            rep.error(
                where,
                f"'{REVIEW_LEGACY_AI_REVIEW}' must not coexist with a v2 round "
                f"(use '{REVIEW_CONSOLIDATED_YAML}' instead)",
            )

    packet_path = round_dir / REVIEW_PACKET_FILE
    if not packet_path.is_file():
        rep.error(where, f"missing '{REVIEW_PACKET_FILE}' (v2 round)")
        return
    try:
        packet = load_yaml(packet_path)
    except Exception as exc:
        rep.error(f"{where}/{REVIEW_PACKET_FILE}", f"unparseable YAML: {exc}")
        return
    if packet.get("schema_version") != REVIEW_SCHEMA_VERSION:
        rep.error(f"{where}/{REVIEW_PACKET_FILE}", "missing 'schema_version: 2'")
        return
    if not isinstance(packet.get("repos"), list) or not packet["repos"]:
        rep.error(f"{where}/{REVIEW_PACKET_FILE}", "'repos' must be a non-empty list")
    files = packet.get("files")
    if not isinstance(files, dict) or not files:
        rep.error(f"{where}/{REVIEW_PACKET_FILE}", "'files' must be a non-empty mapping")
        files = {}
    scope = packet.get("scope", "full")
    if scope not in REVIEW_SCOPES:
        rep.error(f"{where}/{REVIEW_PACKET_FILE}", f"'scope' must be one of {list(REVIEW_SCOPES)}")
        scope = "full"
    if scope == "full" and "paper/main.qmd" not in files:
        rep.error(f"{where}/{REVIEW_PACKET_FILE}", "'files' must anchor 'paper/main.qmd' in full scope")
    agents = packet.get("agents")
    if not isinstance(agents, list) or not agents:
        rep.error(f"{where}/{REVIEW_PACKET_FILE}", "'agents' must be a non-empty list of what ran")
    deferred = packet.get("deferred") or []
    if scope == "code-only" and not deferred:
        rep.error(f"{where}/{REVIEW_PACKET_FILE}", "'deferred' must list what code-only skips (e.g. manuscript checks)")

    raw_dir = round_dir / REVIEW_RAW_DIR
    raw_ids: set[str] = set()
    if not raw_dir.is_dir() or not [p for p in raw_dir.glob("*.yaml") if p.is_file()]:
        rep.error(where, f"missing '{REVIEW_RAW_DIR}/*.yaml' (v2 round)")
    else:
        for raw_file in sorted(p for p in raw_dir.glob("*.yaml") if p.is_file()):
            _check_raw_file(root, raw_file, files, raw_ids, rep)

    con_path = round_dir / REVIEW_CONSOLIDATED_YAML
    ai_ids: set[str] = set()
    ai_majors: set[str] = set()
    if not con_path.is_file():
        rep.error(where, f"missing '{REVIEW_CONSOLIDATED_YAML}' (v2 round)")
    else:
        try:
            ai_data = load_yaml(con_path)
        except Exception as exc:
            rep.error(f"{where}/{REVIEW_CONSOLIDATED_YAML}", f"unparseable YAML: {exc}")
            ai_data = {}
        if ai_data.get("schema_version") != REVIEW_SCHEMA_VERSION:
            rep.error(f"{where}/{REVIEW_CONSOLIDATED_YAML}", "missing 'schema_version: 2'")
        else:
            merged_refs: set[str] = set()
            for i, f in enumerate(ai_data.get("findings") or []):
                tag = f"{where}/{REVIEW_CONSOLIDATED_YAML} findings[{i}]"
                fid = f.get("id") if isinstance(f, dict) else None
                if not fid:
                    rep.error(tag, "missing 'id'")
                    continue
                if not _finding_id_ok(fid):
                    rep.error(tag, f"id '{fid}' must look like 'r1-<object>-<nn>' ({'/'.join(REVIEW_OBJECTS)})")
                if fid in ai_ids:
                    rep.error(tag, f"duplicate finding id '{fid}'")
                ai_ids.add(str(fid))
                if f.get("severity") == "major":
                    ai_majors.add(str(fid))
                if "addressed" in f:
                    rep.error(tag, "'addressed' is banned in v2 (triage.yaml owns state)")
                for key in ("severity", "kind", "basis", "title", "location", "warrant", "fix", "merged_from"):
                    if f.get(key) in (None, "", [], {}):
                        rep.error(tag, f"missing '{key}'")
                if f.get("severity") not in REVIEW_SEVERITIES:
                    rep.error(tag, f"severity must be one of {list(REVIEW_SEVERITIES)}")
                if f.get("kind") not in REVIEW_KINDS:
                    rep.error(tag, f"kind must be one of {list(REVIEW_KINDS)}")
                if f.get("basis") not in REVIEW_BASES:
                    rep.error(tag, f"basis must be one of {list(REVIEW_BASES)}")
                if f.get("severity") == "major" and f.get("basis") != "demonstrable":
                    rep.error(tag, "MVP: major requires basis: demonstrable (normative is always minor)")
                merged = f.get("merged_from")
                if not isinstance(merged, list) or not merged:
                    rep.error(tag, "'merged_from' must be a non-empty list of raw ids")
                else:
                    merged_refs.update(str(x) for x in merged)
                _check_lengths(f, tag, rep)
                _check_evidence(root, f, files, tag, rep)
            for i, d in enumerate(ai_data.get("discarded") or []):
                tag = f"{where}/{REVIEW_CONSOLIDATED_YAML} discarded[{i}]"
                if not isinstance(d, dict) or not d.get("raw_id"):
                    rep.error(tag, "missing 'raw_id'")
                    continue
                if not d.get("reason"):
                    rep.error(tag, "missing 'reason'")
            discarded_ids = {
                str(d.get("raw_id"))
                for d in (ai_data.get("discarded") or [])
                if isinstance(d, dict) and d.get("raw_id")
            }
            for rid in sorted(raw_ids):
                if rid not in merged_refs and rid not in discarded_ids:
                    rep.error(
                        f"{where}/{REVIEW_CONSOLIDATED_YAML}",
                        f"raw finding '{rid}' is neither merged nor discarded "
                        "(the editor must not lose a finding in silence)",
                    )
            for ref in sorted(merged_refs):
                if ref not in raw_ids:
                    rep.error(f"{where}/{REVIEW_CONSOLIDATED_YAML}", f"merged_from '{ref}' has no raw finding")
            for rid in sorted(discarded_ids):
                if rid not in raw_ids:
                    rep.error(f"{where}/{REVIEW_CONSOLIDATED_YAML}", f"discarded '{rid}' has no raw finding")
        md_path = round_dir / REVIEW_CONSOLIDATED_MD
        if not md_path.is_file():
            rep.error(where, f"missing '{REVIEW_CONSOLIDATED_MD}' (generated by render_review.py)")
        else:
            try:
                md_text = md_path.read_text(encoding="utf-8")
            except OSError as exc:
                rep.error(f"{where}/{REVIEW_CONSOLIDATED_MD}", f"cannot read: {exc}")
                md_text = ""
            for fid in sorted(ai_ids):
                if fid not in md_text:
                    rep.error(
                        f"{where}/{REVIEW_CONSOLIDATED_MD}",
                        f"id '{fid}' missing from the generated .md (regenerate it)",
                    )

    tri_path = round_dir / REVIEW_TRIAGE_FILE
    decided: set[str] = set()
    if not tri_path.is_file():
        rep.error(where, f"missing '{REVIEW_TRIAGE_FILE}' (v2 round)")
    else:
        try:
            tri_data = load_yaml(tri_path)
        except Exception as exc:
            rep.error(f"{where}/{REVIEW_TRIAGE_FILE}", f"unparseable YAML: {exc}")
            tri_data = {}
        if tri_data.get("schema_version") != REVIEW_SCHEMA_VERSION:
            rep.error(f"{where}/{REVIEW_TRIAGE_FILE}", "missing 'schema_version: 2'")
        else:
            for i, d in enumerate(tri_data.get("decisions") or []):
                tag = f"{where}/{REVIEW_TRIAGE_FILE} decisions[{i}]"
                if not isinstance(d, dict) or not d.get("finding_id"):
                    rep.error(tag, "missing 'finding_id'")
                    continue
                fid = str(d["finding_id"])
                if fid in decided:
                    rep.error(tag, f"duplicate decision for '{fid}'")
                decided.add(fid)
                decision = d.get("decision")
                if decision not in (*REVIEW_DECISIONS, REVIEW_PENDING):
                    rep.error(tag, f"decision must be one of {[*REVIEW_DECISIONS, REVIEW_PENDING]}")
                if decision in ("reject", "defer") and not d.get("reason"):
                    rep.error(tag, "'reason' is required for reject/defer")
                if decision in ("reject", "defer", REVIEW_PENDING) and d.get("commit"):
                    rep.error(tag, "'commit' belongs only on applied accept decisions")
                if d.get("finding_id") not in ai_ids:
                    rep.error(tag, f"finding_id '{fid}' is not in {REVIEW_CONSOLIDATED_YAML}")
            for fid in sorted(ai_majors - decided):
                rep.error(
                    f"{where}/{REVIEW_TRIAGE_FILE}",
                    f"major '{fid}' has no triage decision "
                    "(a round never closes with an undecided major)",
                )
            pending_majors = sorted(
                fid for fid in ai_majors
                if any(
                    isinstance(d, dict) and str(d.get("finding_id")) == fid
                    and d.get("decision") == REVIEW_PENDING
                    for d in (tri_data.get("decisions") or [])
                )
            )
            for fid in pending_majors:
                rep.error(
                    f"{where}/{REVIEW_TRIAGE_FILE}",
                    f"major '{fid}' is still '{REVIEW_PENDING}' "
                    "(pending is an initial state, never a final one)",
                )


def _check_raw_file(
    root: Path, raw_file: Path, files: dict, raw_ids: set[str], rep: Report
) -> None:
    slug = root.name
    where = f"papers/{slug}/reviews/{raw_file.parent.parent.name}/{REVIEW_RAW_DIR}/{raw_file.name}"
    try:
        data = load_yaml(raw_file)
    except Exception as exc:
        rep.error(where, f"unparseable YAML: {exc}")
        return
    if data.get("schema_version") != REVIEW_SCHEMA_VERSION:
        rep.error(where, "missing 'schema_version: 2'")
        return
    if not data.get("agent"):
        rep.error(where, "missing 'agent'")
    if "omitted_count" not in data or not isinstance(data.get("omitted_count"), int):
        rep.error(where, "'omitted_count' is required (int, 0 when nothing was left out)")
    findings = data.get("findings")
    if not isinstance(findings, list) or not findings:
        rep.error(where, "'findings' must be a non-empty list")
        return
    if len(findings) > REVIEW_MAX_FINDINGS:
        rep.error(where, f"'findings' exceeds {REVIEW_MAX_FINDINGS} (prioritize, declare the rest in omitted_count)")
    if isinstance(data.get("omitted_count"), int) and data["omitted_count"] > 0 and len(findings) != REVIEW_MAX_FINDINGS:
        rep.error(where, "'omitted_count > 0' requires exactly 15 findings (prioritize first)")
    for i, f in enumerate(findings):
        tag = f"{where} findings[{i}]"
        if not isinstance(f, dict) or not f.get("id"):
            rep.error(tag, "missing 'id'")
            continue
        fid = str(f["id"])
        if not _finding_id_ok(fid):
            rep.error(tag, f"id '{fid}' must look like 'r1-<object>-<nn>' ({'/'.join(REVIEW_OBJECTS)})")
        if fid in raw_ids:
            rep.error(tag, f"duplicate raw finding id '{fid}' in this round")
            continue
        raw_ids.add(fid)
        if f.get("severity") not in REVIEW_SEVERITIES:
            rep.error(tag, f"severity must be one of {list(REVIEW_SEVERITIES)}")
        if f.get("kind") not in REVIEW_KINDS:
            rep.error(tag, f"kind must be one of {list(REVIEW_KINDS)}")
        if f.get("basis") not in REVIEW_BASES:
            rep.error(tag, f"basis must be one of {list(REVIEW_BASES)}")
        if f.get("severity") == "major" and f.get("basis") != "demonstrable":
            rep.error(tag, "MVP: major requires basis: demonstrable (normative is always minor)")
        for key in ("title", "location", "warrant", "fix"):
            if f.get(key) in (None, ""):
                rep.error(tag, f"missing '{key}'")
        _check_lengths(f, tag, rep)
        _check_evidence(root, f, files, tag, rep)


def _check_evidence(root: Path, f: dict, files: dict, tag: str, rep: Report) -> None:
    """Presence needs verbatim quotes at the cited location; absence needs
    existing searched paths plus a non-empty expectation. The validator proves
    the quote exists, never that the conclusion is right."""
    kind = f.get("kind")
    loc = _parse_location(f.get("location", ""))
    if loc is None:
        rep.error(tag, "location must look like 'path/to/file:12' or 'path:12-18'")
        return
    rel, first, last = loc
    target = root / rel
    if not target.is_file():
        rep.error(tag, f"location file '{rel}' does not exist")
        return
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        rep.error(tag, f"cannot read location file '{rel}': {exc}")
        return
    lines = text.splitlines()
    if last > len(lines):
        rep.error(tag, f"location lines {first}-{last} exceed {len(lines)} lines in '{rel}'")
        return
    expected_hash = files.get(rel)
    if isinstance(expected_hash, str) and expected_hash:
        try:
            actual = _sha256_normalized(target)
        except OSError as exc:
            rep.error(tag, f"cannot hash '{rel}': {exc}")
            return
        if actual != expected_hash:
            rep.error(
                tag,
                f"'{rel}' changed since packet.yaml "
                "(commit before reviewing, or re-run with --allow-dirty)",
            )
            return
    if kind == "presence":
        evidence = f.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            rep.error(tag, "'evidence' must be a non-empty list for kind: presence")
            return
        if len(evidence) > REVIEW_EVIDENCE_MAX:
            rep.error(tag, f"'evidence' exceeds {REVIEW_EVIDENCE_MAX} entries")
        for j, entry in enumerate(evidence):
            etag = f"{tag} evidence[{j}]"
            if not isinstance(entry, dict) or not entry.get("path") or not entry.get("quote"):
                rep.error(etag, "each evidence entry needs 'path' and 'quote'")
                continue
            epath = str(entry["path"])
            equote = str(entry["quote"])
            if len(equote) > REVIEW_QUOTE_MAX:
                rep.error(etag, f"'quote' exceeds {REVIEW_QUOTE_MAX} chars ({len(equote)})")
            efile = root / epath
            if not efile.is_file():
                rep.error(etag, f"evidence path '{epath}' does not exist")
                continue
            try:
                etext = efile.read_text(encoding="utf-8")
            except OSError as exc:
                rep.error(etag, f"cannot read '{epath}': {exc}")
                continue
            want = _normalize_text(equote)
            if want not in _normalize_text(etext):
                rep.error(etag, "quote not found verbatim (spaces/unicode normalized)")
                continue
            if j == 0:
                cited = _normalize_text("\n".join(lines[first - 1:last]))
                if want not in cited:
                    rep.error(etag, f"quote not inside cited lines {first}-{last}")
    elif kind == "absence":
        searched = f.get("searched")
        if not isinstance(searched, list) or not searched:
            rep.error(tag, "'searched' must be a non-empty list for kind: absence")
        else:
            for s in searched:
                if not (root / str(s)).exists():
                    rep.error(tag, f"searched path '{s}' does not exist")
        if not f.get("expected"):
            rep.error(tag, "'expected' must be non-empty for kind: absence")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def check_cas_fixture(repo: Path, rep: Report) -> None:
    """TeX-free checks for the CAS fidelity fixture and its canonical
    extension. The actual render comparison against cas-sc-sample needs
    quarto/pdflatex and lives in scripts/cas_fidelity.py +
    tests/test_cas_fidelity.py; here we only ensure the pieces exist.
    """
    journal = (
        repo / "templates" / "journals"
        / "engineering-applications-of-artificial-intelligence"
    )
    if not journal.is_dir():
        return
    specimen = journal / "tests" / "specimen"
    for rel in (
        "specimen.qmd",
        "cas-refs.bib",
        "reference/cas-sc-sample.tex",
        "reference/cas-sc-sample.pdf",
        "figs/cas-grabs.pdf",
        "figs/cas-munnar-2024.jpg",
        "figs/cas-pic1.pdf",
        "thumbnails/cas-email.jpeg",
        "thumbnails/cas-url.jpeg",
    ):
        if not (specimen / rel).is_file():
            rep.error(
                f"templates/journals/{journal.name}/tests/specimen/{rel}",
                "missing CAS fidelity fixture file",
            )
    ext = (
        journal / "quarto-extension" / "_extensions"
        / "quarto-journals" / "elsevier-cas"
    )
    for rel in (
        "_extension.yml",
        "cas.lua",
        "cas-pre-ast.lua",
        "cas-docx.lua",
        "nologo.tex",
        "elsevier-harvard.csl",
        "reference.docx",
        "partials/before-body.tex",
        "partials/after-body.tex",
        "partials/hypersetup.latex",
        "partials/fonts.latex",
        "partials/font-settings.latex",
    ):
        if not (ext / rel).is_file():
            rep.error(
                f"templates/journals/{journal.name}/quarto-extension/"
                f"_extensions/quarto-journals/elsevier-cas/{rel}",
                "missing canonical extension file",
            )
    tool = journal / "quarto-extension" / "tools" / "make_reference_docx.py"
    if not tool.is_file():
        rep.error(
            f"templates/journals/{journal.name}/quarto-extension/tools/"
            "make_reference_docx.py",
            "missing the docx reference-doc generator",
        )
    if not (repo / "scripts" / "cas_fidelity.py").is_file():
        rep.error("scripts/cas_fidelity.py", "missing the CAS fidelity harness")


def validate_repo(root: str | Path | None = None) -> Report:
    repo = Path(root).resolve() if root else find_repo_root()
    rep = Report()

    if not (repo / "papers").is_dir():
        rep.error("", "no papers/ directory at repository root")
        return rep
    if not (repo / "AGENTS.md").is_file():
        rep.error("", "missing AGENTS.md at repository root")

    check_authors(repo, rep)
    check_journals(repo, rep)
    check_cas_fixture(repo, rep)
    check_skills(repo, rep)
    check_claude_links(repo, rep)
    check_agent_links(repo, rep)
    check_no_tracked_secrets(repo, rep)

    papers_dir = repo / "papers"
    for root_dir in sorted(papers_dir.iterdir()):
        # Only paper folders. A stray __pycache__ appears here the moment any
        # module is imported from under papers/ (papers/conftest.py does, on
        # every test run), and reporting it as a malformed paper turns the
        # structure gate red for a reason unrelated to any paper.
        if not root_dir.is_dir():
            continue
        if root_dir.name.startswith((".", "_")):
            continue
        check_paper(repo, root_dir, rep)

    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate the repository structure contract.")
    ap.add_argument("--root", default=None, help="repository root (default: auto-detect)")
    ap.add_argument("--json", action="store_true", help="emit a JSON report")
    ap.add_argument("--quiet", action="store_true", help="only print errors")
    args = ap.parse_args()

    rep = validate_repo(args.root)

    if args.json:
        print(
            json.dumps(
                {"ok": rep.ok, "errors": rep.errors, "warnings": rep.warnings, "checked": rep.checked},
                indent=2,
            )
        )
        return 0 if rep.ok else 1

    if not args.quiet:
        for c in rep.checked:
            print(f"  [ok]   {c}")
        for w in rep.warnings:
            print(f"  [warn] {w}")
    for e in rep.errors:
        print(f"  [ERROR] {e}")
    if not args.quiet:
        print()
    print(
        f"RESULT: {'PASS' if rep.ok else 'FAIL'} "
        f"({len(rep.checked)} paper(s) checked, {len(rep.errors)} error(s), "
        f"{len(rep.warnings)} warning(s))"
    )
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

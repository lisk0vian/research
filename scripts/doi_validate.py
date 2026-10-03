#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""doi_validate.py — Validate and fix DOIs in paper references.bib files.

Wraps bib-literature-audit (_bib_audit.py) with the repository CLI pattern
(--slug, --json, --quiet) and adds an interactive metadata fix mode that
fills missing fields from CrossRef and resolves conflicts with the user.

Usage:
    python scripts/doi_validate.py                           # check all papers
    python scripts/doi_validate.py --slug c26-2026           # check one paper
    python scripts/doi_validate.py --fix --dry-run           # preview fixes
    python scripts/doi_validate.py --fix                     # interactive fix
    python scripts/doi_validate.py --fix --force             # auto-fix (DOI wins)
    python scripts/doi_validate.py --fix --conservative      # fill empties only
    python scripts/doi_validate.py --fix --search-missing    # also find missing DOIs

Modes:
    (default)       Check only — validates existing DOIs, reports issues.
    --fix           Interactive fix — fills missing metadata, asks on conflicts.
    --fix --dry-run Preview what --fix would change, without writing.
    --fix --force   Automatic fix — CrossRef metadata always wins.
    --fix --conservative  Fill empty fields only, never overwrite.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import sys
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Optional rich import — graceful fallback to plain print
try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

# Force UTF-8 output on Windows to avoid cp1252 encoding errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root  # noqa: E402
from _bib_audit import (  # noqa: E402
    BibEntry,
    HTTPClient,
    ReferenceClass,
    build_offline_summary,
    classify_reference,
    clean_doi,
    crossref_get,
    crossref_match,
    crossref_search,
    extract_doi,
    first_author_surname,
    normalize_text,
    parse_bibtex,
    strip_latex,
    text_similarity,
    DEFAULT_TIMEOUT,
    DEFAULT_DELAY,
    DEFAULT_RETRIES,
    DEFAULT_ACCEPT_THRESHOLD,
    DEFAULT_CROSSREF_ROWS,
)


# ─── Colours (auto-disabled when not a TTY) ──────────────────────────────────

def _supports_colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_USE_COLOUR = _supports_colour()


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m" if _USE_COLOUR else text


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m" if _USE_COLOUR else text


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m" if _USE_COLOUR else text


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m" if _USE_COLOUR else text


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m" if _USE_COLOUR else text


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m" if _USE_COLOUR else text


# ─── Progress + log panel (rich) ─────────────────────────────────────────────

class ProgressLogManager:
    """Rich-based dashboard: progress bar on top, scrolling log panel below.

    Falls back to plain print when rich is unavailable or in non-TTY / quiet
    / interactive modes.  The caller is responsible for checking ``enabled``
    before calling log/advance/set_detail.
    """

    def __init__(self, total: int, *, quiet: bool = False) -> None:
        self.total = total
        self.quiet = quiet
        self._count = 0
        self._log_lines: list[str] = []
        self._detail = ""
        self.enabled = False
        self._live: Live | None = None
        self._progress: Progress | None = None
        self._task_id: Any = None
        self._log_console: Console | None = None

        # Only enable in TTY with rich available and not quiet
        if (
            _HAS_RICH
            and not quiet
            and hasattr(sys.stdout, "isatty")
            and sys.stdout.isatty()
        ):
            self.enabled = True
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=40),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TextColumn("{task.fields[detail]}"),
            )
            self._task_id = self._progress.add_task(
                "Validating references", total=total, detail=""
            )
            self._log_console = Console(
                file=io.StringIO(),
                force_terminal=True,
                width=min(os.get_terminal_size().columns, 120)
                if hasattr(os, "get_terminal_size")
                else 100,
            )

    # -- public API -----------------------------------------------------------

    def set_detail(self, text: str) -> None:
        """Update the spinner/detail text next to the progress bar."""
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, detail=text)

    def advance(self, entry_key: str, paper_slug: str) -> None:
        """Advance the bar by one entry and update the description."""
        self._count += 1
        if self._progress and self._task_id is not None:
            desc = f"[cyan]{paper_slug}[/cyan] — {entry_key}"
            self._progress.update(
                self._task_id,
                completed=self._count,
                description=desc,
                detail="",
            )

    def log(self, message: str) -> None:
        """Append a line to the scrolling log panel."""
        if self._log_console:
            self._log_console.print(message)
            self._refresh_live()
        elif not self.quiet:
            print(message)

    def log_plain(self, message: str) -> None:
        """Append a plain string (no rich markup) to the log panel."""
        if self._log_console:
            self._log_console.print(message, highlight=False)
            self._refresh_live()
        elif not self.quiet:
            print(message)

    def start(self) -> None:
        """Start the Live display."""
        if self._live and self.enabled:
            self._live.start()

    def stop(self) -> None:
        """Stop the Live display and print final state."""
        if self._live:
            self._live.stop()

    def make_live(self) -> Live | None:
        """Create and store the Live object (call before start)."""
        if not self.enabled:
            return None
        renderable = self._build_renderable()
        self._live = Live(
            renderable,
            console=Console(),
            refresh_per_second=4,
            transient=False,
        )
        return self._live

    # -- internals ------------------------------------------------------------

    def _build_renderable(self):
        """Build the combined progress + log renderable."""
        assert self._progress is not None
        parts = [self._progress]
        if self._log_console:
            log_text = self._log_console.file.getvalue()  # type: ignore[union-attr]
            if log_text.strip():
                # Show last N lines that fit the terminal
                lines = log_text.rstrip("\n").split("\n")
                max_lines = 15
                if len(lines) > max_lines:
                    lines = ["  ..."] + lines[-max_lines:]
                parts.append(Text.from_ansi("\n".join(lines)))
        return Group(*parts)

    def _refresh_live(self) -> None:
        if self._live:
            self._live.update(self._build_renderable())


# ─── Preprint DOI prefixes (skipped in CI mode) ──────────────────────────────

PREPRINT_PREFIXES = (
    "10.48550/",   # arXiv
    "10.1101/",    # bioRxiv / medRxiv
    "10.21203/",   # Research Square
    "10.31219/",   # OSF Preprints
    "10.22541/",   # PeerJ Preprints
    "10.20944/",   # Preprints.org
)


def is_preprint_doi(doi: str) -> bool:
    """Check if a DOI belongs to a known preprint server."""
    return any(doi.startswith(prefix) for prefix in PREPRINT_PREFIXES)


# ─── Data models ─────────────────────────────────────────────────────────────

@dataclass
class FieldChange:
    """A single field addition or modification."""
    field_name: str
    old_value: str          # "" if adding new field
    new_value: str          # from CrossRef
    action: str             # "auto_fill" | "auto_fix" | "accepted" | "rejected" | "skipped"
    reason: str = ""        # why this action was taken


@dataclass
class EntryResult:
    """Result of processing one bib entry."""
    key: str
    doi: str
    ref_kind: str
    doi_status: str = ""          # "verified" | "not_found" | "no_doi" | "network_error"
    changes: list[FieldChange] = field(default_factory=list)
    doi_candidates: list[dict] = field(default_factory=list)  # for search-missing
    warnings: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any(c.action not in ("rejected", "skipped") for c in self.changes)


@dataclass
class PaperReport:
    """Report for one paper."""
    slug: str
    bib_path: str
    entry_count: int = 0
    doi_count: int = 0
    no_doi_count: int = 0
    preprint_skipped: int = 0
    results: list[EntryResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class GlobalReport:
    """Aggregated report across all papers."""
    papers: list[PaperReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(p.ok for p in self.papers)

    @property
    def total_entries(self) -> int:
        return sum(p.entry_count for p in self.papers)

    @property
    def total_dois(self) -> int:
        return sum(p.doi_count for p in self.papers)

    @property
    def total_changes(self) -> int:
        return sum(
            sum(1 for c in r.changes if c.action not in ("rejected", "skipped"))
            for p in self.papers
            for r in p.results
        )

    @property
    def total_preprint_skipped(self) -> int:
        return sum(p.preprint_skipped for p in self.papers)


# ─── CrossRef metadata extraction ────────────────────────────────────────────

CROSSREF_BIB_FIELDS = [
    ("author",   "author"),
    ("title",    "title"),
    ("journal",  "container-title"),
    ("year",     "published-print"),
    ("volume",   "volume"),
    ("number",   "issue"),
    ("pages",    "page"),
    ("doi",      "DOI"),
    ("publisher", "publisher"),
    ("isbn",     "ISBN"),
    ("issn",     "ISSN"),
]


def _crossref_year_val(item: dict) -> str:
    """Extract year from CrossRef published-print / published-online / issued."""
    for fld in ("published-print", "published-online", "issued"):
        val = item.get(fld)
        try:
            return str(val["date-parts"][0][0])
        except (KeyError, TypeError, IndexError):
            continue
    return ""


def _crossref_authors(item: dict) -> str:
    """Format CrossRef authors as BibTeX 'Last, First and Last2, First2'."""
    authors = item.get("author")
    if not isinstance(authors, list):
        return ""
    parts = []
    for a in authors:
        if not isinstance(a, dict):
            continue
        family = a.get("family", "")
        given = a.get("given", "")
        if family and given:
            parts.append(f"{family}, {given}")
        elif family:
            parts.append(family)
    return " and ".join(parts)


def crossref_to_bibtex_fields(item: dict) -> dict[str, str]:
    """Convert a CrossRef work item to a dict of BibTeX field values."""
    out: dict[str, str] = {}
    for bib_field, cr_field in CROSSREF_BIB_FIELDS:
        if bib_field == "author":
            val = _crossref_authors(item)
        elif bib_field == "year":
            val = _crossref_year_val(item)
        elif bib_field == "journal":
            raw = item.get("container-title")
            val = raw[0] if isinstance(raw, list) and raw else str(raw or "")
        elif bib_field == "title":
            raw = item.get("title")
            val = raw[0] if isinstance(raw, list) and raw else str(raw or "")
        else:
            raw = item.get(cr_field)
            if isinstance(raw, list):
                val = str(raw[0]) if raw else ""
            else:
                val = str(raw or "")
        # Unescape HTML entities from CrossRef (e.g. &amp; → &)
        val = html.unescape(val)
        if val:
            out[bib_field] = val
    return out


# ─── BibTeX field manipulation ───────────────────────────────────────────────

def _find_field_range(raw: str, field_name: str) -> tuple[int, int] | None:
    """Find the start and end positions of a field in raw BibTeX text.

    Returns (start_of_field_line, end_of_field_line) or None if not found.
    The range includes the field name, '=', value, and trailing comma.
    """
    # Match field = {value}, or field = "value", or field = value,
    pattern = re.compile(
        r'(?m)^[ \t]*' + re.escape(field_name) + r'\s*=\s*',
        re.IGNORECASE,
    )
    m = pattern.search(raw)
    if not m:
        return None

    start = m.start()
    # Find the value after '='
    eq_pos = raw.index("=", m.start())
    i = eq_pos + 1
    n = len(raw)

    # Skip whitespace
    while i < n and raw[i].isspace():
        i += 1

    if i >= n:
        return None

    # Read the value (handle braced, quoted, or bare)
    if raw[i] == "{":
        depth = 0
        escaped = False
        for j in range(i, n):
            ch = raw[j]
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        else:
            return None
    elif raw[i] == '"':
        escaped = False
        for j in range(i + 1, n):
            ch = raw[j]
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                end = j + 1
                break
        else:
            return None
    else:
        # Bare value (rare in well-formed bib)
        j = i
        while j < n and raw[j] not in ",#\r\n":
            j += 1
        end = j

    # Skip trailing comma and whitespace
    while end < n and raw[end] in " \t,":
        end += 1

    return start, end


def _detect_indent(raw: str) -> str:
    """Detect the indentation style used in a BibTeX entry (tabs or spaces)."""
    for line in raw.splitlines():
        stripped = line.lstrip()
        if stripped and stripped != line:
            indent = line[: len(line) - len(stripped)]
            if indent:
                return indent
    return "  "  # default to 2 spaces


def replace_field(raw: str, field_name: str, new_value: str) -> str:
    """Replace a field's value in raw BibTeX text. Returns modified text."""
    rng = _find_field_range(raw, field_name)
    if rng is None:
        return raw  # Field not found; caller should use insert_field
    start, end = rng
    indent = _detect_indent(raw)
    # Reconstruct with new value in braces
    line = f"{indent}{field_name} = {{{new_value}}},\n"
    return raw[:start] + line + raw[end:]


def insert_field(raw: str, field_name: str, new_value: str) -> str:
    """Insert a new field before the closing brace of a BibTeX entry."""
    indent = _detect_indent(raw)
    line = f"{indent}{field_name} = {{{new_value}}},\n"
    # Find the last closing brace
    last_brace = raw.rfind("}")
    if last_brace < 0:
        return raw
    return raw[:last_brace] + line + raw[last_brace:]


# ─── Interactive prompt ──────────────────────────────────────────────────────

def _truncate(s: str, maxlen: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    if len(s) <= maxlen:
        return s
    return s[: maxlen - 3] + "..."


def prompt_conflict(
    entry_key: str,
    field_name: str,
    bib_value: str,
    doi_value: str,
    bib_title: str = "",
    doi_title: str = "",
) -> str:
    """Show a conflict and ask the user what to do.

    Returns: 'accept' | 'reject' | 'view' | 'skip' | 'quit'
    """
    print()
    print(f"  {_bold(entry_key)} → {_cyan(field_name)}")
    print()
    print(f"    [bib] {_red(_truncate(bib_value))}")
    print(f"    [doi] {_green(_truncate(doi_value))}")
    print()

    while True:
        prompt = "    (v)er más  [a]ceptar doi  [r]echazar  [s]altar entry  [q]uit: "
        choice = input(prompt).strip().lower()
        if choice in ("a", "accept", "aceptar"):
            return "accept"
        elif choice in ("r", "reject", "rechazar"):
            return "reject"
        elif choice in ("v", "view", "ver"):
            print()
            print(f"    {_bold('Bib title:')} {_red(bib_value)}")
            print(f"    {_bold('DOI title:')} {_green(doi_value)}")
            if bib_title and doi_title:
                print()
                print(f"    {_dim('Bib entry title:')} {bib_title}")
                print(f"    {_dim('DOI title:       ')} {doi_title}")
            print()
        elif choice in ("s", "skip", "saltar"):
            return "skip"
        elif choice in ("q", "quit", "salir"):
            return "quit"
        else:
            print(f"    Opción no válida. Use a/r/v/s/q.")


def prompt_missing_doi(
    entry_key: str,
    bib_title: str,
    candidates: list[dict],
) -> str:
    """Show DOI candidates for an entry without DOI.

    Returns: '1' | '2' | ... | 'reject' | 'skip' | 'quit'
    """
    print()
    print(f"  {_bold(entry_key)} → {_cyan('doi')} (missing)")
    print(f"    {_dim('Title:')} {_truncate(bib_title, 70)}")
    print()
    for i, c in enumerate(candidates, 1):
        cr_title = c.get("title", "?")
        cr_doi = c.get("doi", "?")
        cr_year = c.get("year", "?")
        cr_author = c.get("first_author", "?")
        score = c.get("score", 0)
        print(f"    [{i}] {_green(cr_doi)}  (score {score:.2f})")
        print(f"        {_truncate(cr_title, 65)}")
        print(f"        {_dim(f'{cr_author} · {cr_year}')}")
    print()
    nums = "/".join(str(i) for i in range(1, len(candidates) + 1))
    while True:
        prompt = f"    [{nums}] aceptar  [r]echazar  [s]altar entry  [q]uit: "
        choice = input(prompt).strip().lower()
        if choice in ("r", "reject"):
            return "reject"
        if choice in ("s", "skip"):
            return "skip"
        if choice in ("q", "quit"):
            return "quit"
        try:
            idx = int(choice)
            if 1 <= idx <= len(candidates):
                return str(idx)
        except ValueError:
            pass
        print(f"    Opción no válida.")


# ─── Core logic ──────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Normalize for comparison: strip latex, lowercase, collapse spaces."""
    return normalize_text(strip_latex(s))


def _title_differs_significantly(bib_title: str, doi_title: str) -> bool:
    """Check if titles differ by more than 20%."""
    a, b = _norm(bib_title), _norm(doi_title)
    if not a or not b:
        return False
    sim = difflib.SequenceMatcher(None, a, b).ratio()
    return sim < 0.80


def _year_diff(bib_year: str, doi_year: str) -> int | None:
    """Return absolute difference in years, or None if not parseable."""
    try:
        by = int(strip_latex(bib_year).strip())
        dy = int(strip_latex(doi_year).strip())
        return abs(by - dy)
    except (ValueError, TypeError):
        return None


def process_entry_check(
    entry: BibEntry,
    ref_class: ReferenceClass,
    client: HTTPClient,
    *,
    search_missing: bool,
    crossref_rows: int,
    accept_threshold: float,
    ci_mode: bool = False,
) -> EntryResult:
    """Validate an entry's DOI (check-only mode)."""
    local_doi = extract_doi(entry)
    result = EntryResult(key=entry.key, doi=local_doi, ref_kind=ref_class.kind)

    if not local_doi:
        result.doi_status = "no_doi"
        if search_missing and ref_class.doi_search_eligible:
            items, api = crossref_search(client, entry, crossref_rows)
            if items:
                for item in items[:3]:
                    score, ts, ym, yd, am, ss, type_ok = crossref_match(
                        entry, ref_class.kind, item
                    )
                    cr_doi = clean_doi(str(item.get("DOI", "")))
                    cr_title = ""
                    raw_t = item.get("title")
                    if isinstance(raw_t, list) and raw_t:
                        cr_title = str(raw_t[0])
                    cr_year = ""
                    for fld in ("published-print", "published-online", "issued"):
                        val = item.get(fld)
                        try:
                            cr_year = str(val["date-parts"][0][0])
                            break
                        except (KeyError, TypeError, IndexError):
                            continue
                    cr_author = ""
                    authors = item.get("author")
                    if isinstance(authors, list) and authors and isinstance(authors[0], dict):
                        cr_author = str(authors[0].get("family", ""))
                    result.doi_candidates.append({
                        "doi": cr_doi,
                        "title": cr_title,
                        "year": cr_year,
                        "first_author": cr_author,
                        "score": score,
                        "title_sim": ts,
                        "author_match": am,
                        "year_match": ym,
                    })
        return result

    # Verify existing DOI
    cr = crossref_get(client, local_doi)
    if cr.status == "ok" and cr.data:
        score, ts, ym, yd, am, ss, type_ok = crossref_match(entry, ref_class.kind, cr.data)
        if ts >= 0.90 and (yd is None or yd <= 1) and type_ok:
            result.doi_status = "verified"
        else:
            result.doi_status = "mismatch"
            if ts < 0.90:
                result.warnings.append(f"title mismatch (sim={ts:.2f})")
            if yd is not None and yd > 1:
                result.warnings.append(f"year differs by {yd}")
            if not type_ok:
                result.warnings.append(f"type mismatch")
    elif cr.status == "not_found":
        if ci_mode and is_preprint_doi(local_doi):
            result.doi_status = "skipped_preprint"
            result.warnings.append(f"preprint DOI (not in CrossRef)")
        else:
            result.doi_status = "not_found"
            result.warnings.append("DOI not found in CrossRef")
    else:
        result.doi_status = "network_error"
        result.warnings.append(f"CrossRef lookup failed: {cr.message}")

    return result


def process_entry_fix(
    entry: BibEntry,
    ref_class: ReferenceClass,
    client: HTTPClient,
    *,
    mode: str,  # "interactive" | "force" | "conservative"
    search_missing: bool,
    crossref_rows: int,
    accept_threshold: float,
    ci_mode: bool = False,
) -> EntryResult:
    """Validate and fix an entry's metadata (fix mode)."""
    local_doi = extract_doi(entry)
    result = EntryResult(key=entry.key, doi=local_doi, ref_kind=ref_class.kind)

    # ── Phase 1: Find DOI (if missing) ──────────────────────────────────
    if not local_doi:
        result.doi_status = "no_doi"
        if search_missing and ref_class.doi_search_eligible:
            items, api = crossref_search(client, entry, crossref_rows)
            if items:
                best = items[0]
                score, ts, ym, yd, am, ss, type_ok = crossref_match(
                    entry, ref_class.kind, best
                )
                cr_doi = clean_doi(str(best.get("DOI", "")))
                cr_title = ""
                raw_t = best.get("title")
                if isinstance(raw_t, list) and raw_t:
                    cr_title = str(raw_t[0])
                cr_year = _crossref_year_val(best)
                cr_author = ""
                authors = best.get("author")
                if isinstance(authors, list) and authors and isinstance(authors[0], dict):
                    cr_author = str(authors[0].get("family", ""))

                candidate_info = {
                    "doi": cr_doi,
                    "title": cr_title,
                    "year": cr_year,
                    "first_author": cr_author,
                    "score": score,
                    "title_sim": ts,
                    "author_match": am,
                    "year_match": ym,
                }

                # Auto-accept if very high confidence
                if score >= accept_threshold and ts >= 0.97 and type_ok and (am or ym):
                    local_doi = cr_doi
                    result.doi = cr_doi
                    result.changes.append(FieldChange(
                        "doi", "", cr_doi, "auto_fill",
                        f"high-confidence match (score={score:.2f})",
                    ))
                elif mode == "force" and score >= 0.85 and type_ok:
                    local_doi = cr_doi
                    result.doi = cr_doi
                    result.changes.append(FieldChange(
                        "doi", "", cr_doi, "auto_fill",
                        f"force mode (score={score:.2f})",
                    ))
                elif mode == "interactive":
                    # Build candidate list for prompt
                    result.doi_candidates = []
                    for item in items[:3]:
                        s, t, ym2, yd2, a, ss2, to = crossref_match(
                            entry, ref_class.kind, item
                        )
                        rd = clean_doi(str(item.get("DOI", "")))
                        rt = ""
                        raw_t2 = item.get("title")
                        if isinstance(raw_t2, list) and raw_t2:
                            rt = str(raw_t2[0])
                        ry = _crossref_year_val(item)
                        ra = ""
                        auths = item.get("author")
                        if isinstance(auths, list) and auths and isinstance(auths[0], dict):
                            ra = str(auths[0].get("family", ""))
                        result.doi_candidates.append({
                            "doi": rd, "title": rt, "year": ry,
                            "first_author": ra, "score": s,
                        })

        return result

    # ── Phase 2: Fetch CrossRef metadata for existing DOI ────────────────
    cr = crossref_get(client, local_doi)
    if cr.status != "ok" or not cr.data:
        if cr.status == "not_found":
            if ci_mode and is_preprint_doi(local_doi):
                result.doi_status = "skipped_preprint"
                result.warnings.append("preprint DOI (not in CrossRef)")
            else:
                result.doi_status = "not_found"
                result.warnings.append("DOI not found in CrossRef")
        else:
            result.doi_status = "network_error"
            result.warnings.append(f"CrossRef lookup failed: {cr.message}")
        return result

    result.doi_status = "verified"
    cr_fields = crossref_to_bibtex_fields(cr.data)

    # ── Phase 3: Compare and decide ──────────────────────────────────────
    fields_to_check = ["author", "title", "journal", "year", "volume", "number", "pages", "publisher"]

    for fld in fields_to_check:
        bib_val = strip_latex(entry.fields.get(fld, "")).strip()
        doi_val = cr_fields.get(fld, "")

        if not doi_val:
            continue

        if not bib_val:
            # ── Empty field → auto-fill ──────────────────────────────────
            action = "auto_fill"
            reason = "field was empty"
            if mode == "conservative" or mode == "interactive" or mode == "force":
                # All modes fill empty fields
                result.changes.append(FieldChange(fld, "", doi_val, action, reason))
            continue

        # ── Field has content → check for conflict ───────────────────────
        bib_norm = _norm(bib_val)
        doi_norm = _norm(doi_val)

        if bib_norm == doi_norm:
            continue  # Same value, no action needed

        # Special handling for year (±1 is OK)
        if fld == "year":
            diff = _year_diff(bib_val, doi_val)
            if diff is not None and diff <= 1:
                # Year difference of 1 is normal (online-first vs print)
                continue
            if diff is not None and diff > 1:
                # Significant year difference
                if mode == "force":
                    result.changes.append(FieldChange(
                        fld, bib_val, doi_val, "auto_fix",
                        f"year differs by {diff} (force mode)",
                    ))
                elif mode == "conservative":
                    result.changes.append(FieldChange(
                        fld, bib_val, doi_val, "skipped",
                        f"year differs by {diff} (conservative mode)",
                    ))
                elif mode == "interactive":
                    choice = prompt_conflict(
                        entry.key, fld, bib_val, doi_val,
                        bib_title=entry.title,
                        doi_title=cr_fields.get("title", ""),
                    )
                    if choice == "accept":
                        result.changes.append(FieldChange(fld, bib_val, doi_val, "accepted", "user accepted"))
                    elif choice == "reject":
                        result.changes.append(FieldChange(fld, bib_val, doi_val, "rejected", "user rejected"))
                    elif choice == "skip":
                        result.changes.append(FieldChange(fld, bib_val, doi_val, "skipped", "user skipped entry"))
                        return result
                    elif choice == "quit":
                        result.changes.append(FieldChange(fld, bib_val, doi_val, "skipped", "user quit"))
                        return result
                continue

        # Title: check if significantly different
        if fld == "title":
            if _title_differs_significantly(bib_val, doi_val):
                if mode == "force":
                    result.changes.append(FieldChange(
                        fld, bib_val, doi_val, "auto_fix",
                        "title mismatch (force mode)",
                    ))
                elif mode == "conservative":
                    result.changes.append(FieldChange(
                        fld, bib_val, doi_val, "skipped",
                        "title mismatch (conservative mode)",
                    ))
                elif mode == "interactive":
                    choice = prompt_conflict(
                        entry.key, fld, bib_val, doi_val,
                        bib_title=entry.title,
                        doi_title=cr_fields.get("title", ""),
                    )
                    if choice == "accept":
                        result.changes.append(FieldChange(fld, bib_val, doi_val, "accepted", "user accepted"))
                    elif choice == "reject":
                        result.changes.append(FieldChange(fld, bib_val, doi_val, "rejected", "user rejected"))
                    elif choice == "skip":
                        return result
                    elif choice == "quit":
                        return result
                continue
            else:
                # Minor title difference (capitalisation, punctuation, etc.)
                # Don't overwrite — the bib version is likely intentionally formatted
                continue

        # Author: check first author
        if fld == "author":
            bib_first = first_author_surname(bib_val)
            doi_first = first_author_surname(doi_val)
            if bib_first and doi_first and bib_first != doi_first:
                # First author mismatch — possible wrong DOI
                if mode == "force":
                    result.changes.append(FieldChange(
                        fld, bib_val, doi_val, "auto_fix",
                        "first author mismatch (force mode)",
                    ))
                elif mode == "conservative":
                    result.changes.append(FieldChange(
                        fld, bib_val, doi_val, "skipped",
                        "first author mismatch (conservative mode)",
                    ))
                elif mode == "interactive":
                    choice = prompt_conflict(
                        entry.key, fld, bib_val, doi_val,
                        bib_title=entry.title,
                        doi_title=cr_fields.get("title", ""),
                    )
                    if choice == "accept":
                        result.changes.append(FieldChange(fld, bib_val, doi_val, "accepted", "user accepted"))
                    elif choice == "reject":
                        result.changes.append(FieldChange(fld, bib_val, doi_val, "rejected", "user rejected"))
                    elif choice == "skip":
                        return result
                    elif choice == "quit":
                        return result
                continue
            else:
                # Same first author, different format — don't overwrite
                continue

        # Other fields (journal, volume, number, pages, publisher):
        # Only fill if empty. Don't overwrite existing content.
        # (Already handled above — if we're here, bib_val is non-empty
        #  and differs from doi_val. Conservative: skip.)
        if mode == "force":
            result.changes.append(FieldChange(
                fld, bib_val, doi_val, "auto_fix",
                f"{fld} mismatch (force mode)",
            ))
        elif mode == "conservative":
            result.changes.append(FieldChange(
                fld, bib_val, doi_val, "skipped",
                f"{fld} mismatch (conservative mode)",
            ))
        elif mode == "interactive":
            choice = prompt_conflict(
                entry.key, fld, bib_val, doi_val,
                bib_title=entry.title,
                doi_title=cr_fields.get("title", ""),
            )
            if choice == "accept":
                result.changes.append(FieldChange(fld, bib_val, doi_val, "accepted", "user accepted"))
            elif choice == "reject":
                result.changes.append(FieldChange(fld, bib_val, doi_val, "rejected", "user rejected"))
            elif choice == "skip":
                return result
            elif choice == "quit":
                return result

    return result


# ─── Apply changes to BibTeX text ────────────────────────────────────────────

def apply_changes(raw: str, changes: list[FieldChange]) -> str:
    """Apply accepted/auto changes to a BibTeX entry's raw text."""
    result = raw
    for ch in changes:
        if ch.action in ("rejected", "skipped"):
            continue
        if ch.old_value:
            # Replace existing field
            result = replace_field(result, ch.field_name, ch.new_value)
        else:
            # Insert new field
            result = insert_field(result, ch.field_name, ch.new_value)
    return result


def rebuild_bib(original_text: str, entries: list[BibEntry], results: dict[str, EntryResult]) -> str:
    """Rebuild the entire .bib file with changes applied to each entry."""
    pieces = []
    cursor = 0
    for entry in entries:
        er = results.get(entry.uid)
        pieces.append(original_text[cursor:entry.start])
        if er and er.has_changes:
            modified = apply_changes(entry.raw, er.changes)
            pieces.append(modified)
        else:
            pieces.append(entry.raw)
        cursor = entry.end
    pieces.append(original_text[cursor:])
    return "".join(pieces)


# ─── Paper processing ────────────────────────────────────────────────────────

def discover_papers(repo: Path, slug: str | None = None) -> list[tuple[str, Path]]:
    """Find papers with references.bib. Returns [(slug, paper_root), ...]."""
    papers_dir = repo / "papers"
    if not papers_dir.is_dir():
        return []
    results = []
    for d in sorted(papers_dir.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        if slug and d.name != slug:
            continue
        bib = d / "paper" / "references.bib"
        if bib.is_file():
            results.append((d.name, d))
    return results


def process_paper(
    slug: str,
    paper_root: Path,
    client: HTTPClient,
    *,
    mode: str,
    search_missing: bool,
    crossref_rows: int,
    accept_threshold: float,
    quiet: bool,
    ci_mode: bool = False,
    progress: ProgressLogManager | None = None,
) -> PaperReport:
    """Process one paper's references.bib."""
    bib_path = paper_root / "paper" / "references.bib"
    report = PaperReport(slug=slug, bib_path=str(bib_path))

    if progress and progress.enabled:
        progress.set_detail(f"Loading papers/{slug}...")
    elif not quiet:
        print(f"\n  \u2500\u2500\u2500 papers/{slug} \u2500\u2500\u2500")

    try:
        raw_bytes = bib_path.read_bytes()
        text = raw_bytes.decode("utf-8-sig", errors="replace")
    except OSError as exc:
        report.errors.append(f"Cannot read {bib_path}: {exc}")
        return report

    entries, skipped, warnings = parse_bibtex(text)
    if not entries:
        report.errors.append(f"No BibTeX entries found in {bib_path}")
        return report

    report.entry_count = len(entries)

    # Classify entries
    classes: dict[str, ReferenceClass] = {}
    for e in entries:
        classes[e.uid] = classify_reference(e)

    # Count DOIs
    for e in entries:
        if extract_doi(e):
            report.doi_count += 1
        else:
            report.no_doi_count += 1

    # Process each entry
    uid_to_entry: dict[str, BibEntry] = {e.uid: e for e in entries}
    results_by_uid: dict[str, EntryResult] = {}

    for entry in entries:
        cls = classes[entry.uid]

        # Show what we're doing (spinner detail or plain print)
        if progress and progress.enabled:
            progress.set_detail(f"Fetching {entry.key}...")
        elif not quiet:
            print(f"  [{len(report.results) + 1:>3}/{len(entries)}] {entry.key}...", end="", flush=True)

        if mode == "check":
            er = process_entry_check(
                entry, cls, client,
                search_missing=search_missing,
                crossref_rows=crossref_rows,
                accept_threshold=accept_threshold,
                ci_mode=ci_mode,
            )
        else:
            er = process_entry_fix(
                entry, cls, client,
                mode=mode,
                search_missing=search_missing,
                crossref_rows=crossref_rows,
                accept_threshold=accept_threshold,
                ci_mode=ci_mode,
            )

        results_by_uid[entry.uid] = er
        report.results.append(er)

        # Count preprint skips
        if er.doi_status == "skipped_preprint":
            report.preprint_skipped += 1

        # Handle missing DOI prompts in interactive mode
        if (
            mode == "interactive"
            and er.doi_status == "no_doi"
            and er.doi_candidates
        ):
            # In interactive mode we don't use the Live display, so plain print
            if not progress or not progress.enabled:
                # Clear the inline counter
                print()
            choice = prompt_missing_doi(
                entry.key, entry.title, er.doi_candidates,
            )
            if choice not in ("reject", "skip", "quit"):
                try:
                    idx = int(choice) - 1
                    cand = er.doi_candidates[idx]
                    er.doi = cand["doi"]
                    er.changes.append(FieldChange(
                        "doi", "", cand["doi"], "accepted",
                        f"user selected (score={cand['score']:.2f})",
                    ))
                except (IndexError, ValueError):
                    pass
            elif choice == "quit":
                break

        # Log result immediately and advance progress bar
        if progress and progress.enabled:
            progress.advance(entry.key, slug)
            _log_entry_result(progress, er, slug)
        elif not quiet:
            # Plain mode: finish the inline counter line, then print result
            print()  # finish the "... " line
            _print_entry_result(er, slug)

    return report


def _print_entry_result(er: EntryResult, slug: str) -> None:
    """Print the result for one entry (plain print mode)."""
    prefix = f"  papers/{slug}"

    if er.doi_status == "no_doi":
        if er.doi_candidates:
            print(f"  [?]    {prefix}: {er.key} — no DOI, {len(er.doi_candidates)} candidate(s) found")
        else:
            print(f"  [info] {prefix}: {er.key} — no DOI")
        return

    if er.doi_status == "skipped_preprint":
        print(f"  [skip] {prefix}: {er.key} → {er.doi} — preprint DOI (not in CrossRef)")
        return

    if er.doi_status == "not_found":
        print(f"  [warn] {prefix}: {er.key} → {er.doi} — DOI not found in CrossRef")
        return

    if er.doi_status == "network_error":
        warn = er.warnings[0] if er.warnings else "network error"
        print(f"  [warn] {prefix}: {er.key} → {er.doi} — {warn}")
        return

    if er.has_changes:
        n_fill = sum(1 for c in er.changes if c.action == "auto_fill")
        n_fix = sum(1 for c in er.changes if c.action in ("auto_fix", "accepted"))
        n_rej = sum(1 for c in er.changes if c.action == "rejected")
        parts = []
        if n_fill:
            parts.append(f"{n_fill} auto-fill")
        if n_fix:
            parts.append(f"{n_fix} fixed")
        if n_rej:
            parts.append(f"{n_rej} rejected")
        detail = ", ".join(parts)
        print(f"  [fix]  {prefix}: {er.key} → {er.doi} ({detail})")
        for ch in er.changes:
            if ch.action in ("auto_fill", "auto_fix", "accepted"):
                tag = "+" if ch.action == "auto_fill" else "~"
                old = f' "{_truncate(ch.old_value, 30)}" →' if ch.old_value else ""
                print(f"         {tag} {ch.field_name}{old} \"{_truncate(ch.new_value, 50)}\"")
    elif er.warnings:
        warn_str = "; ".join(er.warnings)
        print(f"  [warn] {prefix}: {er.key} → {er.doi} — {warn_str}")
    else:
        print(f"  [ok]   {prefix}: {er.key} → {er.doi}")


def _log_entry_result(pm: ProgressLogManager, er: EntryResult, slug: str) -> None:
    """Send the result for one entry to the rich log panel."""
    prefix = f"papers/{slug}"

    if er.doi_status == "no_doi":
        if er.doi_candidates:
            pm.log(f"  [yellow][?][/yellow]    {prefix}: {er.key} — no DOI, {len(er.doi_candidates)} candidate(s)")
        else:
            pm.log(f"  [dim][info][/dim] {prefix}: {er.key} — no DOI")
        return

    if er.doi_status == "skipped_preprint":
        pm.log(f"  [dim][skip][/dim] {prefix}: {er.key} → {er.doi} — preprint (not in CrossRef)")
        return

    if er.doi_status == "not_found":
        pm.log(f"  [yellow][warn][/yellow] {prefix}: {er.key} → {er.doi} — DOI not found")
        return

    if er.doi_status == "network_error":
        warn = er.warnings[0] if er.warnings else "network error"
        pm.log(f"  [yellow][warn][/yellow] {prefix}: {er.key} → {er.doi} — {warn}")
        return

    if er.has_changes:
        n_fill = sum(1 for c in er.changes if c.action == "auto_fill")
        n_fix = sum(1 for c in er.changes if c.action in ("auto_fix", "accepted"))
        n_rej = sum(1 for c in er.changes if c.action == "rejected")
        parts = []
        if n_fill:
            parts.append(f"{n_fill} auto-fill")
        if n_fix:
            parts.append(f"{n_fix} fixed")
        if n_rej:
            parts.append(f"{n_rej} rejected")
        detail = ", ".join(parts)
        pm.log(f"  [green][fix][/green]  {prefix}: {er.key} → {er.doi} ({detail})")
        for ch in er.changes:
            if ch.action in ("auto_fill", "auto_fix", "accepted"):
                tag = "+" if ch.action == "auto_fill" else "~"
                old = f' "{_truncate(ch.old_value, 30)}" →' if ch.old_value else ""
                pm.log(f"         {tag} {ch.field_name}{old} \"{_truncate(ch.new_value, 50)}\"")
    elif er.warnings:
        warn_str = "; ".join(er.warnings)
        pm.log(f"  [yellow][warn][/yellow] {prefix}: {er.key} → {er.doi} — {warn_str}")
    else:
        pm.log(f"  [green][ok][/green]   {prefix}: {er.key} → {er.doi}")


# ─── Output generation ───────────────────────────────────────────────────────

def write_json_report(report: GlobalReport, out: Path) -> None:
    """Write the full report as JSON."""
    data = {
        "ok": report.ok,
        "total_entries": report.total_entries,
        "total_dois": report.total_dois,
        "total_changes": report.total_changes,
        "papers": [],
    }
    for p in report.papers:
        pdata = {
            "slug": p.slug,
            "bib_path": p.bib_path,
            "entry_count": p.entry_count,
            "doi_count": p.doi_count,
            "no_doi_count": p.no_doi_count,
            "errors": p.errors,
            "entries": [],
        }
        for er in p.results:
            edata = {
                "key": er.key,
                "doi": er.doi,
                "ref_kind": er.ref_kind,
                "doi_status": er.doi_status,
                "warnings": er.warnings,
                "doi_candidates": er.doi_candidates,
                "changes": [
                    {
                        "field": c.field_name,
                        "old": c.old_value,
                        "new": c.new_value,
                        "action": c.action,
                        "reason": c.reason,
                    }
                    for c in er.changes
                ],
            }
            pdata["entries"].append(edata)
        data["papers"].append(pdata)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_diff_report(
    original_text: str,
    fixed_text: str,
    bib_path: Path,
    out: Path,
) -> None:
    """Write a unified diff between original and fixed .bib."""
    diff = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        fixed_text.splitlines(keepends=True),
        fromfile=f"papers/{bib_path.parent.parent.name}/paper/references.bib (original)",
        tofile="references.bib (fixed)",
    )
    with open(out, "w", encoding="utf-8") as f:
        f.writelines(diff)


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate and fix DOIs in paper references.bib files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--slug", default=None, help="Process only this paper (default: all)")
    ap.add_argument("--check", action="store_true", help="Check only (default)")
    ap.add_argument("--fix", action="store_true", help="Fix mode: fill missing metadata from CrossRef")
    ap.add_argument("--dry-run", action="store_true", help="Preview fixes without writing")
    ap.add_argument("--force", action="store_true", help="Auto-accept all CrossRef data (DOI wins)")
    ap.add_argument("--conservative", action="store_true", help="Only fill empty fields, never overwrite")
    ap.add_argument("--search-missing", action="store_true", help="Search CrossRef for missing DOIs")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument("--quiet", action="store_true", help="Only print errors")
    ap.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    ap.add_argument("--ci", action="store_true", help="CI mode: skip preprint DOIs (arXiv, bioRxiv, etc.) as non-errors")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout (s)")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay between requests (s)")
    ap.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="HTTP retries")
    args = ap.parse_args()

    # Determine mode
    if args.fix:
        if args.force:
            mode = "force"
        elif args.conservative:
            mode = "conservative"
        elif args.dry_run:
            # dry-run: preview all changes without asking (no TTY needed)
            mode = "force"
        elif sys.stdin.isatty():
            mode = "interactive"
        else:
            # No terminal available — fall back to force mode
            print("  [warn] No terminal detected; using --force mode (use --conservative to restrict)", file=sys.stderr)
            mode = "force"
    else:
        mode = "check"

    # Find repo root
    repo = find_repo_root()
    papers = discover_papers(repo, args.slug)

    if not papers:
        msg = f"No papers found" + (f" matching '{args.slug}'" if args.slug else "")
        print(f"  [ERROR] {msg}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"DOI validation — {len(papers)} paper(s)")
        if mode == "check":
            print(f"  Mode: check (read-only)")
        elif args.dry_run:
            print(f"  Mode: fix (dry-run — preview only)")
        elif mode == "interactive":
            print(f"  Mode: fix (interactive)")
        elif mode == "force":
            print(f"  Mode: fix (force — DOI wins)")
        elif mode == "conservative":
            print(f"  Mode: fix (conservative — fill empties only)")

    # Create HTTP client
    client = HTTPClient(args.timeout, args.delay, args.retries)

    # Pre-count total entries across all papers for the progress bar
    total_entries = 0
    for slug, paper_root in papers:
        bib_path = paper_root / "paper" / "references.bib"
        try:
            raw_bytes = bib_path.read_bytes()
            text = raw_bytes.decode("utf-8-sig", errors="replace")
            entries, _, _ = parse_bibtex(text)
            total_entries += len(entries)
        except OSError:
            pass  # will be reported during processing

    # Create progress manager (disabled in interactive mode — uses input())
    use_progress = mode != "interactive"
    pm = ProgressLogManager(total_entries, quiet=args.quiet) if use_progress else None

    # Process papers
    global_report = GlobalReport()

    def _run_papers() -> None:
        for slug, paper_root in papers:
            pr = process_paper(
                slug, paper_root, client,
                mode=mode,
                search_missing=args.search_missing,
                crossref_rows=DEFAULT_CROSSREF_ROWS,
                accept_threshold=DEFAULT_ACCEPT_THRESHOLD,
                quiet=args.quiet,
                ci_mode=args.ci,
                progress=pm,
            )
            global_report.papers.append(pr)

    if pm and pm.enabled:
        pm.make_live()
        pm.start()
        try:
            _run_papers()
        finally:
            pm.stop()
    else:
        _run_papers()

    # Write fixed .bib files (if --fix and not --dry-run)
    if args.fix and not args.dry_run:
        for pr in global_report.papers:
            if not pr.ok:
                continue
            bib_path = Path(pr.bib_path)
            try:
                raw_bytes = bib_path.read_bytes()
                original_text = raw_bytes.decode("utf-8-sig", errors="replace")
            except OSError:
                continue

            entries, _, _ = parse_bibtex(original_text)
            results_by_uid = {r.key: r for r in pr.results}

            # Build uid→result mapping
            uid_results: dict[str, EntryResult] = {}
            for e in entries:
                for er in pr.results:
                    if er.key == e.key:
                        uid_results[e.uid] = er
                        break

            fixed_text = rebuild_bib(original_text, entries, uid_results)

            if fixed_text != original_text:
                # Write fixed bib to build/doi_audit/
                audit_dir = paper_root / "build" / "doi_audit"
                audit_dir.mkdir(parents=True, exist_ok=True)
                fixed_path = audit_dir / "references_fixed.bib"
                fixed_path.write_text(fixed_text, encoding="utf-8")

                # Write diff
                diff_path = audit_dir / "references_fixed.diff"
                write_diff_report(original_text, fixed_text, bib_path, diff_path)

                if not args.quiet:
                    n = sum(1 for er in pr.results if er.has_changes)
                    print(f"\n  → {fixed_path} ({n} entries modified)")
                    print(f"  → {diff_path}")

    # Write JSON report
    if args.json:
        json_path = Path("doi_validate_report.json")
        # If single paper, write in its build dir
        if len(global_report.papers) == 1:
            pp = Path(global_report.papers[0].bib_path).parent.parent
            audit_dir = pp / "build" / "doi_audit"
            audit_dir.mkdir(parents=True, exist_ok=True)
            json_path = audit_dir / "doi_audit.json"
        write_json_report(global_report, json_path)
        if not args.quiet:
            print(f"\n  → {json_path}")

    # Summary
    if not args.quiet:
        print()
        total_err = sum(len(p.errors) for p in global_report.papers)
        total_warn = sum(
            sum(len(r.warnings) for r in p.results)
            for p in global_report.papers
        )
        preprint_note = ""
        if global_report.total_preprint_skipped:
            preprint_note = f", {global_report.total_preprint_skipped} preprint(s) skipped"
        print(
            f"RESULT: {'PASS' if global_report.ok else 'FAIL'} "
            f"({len(global_report.papers)} paper(s), "
            f"{global_report.total_entries} entries, "
            f"{global_report.total_dois} DOI(s), "
            f"{global_report.total_changes} change(s), "
            f"{total_err} error(s), {total_warn} warning(s)"
            f"{preprint_note})"
        )

    # Exit code logic
    if args.ci:
        # CI mode: fail only on malformed DOIs or critical parse errors.
        # not_found is common for valid DOIs not indexed in CrossRef (Zenodo,
        # special-char DOIs, very new publications) — those are warnings.
        # Network errors are also tolerated (CrossRef can be flaky).
        # Preprints (arXiv, bioRxiv) are already skipped.
        has_critical_errors = any(
            er.doi_status == "malformed"
            for p in global_report.papers
            for er in p.results
        ) or any(
            p.errors for p in global_report.papers
        )
        return 1 if has_critical_errors else 0

    return 0 if global_report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
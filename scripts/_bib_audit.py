#!/usr/bin/env python3
"""bib_literature_audit.py

Conservative, research-oriented BibTeX quality auditor and DOI enricher.
Uses only the Python standard library.

Designed for thesis/review bibliographies where references may include journal
articles, conference papers, technical reports, project deliverables, datasets,
web pages, standards, software, books, theses, and other grey literature.

Key design rules
----------------
1. Classify first, validate second. A URL does not make a paper a website, and
   a project PDF does not become a journal article merely because Crossref has
   a similarly titled record.
2. Missing DOI is not a defect for every reference type. DOI discovery is
   attempted only for scholarly publication classes by default.
3. DOI enrichment is conservative. Ambiguous Crossref candidates, preprints
   returned for journal articles, metadata contradictions, and type mismatches
   are sent to manual review instead of being written automatically.
4. Existing DOI values are verified against Crossref or DataCite when online
   mode is enabled. A DOI is treated as trusted only when metadata supports it.
5. URL validation distinguishes confirmed HTTP failures from access blocking,
   DNS/network failures, timeouts, and TLS problems. An inconclusive network
   check is never reported as a broken URL.
6. The input .bib file is never modified. Enrichment creates a separate copy.

Examples
--------
Offline audit:
    python bib_literature_audit.py references.bib

Full thesis audit:
    python bib_literature_audit.py references.bib --online --check-urls --write-enriched

PowerShell:
    python bib_literature_audit.py "references.bib" --online --check-urls --write-enriched

Outputs
-------
<stem>_audit/
    report.md
    report.json
    references_audit.csv
    manual_review.csv
    <stem>.enriched.bib          # only with --write-enriched

Crossref, DataCite and doi.org require internet access. The script uses public
metadata APIs and standard HTTP requests; no third-party Python package is
required.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import socket
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable


# =============================================================================
# Configuration
# =============================================================================

APP_NAME = "bib-literature-audit"
APP_VERSION = "1.0.0"

DEFAULT_TIMEOUT = 20.0
DEFAULT_DELAY = 0.20
DEFAULT_RETRIES = 2
DEFAULT_ACCEPT_THRESHOLD = 0.94
DEFAULT_CROSSREF_ROWS = 8

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_REGEX = re.compile(r"^(18|19|20|21)\d{2}$")
URL_REGEX = re.compile(r"^https?://", re.IGNORECASE)

RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
ACCESS_RESTRICTED_HTTP_CODES = {401, 403, 429}
CONFIRMED_BROKEN_HTTP_CODES = {404, 410}
HEAD_FALLBACK_CODES = {400, 401, 403, 404, 405, 406, 429}

# Conservative structural requirements. These are "usable bibliography"
# requirements rather than publisher-specific style rules.
REQUIRED_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "article": (("author",), ("title",), ("journal",), ("year",)),
    "inproceedings": (("author",), ("title",), ("booktitle",), ("year",)),
    "conference": (("author",), ("title",), ("booktitle",), ("year",)),
    "book": (("title",), ("year",), ("publisher",), ("author", "editor")),
    "incollection": (("author",), ("title",), ("booktitle",), ("year",)),
    "inbook": (("author", "editor"), ("title",), ("publisher",), ("year",)),
    "phdthesis": (("author",), ("title",), ("school",), ("year",)),
    "mastersthesis": (("author",), ("title",), ("school",), ("year",)),
    "techreport": (("title",), ("year",), ("author", "institution", "organization")),
    "report": (("title",), ("year",), ("author", "institution", "organization")),
    "unpublished": (("author",), ("title",), ("note",)),
    "online": (("title",), ("url",)),
    "electronic": (("title",), ("url",)),
    "webpage": (("title",), ("url",)),
    "website": (("title",), ("url",)),
    "dataset": (("title",),),
    "software": (("title",),),
    "manual": (("title",),),
    "standard": (("title",),),
    "misc": (("title",),),
}

# DOI discovery is deliberately restricted to publication classes for which
# Crossref matching is normally meaningful. Existing DOI values in all classes
# are still eligible for verification.
DEFAULT_DOI_SEARCH_KINDS = {
    "journal_article",
    "conference_paper",
    "book",
    "book_chapter",
}

WEB_HINTS = {
    "web page",
    "webpage",
    "website",
    "project factsheet",
    "factsheet",
    "project reporting summary",
    "periodic reporting",
    "online resource",
}
REPORT_HINTS = {
    "report",
    "technical report",
    "deliverable",
    "final report",
    "project report",
    "working paper",
    "white paper",
}
DATASET_HINTS = {"dataset", "data set", "data collection"}
SOFTWARE_HINTS = {"software", "source code", "code repository", "github repository"}
STANDARD_HINTS = {"standard", "guideline", "technical specification"}

# Crossref work types expected for each local scholarly class. This is used to
# prevent a preprint/posted-content DOI being silently attached to a final
# journal-article BibTeX record.
CROSSREF_TYPES_BY_KIND: dict[str, set[str]] = {
    "journal_article": {"journal-article"},
    "conference_paper": {"proceedings-article"},
    "book": {"book", "monograph", "edited-book", "reference-book"},
    "book_chapter": {"book-chapter", "reference-entry"},
}

PREPRINT_LIKE_CROSSREF_TYPES = {"posted-content", "peer-review"}


# =============================================================================
# Data models
# =============================================================================


@dataclass
class BibEntry:
    ordinal: int
    entry_type: str
    key: str
    fields: dict[str, str]
    raw: str
    start: int
    end: int

    @property
    def uid(self) -> str:
        # Internal identifier remains unique even if the .bib contains duplicate
        # citation keys.
        return f"{self.ordinal}:{self.key}"

    @property
    def title(self) -> str:
        return self.fields.get("title", "")

    @property
    def year(self) -> str:
        return self.fields.get("year", "")

    @property
    def author(self) -> str:
        return self.fields.get("author", "")

    @property
    def source_name(self) -> str:
        return (
            self.fields.get("journal")
            or self.fields.get("booktitle")
            or self.fields.get("institution")
            or self.fields.get("organization")
            or self.fields.get("publisher")
            or ""
        )

    @property
    def publisher(self) -> str:
        return self.fields.get("publisher", "")

    @property
    def url(self) -> str:
        return self.fields.get("url", "").strip()


@dataclass(frozen=True)
class ReferenceClass:
    kind: str
    family: str
    is_paper: bool
    is_web_resource: bool
    doi_search_eligible: bool
    reason: str


@dataclass
class DuplicatePair:
    uid_a: str
    key_a: str
    uid_b: str
    key_b: str
    reason: str
    title_similarity: float
    token_similarity: float
    same_year: bool
    same_first_author: bool
    same_doi: bool


@dataclass
class DOIResult:
    uid: str
    key: str
    reference_kind: str
    local_doi: str = ""
    discovered_doi: str = ""
    status: str = "offline"
    source: str = ""
    confidence: float = 0.0
    title_similarity: float = 0.0
    year_match: bool = False
    year_difference: int | None = None
    author_match: bool = False
    source_similarity: float = 0.0
    remote_type: str = ""
    type_compatible: bool = False
    remote_title: str = ""
    remote_year: str = ""
    remote_source: str = ""
    remote_publisher: str = ""
    landing_url: str = ""
    resolution_status: str = ""
    message: str = ""

    @property
    def trusted_doi(self) -> str:
        if self.status == "verified_existing":
            return self.local_doi
        if self.status == "found_high_confidence":
            return self.discovered_doi
        return ""

    @property
    def candidate_doi(self) -> str:
        return self.local_doi or self.discovered_doi


@dataclass
class URLResult:
    uid: str
    key: str
    reference_kind: str
    url: str
    status: str = "not_checked"
    http_status: int | None = None
    final_url: str = ""
    host: str = ""
    message: str = ""


@dataclass
class ApiResult:
    status: str
    data: dict[str, Any] | None = None
    http_status: int | None = None
    message: str = ""


@dataclass
class AuditSummary:
    source_file: str
    file_exists: bool
    file_size_bytes: int
    sha256: str
    encoding: str
    entry_count: int
    skipped_directives: int
    type_counts: dict[str, int]
    reference_kind_counts: dict[str, int]
    reference_family_counts: dict[str, int]
    year_counts: dict[str, int]
    source_counts: dict[str, int]
    publisher_counts: dict[str, int]
    host_counts: dict[str, int]
    duplicate_key_groups: dict[str, list[str]]
    key_case_collision_groups: dict[str, list[str]]
    duplicate_local_doi_groups: dict[str, list[str]]
    duplicate_title_groups: dict[str, list[str]]
    probable_duplicates: list[DuplicatePair]
    missing_required_fields: dict[str, list[str]]
    suspicious_year_keys: list[str]
    malformed_explicit_doi_keys: list[str]
    multiple_doi_entries: dict[str, list[str]]
    invalid_url_keys: list[str]
    source_name_variants: dict[str, list[str]]
    scholarly_keys_missing_doi_before_online: list[str]
    nonsearch_keys_without_doi: list[str]
    parse_warnings: list[str]
    doi_results: list[DOIResult] = field(default_factory=list)
    url_results: list[URLResult] = field(default_factory=list)
    duplicate_trusted_doi_groups: dict[str, list[str]] = field(default_factory=dict)


# =============================================================================
# Text, DOI and URL normalization
# =============================================================================


_LATEX_ACCENT = re.compile(r"\\[\"'`^~=\.uvHckbdtr]\s*\{?([A-Za-z])\}?")
_LATEX_COMMAND_WITH_ARG = re.compile(r"\\[A-Za-z]+\*?\s*\{([^{}]*)\}")
_LATEX_COMMAND = re.compile(r"\\[A-Za-z]+\*?")


def strip_latex(value: str) -> str:
    """Remove common LaTeX markup sufficiently for metadata comparison."""
    s = html.unescape(value or "")
    s = s.replace("~", " ")
    s = s.replace(r"\&", "&").replace(r"\%", "%").replace(r"\_", "_")
    s = _LATEX_ACCENT.sub(r"\1", s)
    for _ in range(6):
        new = _LATEX_COMMAND_WITH_ARG.sub(r"\1", s)
        if new == s:
            break
        s = new
    s = _LATEX_COMMAND.sub(" ", s)
    s = s.replace("{", "").replace("}", "")
    return " ".join(s.split())


def normalize_text(value: str) -> str:
    s = strip_latex(value)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def title_tokens(value: str) -> set[str]:
    return {token for token in normalize_text(value).split() if len(token) > 2}


def text_similarity(a: str, b: str) -> float:
    a_n, b_n = normalize_text(a), normalize_text(b)
    if not a_n or not b_n:
        return 0.0
    return SequenceMatcher(None, a_n, b_n).ratio()


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def first_author_surname(author_field: str) -> str:
    if not author_field:
        return ""
    first = re.split(r"\s+and\s+", author_field, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    first = strip_latex(first)
    if "," in first:
        surname = first.split(",", 1)[0]
    else:
        parts = first.split()
        surname = parts[-1] if parts else ""
    return normalize_text(surname)


def clean_doi(value: str) -> str:
    if not value:
        return ""
    decoded = urllib.parse.unquote(strip_latex(value)).strip()
    decoded = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", decoded, flags=re.IGNORECASE)
    decoded = re.sub(r"^doi\s*:\s*", "", decoded, flags=re.IGNORECASE)
    match = DOI_REGEX.search(decoded)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}>\"'").casefold()


def all_dois_in_entry(entry: BibEntry) -> list[str]:
    values: list[str] = []
    for name in ("doi", "url", "note", "howpublished"):
        raw = entry.fields.get(name, "")
        if not raw:
            continue
        for match in DOI_REGEX.finditer(urllib.parse.unquote(strip_latex(raw))):
            doi = match.group(0).rstrip(".,;:)]}>\"'").casefold()
            if doi and doi not in values:
                values.append(doi)
    return values


def extract_doi(entry: BibEntry) -> str:
    # Prefer an explicit DOI field, then DOI embedded in URL/note/howpublished.
    explicit = clean_doi(entry.fields.get("doi", ""))
    if explicit:
        return explicit
    values = all_dois_in_entry(entry)
    return values[0] if values else ""


def valid_http_url(value: str) -> bool:
    if not value or not URL_REGEX.match(value.strip()):
        return False
    try:
        parsed = urllib.parse.urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def url_host(value: str) -> str:
    if not valid_http_url(value):
        return ""
    try:
        return urllib.parse.urlparse(value).netloc.casefold().removeprefix("www.")
    except ValueError:
        return ""


def is_pdf_url(value: str) -> bool:
    if not valid_http_url(value):
        return False
    try:
        return urllib.parse.urlparse(value).path.casefold().endswith(".pdf")
    except ValueError:
        return False


def parse_year(value: str) -> int | None:
    clean = strip_latex(value).strip()
    if YEAR_REGEX.fullmatch(clean):
        return int(clean)
    return None


# =============================================================================
# BibTeX parser
# =============================================================================


def _find_matching_delimiter(text: str, opening_index: int) -> int:
    opener = text[opening_index]
    closer = "}" if opener == "{" else ")"
    depth = 0
    in_quote = False
    escaped = False
    for i in range(opening_index, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top_level_once(text: str, delimiter: str = ",") -> tuple[str, str]:
    brace = paren = 0
    quote = escaped = False
    for i, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            quote = not quote
            continue
        if quote:
            continue
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace = max(0, brace - 1)
        elif ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        elif ch == delimiter and brace == 0 and paren == 0:
            return text[:i], text[i + 1 :]
    return text, ""


def _read_braced_value(text: str, i: int) -> tuple[str, int]:
    depth = 0
    escaped = False
    start = i + 1
    for j in range(i, len(text)):
        ch = text[j]
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
                return text[start:j], j + 1
    return text[start:], len(text)


def _read_quoted_value(text: str, i: int) -> tuple[str, int]:
    escaped = False
    start = i + 1
    for j in range(i + 1, len(text)):
        ch = text[j]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            return text[start:j], j + 1
    return text[start:], len(text)


def _parse_value(text: str, i: int) -> tuple[str, int]:
    pieces: list[str] = []
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        if text[i] == "{":
            value, i = _read_braced_value(text, i)
        elif text[i] == '"':
            value, i = _read_quoted_value(text, i)
        else:
            start = i
            while i < n and text[i] not in ",#\r\n":
                i += 1
            value = text[start:i].strip()
        pieces.append(value.strip())
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == "#":
            i += 1
            continue
        break
    return "".join(pieces), i


def parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    i, n = 0, len(text)
    while i < n:
        while i < n and (text[i].isspace() or text[i] == ","):
            i += 1
        if i >= n:
            break
        start = i
        while i < n and (text[i].isalnum() or text[i] in "_-:"):
            i += 1
        name = text[start:i].strip().casefold()
        while i < n and text[i].isspace():
            i += 1
        if not name or i >= n or text[i] != "=":
            # Recover at the next top-level comma.
            _, remainder = _split_top_level_once(text[i:])
            if not remainder:
                break
            i += len(text[i:]) - len(remainder)
            continue
        i += 1
        value, i = _parse_value(text, i)
        fields[name] = value.strip()
        while i < n and text[i] != ",":
            i += 1
        if i < n:
            i += 1
    return fields


def parse_bibtex(text: str) -> tuple[list[BibEntry], int, list[str]]:
    entries: list[BibEntry] = []
    warnings: list[str] = []
    skipped = 0
    pos = 0
    directives = {"string", "preamble", "comment"}

    while True:
        at = text.find("@", pos)
        if at < 0:
            break
        match = re.match(r"@\s*([A-Za-z]+)\s*([({])", text[at:])
        if not match:
            pos = at + 1
            continue
        entry_type = match.group(1).casefold()
        opening = at + match.end() - 1
        closing = _find_matching_delimiter(text, opening)
        if closing < 0:
            warnings.append(f"Unclosed @{entry_type} entry near character {at}.")
            break
        raw = text[at : closing + 1]
        inner = text[opening + 1 : closing]
        pos = closing + 1

        if entry_type in directives:
            skipped += 1
            continue

        key_part, fields_part = _split_top_level_once(inner)
        key = key_part.strip()
        if not key:
            warnings.append(f"Entry near character {at} has no citation key.")
            continue
        entries.append(
            BibEntry(
                ordinal=len(entries) + 1,
                entry_type=entry_type,
                key=key,
                fields=parse_fields(fields_part),
                raw=raw,
                start=at,
                end=closing + 1,
            )
        )

    return entries, skipped, warnings


# =============================================================================
# Reference classification
# =============================================================================


def _contains_any(text: str, hints: set[str]) -> bool:
    return any(hint in text for hint in hints)


def classify_reference(entry: BibEntry) -> ReferenceClass:
    """Classify by bibliographic role, never by URL presence alone."""
    t = entry.entry_type
    f = entry.fields
    title = normalize_text(f.get("title", ""))
    subtype = normalize_text(f.get("type", ""))
    how = normalize_text(f.get("howpublished", ""))
    note = normalize_text(f.get("note", ""))
    institution = normalize_text(f.get("institution", ""))
    combined = " ".join((title, subtype, how, note, institution))
    url = entry.url

    if t == "article":
        return ReferenceClass("journal_article", "scholarly", True, False, True, "@article")
    if t in {"inproceedings", "conference"}:
        return ReferenceClass("conference_paper", "scholarly", True, False, True, f"@{t}")
    if t == "book":
        return ReferenceClass("book", "scholarly", False, False, True, "@book")
    if t in {"incollection", "inbook"}:
        return ReferenceClass("book_chapter", "scholarly", False, False, True, f"@{t}")
    if t in {"phdthesis", "mastersthesis"}:
        return ReferenceClass("thesis", "scholarly", False, False, False, f"@{t}")
    if t in {"online", "electronic", "webpage", "website"}:
        return ReferenceClass("web_resource", "web", False, True, False, f"@{t}")
    if t == "dataset":
        return ReferenceClass("dataset", "data", False, False, False, "@dataset")
    if t == "software":
        return ReferenceClass("software", "software", False, False, False, "@software")
    if t in {"manual", "standard"}:
        return ReferenceClass("standard_or_manual", "grey_literature", False, False, False, f"@{t}")

    if t in {"techreport", "report"}:
        explicit_web = _contains_any(subtype, WEB_HINTS) or _contains_any(title, WEB_HINTS)
        if explicit_web and url and not is_pdf_url(url):
            return ReferenceClass(
                "web_resource",
                "web",
                False,
                True,
                False,
                "report-like entry explicitly describes an HTML factsheet/reporting page",
            )
        return ReferenceClass("technical_report", "grey_literature", False, False, False, f"@{t}")

    if t == "misc":
        if _contains_any(combined, DATASET_HINTS):
            return ReferenceClass("dataset", "data", False, False, False, "@misc metadata indicates dataset")
        if _contains_any(combined, SOFTWARE_HINTS):
            return ReferenceClass("software", "software", False, False, False, "@misc metadata indicates software")
        if _contains_any(combined, STANDARD_HINTS):
            return ReferenceClass(
                "standard_or_manual",
                "grey_literature",
                False,
                False,
                False,
                "@misc metadata indicates standard/guideline",
            )
        if _contains_any(combined, REPORT_HINTS) and (f.get("institution") or f.get("organization")):
            return ReferenceClass(
                "technical_report",
                "grey_literature",
                False,
                False,
                False,
                "@misc metadata indicates institutional/project report",
            )
        if url and not clean_doi(url):
            return ReferenceClass("web_resource", "web", False, True, False, "@misc with ordinary web URL")
        return ReferenceClass("other_document", "other", False, False, False, "@misc without stronger classification")

    return ReferenceClass("other_document", "other", False, False, False, f"unmapped @{t} type")


# =============================================================================
# Offline quality analysis
# =============================================================================


def required_missing(entry: BibEntry) -> list[str]:
    requirements = REQUIRED_FIELDS.get(entry.entry_type, (("title",),))
    missing: list[str] = []
    for alternatives in requirements:
        if not any(entry.fields.get(name, "").strip() for name in alternatives):
            missing.append("/".join(alternatives))
    return missing


def group_duplicates(
    entries: Iterable[BibEntry],
    value_fn: Callable[[BibEntry], str],
    *,
    display_uid: bool = False,
) -> dict[str, list[str]]:
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for entry in entries:
        value = value_fn(entry)
        if value:
            groups[value].append(entry.uid if display_uid else entry.key)
    return {value: keys for value, keys in groups.items() if len(keys) > 1}


def probable_duplicate_pairs(entries: list[BibEntry]) -> list[DuplicatePair]:
    """Conservative fuzzy duplicate detection with metadata blocking."""
    blocks: defaultdict[tuple[str, str], list[BibEntry]] = defaultdict(list)
    for e in entries:
        title_n = normalize_text(e.title)
        if not title_n:
            continue
        year = str(parse_year(e.year) or "unknown")
        first_words = " ".join(title_n.split()[:4])
        blocks[(year, first_words)].append(e)
        author = first_author_surname(e.author)
        if author:
            blocks[(year, f"author:{author}")].append(e)

    seen: set[tuple[str, str]] = set()
    results: list[DuplicatePair] = []
    for block in blocks.values():
        for i in range(len(block)):
            for j in range(i + 1, len(block)):
                a, b = block[i], block[j]
                pair_id = tuple(sorted((a.uid, b.uid)))
                if pair_id in seen:
                    continue
                seen.add(pair_id)
                if normalize_text(a.title) == normalize_text(b.title):
                    continue

                title_sim = text_similarity(a.title, b.title)
                token_sim = jaccard(title_tokens(a.title), title_tokens(b.title))
                ya, yb = parse_year(a.year), parse_year(b.year)
                same_year = bool(ya is not None and yb is not None and ya == yb)
                a_author, b_author = first_author_surname(a.author), first_author_surname(b.author)
                same_author = bool(a_author and a_author == b_author)
                doi_a, doi_b = extract_doi(a), extract_doi(b)
                same_doi = bool(doi_a and doi_b and doi_a == doi_b)

                likely = (
                    same_doi
                    or title_sim >= 0.982
                    or (title_sim >= 0.93 and token_sim >= 0.84 and same_year and same_author)
                    or (title_sim >= 0.95 and token_sim >= 0.88 and same_author)
                )
                if likely:
                    results.append(
                        DuplicatePair(
                            uid_a=a.uid,
                            key_a=a.key,
                            uid_b=b.uid,
                            key_b=b.key,
                            reason="same DOI" if same_doi else "high metadata similarity",
                            title_similarity=round(title_sim, 4),
                            token_similarity=round(token_sim, 4),
                            same_year=same_year,
                            same_first_author=same_author,
                            same_doi=same_doi,
                        )
                    )
    return sorted(results, key=lambda x: (-x.title_similarity, x.key_a.casefold(), x.key_b.casefold()))


def source_name_variants(entries: list[BibEntry]) -> dict[str, list[str]]:
    variants: defaultdict[str, set[str]] = defaultdict(set)
    for e in entries:
        raw = e.fields.get("journal") or e.fields.get("booktitle") or ""
        clean = strip_latex(raw).strip()
        norm = normalize_text(clean)
        if norm and clean:
            variants[norm].add(clean)
    return {
        normalized: sorted(values, key=str.casefold)
        for normalized, values in variants.items()
        if len(values) > 1
    }


def detect_encoding(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace"), "utf-8-replacement"


def sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].casefold())))


def build_offline_summary(
    path: Path,
) -> tuple[AuditSummary, list[BibEntry], dict[str, ReferenceClass], str]:
    if not path.exists():
        raise FileNotFoundError(f"BibTeX file does not exist: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"Expected a file, got: {path}")

    raw = path.read_bytes()
    text, encoding = detect_encoding(raw)
    entries, skipped, warnings = parse_bibtex(text)
    if not entries:
        raise ValueError("No BibTeX references could be parsed from the input file.")

    classes = {e.uid: classify_reference(e) for e in entries}
    type_counts = sorted_counter(Counter(e.entry_type for e in entries))
    kind_counts = sorted_counter(Counter(classes[e.uid].kind for e in entries))
    family_counts = sorted_counter(Counter(classes[e.uid].family for e in entries))
    years = sorted_counter(Counter(strip_latex(e.year).strip() or "(missing)" for e in entries))
    sources = sorted_counter(Counter(strip_latex(e.source_name).strip() or "(missing)" for e in entries))
    publishers = sorted_counter(Counter(strip_latex(e.publisher).strip() or "(missing)" for e in entries))
    hosts = sorted_counter(Counter(url_host(e.url) for e in entries if url_host(e.url)))

    # Citation keys are normally case-sensitive, so report exact duplicate keys
    # and case-only collisions separately.
    duplicate_keys = group_duplicates(entries, lambda e: e.key, display_uid=True)
    case_collisions_raw = group_duplicates(entries, lambda e: e.key.casefold(), display_uid=False)
    case_collisions = {
        norm: keys
        for norm, keys in case_collisions_raw.items()
        if len(set(keys)) == len(keys) and len({k.casefold() for k in keys}) == 1 and len(set(keys)) > 1
    }

    duplicate_dois = group_duplicates(entries, extract_doi, display_uid=True)
    duplicate_titles = group_duplicates(entries, lambda e: normalize_text(e.title), display_uid=True)

    missing_fields = {e.uid: missing for e in entries if (missing := required_missing(e))}
    suspicious_years = [e.uid for e in entries if e.year.strip() and parse_year(e.year) is None]
    malformed_explicit_doi = [
        e.uid for e in entries if e.fields.get("doi", "").strip() and not clean_doi(e.fields.get("doi", ""))
    ]
    multiple_dois = {e.uid: values for e in entries if len(values := all_dois_in_entry(e)) > 1}
    invalid_urls = [e.uid for e in entries if e.url and not valid_http_url(e.url)]

    scholarly_missing = [
        e.uid for e in entries if classes[e.uid].doi_search_eligible and not extract_doi(e)
    ]
    nonsearch_missing = [
        e.uid for e in entries if not classes[e.uid].doi_search_eligible and not extract_doi(e)
    ]

    summary = AuditSummary(
        source_file=path.name,
        file_exists=True,
        file_size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        encoding=encoding,
        entry_count=len(entries),
        skipped_directives=skipped,
        type_counts=type_counts,
        reference_kind_counts=kind_counts,
        reference_family_counts=family_counts,
        year_counts=years,
        source_counts=sources,
        publisher_counts=publishers,
        host_counts=hosts,
        duplicate_key_groups=duplicate_keys,
        key_case_collision_groups=case_collisions,
        duplicate_local_doi_groups=duplicate_dois,
        duplicate_title_groups=duplicate_titles,
        probable_duplicates=probable_duplicate_pairs(entries),
        missing_required_fields=missing_fields,
        suspicious_year_keys=suspicious_years,
        malformed_explicit_doi_keys=malformed_explicit_doi,
        multiple_doi_entries=multiple_dois,
        invalid_url_keys=invalid_urls,
        source_name_variants=source_name_variants(entries),
        scholarly_keys_missing_doi_before_online=scholarly_missing,
        nonsearch_keys_without_doi=nonsearch_missing,
        parse_warnings=warnings,
    )
    return summary, entries, classes, text


# =============================================================================
# Robust HTTP client
# =============================================================================


class HTTPClient:
    def __init__(
        self,
        timeout: float,
        delay: float,
        retries: int,
    ) -> None:
        self.timeout = max(1.0, timeout)
        self.delay = max(0.0, delay)
        self.retries = max(0, retries)
        self.user_agent = f"{APP_NAME}/{APP_VERSION} (research bibliography audit)"
        self._last_request = 0.0
        self._json_cache: dict[str, ApiResult] = {}
        self._doi_resolution_cache: dict[str, tuple[str, str]] = {}

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.delay - elapsed
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
        raw = exc.headers.get("Retry-After") if exc.headers else None
        if raw:
            try:
                return min(30.0, max(0.0, float(raw)))
            except ValueError:
                pass
        return min(8.0, 0.75 * (2 ** attempt))

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        read_limit: int | None = None,
    ) -> tuple[bytes, int, str]:
        all_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        }
        if headers:
            all_headers.update(headers)

        last_exc: BaseException | None = None
        for attempt in range(self.retries + 1):
            self._throttle()
            req = urllib.request.Request(url, headers=all_headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read() if read_limit is None else response.read(read_limit)
                    status = int(getattr(response, "status", 200) or 200)
                    final_url = response.geturl()
                    return body, status, final_url
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in RETRYABLE_HTTP_CODES and attempt < self.retries:
                    time.sleep(self._retry_after(exc, attempt))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(min(6.0, 0.5 * (2 ** attempt)))
                    continue
                raise
            finally:
                self._last_request = time.monotonic()

        if last_exc:
            raise last_exc
        raise RuntimeError("HTTP request failed without an exception.")

    def get_json(self, url: str, *, use_cache: bool = True) -> ApiResult:
        if use_cache and url in self._json_cache:
            return self._json_cache[url]
        try:
            body, status, _ = self.request(url, headers={"Accept": "application/json"})
            try:
                payload = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                result = ApiResult("invalid_response", None, status, str(exc))
            else:
                result = ApiResult("ok", payload if isinstance(payload, dict) else None, status, "")
        except urllib.error.HTTPError as exc:
            result = ApiResult(
                "not_found" if exc.code == 404 else "http_error",
                None,
                exc.code,
                str(exc),
            )
        except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
            result = ApiResult(classify_network_exception(exc), None, None, str(exc))
        if use_cache:
            self._json_cache[url] = result
        return result

    def resolve_doi(self, doi: str) -> tuple[str, str]:
        if not doi:
            return "", "not_attempted"
        if doi in self._doi_resolution_cache:
            return self._doi_resolution_cache[doi]
        url = "https://doi.org/" + urllib.parse.quote(doi, safe="/:;()")

        # HEAD first; if a server rejects HEAD, use a tiny GET.
        try:
            _, status, final = self.request(url, method="HEAD", headers={"Accept": "text/html"})
            result = (final, "resolved" if 200 <= status < 400 else f"http_{status}")
        except urllib.error.HTTPError as exc:
            if exc.code in HEAD_FALLBACK_CODES:
                try:
                    _, status, final = self.request(
                        url,
                        method="GET",
                        headers={"Range": "bytes=0-1024", "Accept": "text/html"},
                        read_limit=2048,
                    )
                    result = (final, "resolved" if 200 <= status < 400 else f"http_{status}")
                except urllib.error.HTTPError as exc2:
                    result = ("", f"http_{exc2.code}")
                except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc2:
                    result = ("", classify_network_exception(exc2))
            else:
                result = ("", f"http_{exc.code}")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
            result = ("", classify_network_exception(exc))

        self._doi_resolution_cache[doi] = result
        return result


def _unwrap_reason(exc: BaseException) -> BaseException:
    reason = getattr(exc, "reason", None)
    return reason if isinstance(reason, BaseException) else exc


def classify_network_exception(exc: BaseException) -> str:
    reason = _unwrap_reason(exc)
    if isinstance(reason, socket.gaierror):
        return "dns_error"
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(reason, ssl.SSLError):
        return "tls_error"
    if isinstance(reason, (ConnectionResetError, ConnectionRefusedError, ConnectionAbortedError)):
        return "connection_error"
    message = str(reason).casefold()
    if "getaddrinfo" in message or "name or service not known" in message or "nodename nor servname" in message:
        return "dns_error"
    if "timed out" in message:
        return "timeout"
    if "ssl" in message or "certificate" in message:
        return "tls_error"
    return "network_error"


# =============================================================================
# Crossref / DataCite helpers
# =============================================================================


def crossref_get(client: HTTPClient, doi: str) -> ApiResult:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    api = client.get_json(url)
    if api.status != "ok" or not api.data:
        return api
    message = api.data.get("message")
    if isinstance(message, dict):
        return ApiResult("ok", message, api.http_status, "")
    return ApiResult("invalid_response", None, api.http_status, "Crossref response has no work object.")


def datacite_get(client: HTTPClient, doi: str) -> ApiResult:
    url = "https://api.datacite.org/dois/" + urllib.parse.quote(doi, safe="")
    api = client.get_json(url)
    if api.status != "ok" or not api.data:
        return api
    try:
        attrs = api.data["data"]["attributes"]
    except (KeyError, TypeError):
        return ApiResult("invalid_response", None, api.http_status, "DataCite response has no attributes object.")
    if isinstance(attrs, dict):
        return ApiResult("ok", attrs, api.http_status, "")
    return ApiResult("invalid_response", None, api.http_status, "DataCite attributes are not an object.")


def crossref_search(client: HTTPClient, entry: BibEntry, rows: int) -> tuple[list[dict[str, Any]], ApiResult]:
    # Separate fields improve search quality while query.bibliographic supplies
    # combined context. No year filter is used because online-first/print years
    # can legitimately differ by one year.
    title = strip_latex(entry.title)
    author = strip_latex(entry.author)
    source = strip_latex(entry.source_name)
    year = strip_latex(entry.year)
    combined = " ".join(part for part in (title, author, source, year) if part)
    params: dict[str, str] = {
        "query.bibliographic": combined,
        "query.title": title,
        "rows": str(max(2, rows)),
        "select": "DOI,title,author,container-title,publisher,published-print,published-online,issued,type,URL",
    }
    first_author = first_author_surname(entry.author)
    if first_author:
        params["query.author"] = first_author
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    api = client.get_json(url, use_cache=False)
    if api.status != "ok" or not api.data:
        return [], api
    try:
        raw_items = api.data["message"]["items"]
    except (KeyError, TypeError):
        return [], ApiResult("invalid_response", None, api.http_status, "Crossref search returned no items array.")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    return dedupe_crossref_candidates(items), api


def dedupe_crossref_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate search results by DOI before calculating candidate margin."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        doi = clean_doi(str(item.get("DOI", "")))
        marker = doi or json.dumps(item, sort_keys=True, ensure_ascii=False)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(item)
    return unique


def _first_list_value(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def _crossref_title(item: dict[str, Any]) -> str:
    return _first_list_value(item.get("title"))


def _crossref_source(item: dict[str, Any]) -> str:
    return _first_list_value(item.get("container-title"))


def _crossref_year(item: dict[str, Any]) -> str:
    for field_name in ("published-print", "published-online", "issued"):
        value = item.get(field_name)
        try:
            return str(value["date-parts"][0][0])
        except (KeyError, TypeError, IndexError):
            continue
    return ""


def _crossref_first_author(item: dict[str, Any]) -> str:
    authors = item.get("author")
    if isinstance(authors, list) and authors and isinstance(authors[0], dict):
        return normalize_text(str(authors[0].get("family", "")))
    return ""


def _crossref_type(item: dict[str, Any]) -> str:
    return str(item.get("type", "") or "").casefold()


def crossref_type_compatible(reference_kind: str, remote_type: str) -> bool:
    expected = CROSSREF_TYPES_BY_KIND.get(reference_kind)
    if not expected:
        return True
    return remote_type.casefold() in expected


def year_comparison(local_year: str, remote_year: str) -> tuple[bool, int | None, bool]:
    ly = parse_year(local_year)
    ry = parse_year(remote_year)
    if ly is None or ry is None:
        return False, None, True  # absent year does not create a contradiction
    diff = abs(ly - ry)
    return diff == 0, diff, diff <= 1


def crossref_match(
    entry: BibEntry,
    reference_kind: str,
    item: dict[str, Any],
) -> tuple[float, float, bool, int | None, bool, float, bool]:
    title_sim = text_similarity(entry.title, _crossref_title(item))
    remote_year = _crossref_year(item)
    year_match, year_diff, year_compatible = year_comparison(entry.year, remote_year)

    local_author = first_author_surname(entry.author)
    remote_author = _crossref_first_author(item)
    author_match = bool(local_author and remote_author and local_author == remote_author)

    remote_source = _crossref_source(item)
    source_sim = text_similarity(entry.source_name, remote_source) if entry.source_name and remote_source else 0.0
    type_ok = crossref_type_compatible(reference_kind, _crossref_type(item))

    # Weighted metadata score. Type compatibility is kept as a hard acceptance
    # rule rather than allowing a high title score to hide a preprint mismatch.
    components: list[tuple[float, float]] = [(0.70, title_sim)]
    if local_author and remote_author:
        components.append((0.11, 1.0 if author_match else 0.0))
    if parse_year(entry.year) is not None and parse_year(remote_year) is not None:
        year_score = 1.0 if year_match else (0.65 if year_compatible else 0.0)
        components.append((0.08, year_score))
    if entry.source_name and remote_source:
        components.append((0.11, source_sim))
    total = sum(weight for weight, _ in components)
    score = sum(weight * value for weight, value in components) / total if total else 0.0
    return score, title_sim, year_match, year_diff, author_match, source_sim, type_ok


def validate_datacite(
    entry: BibEntry,
    attrs: dict[str, Any],
) -> tuple[float, float, bool, int | None, bool, float, str, str, str, str, str]:
    titles = attrs.get("titles") or []
    remote_title = ""
    if isinstance(titles, list) and titles and isinstance(titles[0], dict):
        remote_title = str(titles[0].get("title", ""))

    remote_year = str(attrs.get("publicationYear", "") or "")
    publisher = str(attrs.get("publisher", "") or "")
    container_obj = attrs.get("container")
    container = str(container_obj.get("title", "")) if isinstance(container_obj, dict) else ""
    resource_type = ""
    types = attrs.get("types")
    if isinstance(types, dict):
        resource_type = str(types.get("resourceTypeGeneral") or types.get("resourceType") or "")

    creators = attrs.get("creators") or []
    remote_author = ""
    if isinstance(creators, list) and creators and isinstance(creators[0], dict):
        remote_author = normalize_text(str(creators[0].get("familyName") or creators[0].get("name", "")))

    title_sim = text_similarity(entry.title, remote_title)
    year_match, year_diff, year_compatible = year_comparison(entry.year, remote_year)
    local_author = first_author_surname(entry.author)
    author_match = bool(local_author and remote_author and (local_author == remote_author or local_author in remote_author))
    source_sim = text_similarity(entry.source_name, container) if entry.source_name and container else 0.0

    score = title_sim
    if year_match:
        score = min(1.0, score + 0.03)
    elif year_diff == 1:
        score = min(1.0, score + 0.01)
    if author_match:
        score = min(1.0, score + 0.03)
    if not year_compatible:
        score *= 0.85
    return (
        score,
        title_sim,
        year_match,
        year_diff,
        author_match,
        source_sim,
        remote_title,
        remote_year,
        container,
        publisher,
        resource_type,
    )


def existing_doi_supported(
    entry: BibEntry,
    title_similarity: float,
    year_difference: int | None,
    author_match: bool,
) -> bool:
    if title_similarity < 0.90:
        return False
    if year_difference is not None and year_difference > 1:
        return False
    local_author = first_author_surname(entry.author)
    if local_author and not author_match:
        return False
    return True


def candidate_acceptance_reasons(
    entry: BibEntry,
    reference_kind: str,
    item: dict[str, Any],
    *,
    score: float,
    title_similarity: float,
    year_difference: int | None,
    author_match: bool,
    source_similarity: float,
    type_compatible: bool,
    margin: float,
    accept_threshold: float,
) -> list[str]:
    reasons: list[str] = []
    remote_type = _crossref_type(item)
    local_author = first_author_surname(entry.author)
    remote_author = _crossref_first_author(item)
    remote_source = _crossref_source(item)

    if score < accept_threshold:
        reasons.append(f"metadata score {score:.3f} < {accept_threshold:.3f}")
    if title_similarity < 0.97:
        reasons.append(f"title similarity {title_similarity:.3f} < 0.970")
    if not type_compatible:
        reasons.append(f"Crossref type '{remote_type or 'missing'}' is incompatible with {reference_kind}")
    if remote_type in PREPRINT_LIKE_CROSSREF_TYPES and reference_kind == "journal_article":
        reasons.append("candidate is preprint/posted content rather than a journal article")
    if local_author and remote_author and not author_match:
        reasons.append("first author does not match")
    if year_difference is not None and year_difference > 1:
        reasons.append(f"publication year differs by {year_difference} years")
    if entry.source_name and remote_source and source_similarity < 0.70:
        reasons.append(f"source similarity {source_similarity:.3f} < 0.700")

    # Candidate separation. Near-perfect metadata can tolerate a slightly smaller
    # margin, but a zero-margin tie between distinct DOI records stays manual.
    minimum_margin = 0.015
    if margin < minimum_margin:
        reasons.append(f"candidate margin {margin:.3f} < {minimum_margin:.3f}")
    return reasons


# =============================================================================
# DOI audit
# =============================================================================


def audit_dois(
    entries: list[BibEntry],
    classes: dict[str, ReferenceClass],
    client: HTTPClient,
    *,
    search_missing: bool,
    accept_threshold: float,
    crossref_rows: int,
) -> list[DOIResult]:
    results: list[DOIResult] = []

    for index, entry in enumerate(entries, start=1):
        cls = classes[entry.uid]
        local_doi = extract_doi(entry)
        result = DOIResult(entry.uid, entry.key, cls.kind, local_doi=local_doi)
        print(f"[DOI {index:>4}/{len(entries)}] {entry.key}")

        # ------------------------------------------------------------------
        # Existing DOI verification
        # ------------------------------------------------------------------
        if local_doi:
            crossref = crossref_get(client, local_doi)
            if crossref.status == "ok" and crossref.data:
                item = crossref.data
                score, ts, ym, yd, am, ss, type_ok = crossref_match(entry, cls.kind, item)
                result.status = "verified_existing" if existing_doi_supported(entry, ts, yd, am) else "existing_doi_review"
                result.source = "Crossref"
                result.confidence = round(score, 4)
                result.title_similarity = round(ts, 4)
                result.year_match = ym
                result.year_difference = yd
                result.author_match = am
                result.source_similarity = round(ss, 4)
                result.remote_type = _crossref_type(item)
                result.type_compatible = type_ok
                result.remote_title = _crossref_title(item)
                result.remote_year = _crossref_year(item)
                result.remote_source = _crossref_source(item)
                result.remote_publisher = str(item.get("publisher", "") or "")
                if result.status != "verified_existing":
                    result.message = "Existing DOI metadata does not sufficiently support the local BibTeX record; review manually."
            elif crossref.status == "not_found":
                datacite = datacite_get(client, local_doi)
                if datacite.status == "ok" and datacite.data:
                    score, ts, ym, yd, am, ss, rt, ry, rs, rp, rtype = validate_datacite(entry, datacite.data)
                    result.status = "verified_existing" if existing_doi_supported(entry, ts, yd, am) else "existing_doi_review"
                    result.source = "DataCite"
                    result.confidence = round(score, 4)
                    result.title_similarity = round(ts, 4)
                    result.year_match = ym
                    result.year_difference = yd
                    result.author_match = am
                    result.source_similarity = round(ss, 4)
                    result.remote_type = rtype
                    result.type_compatible = True
                    result.remote_title, result.remote_year = rt, ry
                    result.remote_source, result.remote_publisher = rs, rp
                    if result.status != "verified_existing":
                        result.message = "Existing DOI metadata does not sufficiently support the local BibTeX record; review manually."
                elif datacite.status == "not_found":
                    result.status = "existing_doi_not_registered"
                    result.message = "DOI was not found in Crossref or DataCite metadata APIs."
                else:
                    result.status = "existing_doi_lookup_inconclusive"
                    result.message = f"DataCite lookup was inconclusive: {datacite.status}: {datacite.message}"
            else:
                # Do not call a network failure a DOI mismatch.
                result.status = "existing_doi_lookup_inconclusive"
                result.message = f"Crossref verification was inconclusive: {crossref.status}: {crossref.message}"

            result.landing_url, result.resolution_status = client.resolve_doi(local_doi)
            results.append(result)
            continue

        # ------------------------------------------------------------------
        # Missing DOI handling by reference class
        # ------------------------------------------------------------------
        if not cls.doi_search_eligible:
            result.status = "not_applicable"
            result.message = (
                f"No missing-DOI search performed because this entry is classified as {cls.kind}. "
                "Absence of a DOI is not treated as a quality defect for this class."
            )
            results.append(result)
            continue

        if not search_missing:
            result.status = "missing_not_searched"
            results.append(result)
            continue

        candidates, search_api = crossref_search(client, entry, crossref_rows)
        if search_api.status != "ok":
            result.status = "doi_search_inconclusive"
            result.message = f"Crossref search was inconclusive: {search_api.status}: {search_api.message}"
            results.append(result)
            continue

        scored: list[tuple[float, dict[str, Any], tuple[float, bool, int | None, bool, float, bool]]] = []
        for item in candidates:
            score, ts, ym, yd, am, ss, type_ok = crossref_match(entry, cls.kind, item)
            scored.append((score, item, (ts, ym, yd, am, ss, type_ok)))
        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            result.status = "not_found"
            result.message = "Crossref returned no DOI candidate."
            results.append(result)
            continue

        score, item, details = scored[0]
        ts, ym, yd, am, ss, type_ok = details
        candidate_doi = clean_doi(str(item.get("DOI", "")))

        # Compare against the next distinct candidate. Candidate list has already
        # been deduplicated by DOI.
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        margin = score - runner_up

        result.discovered_doi = candidate_doi
        result.source = "Crossref search"
        result.confidence = round(score, 4)
        result.title_similarity = round(ts, 4)
        result.year_match = ym
        result.year_difference = yd
        result.author_match = am
        result.source_similarity = round(ss, 4)
        result.remote_type = _crossref_type(item)
        result.type_compatible = type_ok
        result.remote_title = _crossref_title(item)
        result.remote_year = _crossref_year(item)
        result.remote_source = _crossref_source(item)
        result.remote_publisher = str(item.get("publisher", "") or "")

        reasons = candidate_acceptance_reasons(
            entry,
            cls.kind,
            item,
            score=score,
            title_similarity=ts,
            year_difference=yd,
            author_match=am,
            source_similarity=ss,
            type_compatible=type_ok,
            margin=margin,
            accept_threshold=accept_threshold,
        )

        if candidate_doi and not reasons:
            result.status = "found_high_confidence"
            result.landing_url, result.resolution_status = client.resolve_doi(candidate_doi)
        else:
            result.status = "candidate_manual_review"
            if not candidate_doi:
                reasons.insert(0, "best candidate has no valid DOI")
            result.message = "Manual review required: " + "; ".join(reasons)
        results.append(result)

    return results


# =============================================================================
# URL audit
# =============================================================================


def classify_http_status(code: int) -> str:
    if 200 <= code < 400:
        return "reachable"
    if code in ACCESS_RESTRICTED_HTTP_CODES:
        return "access_restricted"
    if code in CONFIRMED_BROKEN_HTTP_CODES:
        return "confirmed_broken"
    if 400 <= code < 500:
        return "http_client_error"
    if 500 <= code < 600:
        return "server_error"
    return "http_error"


def _url_request_once(client: HTTPClient, url: str, method: str) -> tuple[str, int | None, str, str]:
    try:
        headers = {"Accept": "*/*"}
        read_limit = None
        if method == "GET":
            headers["Range"] = "bytes=0-2047"
            read_limit = 4096
        _, status, final = client.request(url, method=method, headers=headers, read_limit=read_limit)
        return classify_http_status(status), status, final, ""
    except urllib.error.HTTPError as exc:
        return classify_http_status(exc.code), exc.code, getattr(exc, "url", "") or "", str(exc)
    except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
        return classify_network_exception(exc), None, "", str(exc)


def check_reference_urls(
    entries: list[BibEntry],
    classes: dict[str, ReferenceClass],
    client: HTTPClient,
    *,
    include_paper_urls: bool,
) -> list[URLResult]:
    # By default validate web/grey/data/other references. Paper landing URLs are
    # not needed for DOI quality control and can trigger publisher bot defenses.
    candidates = [
        e
        for e in entries
        if e.url and (include_paper_urls or not classes[e.uid].is_paper)
    ]
    results: list[URLResult] = []

    for index, entry in enumerate(candidates, start=1):
        cls = classes[entry.uid]
        url = entry.url
        result = URLResult(entry.uid, entry.key, cls.kind, url, host=url_host(url))
        print(f"[URL {index:>4}/{len(candidates)}] {entry.key}")

        if not valid_http_url(url):
            result.status = "invalid_url"
            result.message = "URL is not a syntactically valid HTTP/HTTPS URL."
            results.append(result)
            continue

        status, http_code, final, message = _url_request_once(client, url, "HEAD")

        # HEAD is frequently blocked or incorrectly implemented. For suspicious
        # 4xx HEAD results, make one small GET before concluding anything.
        if http_code in HEAD_FALLBACK_CODES:
            status2, code2, final2, message2 = _url_request_once(client, url, "GET")
            status, http_code = status2, code2
            final = final2 or final
            message = message2 or message

        result.status = status
        result.http_status = http_code
        result.final_url = final
        result.message = message
        results.append(result)

    return results


# =============================================================================
# Derived online statistics
# =============================================================================


def doi_statistics(
    entries: list[BibEntry],
    classes: dict[str, ReferenceClass],
    results: list[DOIResult],
) -> dict[str, int]:
    eligible = [e for e in entries if classes[e.uid].doi_search_eligible]
    by_uid = {r.uid: r for r in results}

    original_with_doi = sum(bool(extract_doi(e)) for e in eligible)
    verified_existing = sum(by_uid.get(e.uid) and by_uid[e.uid].status == "verified_existing" for e in eligible)
    existing_review = sum(
        by_uid.get(e.uid)
        and by_uid[e.uid].status in {
            "existing_doi_review",
            "existing_doi_not_registered",
            "existing_doi_lookup_inconclusive",
        }
        for e in eligible
    )
    discovered = sum(by_uid.get(e.uid) and by_uid[e.uid].status == "found_high_confidence" for e in eligible)
    manual = sum(by_uid.get(e.uid) and by_uid[e.uid].status == "candidate_manual_review" for e in eligible)
    not_found = sum(by_uid.get(e.uid) and by_uid[e.uid].status == "not_found" for e in eligible)
    inconclusive = sum(by_uid.get(e.uid) and by_uid[e.uid].status == "doi_search_inconclusive" for e in eligible)
    missing_not_searched = sum(by_uid.get(e.uid) and by_uid[e.uid].status == "missing_not_searched" for e in eligible)

    trusted = verified_existing + discovered
    enriched_field_coverage = original_with_doi + discovered
    return {
        "doi_search_eligible_references": len(eligible),
        "original_with_doi_field": original_with_doi,
        "verified_existing_doi": verified_existing,
        "existing_doi_needing_review_or_inconclusive": existing_review,
        "high_confidence_doi_found": discovered,
        "manual_review_candidates": manual,
        "no_candidate_found": not_found,
        "search_inconclusive": inconclusive,
        "missing_not_searched": missing_not_searched,
        "trusted_doi_coverage": trusted,
        "trusted_doi_unresolved": len(eligible) - trusted,
        "enriched_file_doi_field_coverage": enriched_field_coverage,
    }


def url_statistics(results: list[URLResult]) -> dict[str, int]:
    c = Counter(r.status for r in results)
    inconclusive = sum(c[s] for s in ("dns_error", "timeout", "tls_error", "connection_error", "network_error"))
    return {
        "checked": len(results),
        "reachable": c["reachable"],
        "access_restricted": c["access_restricted"],
        "confirmed_broken": c["confirmed_broken"],
        "http_client_error": c["http_client_error"],
        "server_error": c["server_error"],
        "invalid_url": c["invalid_url"],
        "network_inconclusive": inconclusive,
        "dns_error": c["dns_error"],
        "timeout": c["timeout"],
        "tls_error": c["tls_error"],
        "connection_error": c["connection_error"],
        "network_error": c["network_error"],
    }


def trusted_doi_duplicate_groups(results: list[DOIResult]) -> dict[str, list[str]]:
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for r in results:
        if r.trusted_doi:
            groups[r.trusted_doi].append(r.uid)
    return {doi: uids for doi, uids in groups.items() if len(uids) > 1}


# =============================================================================
# Reporting
# =============================================================================


def safe_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def top_items(mapping: dict[str, int], limit: int = 25) -> list[tuple[str, int]]:
    return list(mapping.items())[:limit]


def write_csv(
    entries: list[BibEntry],
    classes: dict[str, ReferenceClass],
    doi_results: list[DOIResult],
    url_results: list[URLResult],
    out: Path,
) -> None:
    doi_map = {r.uid: r for r in doi_results}
    url_map = {r.uid: r for r in url_results}
    fields = [
        "uid",
        "key",
        "entry_type",
        "reference_kind",
        "reference_family",
        "is_paper",
        "is_web_resource",
        "doi_search_eligible",
        "classification_reason",
        "title",
        "authors",
        "year",
        "source",
        "publisher",
        "url",
        "url_host",
        "url_status",
        "url_http_status",
        "url_final",
        "local_doi",
        "discovered_doi",
        "trusted_doi",
        "doi_status",
        "doi_source",
        "doi_confidence",
        "doi_title_similarity",
        "doi_year_difference",
        "doi_author_match",
        "doi_source_similarity",
        "doi_remote_type",
        "doi_type_compatible",
        "publisher_landing_page",
        "doi_resolution_status",
        "missing_required_fields",
    ]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for e in entries:
            cls = classes[e.uid]
            dr = doi_map.get(
                e.uid,
                DOIResult(e.uid, e.key, cls.kind, local_doi=extract_doi(e), status="not_run"),
            )
            ur = url_map.get(e.uid, URLResult(e.uid, e.key, cls.kind, e.url, host=url_host(e.url)))
            writer.writerow(
                {
                    "uid": e.uid,
                    "key": e.key,
                    "entry_type": e.entry_type,
                    "reference_kind": cls.kind,
                    "reference_family": cls.family,
                    "is_paper": cls.is_paper,
                    "is_web_resource": cls.is_web_resource,
                    "doi_search_eligible": cls.doi_search_eligible,
                    "classification_reason": cls.reason,
                    "title": strip_latex(e.title),
                    "authors": strip_latex(e.author),
                    "year": strip_latex(e.year),
                    "source": strip_latex(e.source_name),
                    "publisher": strip_latex(e.publisher),
                    "url": e.url,
                    "url_host": ur.host,
                    "url_status": ur.status,
                    "url_http_status": ur.http_status or "",
                    "url_final": ur.final_url,
                    "local_doi": dr.local_doi,
                    "discovered_doi": dr.discovered_doi,
                    "trusted_doi": dr.trusted_doi,
                    "doi_status": dr.status,
                    "doi_source": dr.source,
                    "doi_confidence": dr.confidence,
                    "doi_title_similarity": dr.title_similarity,
                    "doi_year_difference": "" if dr.year_difference is None else dr.year_difference,
                    "doi_author_match": dr.author_match,
                    "doi_source_similarity": dr.source_similarity,
                    "doi_remote_type": dr.remote_type,
                    "doi_type_compatible": dr.type_compatible,
                    "publisher_landing_page": dr.landing_url,
                    "doi_resolution_status": dr.resolution_status,
                    "missing_required_fields": "; ".join(required_missing(e)),
                }
            )


def write_manual_review_csv(
    summary: AuditSummary,
    entries: list[BibEntry],
    out: Path,
) -> int:
    entry_map = {e.uid: e for e in entries}
    rows: list[dict[str, str]] = []

    def add(issue: str, uid: str, details: str, candidate: str = "") -> None:
        entry = entry_map.get(uid)
        rows.append(
            {
                "issue_type": issue,
                "uid": uid,
                "key": entry.key if entry else uid.split(":", 1)[-1],
                "title": strip_latex(entry.title) if entry else "",
                "candidate": candidate,
                "details": details,
            }
        )

    for normalized, uids in summary.duplicate_title_groups.items():
        for uid in uids:
            add("exact_title_duplicate", uid, f"Normalized title is shared by {', '.join(uids)}")
    for doi, uids in summary.duplicate_local_doi_groups.items():
        for uid in uids:
            add("duplicate_local_doi", uid, f"Local DOI {doi} is shared by {', '.join(uids)}", doi)
    for doi, uids in summary.duplicate_trusted_doi_groups.items():
        for uid in uids:
            add("duplicate_trusted_doi", uid, f"Trusted DOI {doi} is shared by {', '.join(uids)}", doi)
    for pair in summary.probable_duplicates:
        add("probable_duplicate", pair.uid_a, f"Similar to {pair.uid_b}; title similarity={pair.title_similarity:.3f}")
        add("probable_duplicate", pair.uid_b, f"Similar to {pair.uid_a}; title similarity={pair.title_similarity:.3f}")
    for uid, missing in summary.missing_required_fields.items():
        add("missing_required_fields", uid, "; ".join(missing))
    for uid in summary.malformed_explicit_doi_keys:
        add("malformed_explicit_doi", uid, "Explicit DOI field exists but no syntactically valid DOI was extracted.")
    for uid, dois in summary.multiple_doi_entries.items():
        add("multiple_dois_in_entry", uid, "Multiple different DOI values found in one entry.", "; ".join(dois))

    for r in summary.doi_results:
        if r.status in {
            "candidate_manual_review",
            "existing_doi_review",
            "existing_doi_not_registered",
            "existing_doi_lookup_inconclusive",
            "doi_search_inconclusive",
        }:
            add("doi_" + r.status, r.uid, r.message, r.candidate_doi)

    for r in summary.url_results:
        if r.status in {
            "confirmed_broken",
            "http_client_error",
            "server_error",
            "invalid_url",
        }:
            add("url_" + r.status, r.uid, f"{r.url} | HTTP={r.http_status or ''} | {r.message}")

    # Deduplicate identical rows while preserving order.
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        marker = (row["issue_type"], row["uid"], row["candidate"], row["details"])
        if marker not in seen:
            seen.add(marker)
            unique.append(row)

    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["issue_type", "uid", "key", "title", "candidate", "details"])
        writer.writeheader()
        writer.writerows(unique)
    return len(unique)


def write_json(summary: AuditSummary, out: Path) -> None:
    out.write_text(json.dumps(asdict(summary), indent=2, ensure_ascii=False), encoding="utf-8")


def write_markdown(
    summary: AuditSummary,
    entries: list[BibEntry],
    classes: dict[str, ReferenceClass],
    out: Path,
) -> None:
    doi_stats = doi_statistics(entries, classes, summary.doi_results)
    url_stats = url_statistics(summary.url_results)

    lines: list[str] = [
        "# Literature Bibliography Audit Report",
        "",
        "## Provenance",
        "",
        f"- Source: `{summary.source_file}`",
        f"- File size: `{summary.file_size_bytes:,}` bytes",
        f"- Encoding: `{summary.encoding}`",
        f"- SHA-256: `{summary.sha256}`",
        f"- Parsed references: **{summary.entry_count}**",
        f"- Skipped BibTeX directives: **{summary.skipped_directives}**",
        "",
        "## Reference classification",
        "",
        "Classification is bibliographic rather than URL-based. A journal article remains a journal article when it has a URL; a PDF project deliverable remains a technical report; and only genuinely web-based records are classified as web resources.",
        "",
        "| Reference kind | Count |",
        "|---|---:|",
    ]
    for key, value in summary.reference_kind_counts.items():
        lines.append(f"| {safe_cell(key)} | {value} |")

    lines += ["", "### Reference families", "", "| Family | Count |", "|---|---:|"]
    for key, value in summary.reference_family_counts.items():
        lines.append(f"| {safe_cell(key)} | {value} |")

    lines += [
        "",
        "## Quality summary",
        "",
        f"- Entries missing required structural metadata: **{len(summary.missing_required_fields)}**",
        f"- Exact duplicate citation-key groups: **{len(summary.duplicate_key_groups)}**",
        f"- Case-only citation-key collision groups: **{len(summary.key_case_collision_groups)}**",
        f"- Duplicate local DOI groups: **{len(summary.duplicate_local_doi_groups)}**",
        f"- Exact normalized-title duplicate groups: **{len(summary.duplicate_title_groups)}**",
        f"- Probable fuzzy duplicate pairs: **{len(summary.probable_duplicates)}**",
        f"- Duplicate trusted DOI groups after online audit: **{len(summary.duplicate_trusted_doi_groups)}**",
        f"- Suspicious year fields: **{len(summary.suspicious_year_keys)}**",
        f"- Malformed explicit DOI fields: **{len(summary.malformed_explicit_doi_keys)}**",
        f"- Entries containing multiple different DOI values: **{len(summary.multiple_doi_entries)}**",
        f"- Invalid URL syntax: **{len(summary.invalid_url_keys)}**",
        f"- DOI-search-eligible scholarly references originally lacking DOI: **{len(summary.scholarly_keys_missing_doi_before_online)}**",
        f"- Non-search reference classes without DOI: **{len(summary.nonsearch_keys_without_doi)}** (not treated as DOI defects)",
        "",
        "### DOI result summary",
        "",
        f"- DOI-search-eligible scholarly references: **{doi_stats['doi_search_eligible_references']}**",
        f"- DOI fields present before enrichment: **{doi_stats['original_with_doi_field']}**",
        f"- Existing DOI values verified: **{doi_stats['verified_existing_doi']}**",
        f"- Existing DOI values needing review or inconclusive verification: **{doi_stats['existing_doi_needing_review_or_inconclusive']}**",
        f"- High-confidence missing DOIs discovered: **{doi_stats['high_confidence_doi_found']}**",
        f"- Candidate DOIs requiring manual review: **{doi_stats['manual_review_candidates']}**",
        f"- No Crossref candidate found: **{doi_stats['no_candidate_found']}**",
        f"- DOI searches inconclusive because of API/network problems: **{doi_stats['search_inconclusive']}**",
        f"- Trusted DOI coverage after audit: **{doi_stats['trusted_doi_coverage']} / {doi_stats['doi_search_eligible_references']}**",
        f"- Scholarly references without a trusted DOI after audit: **{doi_stats['trusted_doi_unresolved']}**",
    ]

    if summary.url_results:
        lines += [
            "",
            "### URL validation summary",
            "",
            f"- URLs checked: **{url_stats['checked']}**",
            f"- Confirmed reachable: **{url_stats['reachable']}**",
            f"- Access restricted / automated checking blocked: **{url_stats['access_restricted']}**",
            f"- Confirmed broken (HTTP 404/410): **{url_stats['confirmed_broken']}**",
            f"- Other HTTP client errors: **{url_stats['http_client_error']}**",
            f"- Server errors: **{url_stats['server_error']}**",
            f"- Invalid URL syntax: **{url_stats['invalid_url']}**",
            f"- Inconclusive network/DNS/TLS/timeout checks: **{url_stats['network_inconclusive']}**",
        ]

    lines += ["", "## BibTeX entry types", "", "| Entry type | Count |", "|---|---:|"]
    for key, value in summary.type_counts.items():
        lines.append(f"| {safe_cell(key)} | {value} |")

    lines += ["", "## Publication years", "", "| Year | Count |", "|---|---:|"]
    # Sort years descending where possible, then missing/other labels.
    year_items = list(summary.year_counts.items())
    year_items.sort(key=lambda kv: (parse_year(kv[0]) is not None, parse_year(kv[0]) or -1), reverse=True)
    for key, value in year_items:
        lines.append(f"| {safe_cell(key)} | {value} |")

    lines += ["", "## Most represented sources", "", "| Journal / proceedings / institution | Count |", "|---|---:|"]
    for key, value in top_items(summary.source_counts, 30):
        lines.append(f"| {safe_cell(key)} | {value} |")

    if summary.host_counts:
        lines += ["", "## Most represented URL hosts", "", "| Host | Count |", "|---|---:|"]
        for key, value in top_items(summary.host_counts, 30):
            lines.append(f"| {safe_cell(key)} | {value} |")

    lines += ["", "## Duplicate citation keys", ""]
    if summary.duplicate_key_groups:
        for key, uids in summary.duplicate_key_groups.items():
            lines.append(f"- `{safe_cell(key)}`: {', '.join(f'`{u}`' for u in uids)}")
    else:
        lines.append("None detected.")

    lines += ["", "## Exact normalized-title duplicates", ""]
    if summary.duplicate_title_groups:
        lines += ["| Normalized title | Entries |", "|---|---|"]
        for title, uids in summary.duplicate_title_groups.items():
            short = title if len(title) <= 110 else title[:107] + "..."
            lines.append(f"| {safe_cell(short)} | {safe_cell(', '.join(uids))} |")
    else:
        lines.append("None detected.")

    lines += ["", "## Probable duplicate pairs", ""]
    if summary.probable_duplicates:
        lines += [
            "| Entry A | Entry B | Reason | Title similarity | Token similarity |",
            "|---|---|---|---:|---:|",
        ]
        for p in summary.probable_duplicates:
            lines.append(
                f"| `{p.uid_a}` | `{p.uid_b}` | {p.reason} | {p.title_similarity:.3f} | {p.token_similarity:.3f} |"
            )
    else:
        lines.append("None detected above the conservative threshold.")

    lines += ["", "## Missing required fields", ""]
    if summary.missing_required_fields:
        for uid, missing in summary.missing_required_fields.items():
            lines.append(f"- `{uid}`: {', '.join(missing)}")
    else:
        lines.append("All entries contain the basic structural fields expected for their BibTeX type.")

    lines += ["", "## Source-name capitalization/punctuation variants", ""]
    if summary.source_name_variants:
        lines += ["| Normalized source | Variants found |", "|---|---|"]
        for normalized, variants in summary.source_name_variants.items():
            lines.append(f"| {safe_cell(normalized)} | {safe_cell('; '.join(variants))} |")
    else:
        lines.append("No variants detected for journal or proceedings names.")

    lines += [
        "",
        "## DOI audit",
        "",
        "| Key | Class | DOI/candidate | Status | Confidence | Type | Type compatible | Publisher landing page |",
        "|---|---|---|---|---:|---|---|---|",
    ]
    for r in summary.doi_results:
        lines.append(
            f"| `{r.key}` | {r.reference_kind} | {safe_cell(r.candidate_doi)} | {r.status} | "
            f"{r.confidence:.3f} | {safe_cell(r.remote_type)} | {r.type_compatible} | {safe_cell(r.landing_url)} |"
        )

    if summary.url_results:
        lines += [
            "",
            "## Web/report URL audit",
            "",
            "| Key | Class | URL | Status | HTTP | Final URL |",
            "|---|---|---|---|---:|---|",
        ]
        for r in summary.url_results:
            lines.append(
                f"| `{r.key}` | {r.reference_kind} | {safe_cell(r.url)} | {r.status} | "
                f"{r.http_status or ''} | {safe_cell(r.final_url)} |"
            )

    if summary.parse_warnings:
        lines += ["", "## Parser warnings", ""]
        lines.extend(f"- {warning}" for warning in summary.parse_warnings)

    lines += [
        "",
        "## Interpretation",
        "",
        "A missing DOI is counted as unresolved only for bibliographic classes that are normally discoverable as scholarly publications. Technical reports, project deliverables, web resources, datasets, software, standards, and similar grey literature may legitimately have no DOI. Existing DOI values in those classes are still verified when online mode is enabled.",
        "",
        "A network, DNS, TLS, timeout, or access-restriction result does not prove that a URL is broken. Only confirmed HTTP 404 or 410 responses are labelled confirmed_broken by this audit.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


# =============================================================================
# BibTeX enrichment
# =============================================================================


def insert_doi_into_raw(raw: str, doi: str) -> str:
    if not doi or re.search(r"(?im)^\s*doi\s*=", raw):
        return raw
    closing = raw[-1]
    body = raw[:-1].rstrip()
    if not body.endswith(","):
        body += ","
    return f"{body}\n  doi = {{{doi}}}\n{closing}"


def write_enriched_bib(
    original_text: str,
    entries: list[BibEntry],
    doi_results: list[DOIResult],
    out: Path,
) -> int:
    additions = {
        r.uid: r.discovered_doi
        for r in doi_results
        if r.status == "found_high_confidence" and r.discovered_doi and not r.local_doi
    }

    pieces: list[str] = []
    cursor = 0
    added = 0
    for entry in entries:
        pieces.append(original_text[cursor : entry.start])
        doi = additions.get(entry.uid, "")
        if doi:
            pieces.append(insert_doi_into_raw(entry.raw, doi))
            added += 1
        else:
            pieces.append(entry.raw)
        cursor = entry.end
    pieces.append(original_text[cursor:])
    out.write_text("".join(pieces), encoding="utf-8")
    return added


# =============================================================================
# CLI
# =============================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify, audit, duplicate-check, validate, and conservatively DOI-enrich a BibTeX bibliography."
    )
    parser.add_argument("bibfile", type=Path, help="Input .bib file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: <bib-stem>_audit)")
    parser.add_argument("--online", action="store_true", help="Verify existing DOIs and search missing scholarly DOIs")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"HTTP timeout in seconds (default {DEFAULT_TIMEOUT:g})")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"Minimum delay between HTTP requests (default {DEFAULT_DELAY:g}s)")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help=f"Retries for transient HTTP/network failures (default {DEFAULT_RETRIES})")
    parser.add_argument(
        "--accept-threshold",
        type=float,
        default=DEFAULT_ACCEPT_THRESHOLD,
        help=f"Minimum metadata score for automatic DOI acceptance (default {DEFAULT_ACCEPT_THRESHOLD:.2f})",
    )
    parser.add_argument("--crossref-rows", type=int, default=DEFAULT_CROSSREF_ROWS, help=f"Crossref candidates per search (default {DEFAULT_CROSSREF_ROWS})")
    parser.add_argument("--no-search-missing", action="store_true", help="Verify existing DOIs but do not search for missing ones")
    parser.add_argument("--check-urls", action="store_true", help="Validate URLs for non-paper references")
    parser.add_argument("--check-paper-urls", action="store_true", help="With --check-urls, also validate URLs attached to papers")
    parser.add_argument("--write-enriched", action="store_true", help="Write a new .bib containing only high-confidence missing DOI additions")
    return parser.parse_args(argv)


def validate_cli_args(args: argparse.Namespace) -> None:
    if not (0.0 <= args.accept_threshold <= 1.0):
        raise ValueError("--accept-threshold must be between 0 and 1.")
    if args.crossref_rows < 2 or args.crossref_rows > 20:
        raise ValueError("--crossref-rows must be between 2 and 20.")
    if args.retries < 0 or args.retries > 10:
        raise ValueError("--retries must be between 0 and 10.")
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than zero.")
    if args.delay < 0:
        raise ValueError("--delay cannot be negative.")


def offline_doi_rows(entries: list[BibEntry], classes: dict[str, ReferenceClass]) -> list[DOIResult]:
    rows: list[DOIResult] = []
    for e in entries:
        cls = classes[e.uid]
        local = extract_doi(e)
        if local:
            status = "present_not_verified"
        elif cls.doi_search_eligible:
            status = "missing_not_searched"
        else:
            status = "not_applicable"
        rows.append(DOIResult(e.uid, e.key, cls.kind, local_doi=local, status=status))
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_cli_args(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    bibfile: Path = args.bibfile
    try:
        summary, entries, classes, original_text = build_offline_summary(bibfile)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    output_dir = args.output_dir or bibfile.with_name(f"{bibfile.stem}_audit")
    output_dir.mkdir(parents=True, exist_ok=True)

    client: HTTPClient | None = None
    if args.online or args.check_urls:
        client = HTTPClient(args.timeout, args.delay, args.retries)

    if args.online and client:
        summary.doi_results = audit_dois(
            entries,
            classes,
            client,
            search_missing=not args.no_search_missing,
            accept_threshold=args.accept_threshold,
            crossref_rows=args.crossref_rows,
        )
    else:
        summary.doi_results = offline_doi_rows(entries, classes)

    if args.check_urls and client:
        summary.url_results = check_reference_urls(
            entries,
            classes,
            client,
            include_paper_urls=args.check_paper_urls,
        )

    summary.duplicate_trusted_doi_groups = trusted_doi_duplicate_groups(summary.doi_results)

    report_md = output_dir / "report.md"
    report_json = output_dir / "report.json"
    audit_csv = output_dir / "references_audit.csv"
    manual_csv = output_dir / "manual_review.csv"

    write_markdown(summary, entries, classes, report_md)
    write_json(summary, report_json)
    write_csv(entries, classes, summary.doi_results, summary.url_results, audit_csv)
    manual_count = write_manual_review_csv(summary, entries, manual_csv)

    enriched_path: Path | None = None
    added = 0
    if args.write_enriched:
        enriched_path = output_dir / f"{bibfile.stem}.enriched.bib"
        if args.online:
            added = write_enriched_bib(original_text, entries, summary.doi_results, enriched_path)
        else:
            # Preserve behavior but make it explicit that no new DOI can be added.
            enriched_path.write_text(original_text, encoding="utf-8")
            print("WARNING: --write-enriched used without --online; enriched file is an unchanged copy.", file=sys.stderr)

    dstat = doi_statistics(entries, classes, summary.doi_results)
    ustat = url_statistics(summary.url_results)

    print("\nLiterature bibliography audit complete")
    print(f"  References:                           {summary.entry_count}")
    for kind, count in summary.reference_kind_counts.items():
        print(f"    {kind:<33} {count}")
    print(f"  Exact duplicate key groups:           {len(summary.duplicate_key_groups)}")
    print(f"  Duplicate local DOI groups:           {len(summary.duplicate_local_doi_groups)}")
    print(f"  Duplicate title groups:               {len(summary.duplicate_title_groups)}")
    print(f"  Probable duplicate pairs:             {len(summary.probable_duplicates)}")
    print(f"  Missing required data:                {len(summary.missing_required_fields)}")
    print(f"  DOI-search-eligible scholarly refs:   {dstat['doi_search_eligible_references']}")
    print(f"  DOI fields present originally:        {dstat['original_with_doi_field']}")
    print(f"  Existing DOI verified:                {dstat['verified_existing_doi']}")
    print(f"  High-confidence DOI found:            {dstat['high_confidence_doi_found']}")
    print(f"  Manual DOI review:                    {dstat['manual_review_candidates']}")
    print(f"  No DOI candidate found:               {dstat['no_candidate_found']}")
    print(f"  DOI searches inconclusive:            {dstat['search_inconclusive']}")
    print(f"  Trusted scholarly refs with DOI:      {dstat['trusted_doi_coverage']}")
    print(f"  Scholarly refs without trusted DOI:   {dstat['trusted_doi_unresolved']}")
    print(f"  Duplicate trusted DOI groups:         {len(summary.duplicate_trusted_doi_groups)}")
    if summary.url_results:
        print(f"  URLs checked:                         {ustat['checked']}")
        print(f"  URLs confirmed reachable:             {ustat['reachable']}")
        print(f"  URLs access-restricted:               {ustat['access_restricted']}")
        print(f"  URLs confirmed broken (404/410):      {ustat['confirmed_broken']}")
        print(f"  URL checks network-inconclusive:      {ustat['network_inconclusive']}")
    print(f"  Manual-review rows:                   {manual_count}")
    print(f"  Markdown report:                      {report_md}")
    print(f"  JSON report:                          {report_json}")
    print(f"  CSV audit table:                      {audit_csv}")
    print(f"  Manual review table:                  {manual_csv}")
    if enriched_path:
        print(f"  Enriched BibTeX:                      {enriched_path} ({added} DOI(s) added)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

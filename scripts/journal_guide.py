#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""journal_guide.py — build and check the local Guide-for-Authors bank.

The publisher's guides live behind a captcha, so the only copy that will ever
exist is the one the user downloads and hands over. This script turns that file
into a bank the agent can consult without loading 2000 lines to answer a
question about the abstract limit.

Division of labour (deliberate, and the reason this file is not bigger):

  the script does everything deterministic — read the source, strip the page's
  boilerplate *and report what it stripped*, cut on headings, resolve links,
  check the result. The agent does the decisions — where a section really
  starts and ends, whether a link is internal or external, what the index says.
  Those decisions are not hard-coded here; `propose` writes a candidate into
  guide/_work/ and the `paper-guide` skill reviews it before `apply`.

Nothing here summarises. The guide is kept verbatim: segmented and
cross-referenced, never condensed. A condensed guide can only be as good as the
model that condensed it, and these limits are exactly what must not drift.

    convert   HTML/Markdown/text -> clean Markdown + a report of what was dropped
    outline   the heading tree with line counts (the candidate cut points)
    propose   write guide/_work/sections/NN-slug.md as a *proposal*
    apply     move the reviewed proposal into guide/sections/
    scaffold  create the guide/ skeleton for a journal that has none
    sources   record url + retrieval date + sha256 of the raw source
    cites     reverse index: who links to a URL (must reach zero after promotion)
    dedup     find byte-identical sections in 2+ guides (must come back empty
              after promotion)
    check     the contract: links, anchors, orphans, stale queue, duplicates

Only `convert`/`outline` need an HTML parser, and both work with the standard
library alone (markitdown is used instead when it happens to be installed).
`check` is dependency-free so CI, which installs only requirements-dev.txt, can
enforce the contract on the committed Markdown.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402
from _structure import set_type_field  # noqa: E402

# A section above this is split further: the whole point of the bank is that a
# lookup reads what it needs, and 300 lines is already a lot of context.
MAX_SECTION_LINES = 300

GUIDE_FILES = ("index.md", "SOURCES.md", "external.md")
SHARED_DIRNAME = "_shared"
SHARED_NAMESPACE = "elsevier"

# Chrome that never carries guide content. Dropping it is lossy in principle, so
# `convert` prints every removal and the agent checks the list before accepting.
SKIP_TAGS = {
    "script", "style", "noscript", "nav", "header", "footer", "aside", "form",
    "svg", "iframe", "template", "button", "select", "picture", "head", "title",
}
NOISE_HINT = re.compile(
    r"cookie|consent|newsletter|subscribe|skip[-_ ]?link|breadcrumb|social|share|"
    r"related[-_ ]?(article|content)|advert|banner|subscribe|login|sign[-_ ]?in",
    re.I,
)

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text"}
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+?)(?:\s+\"[^\"]*\")?\s*\)")
EXPLICIT_ANCHOR_RE = re.compile(r"<a\s[^>]*?\bid=[\"']([^\"']+)[\"']", re.I)
ANCHOR_LINE_RE = re.compile(r"^\s*<a\s+[^>]*\bid=[\"'][^\"']+[\"'][^>]*>\s*</a>\s*$", re.I)
HTML_COMMENT_RE = re.compile(r"^<!--.*?-->\s*$", re.S)

NOT_MIRRORED = "NOT MIRRORED"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def slugify(text: str) -> str:
    """`Data statement` -> `data-statement` (matches the HTML id Elsevier uses)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "section"


def heading_slug(text: str) -> str:
    """Slug of a Markdown heading, for anchors written without an explicit id."""
    text = re.sub(r"\{#([^}]+)\}", r"\1", text or "").strip()
    return slugify(text)


def journal_dir(repo: Path, journal: str) -> Path:
    return repo / "templates" / "journals" / journal


def guide_dir(repo: Path, journal: str) -> Path:
    return journal_dir(repo, journal) / "guide"


def publisher_namespace(repo: Path, journal: str) -> str:
    """The `_shared/` folder a journal's identical pages belong to.

    Derived from the catalog's own `publisher`, never from a URL, so it stays
    right when a journal changes house. Elsevier's open-access policy is not
    Springer Nature's, and filing them together would give a Springer page an
    Elsevier path.
    """
    meta = load_yaml(journal_dir(repo, journal) / "type.yaml")
    publisher = str(meta.get("publisher") or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", publisher).strip("-") or SHARED_NAMESPACE


def shared_dir(repo: Path, journal: str = "") -> Path:
    """Where a mirrored page that is identical across journals lives."""
    namespace = publisher_namespace(repo, journal) if journal else SHARED_NAMESPACE
    return repo / "templates" / "journals" / SHARED_DIRNAME / namespace


def iter_journals(repo: Path) -> list[Path]:
    base = repo / "templates" / "journals"
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("_"))


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def strip_code_fences(text: str) -> str:
    """Blank out fenced blocks so headings/links inside code are not misread."""
    out, fenced = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return "\n".join(out)


# --------------------------------------------------------------------------
# HTML -> Markdown
# --------------------------------------------------------------------------


class _HtmlToMarkdown(HTMLParser):
    """A small dependency-free HTML reader.

    It is deliberately not a general-purpose converter: Elsevier's guide pages
    are headings, paragraphs, lists, tables and links, and anything dropped that
    matters should be reported. markitdown is preferred when installed.
    """

    BLOCK = {
        "p", "div", "section", "article", "main", "ul", "ol", "table", "blockquote",
        "pre", "dl", "figure", "figcaption", "address",
    }
    SKIP = SKIP_TAGS

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.removed: list[tuple[str, str]] = []
        self.duplicate_anchors: list[str] = []
        self._skip: list[str] = []
        self._pre = 0
        self._list_stack: list[tuple[str, int]] = []
        self._table: list[list[str]] = []
        self._in_table = False
        self._cell: list[str] | None = None
        self._row: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._pending_anchor: str | None = None
        self._inline: list[str] = []
        self._open_inline: list[str] = []
        self._in_li = False
        self._emitted: set[str] = set()

    # -- emission -----------------------------------------------------
    def _emit(self, text: str = "") -> None:
        if self._cell is not None:
            self._cell.append(text)
        else:
            self.chunks.append(text)

    def _flush_inline(self) -> None:
        """Materialise deferred emphasis markers, once real text arrives."""
        if self._inline:
            self.chunks.extend(self._inline)
            self._open_inline.extend(self._inline)
            self._inline = []

    def _nl(self, n: int = 1) -> None:
        self._emit("\n" * n)

    def _close_list(self) -> None:
        while self._list_stack:
            self._list_stack.pop()
            self._nl()

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        noise = " ".join([a.get("id", ""), a.get("class", ""), a.get("role", "")])
        if self._skip:
            if tag not in ("p", "div", "li"):
                self._skip.append(tag)
            return
        if tag in self.SKIP or (noise and NOISE_HINT.search(noise)):
            label = a.get("class") or a.get("id") or tag
            self.removed.append((tag, label))
            self._skip.append(tag)
            return
        if tag in self.BLOCK and self.chunks and not self.chunks[-1].endswith("\n"):
            # ScienceDirect wraps each list item's text in its own <p>. Right
            # after the "- " marker there is nothing to separate, and emitting a
            # newline turns every bullet into "-\n\ntext" — a loose list, with
            # twice the lines for no gain.
            if self._in_li and self.chunks[-1].endswith(("- ", "1. ")):
                pass
            else:
                self._nl(1 if self._in_li else 2)
        if re.fullmatch(r"h[1-6]", tag):
            self._close_list()
            self._emit("\n\n")
            # Carry the HTML id over as an explicit anchor. Internal links point at
            # these ids, and dropping them would break every one of them silently.
            # ScienceDirect puts the id on the wrapper `<div>` that opens the
            # heading rather than on the heading itself, so an id seen just before
            # the heading belongs to it.
            anchor = a.get("id") or self._pending_anchor
            self._pending_anchor = None
            if anchor:
                # ScienceDirect repeats some ids on the page (an "About the
                # journal" wrapper id appears twice). A duplicate anchor in the
                # bank is ambiguous: two files would answer to the same link.
                # Keep the first and report the page's bug.
                if anchor in self._emitted:
                    self.duplicate_anchors.append(anchor)
                else:
                    self._emitted.add(anchor)
                    self._emit(f'<a id="{anchor}"></a>\n')
            self._emit("#" * int(tag[1]) + " ")
        elif a.get("id"):
            self._pending_anchor = a["id"]
        elif tag == "br":
            self._emit("\n")
        elif tag == "hr":
            self._close_list()
            self._nl(2)
            self._emit("---")
            self._nl(2)
        elif tag in ("ul", "ol"):
            self._close_list()
            self._list_stack.append((tag, 0))
            self._nl()
        elif tag == "li":
            if not self._list_stack:
                self._list_stack.append(("ul", 0))
            kind, _ = self._list_stack[-1]
            self._list_stack[-1] = (kind, self._list_stack[-1][1] + 1)
            depth = len(self._list_stack) - 1
            self._emit("\n" + "  " * depth + ("1. " if kind == "ol" else "- "))
            self._in_li = True
        elif tag == "table":
            self._close_list()
            self._in_table, self._table = True, []
            self._nl(2)
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "a":
            self._href = a.get("href", "")
            self._link_text = []
        elif tag in ("strong", "b", "em", "i"):
            # Deferred, not immediate: an empty <b></b> is common page chrome, and
            # emitting "**" for it leaves a stray "****" in the text.
            self._inline.append("**" if tag in ("strong", "b") else "*")
        elif tag in ("code", "samp", "kbd"):
            self._emit("`")
        elif tag == "pre":
            self._close_list()
            self._nl(2)
            self._emit("```\n")
            self._pre += 1
        elif tag == "blockquote":
            self._close_list()
            self._nl(2)
            self._emit("> ")

    def handle_endtag(self, tag):
        if self._skip:
            if tag in self._skip:
                while self._skip:
                    if self._skip.pop() == tag:
                        break
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._emit("\n\n")
        elif tag in ("ul", "ol"):
            # Real pages ship unclosed and stray list tags. A pop on an empty
            # stack would abort the whole conversion on a malformed page, so the
            # state is repaired instead: the guide is still worth extracting.
            if self._list_stack:
                self._list_stack.pop()
            self._nl()
        elif tag == "li":
            self._in_li = False
            self._nl()
        elif tag == "a" and self._href:
            text = "".join(self._link_text).strip()
            href = self._href.strip()
            if text and href and not href.startswith(("javascript:", "#!")):
                self._emit(f"[{text}]({unwrap_redirect(href.strip())})")
            else:
                self._emit(text)
            self._href, self._link_text = None, []
        elif tag in ("strong", "b", "em", "i"):
            marker = "**" if tag in ("strong", "b") else "*"
            if self._inline and self._inline[-1] == marker:
                # Closed without ever holding text (an empty or whitespace-only
                # <b>, which is page chrome): drop it instead of writing "**".
                self._inline.pop()
            elif self._open_inline and self._open_inline[-1] == marker:
                self._open_inline.pop()
                self._emit(marker)
            else:
                self._open_inline.append(marker)
                self._emit(marker)
        elif tag in ("code", "samp", "kbd"):
            self._emit("`")
        elif tag == "pre":
            self._pre = max(0, self._pre - 1)
            self._emit("\n```")
            self._nl(2)
        elif tag == "blockquote":
            self._nl(2)
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._in_table:
            if any(self._row):
                self._table.append(self._row)
            self._row = []
        elif tag == "table":
            self._flush_table()
            self._in_table = False
            self._nl(2)
        elif tag in self.BLOCK:
            # The </li> already separates items; a closing </p> inside a list item
            # would put a blank line between every bullet.
            if not self._in_li:
                self._nl(2)

    def handle_data(self, data):
        if self._skip or not data.strip():
            return
        text = re.sub(r"[ \t]+", " ", data)
        if self._href is not None:
            # While inside an <a> the text is held back: emitting it here as well
            # would print the anchor's words twice, once bare and once as a link.
            self._link_text.append(text)
            return
        self._flush_inline()
        self._emit(text)

    def _flush_table(self):
        if not self._table:
            return
        width = max(len(r) for r in self._table)
        rows = [r + [""] * (width - len(r)) for r in self._table]
        self._emit("\n| " + " | ".join(rows[0]) + " |\n")
        self._emit("|" + "---|" * width + "\n")
        for row in rows[1:]:
            self._emit("| " + " | ".join(row) + " |\n")

    def markdown(self) -> str:
        # Whatever emphasis was left dangling (an unclosed <b>) is dropped rather
        # than written out as a stray marker.
        self._inline = []
        return tidy_markdown("".join(self.chunks))


def tidy_markdown(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    # Springer marks each step with an *empty* `<h3 id="…"></h3>` anchor holder,
    # which reads as a bare `###`. A heading with no text says nothing, and a
    # bare `###` also stops widen_to_anchor from reaching the anchor above it,
    # stranding that anchor in the previous section.
    text = re.sub(r"(?m)^#{1,6}\s*$\n?", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def convert_html(path: Path, engine: str = "builtin") -> tuple[str, list[tuple[str, str]]]:
    """Return (markdown, removed). `removed` is what the agent must eyeball.

    The built-in reader is the default, not markitdown. Markitdown produces
    prettier Markdown but drops `<a id>` attributes and keeps the navigation,
    cookie banner and footer — and it reports having removed nothing. Every
    internal reference in the guide would then point at an anchor that no longer
    exists, which is precisely the silent breakage this bank exists to prevent.
    Keep markitdown as an escape hatch for pages the built-in reader mangles, but
    never as the default.
    """
    if engine == "markitdown":
        try:
            from markitdown import MarkItDown  # type: ignore

            text = MarkItDown().convert(str(path)).text_content
            print("NOTE: markitdown drops <a id> anchors. The section links in this "
                  "guide will not resolve until you add them back by hand.")
            return tidy_markdown(text or ""), []
        except ImportError:
            raise SystemExit(
                "ERROR: --engine markitdown asked for but markitdown is not "
                "installed (pip install markitdown)."
            )
        except Exception as exc:  # noqa: BLE001 - a broken page must not kill the run
            print(f"WARN: markitdown failed ({exc}); falling back to the built-in reader.")
    parser = _HtmlToMarkdown()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser.close()
    for dup in dict.fromkeys(parser.duplicate_anchors):
        print(f"NOTE: the page repeats id=\"{dup}\". Kept the first occurrence; a "
              f"second file with the same anchor would make the link ambiguous.")
    return parser.markdown(), parser.removed


def to_markdown(src: Path, engine: str = "builtin") -> tuple[str, list[tuple[str, str]]]:
    if src.suffix.lower() in TEXT_SUFFIXES:
        return tidy_markdown(src.read_text(encoding="utf-8", errors="replace")), []
    if src.suffix.lower() in (".html", ".htm", ".xhtml"):
        return convert_html(src, engine)
    raise SystemExit(
        f"ERROR: {src.suffix} is not a readable source here. Convert it to HTML, "
        f"Markdown or text first (util-office-to-md)."
    )


# --------------------------------------------------------------------------
# headings and sections
# --------------------------------------------------------------------------


@dataclass
class Section:
    level: int
    title: str
    lines: list[str]
    start: int

    @property
    def filename(self) -> str:
        return f"{slugify(self.title)}.md"

    @property
    def anchors(self) -> set[str]:
        found = set(EXPLICIT_ANCHOR_RE.findall("\n".join(self.lines)))
        for line in self.lines:
            m = HEADING_RE.match(line)
            if m:
                found.add(heading_slug(m.group(2)))
        return found

    @property
    def is_heading_only(self) -> bool:
        """True when the section is nothing but its anchor and its heading.

        A grouping heading like "Ethics and policies" has no prose of its own —
        it is a level in the publisher's outline, not a section anyone can read.
        Cutting it into its own file would put a 3-line stub next to 46 real
        ones. The grouping belongs in index.md, where it says what the sections
        under it are about.
        """
        for line in self.lines:
            stripped = line.strip()
            if not stripped or ANCHOR_LINE_RE.match(stripped) or HEADING_RE.match(stripped):
                continue
            if stripped.startswith("<!--") and stripped.endswith("-->"):
                continue
            return False
        return True


def scan_headings(markdown: str) -> list[tuple[int, str, int]]:
    """(level, title, 0-based line) for every heading outside code fences."""
    out = []
    for i, line in enumerate(strip_code_fences(markdown).splitlines()):
        m = HEADING_RE.match(line)
        if m:
            title = re.sub(r"\{#[^}]+\}", "", m.group(2)).strip()
            out.append((len(m.group(1)), title, i))
    return out


def widen_to_anchor(lines: list[str], start: int, split_level: int = 0) -> int:
    """Pull the anchor (and any heading it belongs to) into the section.

    `<a id="open-access"></a>` sits on its own line *above* the heading it names.
    Cutting at the heading line would leave the anchor behind in the previous
    section, and every link pointing at it would then resolve to a file that
    does not define it.

    `split_level` also matters when the anchor belongs to a heading of a *more*
    significant level than the one being cut on. Springer puts an id on every
    `<h2>Step N …</h2>` and none on the `<h4>`s beneath it, so cutting on h4
    would leave "## Step 1" and its anchor stranded in the tail of the last
    section of the previous step. Swallowing the heading moves both to the first
    section of the step they introduce, which is where they belong.
    """
    i = start - 1
    seen_anchor = False
    while i >= 0:
        line = lines[i]
        if ANCHOR_LINE_RE.match(line):
            seen_anchor = True
            i -= 1
            continue
        heading = HEADING_RE.match(line)
        if split_level and heading and len(heading.group(1)) < split_level:
            seen_anchor = True
            i -= 1
            continue
        if not heading and re.fullmatch(r"#{1,6}\s*", line):
            continue  # a text-less heading left by an empty anchor holder
        if not line.strip() and seen_anchor:
            i -= 1
            continue
        break
    return i + 1


def split_sections(
    markdown: str, split_level: int = 2, max_lines: int = MAX_SECTION_LINES
) -> tuple[list[Section], list[str]]:
    """Cut on headings, then cut oversized sections further.

    Returns (sections, dropped_title): the page's own <h1> is not a section (it
    would be a one-line file) and not lost either — it is handed back so the
    caller can put it in index.md.

    Cutting again rather than accepting a 900-line "Ethics" is the difference
    between a bank you can consult and a file you have to page through.
    """
    lines = markdown.splitlines()
    heads = scan_headings(markdown)
    doc_title: list[str] = []

    if not heads:
        return [Section(0, "guide", lines, 0)], doc_title

    first_cut = next(
        (widen_to_anchor(lines, start) for level, _t, start in heads
         if 1 < level <= split_level),
        None,
    )
    if first_cut is None:
        return [Section(0, "guide", lines, 0)], doc_title

    # Cut on the target level *and on anything more significant than it*, but never
    # on the h1: that is the page's title, handled separately. A page whose top
    # level is "Step 1 — …" puts its id on that heading and none on the headings
    # beneath it; cutting only on h4 would leave the step and its own introduction
    # paragraphs stranded in the tail of the previous step's last section. A
    # heading that turns out to carry no text of its own (Elsevier's "Ethics and
    # policies") is dropped later as heading-only.
    cuts: list[tuple[str, int]] = [
        (title, widen_to_anchor(lines, start, split_level))
        for level, title, start in heads
        if 1 < level <= split_level
    ]
    # Anything before the first cut is a preamble, unless it is only the page's
    # own <h1>: that is the document's title, not content, and cutting it into a
    # one-line file would be noise. It is handed back for index.md instead.
    lead = lines[: first_cut]
    if any(ln.strip() for ln in lead):
        if all(not ln.strip() or HEADING_RE.match(ln) for ln in lead):
            head_here = HEADING_RE.match(lines[next(
                i for i, ln in enumerate(lines) if HEADING_RE.match(ln)
            )])
            if head_here:
                doc_title.append(head_here.group(2).strip())
        else:
            cuts.insert(0, ("preamble", 0))
    if not cuts:
        return [Section(0, "guide", lines, 0)], doc_title

    # The next section owns everything from its own widened start, so an anchor
    # never appears both at the end of one file and at the start of the next.
    sections: list[Section] = []
    for i, (title, start) in enumerate(cuts):
        end = cuts[i + 1][1] if i + 1 < len(cuts) else len(lines)
        level = 0 if title == "preamble" else split_level
        sections.append(Section(level, title, lines[start:end], start))

    # An oversized section is re-cut on its sub-headings. The first part keeps the
    # parent's own heading and its lead-in paragraphs: cutting at the first
    # sub-heading would silently drop the text that introduces the whole section.
    out: list[Section] = []
    for sec in sections:
        if len(sec.lines) <= max_lines:
            out.append(sec)
            continue
        body = sec.lines
        local = [h for h in scan_headings("\n".join(body)) if h[0] > sec.level]
        if not local:
            out.append(sec)
            continue
        level = min(h[0] for h in local)
        cuts = [(sec.title, 0)]
        cuts += [(title, widen_to_anchor(body, start))
                 for _l, title, start in local if _l == level]
        for i, (title, start) in enumerate(cuts):
            end = cuts[i + 1][1] if i + 1 < len(cuts) else len(body)
            out.append(Section(level, title, body[start:end], sec.start + start))
    return out, doc_title


def numbered(names: list[str]) -> list[str]:
    """01-, 02-, ... preserving order."""
    width = max(2, len(str(len(names))))
    return [f"{i:0{width}d}-{n}" for i, n in enumerate(names, 1)]


def section_header(src: str, section: Section) -> str:
    return (
        f"<!-- guide section | source: {src} | heading: {section.title} | "
        f"lines: {section.start}-{section.start + len(section.lines)} -->\n"
    )


# --------------------------------------------------------------------------
# links
# --------------------------------------------------------------------------


@dataclass
class Link:
    target: str
    line: int


def find_links(markdown: str) -> list[Link]:
    out = []
    for i, line in enumerate(strip_code_fences(markdown).splitlines()):
        if line.lstrip().startswith("<!--"):
            continue
        for m in LINK_RE.finditer(line):
            out.append(Link(m.group(1), i + 1))
    return out


def unwrap_redirect(url: str) -> str:
    """Return the destination of an email-tracking wrapper, or the url unchanged.

    Elsevier's support addresses link through Outlook SafeLinks, which encodes
    the real target in a `url=` parameter and adds a per-recipient token. Keeping
    the wrapper would record a URL that is useless to a reader and different for
    every recipient, so the token has to go for the link to mean anything.
    """
    parts = urlsplit(url)
    if "safelinks.protection.outlook.com" not in parts.netloc.lower():
        return url
    qs = parse_qs(parts.query)
    target = (qs.get("url") or [None])[0]
    return unwrap_redirect(target) if target else url


def normalise_url(url: str) -> str:
    """Compare URLs the way the bank stores them: no trailing slash, no fragment,
    no tracking query. Elsevier's own links jump between trailing-slash forms."""
    url = unwrap_redirect(url.strip())
    parts = urlsplit(url)
    query = parts.query
    for noise in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
        query = re.sub(rf"(^|&){noise}=[^&]*&?", "", query)
    query = query.strip("&")
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"
    # http and https are the same document; treating them as different would make
    # a mirrored page look uncited and keep it queued forever.
    scheme = "https" if parts.scheme.lower() in ("", "http", "https") else parts.scheme.lower()
    return urlunsplit((scheme, netloc, path, query, ""))


def is_external(target: str) -> bool:
    """True for anything that is not a path inside the bank.

    That includes `mailto:` and other schemes: an e-mail address is a real
    reference to the publisher, not a broken link to a missing file.
    """
    return bool(re.match(r"^(?:[a-z][a-z0-9+.-]*:)?//", target, re.I)) or bool(
        re.match(r"^(?:mailto|tel|data):", target, re.I)
    )


def read_anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    anchors = set(EXPLICIT_ANCHOR_RE.findall(text))
    for _lvl, title, _ln in scan_headings(text):
        anchors.add(heading_slug(title))
    return anchors


# --------------------------------------------------------------------------
# the contract (shared with paper_validate.py)
# --------------------------------------------------------------------------


@dataclass
class Issue:
    level: str  # "error" | "warn"
    where: str
    message: str


@dataclass
class Result:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warns(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, where: str, message: str) -> None:
        self.issues.append(Issue(level, where, message))


def check_guide(repo: Path, journal: str) -> Result:
    """Validate one journal's guide. A journal without `guide:` is opt-in, so it
    reports nothing: declaring the field is what makes the guide auditable."""
    res = Result()
    jdir = journal_dir(repo, journal)
    type_yaml = jdir / "type.yaml"
    gdir = jdir / "guide"

    meta = load_yaml(type_yaml) if type_yaml.is_file() else {}
    declared = str(meta.get("guide") or "").strip()
    if not declared:
        return res

    where = f"templates/journals/{journal}"
    if not gdir.is_dir():
        res.add("error", where, f"type.yaml declares guide: {declared} but guide/ is missing")
        return res

    index = gdir / "index.md"
    if not index.is_file():
        res.add("error", f"{where}/guide", "missing index.md (the map of the guide)")
    for name in GUIDE_FILES:
        if not (gdir / name).is_file():
            res.add("error", f"{where}/guide", f"missing {name}")

    sections_dir = gdir / "sections"
    # A section is a file, or a directory standing for one. A big topic like
    # References becomes `50-references/index.md` plus its own files, so its
    # sub-topics are reachable in one hop instead of inside a 150-line file.
    entries = section_entries(sections_dir)
    if sections_dir.is_dir():
        for d in sorted(p for p in sections_dir.iterdir() if p.is_dir()):
            if not (d / "index.md").is_file():
                res.add("error", f"{md_rel(repo, d)}",
                        "a section folder must contain index.md: it is what the "
                        "guide index links to and what maps its own files")
    sections = sorted(sections_dir.rglob("*.md")) if sections_dir.is_dir() else []

    # 1. every section is reachable from the index, and vice versa
    if index.is_file():
        listed = {
            (index.parent / l.target.split("#")[0]).resolve()
            for l in find_links(index.read_text(encoding="utf-8"))
            if not is_external(l.target) and l.target.split("#")[0].strip()
        }
        for entry in entries:
            # A directory is listed by its index.md, not by its own path.
            target = (entry / "index.md") if entry.is_dir() else entry
            if target.resolve() not in listed:
                res.add("error", f"{where}/guide/index.md",
                        f"{entry.name} is not listed in index.md")
        for ref in listed:
            if ref.suffix == ".md" and not ref.is_file():
                res.add("error", f"{where}/guide/index.md",
                        f"index.md links to {ref.name}, which does not exist")

    # 1b. a section folder maps its own files, or it is just a hiding place
    for entry in entries:
        if not entry.is_dir():
            continue
        sub = entry / "index.md"
        mapped = {
            (sub.parent / l.target.split("#")[0]).resolve()
            for l in find_links(sub.read_text(encoding="utf-8"))
            if not is_external(l.target) and l.target.split("#")[0].strip()
        }
        for f in sorted(p for p in entry.glob("*.md") if p.name != "index.md"):
            if f.resolve() not in mapped:
                res.add("error", f"{md_rel(repo, sub)}",
                        f"{f.name} is not listed in the folder's index")

    # 2. relative links resolve, anchors included
    for md in [index, *sections, gdir / "external.md"]:
        if not md.is_file():
            continue
        text = md.read_text(encoding="utf-8")
        for link in find_links(text):
            target = link.target
            if is_external(target):
                continue
            path_part, _, frag = target.partition("#")
            dest = (md.parent / path_part).resolve() if path_part else md.resolve()
            if not dest.is_file():
                res.add("error", f"{md_rel(repo, md)}:{link.line}",
                        f"broken link: {target} (no such file)")
                continue
            if frag and dest.suffix == ".md" and frag not in read_anchors(dest):
                res.add("error", f"{md_rel(repo, md)}:{link.line}",
                        f"broken anchor: {target} (no heading or <a id> matches "
                        f"'{frag}' in {dest.name})")

    # 3. a section big enough to defeat the point of the bank
    for sec in sections:
        n = len(sec.read_text(encoding="utf-8").splitlines())
        if n > MAX_SECTION_LINES:
            res.add("warn", f"{md_rel(repo, sec)}", f"{n} lines, over the {MAX_SECTION_LINES} cap")

    # 4. provenance
    sources = gdir / "SOURCES.md"
    if sources.is_file():
        text = sources.read_text(encoding="utf-8")
        header = table_header(text)
        for column in ("url", "retrieved", "sha256"):
            if column not in header:
                res.add("error", f"{where}/guide/SOURCES.md",
                        f"no '{column}' column in the provenance table "
                        f"(found: {', '.join(header) or 'no table'})")
        if not table_rows(text):
            res.add("warn", f"{where}/guide/SOURCES.md",
                    "the provenance table has no rows: nothing records which "
                    "download this guide came from")
    if not str(meta.get("guide_retrieved") or "").strip():
        res.add("warn", f"{where}/type.yaml",
                "no guide_retrieved date: the guide may be out of date")

    # 5. the raw source is never committed
    raw = gdir / "_raw"
    if raw.is_dir():
        tracked = git_tracked(repo, raw)
        if tracked:
            res.add("error", f"{where}/guide/_raw",
                    f"{len(tracked)} raw source file(s) are tracked by git")

    # 6. the external queue tells the truth
    external = gdir / "external.md"
    if external.is_file():
        check_external_queue(repo, journal, external, sections, res)
    return res


def table_cells(line: str) -> list[str]:
    return [c.strip().lower() for c in line.strip().strip("|").split("|")]


def table_header(text: str) -> list[str]:
    """The header row of the first pipe table (the row followed by a `---|` rule)."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        if line.strip().startswith("|") and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            return table_cells(line)
    return []


def table_rows(text: str) -> list[list[str]]:
    """Data rows of the first pipe table, minus the header and the rule."""
    lines = text.splitlines()
    out = []
    for i in range(len(lines) - 1):
        if lines[i].strip().startswith("|") and re.match(
            r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]
        ):
            out = [table_cells(ln) for ln in lines[i + 2:] if ln.strip().startswith("|")]
            break
    return out


def section_entries(sections_dir: Path) -> list[Path]:
    """Top-level sections: each `.md` file, or each folder standing for one.

    The guide index links to a folder through its `index.md`, so a folder counts
    as one section and its files are one level down.
    """
    if not sections_dir.is_dir():
        return []
    return sorted(
        p for p in sections_dir.iterdir()
        if (p.is_file() and p.suffix == ".md")
        or (p.is_dir() and (p / "index.md").is_file())
    )


def md_rel(repo: Path, path: Path) -> str:
    """Repo-relative path with forward slashes, so messages read the same on
    Windows and in CI output."""
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def git_tracked(repo: Path, path: Path) -> list[str]:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--", str(path.relative_to(repo))],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, ValueError):
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def parse_external(path: Path) -> list[tuple[str, str, str, int]]:
    """Rows of external.md as (url, topic, state, line)."""
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        url = cells[0].strip("`<> ")
        if not url.startswith(("http://", "https://")):
            continue
        rows.append((url, cells[1], cells[2], i))
    return rows


def is_shared_path(repo: Path, path: Path) -> bool:
    """True when a resolved path lives under `templates/journals/_shared/`."""
    try:
        path.relative_to(repo / "templates" / "journals" / SHARED_DIRNAME)
        return True
    except ValueError:
        return False


def check_external_queue(
    repo: Path, journal: str, external: Path, sections: list[Path], res: Result
) -> None:
    where = f"templates/journals/{journal}/guide/external.md"
    corpus_parts = [s.read_text(encoding="utf-8") for s in sections if s.is_file()]
    # Links that moved to `_shared/` still count as cited by this journal: the
    # text lives in the shared copy now, not in `sections/`. Without this, every
    # promotion would flood the queue with "no section links to it" warnings for
    # URLs that are still linked — just from the shared file.
    gdir = guide_dir(repo, journal)
    index_files = [gdir / "index.md"] + sorted((gdir / "sections").glob("*/index.md"))
    seen_shared: set[str] = set()
    for index in index_files:
        if not index.is_file():
            continue
        for link in find_links(index.read_text(encoding="utf-8")):
            if is_external(link.target):
                continue
            part, _, _ = link.target.partition("#")
            if not part.strip():
                continue
            dest = (index.parent / part).resolve()
            key = str(dest)
            if dest.is_file() and is_shared_path(repo, dest) and key not in seen_shared:
                seen_shared.add(key)
                corpus_parts.append(dest.read_text(encoding="utf-8", errors="replace"))
    corpus = "\n".join(corpus_parts)
    corpus_urls = {normalise_url(u.target) for u in find_links(corpus) if is_external(u.target)}
    for url, topic, state, line in parse_external(external):
        # A local copy that exists while the queue still says NOT MIRRORED is the
        # classic half-finished promotion: the file was written and the references
        # were never rewritten, so the bank still points at a dead web page.
        if NOT_MIRRORED in state:
            guess = shared_dir(repo, journal) / f"{slugify(topic)}.md"
            # A shared *section* (identical guide text promoted by `dedup`) is
            # not a mirrored external page, even when the file name matches the
            # topic slug. Only a mirrored page clears the queue.
            if guess.is_file() and not is_shared_section(guess):
                res.add("warn", f"{where}:{line}",
                        f"stale queue: still {NOT_MIRRORED} but "
                        f"{md_rel(repo, guess)} exists — rewrite the references "
                        f"(`cites --url {url}` must come back empty)")
        # Only a NOT_MIRRORED row should still be cited by URL: that link is the
        # reminder that the text is not in the bank. Once promoted, the sections
        # point at the local file and the row is the record of origin, not a gap.
        if normalise_url(url) not in corpus_urls and NOT_MIRRORED in state:
            res.add("warn", f"{where}:{line}",
                    f"{url} is registered here but no section links to it "
                    f"(the reference may have been lost in the conversion)")


def cites(repo: Path, url: str) -> list[tuple[Path, int, str]]:
    """Reverse index: every file in the bank that links to `url`."""
    want = normalise_url(url)
    hits = []
    base = repo / "templates" / "journals"
    for md in sorted(base.rglob("*.md")):
        parts = md.relative_to(base).parts
        if "_raw" in parts or "_work" in parts:
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        for link in find_links(text):
            if is_external(link.target) and normalise_url(link.target) == want:
                hits.append((md, link.line, link.target))
    return hits


# --------------------------------------------------------------------------
# deduplication: one copy for byte-identical sections
# --------------------------------------------------------------------------


# Provenance headers written by `propose` and by hand when a section is split.
# They record *which* download a file came from (source file, heading, line
# numbers), so two files from two different downloads never compare equal even
# when the publisher wrote the same words twice.
SECTION_PROVENANCE_RE = re.compile(
    r"^<!--\s*(guide section|references|article structure|artwork)\s*\|.*-->\s*$"
)

SHARED_HEADER_RE = re.compile(r"^<!--\s*shared section\s*\|.*-->\s*$")


def is_shared_section(path: Path) -> bool:
    """True when a `_shared/` file is a promoted guide section.

    Shared sections carry an origins header written by `promote_group`; a
    mirrored external *page* does not. The stale-queue check must tell them
    apart: a section named `article-transfer-service.md` does not clear a queue
    row waiting for the Article Transfer Service policy page.
    """
    try:
        first = next(
            ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()
        )
    except (OSError, StopIteration):
        return False
    return bool(SHARED_HEADER_RE.match(first.strip()))


def normalize_section_text(text: str) -> str:
    """Canonical form for comparing two section files.

    Strips the per-download provenance comment (different line numbers per
    journal), trailing whitespace and the final newline run. Everything else —
    anchors, headings, prose, links — must match exactly. A file that differs
    in a single word is a different file: usually the journal's name.
    """
    text = text.replace("\r\n", "\n")
    lines = [
        ln.rstrip()
        for ln in text.split("\n")
        if not SECTION_PROVENANCE_RE.match(ln.strip())
    ]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def section_hash(text: str) -> str:
    return hashlib.sha256(normalize_section_text(text).encode("utf-8")).hexdigest()


def local_section_files(repo: Path, journal: str) -> list[Path]:
    """Every section file that could move to `_shared/`.

    Folder `index.md` files are maps, not content: they list that folder's own
    files with journal-specific numbering, so they stay local by design.
    """
    sdir = guide_dir(repo, journal) / "sections"
    if not sdir.is_dir():
        return []
    return sorted(
        p for p in sdir.rglob("*.md")
        if p.is_file() and not (p.parent != sdir and p.name == "index.md")
    )


def duplicate_groups(repo: Path, publisher: str = "") -> list[dict]:
    """Groups of byte-identical section files used by 2+ journals.

    Grouped per publisher namespace: Elsevier's boilerplate is not Springer
    Nature's, even when the words happen to match. Journals without `guide:`
    are opt-in and skipped, the same rule `check_guide` applies.
    """
    by_key: dict[tuple[str, str], list[tuple[str, Path]]] = {}
    for jdir in iter_journals(repo):
        journal = jdir.name
        if publisher and publisher_namespace(repo, journal) != publisher:
            continue
        meta = load_yaml(jdir / "type.yaml")
        if not str(meta.get("guide") or "").strip():
            continue
        ns = publisher_namespace(repo, journal)
        for path in local_section_files(repo, journal):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            by_key.setdefault((ns, section_hash(text)), []).append((journal, path))
    out = []
    for (ns, digest), files in sorted(by_key.items()):
        journals = {journal for journal, _ in files}
        if len(journals) >= 2:
            out.append({"namespace": ns, "hash": digest, "files": sorted(files)})
    return out


def shared_filename_for(path: Path) -> str:
    """File name a promoted section gets under `_shared/<namespace>/`.

    Local names carry per-guide numbering (`06-`, `51-references/`), which is
    meaningless once the file serves several guides. What survives is the slug
    the publisher's own heading gave it; a nested file keeps its folder's slug
    as a prefix so `references/management-software.md` cannot collide with a
    top-level `management-software.md`.
    """
    if path.parent.name == "sections":
        return re.sub(r"^\d+-", "", path.name)
    folder = re.sub(r"^\d+-", "", path.parent.name)
    return f"{folder}-{path.name}"


def shared_header(namespace: str, digest: str, files: list[tuple[str, Path]], repo: Path) -> str:
    origins = " ".join(
        f"{journal}/guide/{path.relative_to(guide_dir(repo, journal)).as_posix()}"
        for journal, path in files
    )
    return (
        f"<!-- shared section | publisher: {namespace} | hash: {digest} | "
        f"origins: {origins} -->\n"
    )


def rewrite_index_links(index_path: Path, mapping: dict[str, Path]) -> bool:
    """Point an index at the shared copies. Returns True when it changed.

    Only the target path is rewritten; link text and `#fragment` survive. Lines
    inside code fences and HTML comments are left alone, the same rule
    `find_links` reads by.
    """
    text = index_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    fenced = False
    changed = False
    out = []
    for line in lines:
        if FENCE_RE.match(line):
            fenced = not fenced
            out.append(line)
            continue
        if fenced or line.lstrip().startswith("<!--"):
            out.append(line)
            continue

        def replace(match: re.Match) -> str:
            nonlocal changed
            target = match.group(1)
            path_part, hash_mark, frag = target.partition("#")
            if not path_part.strip() or is_external(target):
                return match.group(0)
            dest = (index_path.parent / path_part).resolve()
            key = str(dest)
            if key not in mapping:
                return match.group(0)
            rel = os_path_relpath(mapping[key], index_path.parent)
            changed = True
            return match.group(0).replace(target, rel + (hash_mark + frag if hash_mark else ""), 1)

        out.append(LINK_RE.sub(replace, line))
    if changed:
        index_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def os_path_relpath(target: Path, start: Path) -> str:
    """`os.path.relpath` with forward slashes, so links read the same on Windows."""
    import os

    return os.path.relpath(str(target), str(start)).replace("\\", "/")


def promote_group(repo: Path, group: dict) -> Path:
    """Move one duplicate group into `_shared/<namespace>/`.

    Writes the single copy (first file's body, provenance header replaced by a
    shared origins header), rewrites every `index.md` that pointed at a local
    copy — the guide index for top-level files, the folder index for nested
    ones — and deletes the locals. Raises SystemExit on a filename collision
    with different content rather than merging two different texts.
    """
    namespace, digest, files = group["namespace"], group["hash"], group["files"]
    dest_dir = repo / "templates" / "journals" / SHARED_DIRNAME / namespace
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / shared_filename_for(files[0][1])
    if dest.is_file() and section_hash(dest.read_text(encoding="utf-8")) != digest:
        raise SystemExit(
            f"ERROR: {md_rel(repo, dest)} already exists with different content. "
            f"Name it by hand: two different texts want the same shared name."
        )
    first = files[0][1].read_text(encoding="utf-8", errors="replace")
    body = normalize_section_text(first)
    if not dest.is_file():
        dest.write_text(shared_header(namespace, digest, files, repo) + body, encoding="utf-8")

    mapping = {str(path.resolve()): dest.resolve() for _, path in files}
    for journal, path in files:
        gdir = guide_dir(repo, journal)
        indexes = [gdir / "index.md"] if (gdir / "index.md").is_file() else []
        indexes += sorted(
            p for p in (gdir / "sections").glob("*/index.md") if p.is_file()
        )
        for index in indexes:
            rewrite_index_links(index, mapping)
        if path.is_file():
            path.unlink()
    return dest


def check_duplicates(repo: Path) -> Result:
    """Warn about byte-identical sections still living in 2+ guides.

    A warning, not an error: a fresh guide legitimately duplicates the
    boilerplate until someone promotes it. But every row here is a file that
    should live once under `_shared/`, and two copies are already one too many
    to keep in sync by hand.
    """
    res = Result()
    for group in duplicate_groups(repo):
        journals = sorted({journal for journal, _ in group["files"]})
        where = f"templates/journals/_shared/{group['namespace']}"
        files = ", ".join(
            f"{journal}/guide/{path.relative_to(guide_dir(repo, journal)).as_posix()}"
            for journal, path in group["files"]
        )
        res.add(
            "warn", where,
            f"identical section in {len(journals)} guides ({', '.join(journals)}), "
            f"hash {group['hash'][:12]}: {files} — "
            f"promote with `dedup --publisher {group['namespace']} --promote` "
            f"(suggested name: {shared_filename_for(group['files'][0][1])})",
        )
    return res


def check_shared_files(repo: Path) -> Result:
    """Validate the single copies themselves.

    A shared file is read by several guides, so a broken link inside it breaks
    several guides at once. Missing provenance is a warning: the file is usable,
    but nobody can tell which downloads it came from.
    """
    res = Result()
    base = repo / "templates" / "journals" / SHARED_DIRNAME
    if not base.is_dir():
        return res
    for path in sorted(base.rglob("*.md")):
        if not path.is_file():
            continue
        where = md_rel(repo, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        if not first.startswith("<!--") or "origins:" not in first:
            res.add("warn", where,
                    "no shared origins header: nothing records which guides "
                    "this copy came from")
        for link in find_links(text):
            if is_external(link.target):
                continue
            part, _, frag = link.target.partition("#")
            dest = (path.parent / part).resolve() if part else path.resolve()
            if not dest.is_file():
                res.add("error", where, f"broken link: {link.target} (no such file)")
            elif frag and dest.suffix == ".md" and frag not in read_anchors(dest):
                res.add("error", where, f"broken anchor: {link.target}")
    return res


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def read_source(args, repo: Path) -> Path:
    src = Path(args.source)
    if not src.is_absolute():
        for base in (Path.cwd(), repo):
            if (base / src).is_file():
                src = base / src
                break
    if not src.is_file():
        raise SystemExit(f"ERROR: source not found: {args.source}")
    return src


def cmd_convert(args, repo: Path) -> int:
    src = read_source(args, repo)
    markdown, removed = to_markdown(src, args.engine)
    out = Path(args.out) if args.out else src.with_suffix(".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    print(f"converted {src.name} -> {out}  ({len(markdown.splitlines())} lines)")
    if removed:
        print(f"\nremoved {len(removed)} non-content element(s) — check this list, a")
        print("lost paragraph would otherwise be silent:")
        seen = set()
        for tag, label in removed:
            key = (tag, label)
            if key in seen:
                continue
            seen.add(key)
            print(f"  - <{tag}> {label[:70]}")
    else:
        print("removed: nothing")
    return 0


def cmd_outline(args, repo: Path) -> int:
    src = read_source(args, repo)
    markdown, _ = to_markdown(src, args.engine)
    heads = scan_headings(markdown)
    lines = markdown.splitlines()
    if not heads:
        print("no headings found — the source has no structure to cut on")
        return 1
    print(f"{len(heads)} headings in {len(lines)} lines\n")
    for i, (level, title, start) in enumerate(heads):
        end = len(lines)
        for _l, _t, ln in heads[i + 1:]:
            if ln > start:
                end = ln
                break
        mark = "  <- cut" if level == args.split_level else ""
        print(f"  h{level} {title[:60]:<62} L{start + 1}-{end} ({end - start}){mark}")
    print(f"\ncut level h{args.split_level}, cap {MAX_SECTION_LINES} lines "
          f"(`propose` also re-cuts oversized sections on their sub-headings)")
    return 0


def cmd_propose(args, repo: Path) -> int:
    src = read_source(args, repo)
    gdir = guide_dir(repo, args.journal)
    work = gdir / "_work"
    sections_dir = work / "sections"
    if sections_dir.exists() and not args.force:
        raise SystemExit(
            f"ERROR: {sections_dir} already exists. This is a proposal; review or "
            f"delete it first, or re-run with --force."
        )
    markdown, removed = to_markdown(src, args.engine)
    sections, doc_title = split_sections(markdown, args.split_level, args.max_lines)
    groups = [s.title for s in sections if s.is_heading_only]
    sections = [s for s in sections if not s.is_heading_only]
    if not sections:
        raise SystemExit(
            "ERROR: every proposed section is a bare heading. That means the cut "
            "landed one level too high; retry with a deeper --split-level."
        )

    if sections_dir.exists():
        shutil.rmtree(sections_dir)
    sections_dir.mkdir(parents=True, exist_ok=True)
    names = numbered([s.filename for s in sections])
    for sec, name in zip(sections, names):
        body = "\n".join(sec.lines).strip()
        (sections_dir / name).write_text(
            section_header(src.name, sec) + body + "\n", encoding="utf-8"
        )

    heads = scan_headings(markdown)
    (work / "outline.md").write_text(
        f"# Outline — {src.name}\n\n"
        + (f"The page's own title is **{doc_title[0]}**. It is not a section; put it "
           f"in `index.md` as the guide's title.\n\n" if doc_title else "")
        + (f"Grouping headings with no text of their own (keep them in `index.md` to "
           f"say what the sections under them cover): {', '.join(groups)}\n\n" if groups else "")
        + f"{len(sections)} proposed section(s) from {len(heads)} heading(s), "
        f"{len(markdown.splitlines())} lines.\n\n"
        "| file | heading | lines |\n|---|---|---|\n"
        + "".join(
            f"| [{n}](sections/{n}) | {s.title} | {len(s.lines)} |\n"
            for n, s in zip(names, sections)
        ),
        encoding="utf-8",
    )
    print(f"proposal in {md_rel(repo, sections_dir)} ({len(sections)} files)")
    for n, s in zip(names, sections):
        flag = "  OVER CAP" if len(s.lines) > args.max_lines else ""
        print(f"  {n}  {len(s.lines):>5} lines  {s.title}{flag}")
    if doc_title:
        print(f"\npage title (not a section, put it in index.md): {doc_title[0]}")
    if groups:
        print(f"grouping headings kept out of sections/ (put them in index.md): "
              f"{', '.join(groups)}")
    if removed:
        print(f"\n{len(removed)} element(s) stripped in conversion — see `convert` output")
    print(f"\nThis is a PROPOSAL. Nothing in guide/ has changed. Review "
          f"{md_rel(repo, work / 'outline.md')}, edit the files, then `apply`.")
    return 0


def cmd_apply(args, repo: Path) -> int:
    gdir = guide_dir(repo, args.journal)
    src_dir = gdir / "_work" / "sections"
    dest = gdir / "sections"
    if not src_dir.is_dir():
        raise SystemExit(f"ERROR: no proposal at {md_rel(repo, src_dir)} — run `propose` first")
    proposed = section_entries(src_dir)
    if not proposed:
        raise SystemExit(f"ERROR: the proposal in {md_rel(repo, src_dir)} is empty")

    # The gate. Where the sections end is a judgement call — merging two topics,
    # splitting one, dropping the page's own index — and it is the user's to make,
    # not the script's. `apply` is the only step that writes into guide/, so it is
    # the only place the gate has to hold.
    if not args.approved:
        raise SystemExit(
            f"NOT APPLIED. {len(proposed)} proposed section(s) are waiting in "
            f"{md_rel(repo, src_dir)}.\n"
            f"  1. Read {md_rel(repo, gdir / '_work' / 'outline.md')} — the cut, in order.\n"
            f"  2. Read the files that look wrong and fix them there.\n"
            f"  3. Show the proposal to the user and get their approval. Do not skip\n"
            f"     this: the cut is a judgement call, and an unapproved `apply` writes\n"
            f"     decisions nobody made.\n"
            f"  4. Re-run with --approved once they have."
        )

    if dest.exists() and any(dest.iterdir()) and not args.force:
        raise SystemExit(
            f"ERROR: {md_rel(repo, dest)} is not empty. `apply` overwrites sections; "
            f"re-run with --force if that is what you want."
        )
    dest.mkdir(parents=True, exist_ok=True)
    # The proposal may hold a folder as well as files: a section too big for one
    # file becomes `NN-topic/index.md` plus its own files.
    for entry in section_entries(src_dir):
        if entry.is_dir():
            shutil.copytree(entry, dest / entry.name, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, dest / entry.name)
    # The proposal is the complete intended set. Leaving anything from an earlier,
    # differently-cut proposal behind would leave the index listing sections that
    # no longer correspond to anything, and orphans that `check` would then report
    # as errors with no obvious cause.
    kept = {e.name for e in section_entries(src_dir)}
    stale = [
        e for e in dest.iterdir()
        if e.name not in kept and (e.is_file() or (e.is_dir() and any(e.iterdir())))
    ]
    for e in stale:
        shutil.rmtree(e) if e.is_dir() else e.unlink()
    print(f"applied {len(kept)} section(s) to {md_rel(repo, dest)}")
    if stale:
        print(f"removed {len(stale)} section(s) no longer in the proposal: "
              f"{', '.join(sorted(e.name for e in stale)[:5])}"
              f"{' ...' if len(stale) > 5 else ''}")
    print("still to do by hand: index.md, SOURCES.md, external.md, and the "
          "cross-references between sections (`cites` for the reverse index).")
    return 0


def cmd_scaffold(args, repo: Path) -> int:
    gdir = guide_dir(repo, args.journal)
    sections = gdir / "sections"
    sections.mkdir(parents=True, exist_ok=True)
    (gdir / "index.md").write_text(
        f"# {args.journal} — Guide for Authors\n\n"
        "> Local, offline copy of the journal's Guide for Authors. The publisher's\n"
        "> site is behind a captcha, so this is the only copy that survives.\n\n"
        "Read `sections/` for the content; provenance is in `SOURCES.md` and pages\n"
        "this guide links to but does not contain are in `external.md`.\n\n"
        "## Sections\n\n<!-- one line per section, then the link -->\n",
        encoding="utf-8",
    )
    (gdir / "SOURCES.md").write_text(
        f"# Sources — {args.journal}\n\n"
        "Provenance for the raw material. The raw file itself is never committed\n"
        "(it is a page download; `guide/_raw/` is gitignored), so this table is\n"
        "the record of what was converted and whether the conversion can be redone.\n\n"
        "| what | url | retrieved | sha256 |\n|---|---|---|---|\n",
        encoding="utf-8",
    )
    (gdir / "external.md").write_text(
        f"# External references — {args.journal}\n\n"
        "Pages this guide links to that are not part of it. A row marked "
        f"`{NOT_MIRRORED}` means the text is NOT in the bank: the URL is where to "
        "get it. Download that page and hand it over the same way, and the "
        "reference becomes a local link.\n\n"
        "| url | topic | state |\n|---|---|---|\n",
        encoding="utf-8",
    )
    type_yaml = journal_dir(repo, args.journal) / "type.yaml"
    if type_yaml.is_file():
        set_type_field(type_yaml, "guide", "guide/index.md")
    print(f"scaffolded {md_rel(repo, gdir)}")
    print(f"  sections/  index.md  SOURCES.md  external.md")
    if type_yaml.is_file():
        print(f"  type.yaml: guide: guide/index.md")
    return 0


def cmd_sources(args, repo: Path) -> int:
    gdir = guide_dir(repo, args.journal)
    sources = gdir / "SOURCES.md"
    if not sources.is_file():
        raise SystemExit(f"ERROR: {md_rel(repo, sources)} not found — run `scaffold` first")
    raw = Path(args.raw) if args.raw else None
    sha = ""
    if raw:
        if not raw.is_file():
            raise SystemExit(f"ERROR: raw file not found: {raw}")
        sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    row = (
        f"| {args.what} | {args.url} | {args.retrieved or date.today().isoformat()} "
        f"| {sha or 'TODO'} |\n"
    )
    text = sources.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    sources.write_text(text + row, encoding="utf-8")
    if raw:
        print(f"sha256({raw.name}) = {sha}")
    print(f"recorded in {md_rel(repo, sources)}")
    if args.set_type_date:
        set_type_field(journal_dir(repo, args.journal) / "type.yaml",
                       "guide_retrieved", args.retrieved or date.today().isoformat())
        print("type.yaml: guide_retrieved updated")
    return 0


def cmd_cites(args, repo: Path) -> int:
    hits = cites(repo, args.url)
    if not hits:
        print(f"nothing in the bank links to {args.url}")
        return 0
    print(f"{len(hits)} reference(s) to {args.url}:\n")
    for md, line, target in hits:
        print(f"  {md_rel(repo, md)}:{line}  -> {target}")
    print("\nRewrite every one of these to the local path. Then run this command")
    print("again: it must print nothing. That zero is the proof the promotion is")
    print("complete — a missed link would otherwise survive until someone cites it.")
    return 1 if args.strict else 0


def cmd_check(args, repo: Path) -> int:
    journals = iter_journals(repo)
    if args.journal:
        journals = [journal_dir(repo, args.journal)]
        if not journals[0].is_dir():
            raise SystemExit(f"ERROR: unknown journal '{args.journal}'")
    total_e = total_w = 0
    for jdir in journals:
        res = check_guide(repo, jdir.name)
        for issue in res.issues:
            print(f"{issue.level.upper()}: {issue.where}: {issue.message}")
        total_e += len(res.errors)
        total_w += len(res.warns)
        if not res.issues and jdir.name == args.journal:
            print(f"OK: {jdir.name} guide is consistent")
    if not args.journal:
        # Cross-guide checks only make sense over the whole bank: duplicates
        # are, by definition, never visible from a single journal.
        for res in (check_duplicates(repo), check_shared_files(repo)):
            for issue in res.issues:
                print(f"{issue.level.upper()}: {issue.where}: {issue.message}")
            total_e += len(res.errors)
            total_w += len(res.warns)
    print(f"\n{total_e} error(s), {total_w} warning(s)")
    return 1 if total_e else 0


def cmd_dedup(args, repo: Path) -> int:
    groups = duplicate_groups(repo, args.publisher or "")
    if not args.promote:
        if not groups:
            print("no byte-identical section lives in 2+ guides: nothing to promote")
            return 0
        print(f"{len(groups)} group(s) of byte-identical sections in 2+ guides:\n")
        for group in groups:
            journals = sorted({journal for journal, _ in group["files"]})
            print(f"  hash {group['hash'][:12]}  {len(group['files'])} files "
                  f"in {', '.join(journals)}  ->  "
                  f"_shared/{group['namespace']}/{shared_filename_for(group['files'][0][1])}")
            for journal, path in group["files"]:
                print(f"    {journal}/guide/{path.relative_to(guide_dir(repo, journal)).as_posix()}")
        print("\nThis is a PROPOSAL. Nothing has moved. Show it to the user, get "
              "their approval, then re-run with --promote --approved.")
        return 0
    if not args.approved:
        raise SystemExit(
            f"NOT APPLIED. {len(groups)} duplicate group(s) are waiting for promotion.\n"
            f"  1. Read the report above (`dedup` without --promote lists every group).\n"
            f"  2. Show it to the user and get their approval. Do not skip this: "
            f"merging N copies into one shared file is a judgement call.\n"
            f"  3. Re-run with --promote --approved once they have."
        )
    if not groups:
        print("nothing to promote")
        return 0
    for group in groups:
        dest = promote_group(repo, group)
        print(f"promoted {len(group['files'])} copies -> {md_rel(repo, dest)}")
    print("still to do by hand: nothing — each guide index now points at the "
          "shared copy. Run `check` to verify.")
    return 0


def propose(repo: Path, journal: str, source: Path, engine: str = "builtin",
            split_level: int = 2, max_lines: int = MAX_SECTION_LINES,
            force: bool = False) -> int:
    """Write the section split into guide/_work/ as a proposal.

    Exposed as a plain function (not only a CLI) so the tests can drive the real
    pipeline instead of a stand-in for it.
    """
    return cmd_propose(argparse.Namespace(
        journal=journal, source=str(source), engine=engine,
        split_level=split_level, max_lines=max_lines, force=force,
    ), repo)


def scaffold(repo: Path, journal: str) -> int:
    return cmd_scaffold(argparse.Namespace(journal=journal), repo)


def apply(repo: Path, journal: str, force: bool = False, approved: bool = False) -> int:
    return cmd_apply(argparse.Namespace(journal=journal, force=force, approved=approved), repo)


def main(argv: list[str] | None = None) -> int:
    # The messages mix arrows and dashes with plain ASCII; a cp1252 console would
    # mangle them, and a mojibake report is a report nobody reads.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-tty/old streams
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="repository root (default: autodetect)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_engine(p):
        p.add_argument("--engine", choices=["builtin", "markitdown"], default="builtin",
                       help="builtin keeps <a id> anchors (default); markitdown reads "
                            "prettier but drops them, breaking every internal link")
        return p

    with_engine(sub.add_parser("convert", help="HTML/Markdown/text -> clean Markdown"))
    sub.choices["convert"].add_argument("--source", required=True, help="the downloaded file")
    sub.choices["convert"].add_argument("--out", help="output .md (default: alongside --source)")

    o = with_engine(sub.add_parser("outline", help="heading tree with line counts"))
    o.add_argument("--source", required=True)
    o.add_argument("--split-level", type=int, default=2)

    p = with_engine(sub.add_parser("propose", help="write the section split as a proposal"))
    p.add_argument("--journal", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--split-level", type=int, default=2)
    p.add_argument("--max-lines", type=int, default=MAX_SECTION_LINES)
    p.add_argument("--force", action="store_true")

    a = sub.add_parser("apply", help="move the reviewed proposal into guide/sections/")
    a.add_argument("--journal", required=True)
    a.add_argument("--force", action="store_true")
    a.add_argument("--approved", action="store_true",
                   help="the user has reviewed the proposal in guide/_work/ and "
                        "agreed with the cut; required to write anything into "
                        "guide/sections/")

    s = sub.add_parser("scaffold", help="create the guide/ skeleton")
    s.add_argument("--journal", required=True)

    so = sub.add_parser("sources", help="record url + date + sha256 of a raw source")
    so.add_argument("--journal", required=True)
    so.add_argument("--what", required=True, help="label, e.g. 'guide-for-authors'")
    so.add_argument("--url", required=True)
    so.add_argument("--retrieved", help="YYYY-MM-DD (default: today)")
    so.add_argument("--raw", help="raw file to hash")
    so.add_argument("--set-type-date", action="store_true",
                    help="also write guide_retrieved into type.yaml")

    c = sub.add_parser("cites", help="reverse index: who links to this URL")
    c.add_argument("--url", required=True)
    c.add_argument("--strict", action="store_true", help="exit 1 when there are hits")

    ck = sub.add_parser("check", help="validate the guides")
    ck.add_argument("--journal")
    ck.add_argument("--root-unused", help=argparse.SUPPRESS)

    d = sub.add_parser("dedup", help="find byte-identical sections shared by 2+ guides")
    d.add_argument("--publisher", help="limit to one publisher namespace, e.g. elsevier")
    d.add_argument("--promote", action="store_true",
                   help="move each group into _shared/ and rewrite the indexes")
    d.add_argument("--approved", action="store_true",
                   help="the user has reviewed the dedup report and agreed; "
                        "required to move anything")

    args = ap.parse_args(argv)
    repo = Path(args.root).resolve() if args.root else find_repo_root(Path(__file__))
    handler = {
        "convert": cmd_convert, "outline": cmd_outline, "propose": cmd_propose,
        "apply": cmd_apply, "scaffold": cmd_scaffold, "sources": cmd_sources,
        "cites": cmd_cites, "check": cmd_check, "dedup": cmd_dedup,
    }[args.cmd]
    return handler(args, repo)


if __name__ == "__main__":
    raise SystemExit(main())
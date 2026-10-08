#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""cas_docx_post.py — give a rendered elsevier-cas DOCX the layout of the PDF.

pandoc/Quarto decide parts of the OOXML that no reference document or Lua
filter can reach: floats come wrapped in one-cell tables, equation numbers
sit inside the centred math, list indents and footnote marks are fixed. This
post-processor rewrites word/document.xml (+ footnotes, numbering, settings)
of the built DOCX so that it follows cas-sc as rendered by pdfTeX:

  front matter   highlights-page section break gets the body geometry; the
                 ARTICLE INFO | ABSTRACT table gets the 0.35/0.65 columns and
                 the four 0.2 pt rules; front notes get the PDF's marks (*,
                 none) instead of Word numbers
  headings       "2.1 Title" -> "2.1. Title"; a subsection right after its
                 section loses its space above (LaTeX keeps the larger skip)
  lists          bullet at 14.7 pt, text at 24.9 pt, 8 pt between items and
                 10 pt around the list
  figures        unwrapped, .9\\textwidth wide, centred; caption in sans 9 pt
                 with a bold "Figure N:" label
  tables         unwrapped; "Table N" (bold) over the caption; booktabs rules
                 (0.8/0.5/0.8 pt), .9\\textwidth, equal p{} columns, sans 9 pt
  equations      centred on a tab stop with the number flush right
  notes          0.4\\textwidth separator rule, typewriter text at 8 pt
  settings       STIX Math; WordPerfect justification (shrinks spaces like
                 TeX's glue), no Word hyphenation
  --pdf          every float LaTeX put at the top of a page goes, in an
                 anchored text box, to the top of the same page (the first
                 paragraph that starts there in the PDF anchors it)
  --latex-zip    references rebuilt from the zip's .bbl (cas-model2-names.bst
                 text, doi:/URL: in typewriter) and citations relabelled from
                 its natbib labels, long author lists first (longnamesfirst)
  --short-citations
                 with cas-model2-names-etal.bst: keep every citation in the
                 short form ("Hwang et al., 2019"), as that bst's PDF does

Every number is measured on the CAS PDF; scripts/paper_parity.py measures the
result. Stdlib only (plus Poppler's pdftotext for --pdf). Usage
(paper_build.py calls it after every docx render):

    python tools/cas_docx_post.py build/<slug>.docx \\
        --pdf build/<slug>.pdf --latex-zip build/<slug>-latex.zip
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"

# geometry shared with make_reference_docx.py (twips)
PAGE_W = 10885
MARGIN_LR = 777
TEXT_WIDTH = PAGE_W - 2 * MARGIN_LR          # 9331
EMU_PER_TWIP = 635
FLOAT_WIDTH = round(0.9 * TEXT_WIDTH)        # width=.9\linewidth
SANS = "LM Sans 9"
SANS_BOLD = "LM Sans 10"
MONO_SMALL = "LM Mono 8"
FONT = "STIX"
MATH_FONT = "STIX Math"
MARK_OPEN, MARK_CLOSE = "", ""


def tw(tex_pt: float) -> int:
    return round(tex_pt * 72 / 72.27 * 20)


def bp(points: float) -> int:
    return round(points * 20)


TABCOLSEP = tw(6)
RULE_HEAVY = 6       # eighths of a point: booktabs \heavyrulewidth .08em
RULE_LIGHT = 4       # \lightrulewidth .05em
RULE_CAS = 2         # cas-sc \rule{..}{.2pt}

# Vertical metrics calibrated against the PDF with scripts/paper_parity.py.
LIST_FIRST_BEFORE = tw(10)
LIST_ITEM_BEFORE = tw(8)
LIST_LAST_AFTER = tw(10)
# (Word: baseline of an exact line at 80 % of its height; values in bp place
# each baseline on the PDF's ink baseline)
HIGHLIGHTS_TOP = 999           # highlights page: "Highlights" baseline 63.5 pt
FIRST_HIGHLIGHT_BEFORE = bp(19.94)
INFO_LABEL_BEFORE = bp(5.59)
INFO_RULE_TO_TEXT = bp(2.0)
INFO_BOTTOM_PAD = bp(16.5)
FIRST_SECTION_BEFORE = bp(20.5)
FIG_ABOVE = tw(10)
FIG_CAPTION_GAP = tw(6)
FIG_BELOW = tw(12)
TBL_ABOVE = tw(10)
TBL_BELOW = tw(12)
ROW_PAD = tw(1.5)
FLOAT_SEP = tw(20)     # textfloatsep below a top float
EQ_ABOVE = tw(6)
EQ_BELOW = tw(6)


def q(tag: str, ns: str = W) -> str:
    return f"{{{ns}}}{tag}"


def register_namespaces(xml: bytes) -> None:
    for prefix, uri in re.findall(rb'xmlns:(\w+)="([^"]+)"', xml):
        ET.register_namespace(prefix.decode(), uri.decode())


# ---------------------------------------------------------------------------
# small OOXML helpers
# ---------------------------------------------------------------------------

def child(el: ET.Element, tag: str, ns: str = W) -> ET.Element | None:
    return el.find(q(tag, ns))


def ensure(el: ET.Element, tag: str, first: bool = False) -> ET.Element:
    found = child(el, tag)
    if found is None:
        found = ET.Element(q(tag))
        if first:
            el.insert(0, found)
        else:
            el.append(found)
    return found


def ppr(p: ET.Element) -> ET.Element:
    """The paragraph's pPr, merging the duplicate pPr Quarto emits for
    captions (Word reads only the first one)."""
    props = p.findall(q("pPr"))
    if not props:
        new = ET.Element(q("pPr"))
        p.insert(0, new)
        return new
    main = props[0]
    for extra in props[1:]:
        for c in list(extra):
            old = child(main, c.tag.split("}")[1])
            if old is not None:
                main.remove(old)
            main.append(c)
        p.remove(extra)
    # pStyle must come first
    style = child(main, "pStyle")
    if style is not None and list(main).index(style) != 0:
        main.remove(style)
        main.insert(0, style)
    return main


def style_of(p: ET.Element) -> str | None:
    # Quarto's captions carry two pPr; the style may sit in either
    for pp in p.findall(q("pPr")):
        st = pp.find(q("pStyle"))
        if st is not None:
            return st.get(q("val"))
    return None


def set_style(p: ET.Element, style: str) -> None:
    pp = ppr(p)
    st = child(pp, "pStyle")
    if st is None:
        st = ET.Element(q("pStyle"))
        pp.insert(0, st)
    st.set(q("val"), style)


def set_attr_child(parent: ET.Element, tag: str, **attrs) -> ET.Element:
    el = child(parent, tag)
    if el is None:
        el = ET.SubElement(parent, q(tag))
    for k, v in attrs.items():
        el.set(q(k), str(v))
    return el


def spacing(p: ET.Element, **attrs) -> None:
    set_attr_child(ppr(p), "spacing", **attrs)


def remove_child(parent: ET.Element, tag: str) -> None:
    for c in parent.findall(q(tag)):
        parent.remove(c)


def text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(q("t")))


def run(text_value: str, *, bold: bool = False, font: str | None = None,
        sz: int | None = None, vert: str | None = None,
        rstyle: str | None = None) -> ET.Element:
    r = ET.Element(q("r"))
    rpr = ET.SubElement(r, q("rPr"))
    if rstyle:
        ET.SubElement(rpr, q("rStyle")).set(q("val"), rstyle)
    if font:
        rf = ET.SubElement(rpr, q("rFonts"))
        for a in ("ascii", "hAnsi", "cs"):
            rf.set(q(a), font)
    if bold:
        ET.SubElement(rpr, q("b"))
    if sz:
        ET.SubElement(rpr, q("sz")).set(q("val"), str(sz))
        ET.SubElement(rpr, q("szCs")).set(q("val"), str(sz))
    if vert:
        ET.SubElement(rpr, q("vertAlign")).set(q("val"), vert)
    t = ET.SubElement(r, q("t"))
    t.text = text_value
    t.set(f"{{{XML_NS}}}space", "preserve")
    if not len(rpr):
        r.remove(rpr)
    return r


def border(parent: ET.Element, edge: str, sz: int, space: int = 0,
           val: str = "single") -> None:
    el = set_attr_child(parent, edge, val=val, sz=sz, space=space, color="auto")
    if val == "nil":
        for a in ("sz", "space", "color"):
            el.attrib.pop(q(a), None)


def tbl_props(tbl: ET.Element, width: int, jc: str, borders: dict[str, int],
              cell_mar: tuple[int, int, int, int]) -> None:
    """Replace tblPr: fixed width, alignment, outer rules, cell margins."""
    old = child(tbl, "tblPr")
    if old is not None:
        tbl.remove(old)
    pr = ET.Element(q("tblPr"))
    tbl.insert(0, pr)
    ET.SubElement(pr, q("tblW")).attrib.update({q("w"): str(width), q("type"): "dxa"})
    ET.SubElement(pr, q("jc")).set(q("val"), jc)
    ET.SubElement(pr, q("tblInd")).attrib.update({q("w"): "0", q("type"): "dxa"})
    bd = ET.SubElement(pr, q("tblBorders"))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        sz = borders.get(edge)
        border(bd, edge, sz or 0, val="single" if sz else "nil")
    ET.SubElement(pr, q("tblLayout")).set(q("type"), "fixed")
    mar = ET.SubElement(pr, q("tblCellMar"))
    for edge, v in zip(("top", "left", "bottom", "right"), cell_mar):
        ET.SubElement(mar, q(edge)).attrib.update({q("w"): str(v), q("type"): "dxa"})
    ET.SubElement(pr, q("tblLook")).set(q("val"), "0000")


def set_grid(tbl: ET.Element, widths: list[int]) -> None:
    grid = child(tbl, "tblGrid")
    if grid is None:
        grid = ET.Element(q("tblGrid"))
        tbl.insert(1, grid)
    for c in list(grid):
        grid.remove(c)
    for w in widths:
        ET.SubElement(grid, q("gridCol")).set(q("w"), str(w))


def cell_props(tc: ET.Element) -> ET.Element:
    pr = child(tc, "tcPr")
    if pr is None:
        pr = ET.Element(q("tcPr"))
        tc.insert(0, pr)
    return pr


# ---------------------------------------------------------------------------
# passes
# ---------------------------------------------------------------------------

def body_sectpr(body: ET.Element) -> ET.Element | None:
    return child(body, "sectPr")


def fix_section_break(body: ET.Element) -> None:
    final = body_sectpr(body)
    for p in body.iter(q("p")):
        if style_of(p) != "CasSectionBreak":
            continue
        pp = ppr(p)
        remove_child(pp, "pStyle")
        sect = child(pp, "sectPr")
        if sect is None or final is None:
            continue
        for tag in ("pgSz", "pgMar", "cols"):
            src = child(final, tag)
            if src is not None:
                sect.append(copy.deepcopy(src))
        mar = child(sect, "pgMar")
        if mar is not None:
            mar.set(q("top"), str(HIGHLIGHTS_TOP))
        # the break paragraph must not add a line to the highlights page
        set_attr_child(pp, "spacing", before=0, after=0, line=20, lineRule="exact")


def fix_info_box(body: ET.Element) -> ET.Element | None:
    for tbl in body.findall(q("tbl")):
        styles = [style_of(p) for p in tbl.iter(q("p"))]
        if "AbstractTitle" not in styles:
            continue
        left = round(0.35 * TEXT_WIDTH)
        widths = [left, TEXT_WIDTH - left]
        tbl_props(tbl, TEXT_WIDTH, "left", {"top": RULE_CAS, "bottom": RULE_CAS},
                  (0, 0, INFO_BOTTOM_PAD, 0))
        set_grid(tbl, widths)
        for tr in tbl.findall(q("tr")):
            remove_child(tr, "trPr")
            for tc, w in zip(tr.findall(q("tc")), widths):
                pr = cell_props(tc)
                remove_child(pr, "tcW")
                ET.SubElement(pr, q("tcW")).attrib.update({q("w"): str(w), q("type"): "dxa"})
                for i, p in enumerate(tc.findall(q("p"))):
                    if style_of(p) == "AbstractTitle":
                        spacing(p, before=INFO_LABEL_BEFORE, after=INFO_RULE_TO_TEXT)
                        if w == left:
                            # the ARTICLE INFO rule is .25\textwidth long
                            set_attr_child(ppr(p), "ind", right=left - round(0.25 * TEXT_WIDTH))
                    else:
                        remove_child(ppr(p), "jc")
        return tbl
    return None


HEADING_NUM = re.compile(r"^(\d+(?:\.\d+)+)(\s)")


def fix_headings(body: ET.Element, info_box: ET.Element | None) -> None:
    children = list(body)
    prev_style = None
    after_box = info_box is None
    for el in children:
        if el is info_box:
            after_box = True
            prev_style = "InfoBox"
            continue
        if el.tag in (q("bookmarkStart"), q("bookmarkEnd")):
            continue
        if el.tag != q("p"):
            prev_style = None
            continue
        st = style_of(el)
        if st and st.startswith("Heading"):
            first_t = el.find(".//" + q("t"))
            if first_t is not None and first_t.text:
                first_t.text = HEADING_NUM.sub(r"\1.\2", first_t.text)
            if prev_style and prev_style.startswith("Heading"):
                spacing(el, before=0)
            if prev_style == "InfoBox" and after_box:
                spacing(el, before=FIRST_SECTION_BEFORE)
        prev_style = st


def numbering_kinds(numbering: ET.Element) -> dict[str, str]:
    """numId -> 'bullet' | 'ordered' (level 0)."""
    abstract = {}
    for an in numbering.findall(q("abstractNum")):
        lvl0 = an.find(q("lvl"))
        fmt = lvl0.find(q("numFmt")) if lvl0 is not None else None
        abstract[an.get(q("abstractNumId"))] = (
            fmt.get(q("val")) if fmt is not None else "bullet")
    kinds = {}
    for num in numbering.findall(q("num")):
        aid = num.find(q("abstractNumId")).get(q("val"))
        kinds[num.get(q("numId"))] = "bullet" if abstract.get(aid) == "bullet" else "ordered"
    return kinds


def fix_numbering(numbering: ET.Element) -> None:
    """itemize: bullet at 14.7 pt, text at 24.9 pt (measured)."""
    for an in numbering.findall(q("abstractNum")):
        for lvl in an.findall(q("lvl")):
            depth = int(lvl.get(q("ilvl")))
            fmt = lvl.find(q("numFmt"))
            if fmt is not None and fmt.get(q("val")) == "bullet":
                lt = lvl.find(q("lvlText"))
                if lt is not None:
                    lt.set(q("val"), "•" if depth == 0 else "–")
                rpr = lvl.find(q("rPr"))
                if rpr is None:
                    rpr = ET.SubElement(lvl, q("rPr"))
                remove_child(rpr, "rFonts")
                rf = ET.SubElement(rpr, q("rFonts"))
                for a in ("ascii", "hAnsi", "cs"):
                    rf.set(q(a), FONT)
            pp = lvl.find(q("pPr"))
            if pp is None:
                pp = ET.SubElement(lvl, q("pPr"))
            ind = set_attr_child(pp, "ind", left=498 + depth * 400, hanging=204)
            ind.attrib.pop(q("firstLine"), None)


def fix_highlights(body: ET.Element) -> None:
    first = next((p for p in body.iter(q("p")) if style_of(p) == "Highlight"), None)
    if first is not None:
        spacing(first, before=FIRST_HIGHLIGHT_BEFORE)


def fix_lists(body: ET.Element) -> None:
    items = list(body)
    i = 0
    while i < len(items):
        el = items[i]
        if el.tag == q("p") and el.find(q("pPr") + "/" + q("numPr")) is not None:
            j = i
            while (j + 1 < len(items) and items[j + 1].tag == q("p")
                   and items[j + 1].find(q("pPr") + "/" + q("numPr")) is not None):
                j += 1
            for k in range(i, j + 1):
                p = items[k]
                set_style(p, "Compact")
                set_attr_child(ppr(p), "jc", val="both")
                spacing(p, before=LIST_FIRST_BEFORE if k == i else LIST_ITEM_BEFORE,
                        after=LIST_LAST_AFTER if k == j else 0)
            i = j + 1
        else:
            i += 1


def caption_runs(p: ET.Element, label_re: str, newline: bool) -> None:
    """Split 'Figure 1: text' into a bold sans label and the caption text."""
    full = text(p)
    m = re.match(label_re, full)
    if not m:
        return
    label, rest = m.group(1), full[m.end():]
    pp = ppr(p)
    for c in list(p):
        if c is not pp and c.tag in (q("r"), q("hyperlink")):
            p.remove(c)
    p.append(run(label, bold=True, font=SANS_BOLD))
    if newline:
        br = ET.Element(q("r"))
        ET.SubElement(br, q("br"))
        p.append(br)
        p.append(run(rest))
    else:
        p.append(run(" " + rest))


def unwrap_float(body: ET.Element, tbl: ET.Element) -> list[ET.Element]:
    """Quarto wraps each float in a one-cell table; return its content."""
    tc = tbl.find(q("tr") + "/" + q("tc"))
    out = [c for c in tc if c.tag != q("tcPr")]
    idx = list(body).index(tbl)
    body.remove(tbl)
    for k, c in enumerate(out):
        body.insert(idx + k, c)
    return out


def scale_drawing(p: ET.Element, width_twips: int) -> None:
    target = width_twips * EMU_PER_TWIP
    for ext in list(p.iter(q("extent", WP))) + list(p.iter(q("ext", A))):
        cx, cy = int(ext.get("cx")), int(ext.get("cy"))
        if cx:
            ext.set("cx", str(target))
            ext.set("cy", str(round(cy * target / cx)))


def is_float_wrapper(tbl: ET.Element) -> bool:
    rows = tbl.findall(q("tr"))
    if len(rows) != 1 or len(rows[0].findall(q("tc"))) != 1:
        return False
    tc = rows[0].find(q("tc"))
    return any(style_of(p) == "ImageCaption" for p in tc.findall(q("p")))


def fix_figures_and_tables(body: ET.Element) -> list[dict]:
    """Unwrap and style every float; return them as
    {kind: 'Figure'|'Table', number: int, elements: [...]} in document order."""
    floats: list[dict] = []
    for tbl in [t for t in body.findall(q("tbl")) if is_float_wrapper(t)]:
        content = unwrap_float(body, tbl)
        caption = next((c for c in content if c.tag == q("p")
                        and style_of(c) == "ImageCaption"), None)
        inner = next((c for c in content if c.tag == q("tbl")), None)
        m = re.match(r"^(Figure|Table)\s+(\d+)",
                     text(caption) if caption is not None else "")
        if m:
            floats.append({"kind": m.group(1), "number": int(m.group(2)),
                           "elements": content})
        if inner is not None:
            fix_data_table(inner)
            if caption is not None:
                set_style(caption, "TableCaption")
                pp = ppr(caption)
                remove_child(pp, "jc")
                set_attr_child(pp, "jc", val="left")
                margin = (TEXT_WIDTH - FLOAT_WIDTH) // 2
                set_attr_child(pp, "ind", left=margin, right=margin)
                spacing(caption, before=TBL_ABOVE, after=tw(2))
                set_attr_child(pp, "keepNext", val="1")
                caption_runs(caption, r"^(Table\s+\d+)[:.]?\s*", newline=True)
            # the paragraph after the table gets the \belowtbl skip
            continue
        pics = [c for c in content if c.tag == q("p") and c.find(".//" + q("drawing")) is not None]
        for k, pic in enumerate(pics):
            set_style(pic, "FigureParagraph")
            pp = ppr(pic)
            remove_child(pp, "jc")
            set_attr_child(pp, "jc", val="center")
            set_attr_child(pp, "keepNext", val="1")
            # auto line height: an exact one would clip the inline picture
            spacing(pic, before=FIG_ABOVE if k == 0 else 0, after=0,
                    line=240, lineRule="auto")
            scale_drawing(pic, FLOAT_WIDTH)
        if caption is not None:
            pp = ppr(caption)
            remove_child(pp, "jc")
            spacing(caption, before=FIG_CAPTION_GAP, after=FIG_BELOW)
            caption_runs(caption, r"^(Figure\s+\d+:)\s*", newline=False)
            # cas centres a caption that fits on one line, else justifies it
            short = len(text(caption)) < 120
            set_attr_child(pp, "jc", val="center" if short else "both")
    return floats


# ---------------------------------------------------------------------------
# float placement: put each float on the PDF's page, at the top like [t]
# ---------------------------------------------------------------------------

PDF_WORD_RE = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" '
                         r'yMax="([\d.]+)">([^<]*)</word>')


def pdf_words(pdf: Path) -> list[list[tuple[str, float, float, float, float]]]:
    """Words per page via Poppler's pdftotext -bbox (Git for Windows ships
    an Xpdf pdftotext without -bbox: try every one on PATH)."""
    import shutil
    import subprocess
    cands: list[str] = []
    finder = ["where", "pdftotext"] if sys.platform == "win32" else ["which", "-a", "pdftotext"]
    try:
        out = subprocess.run(finder, capture_output=True, text=True).stdout
        cands = [c.strip() for c in out.splitlines() if c.strip()]
    except OSError:
        pass
    if shutil.which("pdftotext"):
        cands.append(shutil.which("pdftotext") or "")
    for exe in dict.fromkeys(cands):
        proc = subprocess.run([exe, "-bbox", str(pdf), "-"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0 and "<page" in proc.stdout:
            return [[(m.group(5), float(m.group(1)), float(m.group(2)),
                      float(m.group(3)), float(m.group(4)))
                     for m in PDF_WORD_RE.finditer(chunk)]
                    for chunk in proc.stdout.split("<page ")[1:]]
    return []


def key(word: str) -> str:
    import unicodedata
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", word)).lower()


def float_plan(pages) -> dict[tuple[str, int], tuple[int, str]]:
    """(kind, n) -> (page index, 'top' | 'here') from the PDF's captions:
    a float with no body text above it on its page is a top float."""
    plan: dict[tuple[str, int], tuple[int, str]] = {}
    for pno, words in enumerate(pages):
        body = [w for w in words if 50 < w[4] < 695]
        for i, w in enumerate(words[:-1]):
            nxt = words[i + 1]
            starts_line = i == 0 or abs(words[i - 1][4] - w[4]) > 1
            if (w[0] in ("Figure", "Table") and re.match(r"^\d+:?$", nxt[0])
                    and abs(nxt[4] - w[4]) < 1 and starts_line):
                n = int(nxt[0].rstrip(":"))
                above = [b for b in body if b[4] < w[2] - 1]
                plan.setdefault((w[0], n), (pno, "here" if above else "top"))
    return plan


def paragraph_pages(body: ET.Element, pages, skip: set) -> dict[int, int]:
    """id(paragraph) -> PDF page where its text starts (its first six words
    found, in order, in the PDF's word stream)."""
    stream = [(key(w[0]), pno) for pno, ws in enumerate(pages) for w in ws]
    stream = [(k, p) for k, p in stream if k]
    keys = [k for k, _ in stream]
    out: dict[int, int] = {}
    pos = 0
    for p in body:
        if p.tag != q("p") or id(p) in skip:
            continue
        words = [k for k in (key(w) for w in text(p).split()) if k][:6]
        if len(words) < 3:
            continue
        for j in range(pos, min(len(keys) - len(words), pos + 6000)):
            if keys[j:j + len(words)] == words:
                out[id(p)] = stream[j][1]
                pos = j + len(words)
                break
    return out


V = "urn:schemas-microsoft-com:vml"
O = "urn:schemas-microsoft-com:office:office"
W10 = "urn:schemas-microsoft-com:office:word"


def float_box(elements: list[ET.Element], below_pt: float, n: int) -> ET.Element:
    """A run holding an anchored, auto-sized VML text box at the top of the
    text area (LaTeX [t]). Unlike a floating table it is positioned on its
    anchor's page regardless of the text before the anchor, and the
    top-and-bottom wrap pushes the page's text below it (textfloatsep)."""
    width_pt = TEXT_WIDTH / 20
    r = ET.Element(q("r"))
    pict = ET.SubElement(r, q("pict"))
    shape = ET.SubElement(pict, f"{{{V}}}shape")
    shape.set("id", f"casFloat{n}")
    shape.set(f"{{{O}}}spt", "202")
    shape.set("style", ";".join([
        "position:absolute", "margin-left:0", "margin-top:0",
        f"width:{width_pt:.2f}pt", "height:20pt", f"z-index:{n}",
        "mso-position-horizontal:center",
        "mso-position-horizontal-relative:margin",
        "mso-position-vertical:top", "mso-position-vertical-relative:margin",
        f"mso-wrap-distance-bottom:{below_pt:.2f}pt",
        "mso-wrap-distance-top:0", "mso-wrap-distance-left:0",
        "mso-wrap-distance-right:0"]))
    shape.set("stroked", "f")
    shape.set("filled", "f")
    box = ET.SubElement(shape, f"{{{V}}}textbox")
    box.set("style", "mso-fit-shape-to-text:t")
    box.set("inset", "0,0,0,0")
    content = ET.SubElement(box, q("txbxContent"))
    for el in elements:
        content.append(el)
    if elements[-1].tag != q("p"):
        content.append(ET.Element(q("p")))
    wrap = ET.SubElement(shape, f"{{{W10}}}wrap")
    wrap.set("type", "topAndBottom")
    wrap.set("anchorx", "margin")
    wrap.set("anchory", "margin")
    return r


def place_floats(body: ET.Element, floats: list[dict], pdf: Path | None) -> None:
    """Move every top float of the PDF in front of the first paragraph that
    starts on the same PDF page, floated to the top margin."""
    if not floats or pdf is None or not pdf.is_file():
        return
    pages = pdf_words(pdf)
    if not pages:
        return
    plan = float_plan(pages)
    float_ids = {id(e) for f in floats for e in f["elements"]}
    starts = paragraph_pages(body, pages, float_ids)
    for f in floats:
        where = plan.get((f["kind"], f["number"]))
        if where is None or where[1] != "top":
            continue
        anchor = next((p for p in body if starts.get(id(p)) == where[0]), None)
        if anchor is None:
            continue
        for el in f["elements"]:
            body.remove(el)
        blocks = [e for e in f["elements"] if e.tag in (q("p"), q("tbl"))]
        if blocks and blocks[0].tag == q("p"):
            spacing(blocks[0], before=0)
        caps = [e for e in blocks if e.tag == q("p")
                and style_of(e) in ("ImageCaption", "TableCaption")]
        if caps and f["kind"] == "Figure":
            spacing(caps[-1], after=0)
        # the box rides on the first run of the anchor paragraph
        pp = anchor.find(q("pPr"))
        pos = list(anchor).index(pp) + 1 if pp is not None else 0
        anchor.insert(pos, float_box(blocks, FLOAT_SEP / 20, f["number"] + (100 if f["kind"] == "Table" else 0)))


# ---------------------------------------------------------------------------
# references and citations from the PDF's own .bbl (cas-model2-names.bst)
# ---------------------------------------------------------------------------

LATEX_TEXT = [
    ("---", "\u2014"), ("--", "\u2013"), ("``", "\u201c"), ("''", "\u201d"),
    ("`", "\u2018"), ("~", "\u00a0"), ("\\&", "&"), ("\\%", "%"), ("\\_", "_"),
    ("\\$", "$"), ("\\#", "#"), ("\\ ", " "),
]


ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308",
           "~": "\u0303", "=": "\u0304", ".": "\u0307", "c": "\u0327",
           "v": "\u030c", "H": "\u030b", "u": "\u0306", "k": "\u0328"}
LETTERS = {"\\ss": "\u00df", "\\o": "\u00f8", "\\O": "\u00d8", "\\ae": "\u00e6",
           "\\aa": "\u00e5", "\\l": "\u0142"}


def decode_accents(tex: str) -> str:
    r"""\'{e}, \'e, {\'e}, \c{c} -> composed Unicode characters."""
    import unicodedata

    def sub(m: re.Match) -> str:
        base = m.group(2) or m.group(3)
        base = {"\\i": "i", "\\j": "j"}.get(base, base)
        return unicodedata.normalize("NFC", base + ACCENTS[m.group(1)])
    tex = re.sub(r"""\\(['`^"~=.])\s*(?:\{(\\?[A-Za-z])\}|(\\[ij](?![A-Za-z])|[A-Za-z]))""",
                 sub, tex)
    tex = re.sub(r"\\([cvHuk])(?:\s*\{(\\?[A-Za-z])\}|\s+(\\[ij](?![A-Za-z])|[A-Za-z]))",
                 sub, tex)
    for macro, char in LETTERS.items():
        tex = re.sub(re.escape(macro) + r"(?![A-Za-z])\s?", char, tex)
    return tex


def bbl_entries(bbl: str) -> list[dict]:
    """[{key, short, year, long, body}] from a natbib thebibliography."""
    out = []
    bbl = decode_accents(bbl)
    lines = [ln for ln in bbl.splitlines() if not ln.lstrip().startswith("%")]
    text = "\n".join(lines)
    parts = re.split(r"\\bibitem\[", text)[1:]
    for part in parts:
        # [{Short(Year)Long}]{key} body ...
        depth, i = 0, 0
        while i < len(part):
            c = part[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == "]" and depth == 0:
                break
            i += 1
        label = part[:i].strip()
        if label.startswith("{") and label.endswith("}"):
            label = label[1:-1]
        rest = part[i + 1:]
        m = re.match(r"\s*\{([^}]*)\}", rest)
        if not m:
            continue
        key = m.group(1)
        body = rest[m.end():]
        body = body.split("\\end{thebibliography}")[0]
        lm = re.match(r"^(.*)\((.*?)\)(.*)$", label, re.S)
        short, year, long = (lm.group(1), lm.group(2), lm.group(3)) if lm else (label, "", "")
        out.append({"key": key, "short": latex_plain(short), "year": latex_plain(year),
                    "long": latex_plain(long), "body": body.strip()})
    return out


def latex_plain(tex: str) -> str:
    tex = re.sub(r"\\natexlab\{([^}]*)\}", r"\1", tex)
    for a, b in LATEX_TEXT:
        tex = tex.replace(a, b)
    tex = re.sub(r"\\[a-zA-Z]+\*?", "", tex)
    tex = tex.replace("{", "").replace("}", "")
    # collapse layout whitespace only: ~ became a no-break space on purpose
    return re.sub(r"[ \t\r\n]+", " ", tex).strip(" ")


def bbl_runs(body: str) -> list[tuple[str, dict]]:
    """Flatten a bibitem body to (text, {italic, bold, mono, link}) runs."""
    runs: list[tuple[str, dict]] = []
    body = body.replace("\\newblock", " ")
    body = re.sub(r"[ \t\r\n]+", " ", body)

    def emit(t: str, fmt: dict) -> None:
        if not t:
            return
        for a, b in LATEX_TEXT:
            t = t.replace(a, b)
        if runs and runs[-1][1] == fmt:
            runs[-1] = (runs[-1][0] + t, fmt)
        else:
            runs.append((t, dict(fmt)))

    def group(src: str, i: int) -> tuple[str, int]:
        """Content of the {...} group starting at src[i] == '{'."""
        depth, j = 0, i
        while j < len(src):
            if src[j] == "{" and (j == 0 or src[j - 1] != "\\"):
                depth += 1
            elif src[j] == "}" and (j == 0 or src[j - 1] != "\\"):
                depth -= 1
                if depth == 0:
                    return src[i + 1:j], j + 1
            j += 1
        return src[i + 1:], len(src)

    def walk(src: str, fmt: dict) -> None:
        i = 0
        buf = ""
        while i < len(src):
            c = src[i]
            if c == "\\":
                m = re.match(r"\\([a-zA-Z]+)\*?\s*", src[i:])
                if not m:                       # \& \% \_ ...
                    buf += src[i:i + 2]
                    i += 2
                    continue
                name = m.group(1)
                j = i + m.end()
                emit(buf, fmt)
                buf = ""
                if name == "DOIprefix":
                    emit("doi:", fmt)
                    i = j
                    continue
                if name == "URLprefix":
                    emit("URL: ", fmt)
                    i = j
                    continue
                if name in ("doi", "url", "path") and j < len(src) and src[j] == "{":
                    arg, k = group(src, j)
                    target = ("https://doi.org/" + arg) if name == "doi" else arg
                    emit(arg, dict(fmt, mono=True, link=target))
                    i = k
                    continue
                if name == "href" and j < len(src) and src[j] == "{":
                    target, k = group(src, j)
                    if k < len(src) and src[k] == "{":
                        label, k = group(src, k)
                        walk(label, dict(fmt, link=target))
                    i = k
                    continue
                if name == "bibinfo" and j < len(src) and src[j] == "{":
                    _field, k = group(src, j)
                    if k < len(src) and src[k] == "{":
                        val, k = group(src, k)
                        walk(val, fmt)
                    i = k
                    continue
                if name in ("emph", "textit", "textbf", "texttt") and j < len(src) and src[j] == "{":
                    arg, k = group(src, j)
                    style = {"emph": "italic", "textit": "italic",
                             "textbf": "bold", "texttt": "mono"}[name]
                    walk(arg, dict(fmt, **{style: True}))
                    i = k
                    continue
                if name in ("em", "it", "itshape"):
                    fmt = dict(fmt, italic=True)
                    i = j
                    continue
                if name == "natexlab" and j < len(src) and src[j] == "{":
                    arg, k = group(src, j)
                    walk(arg, fmt)
                    i = k
                    continue
                i = j                            # unknown macro: drop it
                continue
            if c == "{":
                emit(buf, fmt)
                buf = ""
                arg, k = group(src, i)
                walk(arg, fmt)
                i = k
                continue
            if c == "$":
                k = src.find("$", i + 1)
                buf += src[i + 1:k if k > 0 else len(src)]
                i = (k + 1) if k > 0 else len(src)
                continue
            if c == "}":
                i += 1
                continue
            buf += c
            i += 1
        emit(buf, fmt)

    walk(body, {})
    # collapse doubled spaces left by \newblock
    out = []
    for t, f in runs:
        t = re.sub(r" {2,}", " ", t)
        if out and out[-1][0].endswith(" ") and t.startswith(" "):
            t = t[1:]
        out.append((t, f))
    if out:
        out[0] = (out[0][0].lstrip(), out[0][1])
    return out


def bib_paragraph(entry: dict, bm_id: int, rels: dict) -> list[ET.Element]:
    p = ET.Element(q("p"))
    ET.SubElement(ET.SubElement(p, q("pPr")), q("pStyle")).set(q("val"), "Bibliography")
    start = ET.SubElement(p, q("bookmarkStart"))
    start.set(q("id"), str(bm_id))
    start.set(q("name"), "ref-" + entry["key"])
    for t, fmt in bbl_runs(entry["body"]):
        r = run(t, font=MONO_SMALL if fmt.get("mono") else None)
        rpr = r.find(q("rPr"))
        if rpr is None:
            rpr = ET.Element(q("rPr"))
            r.insert(0, rpr)
        if fmt.get("italic"):
            ET.SubElement(rpr, q("i"))
        if fmt.get("bold"):
            ET.SubElement(rpr, q("b"))
        if fmt.get("link"):
            st = ET.Element(q("rStyle"))
            st.set(q("val"), "Hyperlink")
            rpr.insert(0, st)
            h = ET.SubElement(p, q("hyperlink"))
            h.set(f"{{{R}}}id", rels["add"](fmt["link"]))
            h.append(r)
        else:
            p.append(r)
    ET.SubElement(p, q("bookmarkEnd")).set(q("id"), str(bm_id))
    return [p]


def fix_bibliography(body: ET.Element, entries: list[dict], rels: dict) -> None:
    """Replace pandoc's citeproc bibliography with the .bbl's entries and
    give it natbib's unnumbered "References" heading."""
    kids = list(body)
    bib = [el for el in kids if el.tag == q("p") and style_of(el) == "Bibliography"]
    if not bib or not entries:
        return
    first = kids.index(bib[0])
    # drop the old entries and the ref-* bookmarks around them
    for el in kids[first:]:
        if el.tag == q("p") and style_of(el) == "Bibliography":
            body.remove(el)
        elif el.tag in (q("bookmarkStart"), q("bookmarkEnd")) and (
                (el.get(q("name")) or "").startswith("ref-") or el.get(q("name")) is None):
            if el.tag == q("bookmarkStart") or el.tag == q("bookmarkEnd"):
                body.remove(el)
    pos = first
    while pos > 0 and list(body)[pos - 1].tag in (q("bookmarkStart"), q("bookmarkEnd")):
        pos -= 1
    prev = list(body)[pos - 1] if pos > 0 else None
    if not (prev is not None and prev.tag == q("p")
            and (style_of(prev) or "").startswith("Heading")
            and text(prev).strip().lower() in ("references", "bibliography")):
        h = ET.Element(q("p"))
        ET.SubElement(ET.SubElement(h, q("pPr")), q("pStyle")).set(q("val"), "Heading1")
        h.append(run("References"))
        body.insert(pos, h)
        pos += 1
    for i, entry in enumerate(entries):
        for el in bib_paragraph(entry, 90000 + i, rels):
            body.insert(pos, el)
            pos += 1


def fix_citations(body: ET.Element, entries: list[dict],
                  short_citations: bool = False) -> None:
    """natbib with longnamesfirst: the first citation of a work lists every
    author (the label's long form), later ones the short form. With
    ``short_citations`` (biblio style cas-model2-names-etal), every citation
    keeps the short label, as the PDF does."""
    by_key = {e["key"]: e for e in entries}
    seen: set[str] = set()
    for h in body.iter(q("hyperlink")):
        anchor = h.get(q("anchor")) or ""
        if not anchor.startswith("ref-") or anchor[4:] not in by_key:
            continue
        e = by_key[anchor[4:]]
        old = text(h)
        names = e["short"] if short_citations else (
            e["long"] if (e["long"] and e["key"] not in seen) else e["short"])
        seen.add(e["key"])
        if re.fullmatch(r"\d{4}[a-z]?", old.strip()):
            new = e["year"]                                   # [-@key]
        elif re.search(r"\(\s*\d{4}[a-z]?\s*\)\s*$", old) or (
                not e["year"] and not old.endswith(e["short"])):
            new = f"{names} ({e['year']})" if e["year"] else names   # @key
        else:
            new = f"{names}, {e['year']}" if e["year"] else names   # [@key]
        ts = list(h.iter(q("t")))
        if not ts:
            continue
        ts[0].text = new
        for t in ts[1:]:
            t.text = ""


def fix_data_table(tbl: ET.Element) -> None:
    rows = tbl.findall(q("tr"))
    ncols = max((len(r.findall(q("tc"))) for r in rows), default=1)
    inner = (FLOAT_WIDTH - 2 * TABCOLSEP * (ncols - 1)) // ncols
    widths = [inner + (TABCOLSEP if i in (0, ncols - 1) else 2 * TABCOLSEP)
              for i in range(ncols)]
    if ncols == 1:
        widths = [FLOAT_WIDTH]
    widths[-1] += FLOAT_WIDTH - sum(widths)
    tbl_props(tbl, FLOAT_WIDTH, "center",
              {"top": RULE_HEAVY, "bottom": RULE_HEAVY}, (0, 0, 0, 0))
    set_grid(tbl, widths)
    for ri, tr in enumerate(rows):
        is_head = tr.find(q("trPr") + "/" + q("tblHeader")) is not None
        for ci, tc in enumerate(tr.findall(q("tc"))):
            pr = cell_props(tc)
            for tag in ("tcW", "tcMar", "tcBorders"):
                remove_child(pr, tag)
            ET.SubElement(pr, q("tcW")).attrib.update({q("w"): str(widths[min(ci, ncols - 1)]), q("type"): "dxa"})
            mar = ET.SubElement(pr, q("tcMar"))
            left = 0 if ci == 0 else TABCOLSEP
            right = 0 if ci == ncols - 1 else TABCOLSEP
            for edge, v in (("top", ROW_PAD if ri == 0 or is_head else 0),
                            ("left", left), ("bottom", ROW_PAD if is_head else 0),
                            ("right", right)):
                ET.SubElement(mar, q(edge)).attrib.update({q("w"): str(v), q("type"): "dxa"})
            if is_head:
                bd = ET.SubElement(pr, q("tcBorders"))
                border(bd, "bottom", RULE_LIGHT)
            for p in tc.findall(q("p")):
                set_style(p, "TableText")
                pp = ppr(p)
                remove_child(pp, "jc")
                set_attr_child(pp, "jc", val="left")
                spacing(p, before=0, after=0)
        if ri == len(rows) - 1:
            for tc in tr.findall(q("tc")):
                pr = cell_props(tc)
                mar = child(pr, "tcMar")
                if mar is not None:
                    mar.find(q("bottom")).set(q("w"), str(ROW_PAD))


EQ_NUM = re.compile(r"^\((\d+)\)$")


def fix_equations(body: ET.Element) -> None:
    for p in list(body.iter(q("p"))):
        para = p.find(q("oMathPara", M))
        if para is None:
            continue
        omaths = para.findall(q("oMath", M))
        if len(omaths) != 1:
            continue
        omath = omaths[0]
        # trailing "(n)" as math runs, possibly after a space run
        runs = list(omath)
        tail = []
        while runs and runs[-1].tag == q("r", M) and len(tail) < 6:
            tail.insert(0, runs.pop())
            label = "".join(t.text or "" for r in tail for t in r.iter(q("t", M))).strip()
            if EQ_NUM.match(label):
                break
        label = "".join(t.text or "" for r in tail for t in r.iter(q("t", M))).strip()
        number = None
        if EQ_NUM.match(label):
            number = label
            for r in tail:
                omath.remove(r)
            # drop the space run that separated the number
            while len(omath) and omath[-1].tag == q("r", M) and \
                    "".join(t.text or "" for t in omath[-1].iter(q("t", M))).strip() == "":
                omath.remove(omath[-1])
        idx = list(p).index(para)
        p.remove(para)
        set_style(p, "DisplayMath")
        pp = ppr(p)
        remove_child(pp, "ind")
        set_attr_child(pp, "ind", firstLine=0)
        tabs = ensure(pp, "tabs")
        for c in list(tabs):
            tabs.remove(c)
        ET.SubElement(tabs, q("tab")).attrib.update({q("val"): "center", q("pos"): str(TEXT_WIDTH // 2)})
        ET.SubElement(tabs, q("tab")).attrib.update({q("val"): "right", q("pos"): str(TEXT_WIDTH)})
        spacing(p, before=EQ_ABOVE, after=EQ_BELOW, line=240, lineRule="auto")
        tab1 = ET.Element(q("r"))
        ET.SubElement(tab1, q("tab"))
        new = [tab1, omath]
        if number:
            tab2 = ET.Element(q("r"))
            ET.SubElement(tab2, q("tab"))
            new += [tab2, run(number)]
        for k, el in enumerate(new):
            p.insert(idx + k, el)


def fix_footnotes(doc: ET.Element, notes: ET.Element) -> None:
    marks: dict[str, str] = {}
    for fn in notes.findall(q("footnote")):
        fid = fn.get(q("id"))
        ftype = fn.get(q("type"))
        if ftype in ("separator", "continuationSeparator"):
            for c in list(fn):
                fn.remove(c)
            p = ET.SubElement(fn, q("p"))
            pp = ET.SubElement(p, q("pPr"))
            ET.SubElement(pp, q("spacing")).attrib.update(
                {q("before"): "0", q("after"): str(tw(2.6)), q("line"): "20",
                 q("lineRule"): "exact"})
            bd = ET.SubElement(pp, q("pBdr"))
            border(bd, "top", RULE_CAS)
            ET.SubElement(pp, q("ind")).set(q("right"), str(TEXT_WIDTH - round(0.4 * TEXT_WIDTH)))
            continue
        # typewriter at 8 pt (\ttfamily\footnotesize)
        for r in fn.iter(q("r")):
            rpr = r.find(q("rPr"))
            st = rpr.find(q("rStyle")) if rpr is not None else None
            if st is not None and st.get(q("val")) == "VerbatimChar":
                rf = ensure(rpr, "rFonts")
                for a in ("ascii", "hAnsi", "cs"):
                    rf.set(q(a), MONO_SMALL)
                set_attr_child(rpr, "sz", val=16)
        ts = list(fn.iter(q("t")))
        sentinel = next((t for t in ts if t.text and MARK_OPEN in t.text), None)
        if sentinel is None:
            continue
        m = re.search(f"{MARK_OPEN}(.*?){MARK_CLOSE}", sentinel.text)
        if not m:
            continue
        marks[fid] = m.group(1)
        sentinel.text = sentinel.text.replace(m.group(0), "")
        # replace the automatic mark inside the note
        for r in list(fn.iter(q("r"))):
            if r.find(q("footnoteRef")) is not None:
                for c in list(r):
                    if c.tag == q("footnoteRef"):
                        r.remove(c)
                if m.group(1):
                    t = ET.SubElement(r, q("t"))
                    t.text = m.group(1)
        # drop the space pandoc puts after the mark when there is no mark
        if not m.group(1):
            for t in ts:
                if t.text == " ":
                    t.text = ""
                    break
    if not marks:
        return
    for parent in doc.iter():
        for idx, r in enumerate(list(parent)):
            if r.tag != q("r"):
                continue
            ref = r.find(q("footnoteReference"))
            if ref is None or ref.get(q("id")) not in marks:
                continue
            ref.set(q("customMarkFollows"), "1")
            # an empty custom mark makes Word take the following text as the
            # mark; an unmarked note gets a zero-width space instead
            t = ET.SubElement(r, q("t"))
            t.text = marks[ref.get(q("id"))] or "​"


def insert_after(parent: ET.Element, el: ET.Element, after: tuple[str, ...]) -> None:
    """Insert el after the last child whose tag is in `after` (CT_Settings is
    a strict sequence: Word rejects misplaced elements)."""
    pos = 0
    for i, c in enumerate(list(parent)):
        if c.tag in after:
            pos = i + 1
    parent.insert(pos, el)


def fix_settings(settings: ET.Element) -> None:
    for tag in ("autoHyphenation", "compat"):
        for old in settings.findall(q(tag)):
            settings.remove(old)
    for old in settings.findall(q("mathPr", M)):
        settings.remove(old)
    # Line breaking closest to TeX's, measured with paper_parity.py on c26:
    # WordPerfect-style justification shrinks interword spaces the way TeX's
    # glue does (identical lines 30 % -> 47 %); Word's own hyphenation then
    # only adds breaks TeX avoids, so it stays off.
    hyph = ET.Element(q("autoHyphenation"))
    hyph.set(q("val"), "false")
    insert_after(settings, hyph, tuple(q(t) for t in (
        "zoom", "embedSystemFonts", "proofState", "stylePaneFormatFilter",
        "doNotTrackMoves", "defaultTabStop")))
    # the custom separators in footnotes.xml are used only when referenced
    for old in settings.findall(q("footnotePr")):
        settings.remove(old)
    fpr = ET.Element(q("footnotePr"))
    for fid in ("-1", "0"):
        ET.SubElement(fpr, q("footnote")).set(q("id"), fid)
    insert_after(settings, fpr, tuple(q(t) for t in (
        "zoom", "defaultTabStop", "autoHyphenation",
        "drawingGridHorizontalSpacing", "drawingGridVerticalSpacing",
        "displayHorizontalDrawingGridEvery", "displayVerticalDrawingGridEvery",
        "characterSpacingControl", "savePreviewPicture")))
    compat = ET.Element(q("compat"))
    ET.SubElement(compat, q("wpJustification"))
    insert_after(settings, compat, tuple(q(t) for t in (
        "zoom", "defaultTabStop", "autoHyphenation",
        "drawingGridHorizontalSpacing", "drawingGridVerticalSpacing",
        "displayHorizontalDrawingGridEvery", "displayVerticalDrawingGridEvery",
        "characterSpacingControl", "savePreviewPicture", "footnotePr")))
    math_pr = ET.Element(q("mathPr", M))
    font = ET.SubElement(math_pr, q("mathFont", M))
    font.set(q("val", M), MATH_FONT)
    insert_after(settings, math_pr, tuple(q(t) for t in (
        "zoom", "defaultTabStop", "characterSpacingControl",
        "savePreviewPicture", "compat", "docVars", "rsids")))


# ---------------------------------------------------------------------------
# schema order: Word rejects properties out of their xsd:sequence
# ---------------------------------------------------------------------------

ORDER = {
    "pPr": ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
            "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd",
            "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
            "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN",
            "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
            "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
            "textDirection", "textAlignment", "textboxTightWrap",
            "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"],
    "rPr": ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
            "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
            "noProof", "snapToGrid", "vanish", "webHidden", "color",
            "spacing", "w", "kern", "position", "sz", "szCs", "highlight",
            "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs",
            "em", "lang", "eastAsianLayout", "specVanish", "oMath"],
    "tcPr": ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders",
             "shd", "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign",
             "hideMark"],
    "tblPr": ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual",
              "tblStyleRowBandSize", "tblStyleColBandSize", "tblW", "jc",
              "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout",
              "tblCellMar", "tblLook"],
    "trPr": ["cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore",
             "wAfter", "cantSplit", "trHeight", "tblHeader", "tblCellSpacing",
             "jc", "hidden"],
    "sectPr": ["headerReference", "footerReference", "footnotePr",
               "endnotePr", "type", "pgSz", "pgMar", "paperSrc", "pgBorders",
               "lnNumType", "pgNumType", "cols", "formProt", "vAlign",
               "noEndnote", "titlePg", "textDirection", "bidi", "rtlGutter",
               "docGrid", "printerSettings"],
    "lvl": ["start", "numFmt", "lvlRestart", "pStyle", "isLgl", "suff",
            "lvlText", "lvlPicBulletId", "legacy", "lvlJc", "pPr", "rPr"],
    "pBdr": ["top", "left", "bottom", "right", "between", "bar"],
    "tblBorders": ["top", "left", "bottom", "right", "insideH", "insideV"],
    "tcBorders": ["top", "left", "bottom", "right", "insideH", "insideV",
                  "tl2br", "tr2bl"],
    "tcMar": ["top", "left", "bottom", "right"],
    "tblCellMar": ["top", "left", "bottom", "right"],
}
ORDER_Q = {q(k): {q(t): i for i, t in enumerate(v)} for k, v in ORDER.items()}


def normalize(root: ET.Element) -> None:
    for el in root.iter():
        rank = ORDER_Q.get(el.tag)
        if rank is None:
            continue
        kids = list(el)
        ordered = sorted(kids, key=lambda c: rank.get(c.tag, len(rank)))
        if ordered != kids:
            for c in kids:
                el.remove(c)
            el.extend(ordered)


def read_bbl(latex_zip: Path | None) -> str:
    if latex_zip is None or not latex_zip.is_file():
        return ""
    with zipfile.ZipFile(latex_zip) as z:
        names = [n for n in z.namelist() if n.endswith(".bbl")]
        return z.read(names[0]).decode("utf-8", "replace") if names else ""


def process(docx: Path, pdf: Path | None = None,
            latex_zip: Path | None = None,
            short_citations: bool = False) -> None:
    src = zipfile.ZipFile(docx)
    parts = {n: src.read(n) for n in src.namelist()}
    infos = {i.filename: i for i in src.infolist()}
    src.close()
    for name in ("word/document.xml", "word/footnotes.xml",
                 "word/numbering.xml", "word/settings.xml"):
        if name in parts:
            register_namespaces(parts[name])
    ET.register_namespace("m", M)
    ET.register_namespace("v", V)
    ET.register_namespace("o", O)
    ET.register_namespace("w10", W10)
    doc = ET.fromstring(parts["word/document.xml"])
    body = doc.find(q("body"))
    fix_section_break(body)
    box = fix_info_box(body)
    fix_headings(body, box)
    fix_highlights(body)
    fix_lists(body)
    entries = bbl_entries(read_bbl(latex_zip))
    rels_xml = ET.fromstring(parts["word/_rels/document.xml.rels"])
    counter = [0]

    def add_rel(target: str) -> str:
        counter[0] += 1
        rid = f"rIdCasBib{counter[0]}"
        rel = ET.SubElement(rels_xml, f"{{{PR}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink")
        rel.set("Target", target)
        rel.set("TargetMode", "External")
        return rid

    if entries:
        fix_citations(body, entries, short_citations)
        fix_bibliography(body, entries, {"add": add_rel})
    floats = fix_figures_and_tables(body)
    place_floats(body, floats, pdf)
    fix_equations(body)
    out: dict[str, bytes] = {}
    if "word/footnotes.xml" in parts:
        notes = ET.fromstring(parts["word/footnotes.xml"])
        fix_footnotes(doc, notes)
        normalize(notes)
        out["word/footnotes.xml"] = ET.tostring(notes, encoding="UTF-8", xml_declaration=True)
    if "word/numbering.xml" in parts:
        numbering = ET.fromstring(parts["word/numbering.xml"])
        fix_numbering(numbering)
        normalize(numbering)
        out["word/numbering.xml"] = ET.tostring(numbering, encoding="UTF-8", xml_declaration=True)
    if "word/settings.xml" in parts:
        settings = ET.fromstring(parts["word/settings.xml"])
        fix_settings(settings)
        out["word/settings.xml"] = ET.tostring(settings, encoding="UTF-8", xml_declaration=True)
    ET.register_namespace("", PR)
    out["word/_rels/document.xml.rels"] = ET.tostring(rels_xml, encoding="UTF-8", xml_declaration=True)
    normalize(doc)
    out["word/document.xml"] = ET.tostring(doc, encoding="UTF-8", xml_declaration=True)
    tmp = docx.with_suffix(".post.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(infos[name], out.get(name, data))
    tmp.replace(docx)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docx", type=Path)
    ap.add_argument("--pdf", type=Path, default=None,
                    help="the paper's rendered PDF: top floats go to its pages")
    ap.add_argument("--latex-zip", type=Path, default=None,
                    help="the submission zip: references/citations from its .bbl")
    ap.add_argument("--short-citations", action="store_true",
                    help="cas-model2-names-etal: every citation in short form")
    args = ap.parse_args()
    process(args.docx, args.pdf, args.latex_zip, args.short_citations)
    print(f"cas layout applied to {args.docx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

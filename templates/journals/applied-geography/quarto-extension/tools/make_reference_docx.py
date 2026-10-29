#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""make_reference_docx.py — build the DOCX reference document for elsevier-cas.

The reference doc carries everything pandoc/docx inherits for our papers:

  * fonts: STIX (same family as cas-sc.cls), fallback Times New Roman
    (declared as w:altName for machines without STIX);
  * page geometry copied from cas-sc: 10885 x 14854 twips (544.25 x 742.68 pt
    sample box), 777 twip side margins (38.8 pt), header/footer positions from
    cas-sc-sample.pdf;
  * paragraph styles for the CAS front matter (Title, Author, Affiliation,
    AbstractTitle/Abstract with the ARTICLE INFO rules, Keywords, Highlights),
    body (justified 10 pt, 15 pt first-line indent), headings, captions,
    footnotes, bibliography;
  * running header (paper short title, blank on page 1) and footer
    ("<First author> et al.: Preprint submitted to Elsevier | Page X of Y").

It starts from pandoc's own default reference.docx (so every style pandoc
looks for exists), then patches styles.xml/fontTable.xml, appends header and
footer parts, and rewrites the sectPr of document.xml.

Stdlib only. Typical use (paper_build.py does this for you):

    python tools/make_reference_docx.py \
        --short-title "Subseasonal temperature forecasting in Andean stations" \
        --first-author "Moisés Evangelista Gamarra" \
        --output ../../../../papers/c20-2026/paper/_reference-doc.docx
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML = "http://www.w3.org/XML/1998/namespace"

# ---------------------------------------------------------------------------
# Geometry — measured on tests/specimen/reference/cas-sc-sample.pdf
# (72 dpi raster = 1 px = 1 pt; word boxes via pdftotext -bbox)
# ---------------------------------------------------------------------------
PAGE_W = 10885          # 544.252 pt
PAGE_H = 14854          # 742.677 pt
MARGIN_LR = 777         # 38.835 pt left/right
# Word puts the baseline of an "exact" line at 80 % of its height; the
# vertical values below place every baseline on the PDF's (ink baselines of
# the rendered CAS PDF, measured by scripts/paper_parity.py's tooling).
MARGIN_TOP = 1081       # first body baseline at y = 63.6 pt (54.04 + 0.8 * 11.955)
MARGIN_BOTTOM = 1054    # body ends at y = 690 pt (742.677 - 52.677)
HEADER_DIST = 657       # running-head baseline at y = 41.6 pt
FOOTER_DIST = 564       # footer baseline at y = 712.4 pt
TEXT_WIDTH = PAGE_W - 2 * MARGIN_LR  # 9331 twips (right tab stop for footer)

FONT = "STIX"
FONT_ALT = "Times New Roman"
# The PDF's sans and typewriter faces are cm-super (SFSS0900, SFSX0900,
# SFTT0800); Latin Modern has the same metrics (scripts/install_stix_fonts.ps1).
SANS = "LM Sans 9"           # sans small: tables, captions, running heads
SANS_BOLD = "LM Sans 10"     # LM Sans 9 has no bold face (SFSX0900)
MONO = "LM Mono 10"          # typewriter at 10 pt
MONO_SMALL = "LM Mono 8"     # typewriter in footnotes and references (SFTT0800)
MATH = "STIX Math"
HYPERLINK_COLOR = "2F4F4F"   # xcolor DarkSlateGrey == cas-sc.cls hscolor


def bp(points: float) -> int:
    """PostScript points (what the PDF measures) -> twips."""
    return round(points * 20)


def tw(tex_pt: float) -> int:
    """TeX points (1/72.27 in) -> twips (1/1440 in). The PDF is laid out in
    TeX points; Word works in PostScript points, 0.4 % larger."""
    return round(tex_pt * 72 / 72.27 * 20)


# Baselineskips of cas-sc at 10 pt (TeX pt): the PDF's line pitch per size.
BLS_NORMAL = tw(12)        # normalsize 10/12
BLS_SMALL = tw(11)         # small 9/11 (tables, captions)
BLS_FOOTNOTE = tw(9.5)     # footnotesize 8/9.5 (abstract, keywords, notes)
BLS_BIB = tw(10)           # references: 8 pt on a 10 pt baselineskip

# style id -> (kind, params); kind: "patch rPr/pPr of an existing style",
# "new": create the style.
PPR_ORDER = [
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
    "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs",
    "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct",
    "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
    "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
    "suppressOverlap", "jc", "textDirection", "textAlignment",
    "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr",
    "pPrChange",
]
RPR_ORDER = [
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike",
    "dstrike", "outline", "shadow", "emboss", "imprint", "noProof",
    "snapToGrid", "vanish", "webHidden", "color", "spacing", "w", "kern",
    "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd",
    "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
    "specVanish", "oMath",
]


def q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _ordered_insert(parent: ET.Element, el: ET.Element, order: list[str]) -> None:
    name = el.tag.split("}")[-1]
    idx = order.index(name)
    for i, child in enumerate(list(parent)):
        cname = child.tag.split("}")[-1]
        if cname in order and order.index(cname) > idx:
            parent.insert(i, el)
            return
    parent.append(el)


def set_child(parent: ET.Element, tag: str, order: list[str], **attrs) -> ET.Element:
    for child in list(parent):
        if child.tag == q(tag):
            parent.remove(child)
    el = ET.Element(q(tag))
    for k, v in attrs.items():
        el.set(q(k), str(v))
    _ordered_insert(parent, el, order)
    return el


def get_or_add(parent: ET.Element, tag: str, order: list[str]) -> ET.Element:
    for child in parent:
        if child.tag == q(tag):
            return child
    el = ET.Element(q(tag))
    _ordered_insert(parent, el, order)
    return el


def ensure_rpr(style: ET.Element) -> ET.Element:
    rpr = style.find(q("rPr"))
    if rpr is None:
        rpr = ET.Element(q("rPr"))
        # rPr must come after pPr in a style
        ppr = style.find(q("pPr"))
        if ppr is not None:
            style.insert(list(style).index(ppr) + 1, rpr)
        else:
            style.append(rpr)
    return rpr


def ensure_ppr(style: ET.Element) -> ET.Element:
    """pPr goes after name/basedOn/next/.../qFormat and before rPr."""
    ppr = style.find(q("pPr"))
    if ppr is None:
        ppr = ET.Element(q("pPr"))
        rpr = style.find(q("rPr"))
        if rpr is not None:
            style.insert(list(style).index(rpr), ppr)
        else:
            style.append(ppr)
    return ppr


def style_font(rpr: ET.Element, font: str = FONT, sz: int | None = None,
               bold: bool | None = None, italic: bool | None = None,
               color: str | None = None, underline_none: bool = False,
               char_spacing: int | None = None, caps: bool | None = None) -> None:
    rf = set_child(rpr, "rFonts", RPR_ORDER, ascii=font, hAnsi=font,
                   eastAsia=font, cs=font)
    for a in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        rf.attrib.pop(q(a), None)
    if bold is not None:
        set_child(rpr, "b", RPR_ORDER, val="1" if bold else "0")
    if italic is not None:
        set_child(rpr, "i", RPR_ORDER, val="1" if italic else "0")
    if caps:
        set_child(rpr, "caps", RPR_ORDER, val="1")
    if char_spacing is not None:
        set_child(rpr, "spacing", RPR_ORDER, val=str(char_spacing))
    if color is not None:
        set_child(rpr, "color", RPR_ORDER, val=color)
    if sz is not None:
        set_child(rpr, "sz", RPR_ORDER, val=str(sz))
        set_child(rpr, "szCs", RPR_ORDER, val=str(sz))
    if underline_none:
        set_child(rpr, "u", RPR_ORDER, val="none")


def style_para(ppr: ET.Element, before: int | None = None, after: int | None = None,
               line: int | None = None, jc: str | None = None,
               first_line: int | None = None, hanging: int | None = None,
               keep_next: bool = False, outline: int | None = None,
               border: tuple[str, ...] | None = None,
               tabs_right: int | None = None, left: int | None = None,
               exact: int | None = None, right: int | None = None,
               widow: bool | None = None) -> None:
    if keep_next:
        set_child(ppr, "keepNext", PPR_ORDER, val="1")
    if widow is not None:
        set_child(ppr, "widowControl", PPR_ORDER, val="1" if widow else "0")
    if border:
        # border = ("top bottom", space) -> edges given, in twips of space
        edges, space = border
        pbdr = get_or_add(ppr, "pBdr", PPR_ORDER)
        for edge in ("top", "left", "bottom", "right"):
            for child in list(pbdr):
                if child.tag == q(edge):
                    pbdr.remove(child)
            if edge in edges.split():
                el = ET.SubElement(pbdr, q(edge))
                el.set(q("val"), "single")
                el.set(q("sz"), "2")       # 1/4 pt: the CAS 0.2 pt rules
                el.set(q("space"), str(space))
                el.set(q("color"), "auto")
    if tabs_right is not None:
        tabs = get_or_add(ppr, "tabs", PPR_ORDER)
        for child in list(tabs):
            tabs.remove(child)
        tab = ET.SubElement(tabs, q("tab"))
        tab.set(q("val"), "right")
        tab.set(q("pos"), str(tabs_right))
    spacing_attrs: dict[str, str] = {}
    if before is not None:
        spacing_attrs["before"] = str(before)
    if after is not None:
        spacing_attrs["after"] = str(after)
    if line is not None:
        spacing_attrs["line"] = str(line)
        spacing_attrs["lineRule"] = "auto"
    if exact is not None:
        # TeX keeps a fixed aselineskip; Word's "auto" spacing would use the
        # font's (large) STIX line gap instead.
        spacing_attrs["line"] = str(exact)
        spacing_attrs["lineRule"] = "exact"
    if spacing_attrs:
        set_child(ppr, "spacing", PPR_ORDER, **spacing_attrs)
    ind_attrs: dict[str, str] = {}
    if first_line is not None:
        ind_attrs["firstLine"] = str(first_line)
    if hanging is not None:
        ind_attrs["hanging"] = str(hanging)
        ind_attrs.setdefault("left", str(hanging))
    if left is not None:
        ind_attrs["left"] = str(left)
    if right is not None:
        ind_attrs["right"] = str(right)
    if ind_attrs:
        set_child(ppr, "ind", PPR_ORDER, **ind_attrs)
    if jc is not None:
        set_child(ppr, "jc", PPR_ORDER, val=jc)
    if outline is not None:
        set_child(ppr, "outlineLvl", PPR_ORDER, val=str(outline))


def make_style(style_id: str, name: str, based_on: str = "Normal",
               next_style: str | None = None) -> ET.Element:
    st = ET.Element(q("style"))
    st.set(q("type"), "paragraph")
    st.set(q("styleId"), style_id)
    n = ET.SubElement(st, q("name"))
    n.set(q("val"), name)
    b = ET.SubElement(st, q("basedOn"))
    b.set(q("val"), based_on)
    if next_style:
        nx = ET.SubElement(st, q("next"))
        nx.set(q("val"), next_style)
    qf = ET.SubElement(st, q("qFormat"))
    return st


def patch_styles(xml_bytes: bytes) -> bytes:
    ET.register_namespace("w", W)
    root = ET.fromstring(xml_bytes)

    # --- docDefaults: STIX everywhere, 10 pt, no paragraph gap -------------
    # Every vertical value below is measured on the rendered CAS PDF (word
    # boxes and rules, scripts/paper_parity.py) and expressed in twips; tw()
    # converts the TeX points of cas-common.sty.
    doc_defaults = root.find(q("docDefaults"))
    rpr_default = doc_defaults.find(q("rPrDefault"))
    rpr = rpr_default.find(q("rPr"))
    style_font(rpr, sz=20)
    set_child(rpr, "lang", RPR_ORDER, val="en-US")
    ppr_default = doc_defaults.find(q("pPrDefault"))
    ppr = ppr_default.find(q("pPr"))
    style_para(ppr, after=0, exact=BLS_NORMAL)

    def get(style_id: str) -> ET.Element | None:
        for st in root.findall(q("style")):
            if st.get(q("styleId")) == style_id:
                return st
        return None

    def patch(style_id: str, *, font: str = FONT, sz: int | None = None,
              bold: bool | None = None, italic: bool | None = None,
              color: str | None = None, underline_none: bool = False,
              char_spacing: int | None = None, caps: bool | None = None,
              name: str | None = None, based_on: str = "Normal",
              **pkwargs) -> None:
        st = get(style_id)
        if st is None:
            if name is None:
                return
            st = make_style(style_id, name, based_on=based_on)
            root.append(st)
        style_font(ensure_rpr(st), font=font, sz=sz, bold=bold,
                   italic=italic, color=color, underline_none=underline_none,
                   char_spacing=char_spacing, caps=caps)
        if pkwargs:
            style_para(ensure_ppr(st), **pkwargs)

    # --- body ---------------------------------------------------------------
    patch("Normal", jc="both", after=0, exact=BLS_NORMAL)
    patch("BodyText", first_line=300, after=0)        # parindent 15 pt
    patch("FirstParagraph", first_line=300, after=0)  # cas indents it too
    patch("Compact", after=0, exact=BLS_NORMAL)
    patch("BlockText", sz=20)
    patch("Definition", sz=20)
    patch("DefinitionTerm", sz=20)
    # display math: bovedisplayskip 10 pt around a centred equation whose
    # number sits at the right margin (tab stops set by cas_docx_post.py)
    patch("DisplayMath", name="Display Math", sz=20, before=tw(6), after=tw(6),
          jc="left", exact=None)

    # --- highlights page (cas-sc prints it before the title page) -----------
    # pandoc resolves custom-style by style *name*: names below equal ids.
    patch("HighlightsTitle", name="HighlightsTitle", sz=28, color="000000",
          before=0, after=0, exact=tw(17), jc="left", keep_next=True)
    patch("HighlightsPaperTitle", name="HighlightsPaperTitle", sz=24,
          bold=True, before=bp(11.06), after=0, exact=BLS_NORMAL, jc="both",
          keep_next=True)
    patch("HighlightsAuthors", name="HighlightsAuthors", sz=20,
          before=bp(5.84), after=0, exact=BLS_NORMAL, jc="left", keep_next=True)
    patch("Highlight", name="Highlight", sz=20, before=tw(8), after=0,
          exact=BLS_NORMAL, left=498, hanging=204, jc="left")

    # --- title page ---------------------------------------------------------
    patch("Title", sz=34, color="000000", jc="left", before=0, after=0,
          exact=tw(22))                                    # LARGE 17.28/22
    # the PDF's title baseline sits above where the top margin lets Word put
    # it: raise the glyphs (layout unchanged) by 6.5 pt
    set_child(ensure_rpr(get("Title")), "position", RPR_ORDER, val="13")
    patch("Subtitle", sz=24, italic=True, jc="left", after=120)
    patch("Author", sz=24, jc="left", before=bp(4.04), after=0, exact=tw(14))
    patch("Date", sz=20, jc="left", after=120)
    patch("Affiliation", name="Affiliation", sz=16, italic=True, jc="left",
          before=bp(10.99), after=bp(10.06), exact=BLS_FOOTNOTE)
    # ARTICLE INFO | ABSTRACT box: a borderless two-column table built by
    # cas-docx.lua; labels are letter-spaced caps over a 0.2 pt rule.
    patch("AbstractTitle", sz=20, color="000000", char_spacing=30, before=0,
          after=0, exact=tw(13), jc="left", keep_next=True,
          border=("bottom", 5))
    patch("Abstract", sz=16, before=0, after=0, jc="both", exact=BLS_FOOTNOTE)
    patch("Keywords", name="Keywords", sz=16, before=0, after=0, jc="left",
          exact=BLS_FOOTNOTE)

    # --- headings (cas-common.sty: section 12/14 bold, subsection 11/13) -----
    patch("Heading1", sz=24, bold=True, color="000000", before=bp(17.45),
          after=bp(3.45), exact=tw(14), jc="left", keep_next=True, outline=0)
    patch("Heading2", sz=22, bold=True, color="000000", before=bp(10.1),
          after=0, exact=tw(13), jc="left", keep_next=True, outline=1)
    patch("Heading3", sz=21, bold=True, color="000000", before=bp(10.1),
          after=0, exact=tw(12), jc="left", keep_next=True, outline=2)
    for lvl in range(4, 10):
        patch(f"Heading{lvl}", sz=20, bold=True, color="000000")
    patch("SectionNumber", sz=24, bold=True, color="000000")

    # --- floats: sffamily small (cm-super sans 9/11) -------------------------
    patch("TableCaption", font=SANS, sz=18, italic=False, before=tw(6), after=tw(6),
          exact=BLS_SMALL, jc="left", keep_next=True)
    patch("ImageCaption", font=SANS, sz=18, italic=False, before=tw(6), after=0,
          exact=BLS_SMALL, jc="both")
    patch("Caption", font=SANS, sz=18, italic=False, before=tw(6), after=0,
          exact=BLS_SMALL, jc="both")
    patch("TableText", name="Table Text", font=SANS, sz=18, before=0,
          after=0, exact=BLS_SMALL, jc="left")
    patch("FigureParagraph", name="Figure", sz=20, before=0, after=0,
          jc="center", line=240)
    # Word does not kern unless asked; TeX applies the font's kerns
    set_child(rpr, "kern", RPR_ORDER, val="2")

    # --- notes / bibliography / links ---------------------------------------
    patch("FootnoteText", sz=16, after=0, exact=BLS_FOOTNOTE, jc="both",
          first_line=tw(14.3))
    patch("FootnoteReference", sz=16)
    patch("Bibliography", sz=16, hanging=tw(10), before=0, after=0,
          exact=BLS_BIB, jc="both")
    patch("VerbatimChar", font=MONO, sz=20)
    patch("Hyperlink", color=HYPERLINK_COLOR, underline_none=True)
    patch("TOCHeading", sz=24, bold=True)

    # --- running heads (sans 9, footer over a full-width 0.2 pt rule) -------
    patch("Header", name="Header", font=SANS, sz=18, before=0, after=0,
          exact=BLS_SMALL, jc="center")
    patch("Footer", name="Footer", font=SANS, sz=18, before=0, after=0,
          exact=BLS_SMALL, jc="left", tabs_right=TEXT_WIDTH,
          border=("top", 3))

    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def patch_font_table(xml_bytes: bytes) -> bytes:
    """Declare STIX with Times New Roman as the substitution name (Q10b)."""
    ET.register_namespace("w", W)
    root = ET.fromstring(xml_bytes)
    target = None
    for font in root.findall(q("font")):
        if font.get(q("name")) == FONT:
            target = font
            break
    if target is None:
        target = ET.SubElement(root, q("font"))
        target.set(q("name"), FONT)
    for child in list(target):
        if child.tag in (q("altName"), q("family")):
            target.remove(child)
    alt = ET.SubElement(target, q("altName"))
    alt.set(q("val"), FONT_ALT)
    fam = ET.SubElement(target, q("family"))
    fam.set(q("val"), "roman")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# header / footer parts
# ---------------------------------------------------------------------------

XMLDECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
W_NS = 'xmlns:w="%s" xmlns:r="%s"' % (W, R)


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def header_xml(short_title: str) -> str:
    return (
        XMLDECL
        + f'<w:hdr {W_NS}>'
        + '<w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr>'
        + f'<w:r><w:t xml:space="preserve">{xml_escape(short_title)}</w:t></w:r>'
        + "</w:p></w:hdr>"
    )


def empty_header_xml() -> str:
    # title page: cas-sc prints no running head on the first article page
    return XMLDECL + f'<w:hdr {W_NS}><w:p/></w:hdr>'


def footer_xml(first_author: str) -> str:
    """cas-sc footer: "<author> et al.:" in sans, "Preprint submitted to
    Elsevier" in italic roman, "Page X of Y" flush right in sans. The page
    count is the section's: the highlights page before it is unnumbered.
    An empty first_author drops the "<author> et al.:" run, as the class does
    in its blind modes."""
    def fld(instr: str) -> str:
        return (f'<w:fldSimple w:instr=" {instr} "><w:r><w:t>1</w:t></w:r>'
                '</w:fldSimple>')
    roman_it = (f'<w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" '
                f'w:cs="{FONT}"/><w:i/></w:rPr>')
    author_run = (f'<w:r><w:t xml:space="preserve">{xml_escape(first_author)} et al.: </w:t></w:r>'
                  if first_author else "")
    return (
        XMLDECL
        + f'<w:ftr {W_NS}>'
        + '<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
        + author_run
        + f'<w:r>{roman_it}<w:t>Preprint submitted to Elsevier</w:t></w:r>'
        + "<w:r><w:tab/></w:r>"
        + '<w:r><w:t xml:space="preserve">Page </w:t></w:r>'
        + fld("PAGE")
        + '<w:r><w:t xml:space="preserve"> of </w:t></w:r>'
        + fld("SECTIONPAGES")
        + "</w:p></w:ftr>"
    )


SECTPR = f"""<w:sectPr>
<w:headerReference w:type="default" r:id="rIdCasHdr"/>
<w:headerReference w:type="first" r:id="rIdCasHdrFirst"/>
<w:footerReference w:type="default" r:id="rIdCasFtr"/>
<w:footerReference w:type="first" r:id="rIdCasFtr"/>
<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>
<w:pgMar w:top="{MARGIN_TOP}" w:right="{MARGIN_LR}" w:bottom="{MARGIN_BOTTOM}" w:left="{MARGIN_LR}" w:header="{HEADER_DIST}" w:footer="{FOOTER_DIST}" w:gutter="0"/>
<w:pgNumType w:start="1"/>
<w:cols w:space="720"/>
<w:titlePg/>
<w:textDirection w:val="lrTb"/>
</w:sectPr>"""


def patch_document(xml_bytes: bytes) -> bytes:
    text = xml_bytes.decode("utf-8")
    matches = list(re.finditer(r"<w:sectPr\b.*?</w:sectPr>|<w:sectPr\b[^>]*/>",
                               text, re.S))
    if not matches:
        raise SystemExit("reference document has no w:sectPr")
    m = matches[-1]
    text = text[: m.start()] + SECTPR + text[m.end():]
    return text.encode("utf-8")


def patch_rels(xml_bytes: bytes) -> bytes:
    text = xml_bytes.decode("utf-8")
    add = (
        '<Relationship Id="rIdCasHdr" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/header" Target="header1.xml"/>'
        '<Relationship Id="rIdCasHdrFirst" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/header" Target="header2.xml"/>'
        '<Relationship Id="rIdCasFtr" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
    )
    return text.replace("</Relationships>", add + "</Relationships>").encode("utf-8")


def patch_content_types(xml_bytes: bytes) -> bytes:
    text = xml_bytes.decode("utf-8")
    hdr = "application/vnd.openxmlformats-officedocument.wordprocessingml.header"
    ftr = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer"
    add = (
        f'<Override PartName="/word/header1.xml" ContentType="{hdr}"/>'
        f'<Override PartName="/word/header2.xml" ContentType="{hdr}"/>'
        f'<Override PartName="/word/footer1.xml" ContentType="{ftr}"/>'
    )
    return text.replace("</Types>", add + "</Types>").encode("utf-8")


def default_reference() -> bytes:
    proc = subprocess.run(
        ["quarto", "pandoc", "--print-default-data-file", "reference.docx"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.startswith(b"PK"):
        raise SystemExit(
            "could not obtain pandoc's default reference.docx: "
            + proc.stderr.decode("utf-8", "replace")[:400]
        )
    return proc.stdout


def build(short_title: str, first_author: str, output: Path,
          source: Path | None = None) -> None:
    data = source.read_bytes() if source else default_reference()
    src = zipfile.ZipFile(__import__("io").BytesIO(data))

    replacements: dict[str, bytes] = {}
    names = set(src.namelist())
    for required in ("word/styles.xml", "word/document.xml",
                     "word/_rels/document.xml.rels", "[Content_Types].xml"):
        if required not in names:
            raise SystemExit(f"reference docx lacks {required}")

    replacements["word/styles.xml"] = patch_styles(src.read("word/styles.xml"))
    replacements["word/document.xml"] = patch_document(src.read("word/document.xml"))
    replacements["word/_rels/document.xml.rels"] = patch_rels(
        src.read("word/_rels/document.xml.rels"))
    replacements["[Content_Types].xml"] = patch_content_types(
        src.read("[Content_Types].xml"))
    if "word/fontTable.xml" in names:
        replacements["word/fontTable.xml"] = patch_font_table(
            src.read("word/fontTable.xml"))

    additions: dict[str, bytes] = {
        "word/header1.xml": header_xml(short_title).encode("utf-8"),
        "word/header2.xml": empty_header_xml().encode("utf-8"),
        "word/footer1.xml": footer_xml(first_author).encode("utf-8"),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            out.writestr(item, replacements.get(item.filename,
                                                 src.read(item.filename)))
        for name, blob in additions.items():
            out.writestr(name, blob)
    src.close()


def patch_running_heads(docx: Path, short_title: str, first_author: str) -> None:
    """Rewrite word/header1.xml + word/footer1.xml of an already-built docx.

    The committed reference.docx carries placeholder running heads (they are
    static by design, Q5); paper_build.py calls this after every docx render
    so the header/footer match the paper.
    """
    src = zipfile.ZipFile(docx)
    replacements = {
        "word/header1.xml": header_xml(short_title).encode("utf-8"),
        "word/footer1.xml": footer_xml(first_author).encode("utf-8"),
    }
    missing = [name for name in replacements if name not in src.namelist()]
    if missing:
        src.close()
        raise SystemExit(f"{docx} lacks running-head parts: {missing}")
    tmp = docx.with_suffix(".patched.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            out.writestr(item, replacements.get(item.filename,
                                                 src.read(item.filename)))
    src.close()
    tmp.replace(docx)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--short-title", required=True,
                    help="running head (journal short title)")
    ap.add_argument("--first-author", required=True,
                    help="full name of the first author (running footer)")
    ap.add_argument("--output", type=Path, default=None,
                    help="write a new reference docx to this path")
    ap.add_argument("--patch-running-heads", type=Path, default=None, metavar="DOCX",
                    help="rewrite header1/footer1 of an already-built docx "
                         "instead of generating a reference docx")
    ap.add_argument("--source", type=Path, default=None,
                    help="reuse a pre-dumped reference.docx instead of pandoc's")
    args = ap.parse_args()
    if args.patch_running_heads is not None:
        patch_running_heads(args.patch_running_heads, args.short_title,
                            args.first_author)
        print(f"running heads patched in {args.patch_running_heads}")
        return 0
    if args.output is None:
        ap.error("--output is required unless --patch-running-heads is given")
    build(args.short_title, args.first_author, args.output, args.source)
    print(f"reference docx written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

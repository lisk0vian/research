#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""cas_fidelity.py — prove that Quarto renders reproduce the official CAS sample.

Two suites, selected by flag:

  default        PDF suite against els-cas-templates/cas-sc-sample.tex/.pdf:
                 preamble keywords, normalized frontmatter/body text, fonts,
                 word-box positions, structural pixels (see below).

  --docx         DOCX style suite (Q9/Q11 of the design grill): builds a
                 temporary mini-document through the elsevier-cas-docx format
                 and asserts, structurally (unzip + XML), that it carries the
                 CAS look: STIX fonts (+ Times New Roman fallback), page
                 geometry 10885x14854 twips / 777 twip margins, running
                 header+footer with Page fields, front-matter styles
                 (Author/Affiliation/AbstractTitle/Keywords/Highlights),
                 superscripts, real Word footnotes, embedded rasterized
                 figure, numbered Figure/Table captions, Elsevier-Harvard
                 citations. A LibreOffice headless conversion runs as a
                 NON-blocking visual aid (LO output is saved next to the
                 specimen build); LibreOffice/Word rasterizers differ from
                 pdfTeX, so it never fails the check.

PDF suite details — each check reported PASS/FAIL, exit 1 on any FAIL:

  tex-preamble  keyword checks on both preambles (the preambles are not
                expected to be byte-identical: pandoc emits its own
                boilerplate; the class-level choices must match the sample).
  tex-body      block-structure diff of everything between \\begin{document}
                and \\end{document} (frontmatter as a command multiset,
                body as ordered blocks; normalized the same way for both).
  fonts         pdffonts (name minus subset tag, type, encoding, embedding)
                of reference and specimen PDFs are the same set.
  layout        pdftotext -bbox: the same words on each page and every word
                box within --tol-pt (default 0.5 pt).
  pixels        hard visual differences: no pixel differing by >= 96/255
                (raw AA jitter below that is reported, not failed).

Usage:
  python scripts/cas_fidelity.py [--no-render] [--tex-only] [--dpi 144]
                                 [--tol-pt 0.5] [--specimen DIR]
  python scripts/cas_fidelity.py --docx
"""

from __future__ import annotations

import argparse
import difflib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pdfdiff import find_bbox_tool, run  # noqa: E402
from _pdfdiff import word_boxes as _word_boxes  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
JOURNAL_DIR = REPO / "templates" / "journals" / "engineering-applications-of-artificial-intelligence"
SPECIMEN_DIR = JOURNAL_DIR / "tests" / "specimen"
CANONICAL_EXT = JOURNAL_DIR / "quarto-extension" / "_extensions"
REFERENCE_TEX = SPECIMEN_DIR / "reference" / "cas-sc-sample.tex"
REFERENCE_PDF = SPECIMEN_DIR / "reference" / "cas-sc-sample.pdf"
SPECIMEN_TEX = SPECIMEN_DIR / "specimen.tex"
SPECIMEN_PDF = SPECIMEN_DIR / "build" / "specimen.pdf"

# Preamble contract: what cas-sc-sample.tex promises at class/font level.
PREAMBLE_REQUIRED = [
    r"\\documentclass\[[^\]]*a4paper[^\]]*fleqn\]\{cas-sc\}",
    r"\\usepackage\[authoryear,longnamesfirst\]\{natbib\}",
    r"\\def\\tsc#1\{",
    r"\\tsc\{WGM\}",
    r"\\tsc\{BEC\}",
]
PREAMBLE_FORBIDDEN = [
    (r"\\usepackage(\[[^\]]*\])?\{lmodern\}", "lmodern (sample: STIX)"),
    (r"\\usepackage(\[[^\]]*\])?\{microtype\}", "microtype (sample: none)"),
    (r"\\usepackage(\[[^\]]*\])?\{upquote\}", "upquote (sample: none)"),
    (r"\\usepackage(\[[^\]]*\])?\{parskip\}", "parskip (class owns geometry)"),
    (r"\\documentclass\[[^\]]*\bfinal\b", "formatting: final (sample has no final)"),
    (r"colorlinks\s*=\s*true", "colorlinks=true (sample: black links)"),
]


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        return ok

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.results)

    def print(self) -> None:
        print("=== cas fidelity report ===")
        for name, ok, detail in self.results:
            line = f"  [{'PASS' if ok else 'FAIL'}] {name}"
            if detail:
                line += f" — {detail}"
            print(line)
        print("  RESULT:", "OK" if self.ok else "FAILED")


def sync_extension_to(dest: Path) -> None:
    """Copy the canonical extension (build-time, gitignored) into dest."""
    shutil.copytree(CANONICAL_EXT, dest / "_extensions", dirs_exist_ok=True)


def sync_extension() -> None:
    sync_extension_to(SPECIMEN_DIR)


def render_specimen() -> int:
    rc, out = run(
        ["quarto", "render", "specimen.qmd", "--to", "elsevier-cas-pdf",
         "--output-dir", "build"],
        cwd=SPECIMEN_DIR,
    )
    if rc != 0:
        print(out[-3000:])
    return rc


# ---------------------------------------------------------------------------
# tex checks
# ---------------------------------------------------------------------------

def split_preamble_body(tex: str) -> tuple[str, str]:
    head, sep, rest = tex.partition("\\begin{document}")
    body, _, tail = rest.partition("\\end{document}")
    if not sep:
        return "", tex
    return head, body + ("\\end{document}" if tail else "")


def check_preamble(name: str, preamble: str, rep: Report) -> None:
    joined = re.sub(r"[ \t]*\n[ \t]*", " ", preamble)
    for pattern in PREAMBLE_REQUIRED:
        if not re.search(pattern, joined):
            rep.add(f"tex-preamble {name}: missing {pattern}", False)
    for pattern, why in PREAMBLE_FORBIDDEN:
        if re.search(pattern, joined):
            rep.add(f"tex-preamble {name}: forbidden {why}", False)
    rep.add(f"tex-preamble {name}: keywords", True,
            f"{len(PREAMBLE_REQUIRED)} required, {len(PREAMBLE_FORBIDDEN)} forbidden")


def strip_comments(tex: str) -> str:
    """Remove LaTeX comments (unescaped % to EOL). Verbatim blocks in the
    specimen carry no %, so this is safe for both texts alike."""
    lines = []
    for line in tex.splitlines():
        out = []
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "%" and (i == 0 or line[i - 1] != "\\"):
                break
            out.append(ch)
            i += 1
        lines.append("".join(out))
    return "\n".join(lines)


def normalize_block(block: str) -> str:
    text = " ".join(line.strip() for line in block.splitlines())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    # pandoc/Quarto label section headings; the sample labels nothing there.
    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    # pandoc puts \bibliographystyle in the preamble; the sample in the body.
    text = re.sub(r"\\bibliographystyle\{[^{}]*\}", "", text)
    # soft-space / math-delimiter spelling variants
    text = text.replace("\\LaTeX~", "\\LaTeX ")
    text = text.replace("~", " ")
    text = text.replace("\\(", "$").replace("\\)", "$")
    text = text.replace(",]", "]")
    # keyval spelling: the sample writes "auid=000, bioid=1", pandoc none.
    text = re.sub(r",\s+", ",", text)
    text = re.sub(r"\[\s+", "[", text)
    text = re.sub(r"\s+\]", "]", text)
    text = text.replace(",]", "]")  # sample's trailing "suffix=Jr, ]"
    # tabular* preamble: {@{} LLLL@{}} vs sample's {@{} LLLL@{} }
    text = re.sub(r"@\{\}\s*\}", "@{}}", text)
    text = re.sub(r"\{\s*@\{", "{@{", text)
    # space before the row terminator \\ — replacement via lambda so re.sub's
    # backslash-escape processing cannot halve the two backslashes.
    text = re.sub(r"\s+\\\\", lambda _m: "\\\\", text)
    # control-space (\LaTeX\ manuscript) vs plain space
    text = re.sub(r"(?<!\\)\\ ", " ", text)
    text = re.sub(r"\s+\}", "}", text)
    # Grouping braces that carry no semantics (William {J. Hansen} vs
    # William J. Hansen): stripped on BOTH sides, so equality stays sound
    # while cosmetic grouping differences do not fail the check.
    stripped = None
    while stripped != text:
        stripped = text
        text = re.sub(r"\{([^\{\}\\$%^\_~]*\w[^\{\}\\$%^\_~]*)\}", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def body_blocks(body: str) -> list[str]:
    stripped = strip_comments(body)
    blocks = [normalize_block(b) for b in re.split(r"\n\s*\n", stripped)]
    return [b for b in blocks if b]


ARG_START = " \t\r\n"


def front_chunks(text: str) -> list[str]:
    """Tokenize the pre-\\maketitle region into commands (\\cmd[..]{..}..) and
    environments (\\begin{env}...\\end{env}). Sample and specimen may order and
    wrap these differently — \\author/\\affiliation/\\ead are pure storage until
    \\maketitle — so they are compared as a multiset."""
    text = strip_comments(text)
    chunks: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "\\" or i + 1 >= n or not text[i + 1].isalpha():
            i += 1
            continue
        j = i + 1
        while j < n and text[j].isalpha():
            j += 1
        word = text[i:j]
        if word == "\\begin":
            m = re.match(r"\{([A-Za-z*@]+)\}", text[j:])
            if m:
                name = m.group(1)
                end = text.find("\\end{" + name + "}", j)
                k = (end + len("\\end{" + name + "}")) if end != -1 else n
                chunks.append(text[i:k])
                i = k
                continue
        # command: consume balanced [..] and {..} argument groups
        k = j
        while True:
            save = k
            while k < n and text[k] in ARG_START:
                k += 1
            if k < n and text[k] in "[{":
                closer = "]" if text[k] == "[" else "}"
                opener = text[k]
                depth = 1
                k += 1
                while k < n and depth:
                    if text[k] == opener:
                        depth += 1
                    elif text[k] == closer:
                        depth -= 1
                    k += 1
                continue
            k = save
            break
        chunks.append(text[i:k])
        i = k
    return [normalize_block(c) for c in chunks if normalize_block(c)]


def check_front(ref_body: str, our_body: str, rep: Report) -> None:
    """Multiset comparison of the pre-\\maketitle region. \\author/\\affiliation/
    \\ead are pure storage until \\maketitle, so ordering differences between
    sample and specimen are not visual differences."""
    ref_split = ref_body.partition("\\maketitle")
    our_split = our_body.partition("\\maketitle")
    if not ref_split[1] or not our_split[1]:
        rep.add("tex-frontmatter", False, "\\maketitle not found")
        return
    ref_front = ref_split[0] + "\\maketitle"
    our_front = our_split[0] + "\\maketitle"
    from collections import Counter

    ref_c = Counter(front_chunks(ref_front))
    our_c = Counter(front_chunks(our_front))
    missing = sorted((ref_c - our_c).elements())
    extra = sorted((our_c - ref_c).elements())
    if not missing and not extra:
        total = sum(ref_c.values())
        rep.add("tex-frontmatter", True, f"{total} commands identical")
    else:
        rep.add("tex-frontmatter", False,
                f"{len(missing)} missing / {len(extra)} extra commands")
        for chunk in missing[:10]:
            print(f"    only in sample: {chunk[:160]}")
        for chunk in extra[:10]:
            print(f"    only in specimen: {chunk[:160]}")


def check_body(ref_tex: str, our_tex: str, rep: Report) -> None:
    _, ref_body = split_preamble_body(ref_tex)
    _, our_body = split_preamble_body(our_tex)
    if not our_body:
        rep.add("tex-body", False, "\\begin{document} not found in specimen.tex")
        return
    check_front(ref_body, our_body, rep)
    ref_rest = ref_body.partition("\\maketitle")[2]
    our_rest = our_body.partition("\\maketitle")[2]
    if "\\maketitle" not in ref_body or "\\maketitle" not in our_body:
        return
    ref = body_blocks(ref_rest)
    our = body_blocks(our_rest)
    if ref == our:
        rep.add("tex-body", True, f"{len(ref)} blocks identical")
        return
    diff = list(difflib.unified_diff(ref, our, fromfile="cas-sc-sample.tex",
                                     tofile="specimen.tex", lineterm="", n=1))
    rep.add("tex-body", False,
            f"{len(ref)} reference blocks vs {len(our)} specimen blocks")
    print("\n--- tex body diff (normalized blocks) ---")
    for line in diff[:200]:
        print(line)
    if len(diff) > 200:
        print(f"... ({len(diff) - 200} more diff lines)")
    print("--- end tex body diff ---\n")


# ---------------------------------------------------------------------------
# pdf checks
# ---------------------------------------------------------------------------

FONT_RE = re.compile(
    r"^(\S+)\s+(Type \d\S*|TrueType|CID|MMType1)\s+(\S+)\s+(yes|no)\s+(yes|no)"
)


def font_set(pdf: Path) -> set[tuple[str, str, str, str, str]] | None:
    rc, out = run(["pdffonts", str(pdf)])
    if rc != 0:
        return None
    fonts = set()
    for line in out.splitlines():
        m = FONT_RE.match(line)
        if m:
            name = re.sub(r"^[A-Z]{6}\+", "", m.group(1))
            fonts.add((name, m.group(2), m.group(3), m.group(4), m.group(5)))
    return fonts


def check_fonts(rep: Report) -> None:
    ref = font_set(REFERENCE_PDF)
    our = font_set(SPECIMEN_PDF)
    if ref is None or our is None:
        rep.add("fonts", False, "pdffonts failed")
        return
    missing = sorted(ref - our)
    extra = sorted(our - ref)
    ok = not missing and not extra
    detail = f"{len(ref)} fonts"
    if not ok:
        detail += f"; missing={missing} extra={extra}"
    rep.add("fonts", ok, detail)


def word_boxes(pdf: Path) -> list[list[tuple[str, float, float, float, float]]]:
    if find_bbox_tool(REFERENCE_PDF) is None:
        raise RuntimeError("no pdftotext with -bbox support on PATH")
    return _word_boxes(pdf)


def check_layout(tol_pt: float, rep: Report) -> None:
    try:
        ref = word_boxes(REFERENCE_PDF)
        our = word_boxes(SPECIMEN_PDF)
    except RuntimeError as exc:
        rep.add("layout", False, str(exc))
        return
    if len(ref) != len(our):
        rep.add("layout", False, f"page count {len(ref)} vs {len(our)}")
        return
    worst = 0.0
    where = ""
    word_mismatch = ""
    for pageno, (rp, op) in enumerate(zip(ref, our), start=1):
        if [w[0] for w in rp] != [w[0] for w in op]:
            for i, (a, b) in enumerate(zip([w[0] for w in rp], [w[0] for w in op])):
                if a != b:
                    word_mismatch = (f"page {pageno} word #{i}: "
                                     f"{a!r} vs {b!r}")
                    break
            if not word_mismatch:
                word_mismatch = (f"page {pageno}: {len(rp)} vs {len(op)} words")
            break
        for (word, rx, ry, *_), (_, ox, oy, *__) in zip(rp, op):
            for axis, delta in (("x", abs(rx - ox)), ("y", abs(ry - oy))):
                if delta > worst:
                    worst, where = delta, f"page {pageno} '{word}' {axis}"
    if word_mismatch:
        rep.add("layout", False, word_mismatch)
        return
    rep.add("layout", worst <= tol_pt,
            f"max word-box delta {worst:.3f} pt (tol {tol_pt} pt) at {where}")


def check_pixels(dpi: int, rep: Report) -> None:
    """Structural pixel comparison.

    Raw per-channel diffs also fire on sub-pixel rasterization jitter
    (different TeX builds round glyph positions slightly differently), and
    text-level differences are already covered exhaustively by the layout
    check (word sequence + <= tol-pt boxes). So the PASS/FAIL metric here is
    HARD visual differences: no pixel may differ by >= 96/255 (a third of the
    scale) — that is what a missing/extra glyph, a shifted figure, a wrong
    colour or a changed rule looks like. The ink-mask structural diff and the
    raw statistics are still reported (and the heatmap written) as context.
    """
    try:
        from PIL import Image, ImageChops, ImageFilter
    except ImportError:
        rep.add("pixels", False, "Pillow not installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp)
        for src, tag in ((REFERENCE_PDF, "ref"), (SPECIMEN_PDF, "our")):
            rc, _ = run(["pdftoppm", "-r", str(dpi), "-png",
                         str(src), str(prefix / tag)])
            if rc != 0:
                rep.add("pixels", False, f"pdftoppm failed for {src}")
                return
        ref_pages = sorted(Path(tmp).glob("ref-*.png"))
        our_pages = sorted(Path(tmp).glob("our-*.png"))
        if len(ref_pages) != len(our_pages) or not ref_pages:
            rep.add("pixels", False,
                    f"page count {len(ref_pages)} vs {len(our_pages)}")
            return
        total = 0
        raw_sig = 0
        hard = 0
        structural = 0
        max_delta = 0
        heatmap = None
        for rp, op in zip(ref_pages, our_pages):
            a = Image.open(rp).convert("RGB")
            b = Image.open(op).convert("RGB")
            if a.size != b.size:
                rep.add("pixels", False, f"page size {a.size} vs {b.size}")
                return
            diff = ImageChops.difference(a, b).convert("L")
            hist = diff.histogram()
            total += a.size[0] * a.size[1]
            raw_sig += sum(hist[32:])
            hard += sum(hist[96:])
            max_delta = max(max_delta, max(i for i in range(256) if hist[i]))
            ink_a = a.convert("L").point(lambda v: 255 if v < 160 else 0)
            ink_b = b.convert("L").point(lambda v: 255 if v < 160 else 0)
            dil_a = ink_a.filter(ImageFilter.MaxFilter(3))
            dil_b = ink_b.filter(ImageFilter.MaxFilter(3))
            struct = ImageChops.logical_xor(
                dil_a.convert("1"), dil_b.convert("1")).convert("L")
            shist = struct.histogram()
            structural += shist[255]
            if shist[255] and heatmap is None:
                heatmap = struct
        pct = 100.0 * structural / total if total else 0.0
        ok = hard == 0
        rep.add("pixels", ok,
                f"{hard} px with delta>=96; raw>32: {raw_sig} px "
                f"(max {max_delta}), structural {structural} px ({pct:.5f}%)")
        if heatmap is not None:
            out = SPECIMEN_DIR / "build" / "fidelity-heatmap.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            heatmap.save(out)
            print(f"  heatmap written to {out}")


# ---------------------------------------------------------------------------
# docx suite (temporary mini-document + structural assertions, Q9/Q11)
# ---------------------------------------------------------------------------

# must match tools/make_reference_docx.py (measured on cas-sc-sample.pdf)
PAGE_TW, PAGE_HT = 10885, 14854
MARGIN_LR_TW = 777

DOCX_FIXTURE = """---
title: "DOCX style fixture"
journal:
  short-title: "CAS docx fixture"
  corresponding:
    - mark: cor1
      text: "Corresponding author"
  author-notes:
    - mark: fn1
      text: "First author footnote text."
  highlights:
    - "Highlight one"
    - "Highlight two"
abstract: |
  Fixture abstract rendered through the elsevier-cas-docx format.
keywords:
  - fixture-keyword
author:
  - name: Ada Lovelace
    email: ada@example.org
    orcid: "0000-0001-0002-0003-0004"
    affiliation: [{ref: aff-1}]
    cas:
      cormark: 1
      fnmark: "1"
      credit: "Conceptualization"
  - name: Alan Turing
    affiliation: [{ref: aff-1}]
affiliations:
  - id: aff-1
    name: Analytical Engines Lab
    city: Manchester
    country: United Kingdom
bibliography: references.bib
---

# Introduction

See @tbl-demo, @fig-demo and @Reichstein2019 for the reference style.

![Fixture figure caption.](cas-grabs.pdf){#fig-demo width=.9}

| Col A | Col B |
|---|---|
| 1 | 2 |

: Fixture table caption. {#tbl-demo}
"""

DOCX_FIXTURE_BIB = """@ARTICLE{Reichstein2019,
   author = {Reichstein, Markus and Camps-Valls, Gustau and Stevens, Bjorn and
   Jungstein, Martin and Denzler, Joachim and Mahecha, Miguel},
   title = {Deep learning and process understanding for data-driven Earth
   system science},
   journal = {Nature},
   year = {2019},
   volume = {566},
   number = {7743},
   pages = {192--194},
   doi = {10.1038/s41586-019-0912-1}
}
"""


def _docx_texts(z: zipfile.ZipFile, part: str = "word/document.xml") -> str:
    xml = z.read(part).decode("utf-8", "replace")
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


def _find_soffice() -> str | None:
    if shutil.which("soffice"):
        return "soffice"
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def run_docx_suite(rep: Report) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        fixture = Path(tmp)
        (fixture / "fixture.qmd").write_text(DOCX_FIXTURE, encoding="utf-8")
        (fixture / "references.bib").write_text(DOCX_FIXTURE_BIB, encoding="utf-8")
        shutil.copy2(SPECIMEN_DIR / "figs" / "cas-grabs.pdf",
                     fixture / "cas-grabs.pdf")
        try:
            sync_extension_to(fixture)
        except Exception as exc:
            rep.add("docx render", False, f"extension sync failed: {exc}")
            return

        rc, out = run(["quarto", "render", "fixture.qmd",
                       "--to", "elsevier-cas-docx"], cwd=fixture)
        docx = fixture / "fixture.docx"
        if rc != 0 or not docx.is_file():
            rep.add("docx render", False, out[-1500:])
            return
        rep.add("docx render", True)

        z = zipfile.ZipFile(docx)
        names = set(z.namelist())
        document = z.read("word/document.xml").decode("utf-8", "replace")
        styles = z.read("word/styles.xml").decode("utf-8", "replace")
        full = _docx_texts(z)
        fn_xml = z.read("word/footnotes.xml").decode("utf-8", "replace") \
            if "word/footnotes.xml" in names else ""

        # --- fonts: STIX everywhere, Times New Roman as declared fallback ---
        fonts_ok = 'w:ascii="STIX"' in styles
        font_table = z.read("word/fontTable.xml").decode("utf-8", "replace") \
            if "word/fontTable.xml" in names else ""
        fallback_ok = 'w:name="STIX"' in font_table and "Times New Roman" in font_table
        rep.add("docx fonts", fonts_ok and fallback_ok,
                f"STIX in styles={fonts_ok}, Times New Roman alt={fallback_ok}")

        # --- geometry + running heads (reference-doc sectPr) ----------------
        # document/styles/full are already read: release the file so the
        # head patch can replace it (Windows locks open files)
        z.close()
        geo: list[str] = []
        m = re.search(r"<w:pgSz[^>]*/>", document)
        attrs = dict(re.findall(r'w:(w|h)="(\d+)"', m.group(0))) if m else {}
        if (attrs.get("w"), attrs.get("h")) != (str(PAGE_TW), str(PAGE_HT)):
            geo.append(f"pgSz {attrs}")
        m = re.search(r"<w:pgMar[^>]*/>", document)
        mar = dict(re.findall(r'w:(left|right|top|bottom|header|footer)="(\d+)"',
                              m.group(0))) if m else {}
        if mar.get("left") != str(MARGIN_LR_TW) or mar.get("right") != str(MARGIN_LR_TW):
            geo.append(f"side margins {mar.get('left')}/{mar.get('right')}")
        if "<w:titlePg" not in document:
            geo.append("no titlePg")
        if "headerReference" not in document or "footerReference" not in document:
            geo.append("no header/footer references")
        # the pipeline patches the placeholder heads (paper_build does this for
        # real papers; the harness does it for the fixture)
        tool = CANONICAL_EXT.parent / "tools" / "make_reference_docx.py"
        short, first = "CAS docx fixture", "Ada Lovelace"
        if tool.is_file():
            rc_p, out_p = run([sys.executable, str(tool), "--patch-running-heads",
                               str(docx), "--short-title", short,
                               "--first-author", first])
            if rc_p != 0:
                geo.append("head patch failed: " + out_p[-200:])
        else:
            geo.append("make_reference_docx.py not found")
        z2 = zipfile.ZipFile(docx)
        header = z2.read("word/header1.xml").decode("utf-8", "replace") \
            if "word/header1.xml" in z2.namelist() else ""
        footer = z2.read("word/footer1.xml").decode("utf-8", "replace") \
            if "word/footer1.xml" in z2.namelist() else ""
        z2.close()
        if short not in header:
            geo.append("short title missing from header1")
        # cas-sc footer: "<author> et al.:" in sans, the rest in italic roman
        if f"{first} et al.:" not in footer \
                or "Preprint submitted to Elsevier" not in footer \
                or " PAGE " not in footer:
            geo.append("footer text/PAGE field missing")
        rep.add("docx geometry + running heads", not geo,
                "; ".join(geo) or
                f"{PAGE_TW}x{PAGE_HT} twip, margins {MARGIN_LR_TW}, heads ok")

        # --- front-matter styles + content ----------------------------------
        wanted = ["Title", "Author", "Affiliation", "AbstractTitle",
                  "Abstract", "Keywords", "HighlightsTitle", "Highlight",
                  "Heading1", "ImageCaption", "Bibliography"]
        missing_styles = [s for s in wanted if f'w:styleId="{s}"' not in styles]
        content: list[str] = []
        for needle, why in (
            ("ABSTRACT", "ABSTRACT label"),
            ("Highlight one", "highlights"),
            ("fixture-keyword", "keywords"),
            ("Analytical Engines Lab", "affiliation line"),
            ("Ada Lovelace", "authors"),
        ):
            if needle not in full:
                content.append(why)
        if document.count("w:vertAlign") < 2:
            content.append("superscripts missing")
        rep.add("docx front matter", not missing_styles and not content,
                "; ".join(missing_styles + content) or
                "11 styles, superscripts, abstract/keywords/highlights ok")

        # --- footnotes (cormark/fntext/emails/orcid) ------------------------
        # fn_xml was read above (before the zip was closed for head patching)
        fn_text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", fn_xml))
        fn: list[str] = []
        for needle, why in (
            ("Corresponding author", "cormark note"),
            ("First author footnote text.", "fntext note"),
            # unmarked note behind the PDF's envelope, as cas-sc prints it
            ("ada@example.org (A. Lovelace)", "email note"),
            ("ORCID(s): 0000-0001-0002-0003-0004 (A. Lovelace)", "orcid note"),
        ):
            if needle not in fn_text:
                fn.append(why)
        if document.count("w:footnoteReference") < 4:
            fn.append("fewer than 4 footnote references")
        rep.add("docx footnotes", not fn,
                "; ".join(fn) or "4 notes, 4 references")

        # --- figure rasterized + captions numbered --------------------------
        media = [n for n in names if n.startswith("word/media/")]
        cap: list[str] = []
        if not any(n.lower().endswith((".png", ".jpg", ".jpeg")) for n in media):
            cap.append("no rasterized figure in word/media")
        if not re.search(r"Figure[\s\u00a0]*1\s*:", full):
            cap.append("Figure 1 caption numbering")
        if not re.search(r"Table[\s\u00a0]*1\s*:", full):
            cap.append("Table 1 caption numbering")
        rep.add("docx figure + captions", not cap,
                "; ".join(cap) or f"media={media}, Figure/Table 1 numbered")

        # --- Elsevier-Harvard citations + bibliography ----------------------
        cite: list[str] = []
        # natbib longnamesfirst (the default cas-model2-names.bst PDF):
        # a first citation lists every author
        if "Reichstein, Camps-Valls, Stevens" not in full:
            cite.append("in-text (Reichstein, Camps-Valls, ..., 2019)")
        if "Deep learning and process understanding" not in full:
            cite.append("bibliography entry")
        rep.add("docx citations (elsevier-harvard)", not cite,
                "; ".join(cite) or "author-date in text + bibliography")

        # --- et al. from the first citation (cas-model2-names-etal) ---------
        # -M csl picks the etal variant: the citeproc fallback used when the
        # latex zip is absent must keep every citation short, as that bst's
        # PDF does (paper_build passes the same override for -etal papers).
        etal_csl = ("_extensions/quarto-journals/elsevier-cas/"
                    "elsevier-harvard-etal.csl")
        rc_e, out_e = run(["quarto", "render", "fixture.qmd",
                           "--to", "elsevier-cas-docx", "-o", "fixture-etal.docx",
                           "-M", f"csl:{etal_csl}"], cwd=fixture)
        etal_docx = fixture / "fixture-etal.docx"
        etal: list[str] = []
        if rc_e != 0 or not etal_docx.is_file():
            etal.append("etal render: " + out_e[-300:])
        else:
            with zipfile.ZipFile(etal_docx) as ze:
                full_e = re.sub(r"[\s\u00a0]+", " ", _docx_texts(ze))
            if "Reichstein et al. (2019)" not in full_e:
                etal.append("short citation (Reichstein et al. (2019)) missing")
            if "Reichstein, Camps-Valls, Stevens" in full_e:
                etal.append("long author list still on the first citation")
        rep.add("docx citations (etal variant)", not etal,
                "; ".join(etal) or "short in-text from the first citation")

        # --- non-blocking visual aid: LibreOffice ---------------------------
        z.close()  # Windows: release fixture.docx before soffice/temp cleanup
        soffice = _find_soffice()
        if soffice is None:
            rep.add("docx visual (LibreOffice)", True,
                    "skipped: soffice not found (visual aid only)")
        else:
            out_dir = SPECIMEN_DIR / "build"
            out_dir.mkdir(parents=True, exist_ok=True)
            rc, conv = run([soffice, "--headless", "--convert-to", "pdf",
                            "--outdir", str(out_dir), str(docx)])
            produced = out_dir / "fixture.pdf"
            if rc == 0 and produced.is_file():
                final = out_dir / "docx-fixture.pdf"
                if final.exists():
                    final.unlink()
                produced.replace(final)
                rep.add("docx visual (LibreOffice)", True,
                        f"converted to {final} (open it for a visual check)")
            else:
                rep.add("docx visual (LibreOffice)", False, conv[-400:])


# ---------------------------------------------------------------------------

def main() -> int:
    global SPECIMEN_DIR, SPECIMEN_TEX, SPECIMEN_PDF  # noqa: PLW0603
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-render", action="store_true",
                    help="reuse the existing specimen build")
    ap.add_argument("--tex-only", action="store_true",
                    help="only the .tex checks (no PDF tools needed)")
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--tol-pt", type=float, default=0.5)
    ap.add_argument("--specimen", default=str(SPECIMEN_DIR))
    ap.add_argument("--docx", action="store_true",
                    help="run the DOCX style suite instead of the PDF suite")
    args = ap.parse_args()

    if args.specimen != str(SPECIMEN_DIR):
        SPECIMEN_DIR = Path(args.specimen)
        SPECIMEN_TEX = SPECIMEN_DIR / "specimen.tex"
        SPECIMEN_PDF = SPECIMEN_DIR / "build" / "specimen.pdf"

    rep = Report()

    if args.docx:
        run_docx_suite(rep)
        rep.print()
        return 0 if rep.ok else 1

    if not REFERENCE_TEX.is_file():
        print(f"ERROR: reference not found: {REFERENCE_TEX}")
        return 2

    if not args.no_render:
        sync_extension()
        if render_specimen() != 0:
            rep.add("render", False, "quarto render failed")
            rep.print()
            return 1
        rep.add("render", True)

    if not SPECIMEN_TEX.is_file():
        rep.add("tex", False, f"{SPECIMEN_TEX} missing (keep-tex: true?)")
        rep.print()
        return 1

    ref_tex = REFERENCE_TEX.read_text(encoding="utf-8", errors="replace")
    our_tex = SPECIMEN_TEX.read_text(encoding="utf-8", errors="replace")

    ref_pre, _ = split_preamble_body(ref_tex)
    our_pre, _ = split_preamble_body(our_tex)
    check_preamble("reference", ref_pre, rep)
    check_preamble("specimen", our_pre, rep)
    check_body(ref_tex, our_tex, rep)

    if not args.tex_only:
        if not REFERENCE_PDF.is_file() or not SPECIMEN_PDF.is_file():
            rep.add("pdf", False, "PDF missing")
        else:
            check_fonts(rep)
            check_layout(args.tol_pt, rep)
            check_pixels(args.dpi, rep)

    rep.print()
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())

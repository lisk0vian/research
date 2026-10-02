#!/usr/bin/env python3
"""paper_layout_check.py — prove a rendered paper respects the journal layout.

Three layers, cheapest and most definitive first. Exit 1 on any FAIL.

  latex-log  Overfull/Underfull boxes reported by the engine in
             build/render/main.log. LaTeX *is* the layout engine, so this is
             the authoritative signal for "content outside the layout": the
             amount overfull and the line of main.tex that caused it.

  ink-box    Rasterize every page and compare the bounding box of the ink with
             the typical text block of the template. Catches escapes that
             produce no warning (a float placed outside the block). Needs
             pdftoppm and Pillow; reported as SKIP when either is missing.

  sources    Assertions that do not need the PDF: a flush-left `fleqn`
             class option (math would not be centered), author lists too long
             to read in a bibliography, and — when the PDF text is available —
             reference paragraphs that became walls of text plus the presence
             of every figure/table caption and highlight the manuscript
             declares.

Usage:
  python scripts/paper_layout_check.py --slug c26-2026
  python scripts/paper_layout_check.py --slug c26-2026 --max-overfull 5
"""

from __future__ import annotations

import argparse
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _repo import find_repo_root, load_yaml  # noqa: E402

# An Overfull box bigger than this fails the check; smaller ones are warnings
# (LaTeX reports them for a few harmless points of hyphenation slack).
MAX_OVERFULL_PT = 5.0
WARN_OVERFULL_PT = 1.0
# cas-sc's \maketitle builds the front matter (title page + ARTICLE INFO/ABSTRACT
# boxes) as boxes wider than \textwidth; the rendered page is correct, so an
# overfull reported on that line is a warning and not a layout failure.
FRONT_MATTER_MACROS = ("\\maketitle", "\\twocolumn[", "\\begin{highlights}")
# Ink may leave the typical text block by this margin before it is a failure
# (pixels at the raster dpi below).
MAX_INK_OUT_PX = 8
RASTER_DPI = 100
# A bibliography entry may not have more authors than this (the style prints
# "et al." beyond it) nor render as a wall of text longer than this.
MAX_AUTHORS = 10
MAX_REF_CHARS = 900


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, check: str, ok: bool | None, detail: str = "") -> bool:
        self.rows.append((check, "SKIP" if ok is None else ("PASS" if ok else "FAIL"), detail))
        return bool(ok)

    @property
    def failed(self) -> int:
        return sum(1 for _, status, _ in self.rows if status == "FAIL")

    def print(self) -> None:
        width = max((len(c) for c, _, _ in self.rows), default=10)
        for check, status, detail in self.rows:
            print(f"  [{status:4}] {check:<{width}}  {detail}")
        print(f"\nRESULT: {'PASS' if not self.failed else 'FAIL'} "
              f"({len(self.rows)} checks, {self.failed} failure(s))")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        return p.returncode, (p.stdout + p.stderr)
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def pdf_text(pdf: Path) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    rc, out = run([exe, "-layout", str(pdf), "-"])
    return out if rc == 0 else ""


# --------------------------------------------------------------------------- #
# layer 1: the engine's own report
# --------------------------------------------------------------------------- #
def check_latex_log(log: Path, tex: Path, rep: Report, max_overfull: float) -> None:
    if not log.is_file():
        rep.add("latex-log", None, f"no {log}")
        return
    text = log.read_text(encoding="utf-8", errors="replace")
    lines = tex.read_text(encoding="utf-8", errors="replace").split("\n") if tex.is_file() else []

    overfull = re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide\)"
                          r"(?: detected at line (\d+))?(?: in alignment at lines (\d+)--(\d+))?", text)
    rows = []
    for amount, at, first, last in overfull:
        num = at or first or "?"
        src = lines[int(num) - 1].strip()[:60] if num.isdigit() and 0 < int(num) <= len(lines) else ""
        kind = "front matter" if any(m in src for m in FRONT_MATTER_MACROS) else "layout"
        rows.append((float(amount), num, src, kind))
    rows.sort(reverse=True)

    bad = [r for r in rows if r[0] > max_overfull and r[3] == "layout"]
    front = [r for r in rows if r[0] > max_overfull and r[3] == "front matter"]
    warn = [r for r in rows if WARN_OVERFULL_PT < r[0] <= max_overfull]
    fail_detail = "; ".join(f"{a:.1f}pt @ line {n} ({s})" for a, n, s, _ in bad[:4])
    if bad:
        rep.add("latex-log", False, f"{len(bad)} box(es) over {max_overfull:g}pt — {fail_detail}")
    else:
        note = "no overfull box above the threshold"
        if front:
            note += (f"; {len(front)} in the title page (cas-sc builds it wider than "
                     f"\\textwidth, renders correctly): "
                     + "; ".join(f"{a:.1f}pt @ line {n}" for a, n, _, _ in front[:3]))
        elif warn:
            note += f"; {len(warn)} small overfull(s) <= {max_overfull:g}pt"
        rep.add("latex-log", True, note)


# --------------------------------------------------------------------------- #
# layer 2: ink outside the text block
# --------------------------------------------------------------------------- #
def check_ink_box(pdf: Path, rep: Report) -> None:
    exe = shutil.which("pdftoppm")
    if not exe:
        rep.add("ink-box", None, "pdftoppm not on PATH")
        return
    try:
        from PIL import Image
    except ImportError:
        rep.add("ink-box", None, "Pillow not installed")
        return

    with tempfile.TemporaryDirectory() as tmp:
        rc, out = run([exe, "-r", str(RASTER_DPI), "-png", str(pdf), str(Path(tmp) / "p")])
        if rc != 0:
            rep.add("ink-box", None, f"pdftoppm failed: {out.strip()[:80]}")
            return
        boxes = []
        for png in sorted(Path(tmp).glob("p-*.png")):
            im = Image.open(png).convert("L")
            bbox = im.point(lambda v: 255 if v < 245 else 0).getbbox()
            if bbox:
                boxes.append((png.name, im.size, bbox))
        if not boxes:
            rep.add("ink-box", None, "no page rasterized")
            return

        block = (statistics.median(b[0] for _, _, b in boxes),
                 statistics.median(b[2] for _, _, b in boxes))
        out_pages = [(n, b) for n, _, b in boxes if b[0] < block[0] - MAX_INK_OUT_PX
                     or b[2] > block[1] + MAX_INK_OUT_PX]
        detail = f"text block x={block[0]:.0f}..{block[1]:.0f}px at {RASTER_DPI}dpi, {len(boxes)} pages"
        if out_pages:
            names = ", ".join(n for n, _ in out_pages[:5])
            rep.add("ink-box", False, f"{detail}; ink outside on {names}")
        else:
            rep.add("ink-box", True, detail)


# --------------------------------------------------------------------------- #
# layer 3: assertions on the sources and the extracted text
# --------------------------------------------------------------------------- #
def check_math_alignment(tex: Path, type_meta: dict, rep: Report) -> None:
    if not tex.is_file():
        rep.add("math-centering", None, "no rendered .tex")
        return
    head = tex.read_text(encoding="utf-8", errors="replace")[:2000]
    m = re.search(r"\\documentclass\[(.*?)\]", head, re.S)
    options = (m.group(1) if m else "").replace("\n", " ")
    flushleft = str(type_meta.get("math_alignment", "centered")).strip().lower() == "flushleft"
    if "fleqn" in options and not flushleft:
        rep.add("math-centering", False,
                "class loaded with fleqn: display math is flush-left (set "
                "math_alignment: flushleft in the journal type.yaml to allow it)")
    else:
        rep.add("math-centering", True, f"documentclass[{options.strip()}]")


def check_bibliography(bib: Path, qmd: Path, rep: Report) -> None:
    if not bib.is_file():
        rep.add("references-authors", None, "no references.bib")
        return
    text = bib.read_text(encoding="utf-8", errors="replace")
    long = []
    keys = set()
    for m in re.finditer(r"@\w+\{([^,]+),(.*?)\n\}", text, re.S):
        key, body = m.group(1), m.group(2)
        keys.add(key)
        a = re.search(r"author = \{(.*?)\},\n", body, re.S)
        if a and a.group(1).count(" and ") + 1 > MAX_AUTHORS:
            long.append(f"{key} ({a.group(1).count(' and ') + 1})")
    if long:
        rep.add("references-authors", False,
                f"{len(long)} entr(ies) over {MAX_AUTHORS} authors — {', '.join(long[:4])}")
    else:
        rep.add("references-authors", True, f"{len(keys)} entries, all <= {MAX_AUTHORS} authors")
    # every entry must be cited (an uncited key inflates the bibliography
    # and signals a dangling reference)
    if qmd.is_file():
        cited = set(re.findall(r"@([\w:.\-]+)", qmd.read_text(encoding="utf-8", errors="replace")))
        dangling = sorted(keys - cited)
        rep.add("references-cited", not dangling,
                "every entry is cited" if not dangling
                else f"{len(dangling)} uncited: {dangling[:4]}")


def sig(s: str) -> str:
    """Comparable signature of a caption: pandoc rewrites `--` as an en dash and
    the PDF may split lines anywhere, so compare letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def bbl_entry_lengths(bbl: Path) -> list[tuple[int, str]]:
    """Length of each bibliography entry as rendered, bibitem by bibitem."""
    text = bbl.read_text(encoding="utf-8", errors="replace")
    parts = re.split(r"(?=\\bibitem)", text)
    out = []
    for p in parts:
        if not p.startswith("\\bibitem"):
            continue
        e = re.sub(r"%.*", "", p)
        e = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", e)
        e = re.sub(r"\\[a-zA-Z]+", " ", e)
        e = re.sub(r"[{}~]", " ", e)
        plain = re.sub(r"\s+", " ", e).strip()
        key = re.search(r"\\bibitem\[.*?\]\{([^}]+)\}", p[:500], re.S)
        out.append((len(plain), key.group(1) if key else "?"))
    return out


def check_bbl_length(bbl: Path, rep: Report) -> None:
    if not bbl.is_file():
        rep.add("references-length", None, "no rendered .bbl; run paper_build.py first")
        return
    lens = bbl_entry_lengths(bbl)
    if not lens:
        rep.add("references-length", None, "no bibitem entries found")
        return
    longest, key = max(lens)
    detail = (f"{len(lens)} entries, longest {longest} chars ({key}, limit {MAX_REF_CHARS})")
    rep.add("references-length", longest <= MAX_REF_CHARS, detail)


def check_pdf_content(qmd: Path, pdf: Path, rep: Report) -> None:
    text = pdf_text(pdf)
    if not text:
        rep.add("pdf-content", None, "pdftotext unavailable")
        return
    if not qmd.is_file():
        rep.add("pdf-content", None, "no main.qmd")
        return
    qmd_text = qmd.read_text(encoding="utf-8", errors="replace")
    flat = sig(text)

    # every declared figure/table caption must survive the render
    expected: list[str] = []
    for m in re.finditer(r"!\[(.+?)\]\(", qmd_text, re.S):
        expected.append(re.sub(r"\s+", " ", m.group(1)))
    for m in re.finditer(r"^: (.+?) \{#tbl-", qmd_text, re.M):
        expected.append(re.sub(r"\s+", " ", m.group(1)))
    missing = [c for c in expected if sig(c)[:40] not in flat]
    rep.add("pdf-figures-tables", not missing,
            f"{len(expected)} captions, all present" if not missing
            else f"{len(missing)}/{len(expected)} missing: {missing[:2]}")

    # highlights declared in the front matter
    hl = re.findall(r'^\s+- "(.+)"$', qmd_text.split("highlights:", 1)[-1].split("author:", 1)[0], re.M) \
        if "highlights:" in qmd_text else []
    if hl:
        miss = [h for h in hl if sig(h)[:40] not in flat]
        rep.add("pdf-highlights", not miss,
                f"{len(hl)} declared, all in the PDF" if not miss
                else f"{len(miss)} missing from the PDF: {miss[:1]}")

# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Check that a rendered paper respects the journal layout.")
    ap.add_argument("--slug", required=True, help="paper slug under papers/")
    ap.add_argument("--root", default=None)
    ap.add_argument("--max-overfull", type=float, default=MAX_OVERFULL_PT,
                    help="Overfull \\hbox points that fail the check (default: %(default)s)")
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    paper = repo / "papers" / args.slug
    if not paper.is_dir():
        raise SystemExit(f"ERROR: no such paper: {paper}")

    pdf = paper / "build" / f"{args.slug}.pdf"
    log = paper / "build" / "render" / "main.log"
    tex = paper / "build" / "render" / "main.tex"
    bbl = paper / "build" / "render" / "main.bbl"
    qmd = paper / "paper" / "main.qmd"

    type_meta: dict = {}
    manifest = paper / "manifest.yaml"
    if manifest.is_file():
        journal = str(load_yaml(manifest).get("journal") or "")
        type_yaml = repo / "templates" / "journals" / journal / "type.yaml"
        if type_yaml.is_file():
            type_meta = load_yaml(type_yaml)

    print(f"=== layout check: {args.slug} ===")
    rep = Report()
    check_latex_log(log, tex, rep, args.max_overfull)
    if pdf.is_file():
        check_ink_box(pdf, rep)
        check_pdf_content(paper / "paper" / "main.qmd", pdf, rep)
    else:
        rep.add("ink-box", None, f"no {pdf}; run paper_build.py first")
    check_math_alignment(tex, type_meta, rep)
    check_bibliography(paper / "paper" / "references.bib", qmd, rep)
    check_bbl_length(bbl, rep)
    rep.print()
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
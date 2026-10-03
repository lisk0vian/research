"""Shared PDF comparison helpers (word boxes, lines, rasters, pixel diffs).

Used by scripts/cas_fidelity.py (specimen vs the official CAS sample) and
scripts/paper_parity.py (build PDF vs the DOCX rendered by Word vs the LaTeX
zip). Needs Poppler's pdftotext (-bbox) and pdftoppm; Pillow for the rasters.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

PAGE_RE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">')
WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">'
    r"([^<]*)</word>"
)

# (text, xMin, yMin, xMax, yMax) in PDF points, origin top-left.
Word = tuple[str, float, float, float, float]

_BBOX_TOOL: str | None = None


def run(cmd: list[str], cwd: Path | None = None,
        timeout: float | None = None) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          errors="replace", timeout=timeout)
    return proc.returncode, proc.stdout + proc.stderr


def find_bbox_tool(probe: Path) -> str | None:
    """Some PATHs (Git for Windows) provide an Xpdf pdftotext without -bbox;
    probe every candidate against `probe` and return the first that works."""
    global _BBOX_TOOL  # noqa: PLW0603
    if _BBOX_TOOL is not None:
        return _BBOX_TOOL
    if os.name == "nt":
        rc, out = run(["where", "pdftotext"])
    else:
        rc, out = run(["sh", "-c", "which -a pdftotext"])
    candidates = [line.strip() for line in out.splitlines() if line.strip()] \
        if rc == 0 else []
    if shutil.which("pdftotext"):
        candidates.append(shutil.which("pdftotext") or "")
    for cand in dict.fromkeys(candidates):
        # "-" is the output file in xpdf/Poppler pdftotext and means stdout.
        rc, out = run([cand, "-bbox", str(probe), "-"])
        if rc == 0 and "<page" in out:
            _BBOX_TOOL = cand
            return cand
    return None


def _bbox_xml(pdf: Path) -> str:
    exe = find_bbox_tool(pdf)
    if exe is None:
        raise RuntimeError("no pdftotext with -bbox support on PATH")
    rc, out = run([exe, "-bbox", str(pdf), "-"])
    if rc != 0:
        raise RuntimeError(f"pdftotext -bbox failed for {pdf}")
    return out


def _pages(xml: str):
    pos = 0
    while True:
        m = PAGE_RE.search(xml, pos)
        if not m:
            return
        end = xml.find("</page>", m.end())
        yield m, xml[m.end(): end if end != -1 else len(xml)]
        pos = end if end != -1 else len(xml)


def word_boxes(pdf: Path) -> list[list[Word]]:
    """Words of every page, in pdftotext reading order."""
    return [
        [(w.group(5), float(w.group(1)), float(w.group(2)),
          float(w.group(3)), float(w.group(4)))
         for w in WORD_RE.finditer(region)]
        for _m, region in _pages(_bbox_xml(pdf))
    ]


def page_sizes(pdf: Path) -> list[tuple[float, float]]:
    return [(float(m.group(1)), float(m.group(2)))
            for m, _r in _pages(_bbox_xml(pdf))]


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"',
                         "”": '"', " ": " ", "−": "-"})


def norm(word: str) -> str:
    """Compare words, not glyph choices: NFKC splits ligatures (fi, fl), and
    curly quotes/minus signs become ASCII."""
    return unicodedata.normalize("NFKC", word).translate(_QUOTES)


def lines_of(words: list[Word], y_tol: float = 2.0) -> list[list[Word]]:
    """Group a page's words into text lines: a new line starts when the word
    moves to another baseline or jumps back to the left."""
    lines: list[list[Word]] = []
    for w in words:
        if lines:
            last = lines[-1][-1]
            same_row = abs(w[4] - last[4]) <= y_tol
            if same_row and w[1] >= last[1] - 1:
                lines[-1].append(w)
                continue
        lines.append([w])
    return lines


def rasterize(pdf: Path, dpi: int, out_dir: Path, prefix: str,
              crop: tuple[float, float, float, float] | None = None) -> list[Path]:
    """PNG per page; crop = (x, y, w, h) in PDF points selects a page box."""
    extra: list[str] = []
    if crop is not None:
        k = dpi / 72
        extra = ["-x", str(round(crop[0] * k)), "-y", str(round(crop[1] * k)),
                 "-W", str(round(crop[2] * k)), "-H", str(round(crop[3] * k))]
    rc, out = run(["pdftoppm", "-r", str(dpi), "-png", *extra, str(pdf),
                   str(out_dir / prefix)])
    if rc != 0:
        raise RuntimeError(f"pdftoppm failed for {pdf}: {out[-300:]}")
    return sorted(out_dir.glob(f"{prefix}-*.png"))


def ink(img, threshold: int = 160):
    """Binary ink mask (255 = ink) of an RGB/L page raster."""
    return img.convert("L").point(lambda v: 255 if v < threshold else 0)


def compare_rasters(a, b) -> dict:
    """Pixel metrics between two same-size page rasters.

    hard        pixels differing by >= 96/255 in any channel (a missing glyph,
                a moved figure); sub-pixel AA jitter stays below it.
    raw         pixels differing by >= 32/255.
    structural  XOR of the ink masks after a 3x3 dilation, i.e. ink present in
                one page and not near the same spot in the other.
    """
    from PIL import ImageChops, ImageFilter

    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    hist = diff.histogram()
    ia, ib = ink(a), ink(b)
    da = ia.filter(ImageFilter.MaxFilter(3))
    db = ib.filter(ImageFilter.MaxFilter(3))
    struct = ImageChops.logical_xor(da.convert("1"), db.convert("1")).convert("L")
    return {
        "total": a.size[0] * a.size[1],
        "hard": sum(hist[96:]),
        "raw": sum(hist[32:]),
        "max_delta": max((i for i in range(256) if hist[i]), default=0),
        "structural": struct.histogram()[255],
        "struct_img": struct,
        "ink_a": ia,
        "ink_b": ib,
    }


def overlay(ink_a, ink_b):
    """RGB overlay: black = ink in both, red = only a, blue = only b."""
    from PIL import Image, ImageChops

    both = ImageChops.logical_and(ink_a.convert("1"), ink_b.convert("1")).convert("L")
    only_a = ImageChops.subtract(ink_a, both)
    only_b = ImageChops.subtract(ink_b, both)
    white = Image.new("L", ink_a.size, 255)
    r = ImageChops.subtract(white, ImageChops.add(both, only_b))
    g = ImageChops.subtract(white, ImageChops.add(ImageChops.add(both, only_a), only_b))
    bl = ImageChops.subtract(white, ImageChops.add(both, only_a))
    return Image.merge("RGB", (r, g, bl))


def side_by_side(a, b, gap: int = 12):
    from PIL import Image

    w = a.size[0] + b.size[0] + gap
    h = max(a.size[1], b.size[1])
    out = Image.new("RGB", (w, h), (128, 128, 128))
    out.paste(a.convert("RGB"), (0, 0))
    out.paste(b.convert("RGB"), (a.size[0] + gap, 0))
    return out

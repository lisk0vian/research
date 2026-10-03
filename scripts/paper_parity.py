#!/usr/bin/env python3
"""paper_parity.py — measure how close a paper's DOCX and LaTeX zip are to its PDF.

The PDF that `paper_build.py` renders (pdfLaTeX, cas-sc) is the reference.
Two candidates are compared against it:

  latex-zip  build/<slug>-latex.zip compiled standalone (pdflatex, bibtex,
             pdflatex x2). Strict: same pages, same words, word boxes within
             0.5 pt and no hard pixel differences. Proves the submission
             source reproduces the PDF exactly.

  docx       build/<slug>.docx converted to PDF by Microsoft Word (COM, the
             renderer co-authors use) or LibreOffice (--renderer libreoffice,
             or automatically when Word is missing). An editable DOCX cannot
             match pdfTeX pixel for pixel (Word breaks lines greedily and
             hyphenates differently), so it is measured by levels:

               L0 structure  page size and page count
               L1 pages      every word on the same page as in the PDF
               L2 lines      share of PDF lines Word breaks identically
               L3 geometry   p95 of the word position delta (pt), same page
               L4 pixels     ink XOR after dilation, % of the page area

Thresholds live in templates/journals/<journal>/type.yaml under `parity:`
(defaults below). Artefacts go to papers/<slug>/build/parity/:
report.json, the converted PDFs, and per page `page-NN-side.png`
(PDF | candidate) and `page-NN-overlay.png` (black = both, red = PDF only,
blue = candidate only).

Usage:
  python scripts/paper_parity.py --slug c26-2026
  python scripts/paper_parity.py --slug c26-2026 --build --renderer word
  python scripts/paper_parity.py --slug c26-2026 --only docx --dpi 100
Exit 1 when any threshold fails.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pdfdiff import (  # noqa: E402
    compare_rasters, lines_of, norm, overlay, page_sizes, rasterize, run,
    side_by_side, word_boxes,
)
from _repo import find_repo_root, load_yaml  # noqa: E402

DEFAULTS = {
    "docx": {
        "page_word_match_min": 1.0,   # L1: share of matched words on the same page
        "line_match_min": 0.90,       # L2
        "word_delta_p95_max_pt": 3.0,  # L3
        "ink_xor_max_pct": 2.0,       # L4 (mean over pages)
    },
    "latex_zip": {
        "word_delta_max_pt": 0.5,
        "hard_px_max": 0,
    },
}

# Word prints through "Microsoft Print to PDF": ExportAsFixedFormat mislabels
# fonts installed per user (STIX, LM) as Calibri with Calibri's /Widths, which
# breaks text extraction; the printer driver embeds the real OpenType fonts.
WORD_PS = r"""
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
$prev = $w.ActivePrinter
try {
  $w.ActivePrinter = 'Microsoft Print to PDF'
  $d = $w.Documents.Open($env:PARITY_DOCX, $false, $true, $false)
  $d.Fields.Update() | Out-Null
  foreach ($s in $d.Sections) {
    foreach ($h in $s.Headers) { $h.Range.Fields.Update() | Out-Null }
    foreach ($f in $s.Footers) { $f.Range.Fields.Update() | Out-Null }
  }
  $d.Repaginate()
  # Background:=False, Append:=False, Range:=all, OutputFileName, ...,
  # PrintToFile:=True
  $d.PrintOut($false, $false, 0, $env:PARITY_PDF, '', '', 0, 1, '', 0, $true)
  $d.Close(0)
} finally {
  try { $w.ActivePrinter = $prev } catch {}
  $w.Quit()
}
"""


def find_soffice() -> str | None:
    if shutil.which("soffice"):
        return "soffice"
    for cand in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                 r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                 "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(cand).is_file():
            return cand
    return None


def word_available() -> bool:
    if os.name != "nt":
        return False
    return any(Path(p).is_file() for p in (
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files\Microsoft Office\Office16\WINWORD.EXE",
    ))


def docx_to_pdf(docx: Path, out_pdf: Path, renderer: str) -> str:
    """Convert with Word (COM) or LibreOffice; return the renderer used."""
    if renderer == "auto":
        renderer = "word" if word_available() else "libreoffice"
    if out_pdf.exists():
        out_pdf.unlink()
    if renderer == "word":
        env = dict(os.environ, PARITY_DOCX=str(docx.resolve()),
                   PARITY_PDF=str(out_pdf.resolve()))
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", WORD_PS],
            env=env, capture_output=True, text=True, errors="replace", timeout=600)
        if proc.returncode != 0 or not out_pdf.is_file():
            raise RuntimeError("Word conversion failed: "
                               + (proc.stdout + proc.stderr)[-600:])
        return "word"
    soffice = find_soffice()
    if soffice is None:
        raise RuntimeError("neither Word nor LibreOffice is available")
    with tempfile.TemporaryDirectory() as tmp:
        rc, out = run([soffice, "--headless", "--convert-to", "pdf",
                       "--outdir", tmp, str(docx)], timeout=600)
        produced = Path(tmp) / (docx.stem + ".pdf")
        if rc != 0 or not produced.is_file():
            raise RuntimeError(f"LibreOffice conversion failed: {out[-600:]}")
        shutil.move(str(produced), out_pdf)
    return "libreoffice"


def tex_bin_dir() -> Path | None:
    """The TeX distribution Quarto renders with: its TinyTeX when installed
    (quarto prefers it over PATH), otherwise whatever is on PATH (None).
    Compiling the zip with another distribution compares two TeX setups (e.g.
    a MiKTeX without the cm-super map embeds bitmap Type 3 fonts), not the zip."""
    roots = []
    if os.name == "nt" and os.environ.get("APPDATA"):
        roots.append(Path(os.environ["APPDATA"]) / "TinyTeX" / "bin" / "windows")
    home = Path.home()
    roots += [home / ".TinyTeX" / "bin" / "x86_64-linux",
              home / "Library" / "TinyTeX" / "bin" / "universal-darwin"]
    for root in roots:
        if any((root / n).is_file() for n in ("pdflatex", "pdflatex.exe")):
            return root
    return None


def compile_latex_zip(zip_path: Path, out_pdf: Path) -> None:
    """Compile the submission zip standalone with Quarto's TeX distribution."""
    bin_dir = tex_bin_dir()

    def exe(name: str) -> str:
        return str(bin_dir / name) if bin_dir else name

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(work)
        engine = [exe("pdflatex"), "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
        steps = [engine]
        # The zip ships main.bbl; run bibtex only when it does not.
        if not (work / "main.bbl").is_file():
            steps += [[exe("bibtex"), "main"]]
        steps += [engine, engine]
        for cmd in steps:
            rc, out = run(cmd, cwd=work, timeout=600)
            if rc != 0 and "bibtex" not in cmd[0]:
                raise RuntimeError(f"{' '.join(cmd)} failed: {out[-800:]}")
        shutil.copyfile(work / "main.pdf", out_pdf)


# ---------------------------------------------------------------------------
# text levels
# ---------------------------------------------------------------------------

def flat_words(pages: list[list[tuple]]) -> list[tuple[str, int, tuple]]:
    """(normalized word, page index, box) for the whole document, with words
    hyphenated across lines joined back and hyphens dropped from the key, so
    TeX's and Word's different hyphenation does not count as different text."""
    out: list[tuple[str, int, tuple]] = []
    for pno, words in enumerate(pages):
        lines = lines_of(words)
        carry: tuple[str, int, tuple] | None = None
        for line in lines:
            for i, w in enumerate(line):
                text = norm(w[0])
                if carry is not None and i == 0:
                    out.append(((carry[0] + text).replace("-", ""), carry[1], carry[2]))
                    carry = None
                    continue
                last = i == len(line) - 1
                if (last and len(text) > 2 and text.endswith("-")
                        and text[-2].isalpha()):
                    carry = (text[:-1], pno, w[1:])
                    continue
                out.append((text.replace("-", "") or text, pno, w[1:]))
        if carry is not None:
            out.append((carry[0] + "-", carry[1], carry[2]))
    return out


def line_keys(pages: list[list[tuple]]) -> list[tuple[str, ...]]:
    return [tuple(norm(w[0]) for w in line)
            for words in pages for line in lines_of(words)]


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def text_levels(ref_pages, cand_pages) -> dict:
    a = flat_words(ref_pages)
    b = flat_words(cand_pages)
    sm = difflib.SequenceMatcher(None, [w[0] for w in a], [w[0] for w in b],
                                 autojunk=False)
    matched = same_page = 0
    deltas: list[float] = []
    first_moved = None
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            wa, wb = a[blk.a + k], b[blk.b + k]
            matched += 1
            if wa[1] == wb[1]:
                same_page += 1
                dx = abs(wa[2][0] - wb[2][0])
                dy = abs(wa[2][3] - wb[2][3])
                deltas.append(max(dx, dy))
            elif first_moved is None:
                first_moved = {"word": wa[0], "pdf_page": wa[1] + 1,
                               "candidate_page": wb[1] + 1}
    la, lb = line_keys(ref_pages), line_keys(cand_pages)
    lsm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    lines_matched = sum(blk.size for blk in lsm.get_matching_blocks())
    # first opcode that is not "equal": where the text itself diverges
    first_text_diff = None
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            first_text_diff = {
                "pdf_page": a[i1][1] + 1 if i1 < len(a) else None,
                "pdf": " ".join(w[0] for w in a[i1:min(i2, i1 + 8)]),
                "candidate": " ".join(w[0] for w in b[j1:min(j2, j1 + 8)]),
            }
            break
    return {
        "words_pdf": len(a),
        "words_candidate": len(b),
        "word_coverage": matched / max(len(a), len(b), 1),
        "page_word_match": same_page / max(matched, 1),
        "first_moved_word": first_moved,
        "first_text_difference": first_text_diff,
        "lines_pdf": len(la),
        "lines_candidate": len(lb),
        "line_match": lines_matched / max(len(la), 1),
        "word_delta_median_pt": statistics.median(deltas) if deltas else 0.0,
        "word_delta_p95_pt": p95(deltas),
        "word_delta_max_pt": max(deltas) if deltas else 0.0,
    }


# ---------------------------------------------------------------------------
# pixel level
# ---------------------------------------------------------------------------

def page_offset(ref_pdf: Path, cand_pdf: Path) -> tuple[float, float] | None:
    """Where the reference page box sits on the candidate's sheet. "Microsoft
    Print to PDF" only knows standard paper: it prints the 544x743 pt CAS
    page centred horizontally at the top of a Letter sheet."""
    sa, sb = page_sizes(ref_pdf), page_sizes(cand_pdf)
    if not sa or not sb:
        return None
    (wa, ha), (wb, hb) = sa[0], sb[0]
    if abs(wa - wb) <= 0.5 and abs(ha - hb) <= 0.5:
        return None
    return ((wb - wa) / 2, 0.0)


def shifted(pages, offset):
    if offset is None:
        return pages
    dx, dy = offset
    return [[(w[0], w[1] - dx, w[2] - dy, w[3] - dx, w[4] - dy) for w in p]
            for p in pages]


def pixel_level(ref_pdf: Path, cand_pdf: Path, dpi: int, out_dir: Path,
                tag: str) -> dict:
    from PIL import Image

    pages = []
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        ra = rasterize(ref_pdf, dpi, t, "ref")
        off = page_offset(ref_pdf, cand_pdf)
        crop = None
        if off is not None:
            w, h = page_sizes(ref_pdf)[0]
            crop = (off[0], off[1], w, h)
        rb = rasterize(cand_pdf, dpi, t, "cand", crop)
        for i in range(max(len(ra), len(rb))):
            if i >= len(ra) or i >= len(rb):
                pages.append({"page": i + 1, "missing_in":
                              "pdf" if i >= len(ra) else tag})
                continue
            a = Image.open(ra[i]).convert("RGB")
            b = Image.open(rb[i]).convert("RGB")
            if b.size != a.size:  # 544.2 vs 544.252 pt can round to 1 px
                b = b.resize(a.size)
            m = compare_rasters(a, b)
            nn = f"{i + 1:02d}"
            side_by_side(a, b).save(out_dir / f"{tag}-page-{nn}-side.png")
            overlay(m["ink_a"], m["ink_b"]).save(
                out_dir / f"{tag}-page-{nn}-overlay.png")
            pages.append({
                "page": i + 1,
                "ink_xor_pct": round(100.0 * m["structural"] / m["total"], 3),
                "hard_px": m["hard"],
                "raw_px": m["raw"],
            })
    scored = [p for p in pages if "ink_xor_pct" in p]
    return {
        "pages": pages,
        "ink_xor_mean_pct": round(statistics.mean(
            p["ink_xor_pct"] for p in scored), 3) if scored else 100.0,
        "hard_px_total": sum(p["hard_px"] for p in scored),
    }


# ---------------------------------------------------------------------------
# suites
# ---------------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.rows.append((name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.rows)

    def print(self) -> None:
        print("=== paper parity report ===")
        for name, ok, detail in self.rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name} - {detail}")
        print("  RESULT:", "OK" if self.ok else "FAILED")


def structure(ref_pdf: Path, cand_pdf: Path) -> dict:
    sa, sb = page_sizes(ref_pdf), page_sizes(cand_pdf)
    size_ok = bool(sa and sb) and all(
        abs(x[0] - y[0]) <= 0.5 and abs(x[1] - y[1]) <= 0.5
        for x, y in zip(sa[:1], sb[:1]))
    if not size_ok and page_offset(ref_pdf, cand_pdf) is not None:
        # printed on a larger standard sheet: compared inside the page box
        size_ok = sb[0][0] >= sa[0][0] and sb[0][1] >= sa[0][1]
    return {"pages_pdf": len(sa), "pages_candidate": len(sb),
            "page_size_pdf": sa[0] if sa else None,
            "page_size_candidate": sb[0] if sb else None,
            "page_size_ok": size_ok}


def run_docx(ref_pdf: Path, docx: Path, out_dir: Path, renderer: str,
             dpi: int, th: dict, rep: Report) -> dict:
    cand = out_dir / "docx.pdf"
    used = docx_to_pdf(docx, cand, renderer)
    st = structure(ref_pdf, cand)
    tx = text_levels(word_boxes(ref_pdf),
                     shifted(word_boxes(cand), page_offset(ref_pdf, cand)))
    px = pixel_level(ref_pdf, cand, dpi, out_dir, "docx")
    rep.add("docx L0 structure",
            st["page_size_ok"] and st["pages_pdf"] == st["pages_candidate"],
            f"pages {st['pages_pdf']} vs {st['pages_candidate']} ({used}); "
            f"page size {'ok' if st['page_size_ok'] else 'differs'}")
    moved = tx["first_moved_word"]
    rep.add("docx L1 pages", tx["page_word_match"] >= th["page_word_match_min"],
            f"{100 * tx['page_word_match']:.1f}% of words on the same page "
            f"(min {100 * th['page_word_match_min']:.0f}%); text coverage "
            f"{100 * tx['word_coverage']:.1f}%"
            + (f"; first moved: {moved['word']!r} p{moved['pdf_page']}"
               f"->p{moved['candidate_page']}" if moved else ""))
    rep.add("docx L2 lines", tx["line_match"] >= th["line_match_min"],
            f"{100 * tx['line_match']:.1f}% of lines identical "
            f"(min {100 * th['line_match_min']:.0f}%)")
    rep.add("docx L3 geometry",
            tx["word_delta_p95_pt"] <= th["word_delta_p95_max_pt"],
            f"word delta median {tx['word_delta_median_pt']:.2f} / "
            f"p95 {tx['word_delta_p95_pt']:.2f} pt "
            f"(max {th['word_delta_p95_max_pt']} pt)")
    rep.add("docx L4 pixels", px["ink_xor_mean_pct"] <= th["ink_xor_max_pct"],
            f"ink XOR {px['ink_xor_mean_pct']:.2f}% of page area "
            f"(max {th['ink_xor_max_pct']}%)")
    return {"renderer": used, "structure": st, "text": tx, "pixels": px}


def run_latex_zip(ref_pdf: Path, zip_path: Path, out_dir: Path, dpi: int,
                  th: dict, rep: Report) -> dict:
    cand = out_dir / "latex-zip.pdf"
    compile_latex_zip(zip_path, cand)
    st = structure(ref_pdf, cand)
    ra, rb = word_boxes(ref_pdf), word_boxes(cand)
    same_words = [[w[0] for w in p] for p in ra] == [[w[0] for w in p] for p in rb]
    worst = 0.0
    if same_words:
        for pa, pb in zip(ra, rb):
            for wa, wb in zip(pa, pb):
                worst = max(worst, abs(wa[1] - wb[1]), abs(wa[2] - wb[2]))
    px = pixel_level(ref_pdf, cand, dpi, out_dir, "zip")
    ok = (st["pages_pdf"] == st["pages_candidate"] and same_words
          and worst <= th["word_delta_max_pt"]
          and px["hard_px_total"] <= th["hard_px_max"])
    rep.add("latex-zip identical", ok,
            f"pages {st['pages_pdf']} vs {st['pages_candidate']}; "
            f"words {'same' if same_words else 'DIFFER'}; "
            f"max word delta {worst:.3f} pt; hard px {px['hard_px_total']}")
    return {"structure": st, "same_words": same_words,
            "word_delta_max_pt": worst, "pixels": px}


def thresholds(repo: Path, slug: str) -> dict:
    th = {k: dict(v) for k, v in DEFAULTS.items()}
    manifest = repo / "papers" / slug / "manifest.yaml"
    journal = load_yaml(manifest).get("journal") if manifest.is_file() else None
    type_yaml = repo / "templates" / "journals" / str(journal) / "type.yaml"
    if journal and type_yaml.is_file():
        for suite, values in (load_yaml(type_yaml).get("parity") or {}).items():
            th.setdefault(suite, {}).update(values or {})
    return th


def main() -> int:
    # Windows consoles default to cp1252; words from the paper can be anything.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--build", action="store_true",
                    help="run paper_build.py --format all first")
    ap.add_argument("--only", choices=["docx", "latex-zip"])
    ap.add_argument("--renderer", default="auto",
                    choices=["auto", "word", "libreoffice"])
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    repo = Path(args.root).resolve() if args.root else find_repo_root()
    build = repo / "papers" / args.slug / "build"
    if args.build:
        rc = subprocess.call([sys.executable, str(repo / "scripts" / "paper_build.py"),
                              "--slug", args.slug, "--format", "all"])
        if rc != 0:
            return rc
    ref_pdf = build / f"{args.slug}.pdf"
    if not ref_pdf.is_file():
        raise SystemExit(f"ERROR: {ref_pdf} missing (run paper_build.py first)")
    out_dir = build / "parity"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    th = thresholds(repo, args.slug)
    rep = Report()
    result: dict = {"slug": args.slug, "reference": ref_pdf.name,
                    "thresholds": th}
    if args.only in (None, "latex-zip"):
        zip_path = build / f"{args.slug}-latex.zip"
        if zip_path.is_file():
            result["latex_zip"] = run_latex_zip(
                ref_pdf, zip_path, out_dir, args.dpi, th["latex_zip"], rep)
        else:
            rep.add("latex-zip identical", False, f"{zip_path.name} missing")
    if args.only in (None, "docx"):
        docx = build / f"{args.slug}.docx"
        if docx.is_file():
            result["docx"] = run_docx(ref_pdf, docx, out_dir, args.renderer,
                                      args.dpi, th["docx"], rep)
        else:
            rep.add("docx L0 structure", False, f"{docx.name} missing")
    result["ok"] = rep.ok
    result["checks"] = [{"name": n, "ok": o, "detail": d} for n, o, d in rep.rows]
    (out_dir / "report.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    rep.print()
    print(f"  artefacts: {out_dir}")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

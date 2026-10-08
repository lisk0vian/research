# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Automatic checks for the paper figures (stage 11).

A figure drawn by code can be wrong in ways no exception reports: a point
outside the axes, a legend over the data, two labels on top of each other, a
canvas half empty, text cut at the edge, a NaN that silently drops a series.
Each check returns a list of problems (empty = passes); `Report` collects them
per figure for `qa.json` / `qa.md`. Three kinds:

- data: finite values, expected counts, agreement between independently
  computed tables;
- rendering, on the drawn matplotlib figure: size, clipping, legend overlap,
  text overlap and cut-off, minimum font size;
- image, on the saved PNG: dpi, not blank, white margins.

`simulate_cvd` and `grayscale` write the versions the human review looks at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from _figstyle import MM

PX_TOL = 1.0          # display pixels of slack for overlap and clipping tests
MIN_FONT_PT = 6.0
MAX_MARGIN = 0.06     # white border allowed on each side, as a share of the canvas


# --- data ----------------------------------------------------------------------------------

def check_finite(df, cols: list[str]) -> list[str]:
    bad = []
    for c in cols:
        v = np.asarray(df[c], dtype=float)
        n = int((~np.isfinite(v)).sum())
        if n:
            bad.append(f"{n} non-finite value(s) in plotted column `{c}`")
    return bad


def check_count(df, expected: int, what: str) -> list[str]:
    return [] if len(df) == expected else [f"expected {expected} {what}, got {len(df)}"]


def check_agree(a, b, on: list[str], col_a: str, col_b: str, tol: float, what: str) -> list[str]:
    """Two tables computed by different stages must give the same number."""
    m = a[on + [col_a]].merge(b[on + [col_b]], on=on, suffixes=("_a", "_b"))
    ca = col_a if col_a != col_b else f"{col_a}_a"
    cb = col_b if col_a != col_b else f"{col_b}_b"
    if m.empty:
        return [f"{what}: no common rows to compare"]
    diff = np.abs(m[ca].to_numpy(float) - m[cb].to_numpy(float))
    worst = float(np.nanmax(diff))
    return [] if worst <= tol else [f"{what}: tables disagree by up to {worst:.4g} (tol {tol})"]


# --- rendering -------------------------------------------------------------------------------

def _draw(fig):
    """Lay the figure out once; every rendering check reads the same layout."""
    renderer = getattr(fig, "_qa_renderer", None)
    if renderer is None:
        fig.canvas.draw()
        renderer = fig._qa_renderer = fig.canvas.get_renderer()
    return renderer


def check_size(fig, width_mm: float, max_height_mm: float) -> list[str]:
    w, h = (v / MM for v in fig.get_size_inches())
    out = []
    if abs(w - width_mm) > 0.5:
        out.append(f"width {w:.1f} mm, expected {width_mm:.0f} mm")
    if h > max_height_mm + 0.5:
        out.append(f"height {h:.1f} mm exceeds the {max_height_mm:.0f} mm limit")
    return out


def _data_points(ax) -> np.ndarray:
    """Display coordinates of every plotted data vertex in `ax`."""
    from matplotlib.collections import LineCollection, PathCollection
    from matplotlib.lines import Line2D

    pts = []
    for ln in ax.get_lines():
        if not isinstance(ln, Line2D) or not ln.get_visible() or ln.get_transform() != ax.transData:
            continue
        # get_xydata(): unit-converted floats (dates become day numbers).
        xy = np.asarray(ln.get_xydata(), float)
        pts.append(xy[np.isfinite(xy).all(axis=1)])
    for col in ax.collections:
        if not col.get_visible():
            continue
        if isinstance(col, PathCollection) and col.get_offset_transform() == ax.transData:
            xy = np.asarray(col.get_offsets(), float)
            pts.append(xy[np.isfinite(xy).all(axis=1)])
        elif isinstance(col, LineCollection) and col.get_transform() == ax.transData:
            for seg in col.get_segments():
                # An error bar on a NaN point is an empty segment, shape (0,).
                seg = np.asarray(seg, float).reshape(-1, 2)
                pts.append(seg[np.isfinite(seg).all(axis=1)])
    pts = [p for p in pts if len(p)]
    if not pts:
        return np.empty((0, 2))
    return ax.transData.transform(np.vstack(pts))


def check_clipping(fig) -> list[str]:
    """No data vertex may fall outside its axes (it would be silently cut)."""
    _draw(fig)
    out = []
    for i, ax in enumerate(fig.axes):
        if not ax.get_visible() or getattr(ax, "name", "") != "rectilinear":
            continue
        pts = _data_points(ax)
        if not len(pts):
            continue
        bb = ax.bbox
        outside = ((pts[:, 0] < bb.x0 - PX_TOL) | (pts[:, 0] > bb.x1 + PX_TOL)
                   | (pts[:, 1] < bb.y0 - PX_TOL) | (pts[:, 1] > bb.y1 + PX_TOL))
        if outside.any():
            out.append(f"axes {i}: {int(outside.sum())} data point(s) outside the axes limits")
    return out


def check_legend_overlap(fig) -> list[str]:
    renderer = _draw(fig)
    legends = list(fig.legends) + [ax.get_legend() for ax in fig.axes if ax.get_legend()]
    out = []
    for leg in legends:
        bb = leg.get_window_extent(renderer)
        for i, ax in enumerate(fig.axes):
            pts = _data_points(ax)
            if not len(pts):
                continue
            inside = ((pts[:, 0] > bb.x0 + PX_TOL) & (pts[:, 0] < bb.x1 - PX_TOL)
                      & (pts[:, 1] > bb.y0 + PX_TOL) & (pts[:, 1] < bb.y1 - PX_TOL))
            if inside.any():
                out.append(f"legend covers {int(inside.sum())} data point(s) of axes {i}")
    return out


def _texts(fig):
    """Every text that is actually drawn.

    Tick labels need care: an axis keeps Text objects for ticks outside its view
    interval, with stale positions, which would report overlaps that are not on
    the page. Only labels of ticks inside the view are kept.
    """
    from matplotlib.text import Text

    tick_texts, drawn_ticks = set(), []
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            locs = axis.get_majorticklocs()
            lo, hi = sorted(axis.get_view_interval())
            span = (hi - lo) or 1.0
            for tick, loc in zip(axis.get_major_ticks(len(locs)), locs):
                for lab in (tick.label1, tick.label2):
                    tick_texts.add(id(lab))
                    if (lab.get_visible() and lab.get_text().strip()
                            and lo - 1e-9 * span <= loc <= hi + 1e-9 * span):
                        drawn_ticks.append(lab)
            for tick in axis.get_minor_ticks():
                tick_texts.update((id(tick.label1), id(tick.label2)))
    seen = [t for t in fig.findobj(Text)
            if id(t) not in tick_texts and t.get_visible() and t.get_text().strip()]
    return seen + drawn_ticks


def check_text(fig) -> list[str]:
    """Texts must not overlap each other, leave the canvas, or be under 6 pt."""
    from matplotlib.text import Text

    renderer = _draw(fig)
    texts = _texts(fig)
    fb = fig.bbox
    boxes, out = [], []
    for t in texts:
        if t.get_fontsize() < MIN_FONT_PT - 1e-6:
            out.append(f"text {t.get_text()!r} is {t.get_fontsize():.1f} pt (< {MIN_FONT_PT})")
        # An Annotation's extent includes its arrow; only the text can collide.
        bb = Text.get_window_extent(t, renderer)
        if bb.width <= 0 or bb.height <= 0:
            continue
        if (bb.x0 < fb.x0 - PX_TOL or bb.x1 > fb.x1 + PX_TOL
                or bb.y0 < fb.y0 - PX_TOL or bb.y1 > fb.y1 + PX_TOL):
            out.append(f"text {t.get_text()!r} is cut at the figure edge")
        boxes.append((t, bb))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ti, a), (tj, b) = boxes[i], boxes[j]
            w = min(a.x1, b.x1) - max(a.x0, b.x0)
            h = min(a.y1, b.y1) - max(a.y0, b.y0)
            if w > PX_TOL and h > PX_TOL:
                out.append(f"texts overlap: {ti.get_text()!r} and {tj.get_text()!r}")
    return out


def check_drawn(fig, values, axis: str = "y", tol: float = 1e-9) -> list[str]:
    """Every value in `values` (the CSV of the figure) is somewhere on the canvas.

    `axis` is the coordinate that carries the values (x for a forest plot).
    """
    k = 0 if axis == "x" else 1
    drawn = []
    for ax in fig.axes:
        pts = _data_points(ax)
        if len(pts):
            drawn.append(ax.transData.inverted().transform(pts)[:, k])
        for p in ax.patches:  # bars
            try:
                drawn.append(np.array([p.get_x() + p.get_width() if k == 0
                                       else p.get_y() + p.get_height()]))
            except AttributeError:
                continue
    if not drawn:
        return ["nothing drawn"]
    d = np.concatenate(drawn)
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    missing = [x for x in v if not np.any(np.abs(d - x) <= max(tol, 1e-9 * abs(x)) + 1e-12)]
    return [f"{len(missing)} plotted value(s) not found on the canvas"] if missing else []


def check_glyphs(caught) -> list[str]:
    """Characters the font cannot draw become empty boxes on the page."""
    msgs = sorted({str(w.message) for w in caught if "missing from font" in str(w.message)})
    return [f"font cannot draw a character: {m}" for m in msgs]


# --- image -------------------------------------------------------------------------------------

def check_image(path: Path, min_dpi: int = 300) -> list[str]:
    from PIL import Image

    out = []
    with Image.open(path) as im:
        dpi = im.info.get("dpi", (0, 0))[0]
        if round(dpi) < min_dpi:
            out.append(f"{path.name}: {dpi:.0f} dpi (< {min_dpi})")
        a = np.asarray(im.convert("L"), dtype=float)
    if a.std() < 1.0:
        out.append(f"{path.name}: image is blank")
        return out
    ink = a < 250
    rows, cols = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
    h, w = a.shape
    margins = {"top": rows[0] / h, "bottom": (h - 1 - rows[-1]) / h,
               "left": cols[0] / w, "right": (w - 1 - cols[-1]) / w}
    for side, m in margins.items():
        if m > MAX_MARGIN:
            out.append(f"{path.name}: {m:.0%} empty margin on the {side} (> {MAX_MARGIN:.0%})")
    return out


# Machado, Oliveira & Fernandes (2009), deuteranopia at severity 1.0, linear RGB.
_DEUTAN = np.array([[0.367322, 0.860646, -0.227968],
                    [0.280085, 0.672501, 0.047413],
                    [-0.011820, 0.042940, 0.968881]])


def _to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)


def simulate_cvd(src: Path, dst: Path) -> Path:
    from PIL import Image
    with Image.open(src) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=float) / 255.0
        dpi = im.info.get("dpi")
    sim = _to_srgb(_to_linear(rgb) @ _DEUTAN.T)
    Image.fromarray((sim * 255).round().astype("uint8")).save(dst, dpi=dpi)
    return dst


def grayscale(src: Path, dst: Path) -> Path:
    from PIL import Image
    with Image.open(src) as im:
        dpi = im.info.get("dpi")
        im.convert("L").save(dst, dpi=dpi)
    return dst


def contact_sheet(rows: list[tuple[str, list[Path]]], dst: Path, thumb_w: int = 700) -> Path:
    """One row per figure: original, deuteranopia, grayscale."""
    from PIL import Image, ImageDraw

    thumbs = []
    for name, paths in rows:
        ims = []
        for p in paths:
            with Image.open(p) as im:
                im = im.convert("RGB")
                ims.append(im.resize((thumb_w, max(1, int(im.height * thumb_w / im.width)))))
        thumbs.append((name, ims))
    pad, head = 12, 28
    width = pad + len(rows[0][1]) * (thumb_w + pad) if rows else 100
    height = pad + sum(head + max(i.height for i in ims) + pad for _, ims in thumbs)
    sheet = Image.new("RGB", (width, max(height, 50)), "white")
    draw = ImageDraw.Draw(sheet)
    y = pad
    for name, ims in thumbs:
        draw.text((pad, y + 6), name + "   [original | deuteranopia | grayscale]", fill="black")
        y += head
        x = pad
        for im in ims:
            sheet.paste(im, (x, y))
            x += thumb_w + pad
        y += max(i.height for i in ims) + pad
    sheet.save(dst)
    return dst


# --- report ----------------------------------------------------------------------------------------

@dataclass
class Report:
    figures: dict = field(default_factory=dict)

    def add(self, name: str, problems: list[str], files: list[str] | None = None,
            notes: list[str] | None = None) -> None:
        entry = self.figures.setdefault(name, {"problems": [], "files": [], "notes": []})
        entry["problems"].extend(problems)
        entry["files"].extend(files or [])
        entry["notes"].extend(notes or [])

    @property
    def failed(self) -> list[str]:
        return [n for n, e in self.figures.items() if e["problems"]]

    def write(self, folder: Path) -> tuple[Path, Path]:
        js = folder / "qa.json"
        js.write_text(json.dumps({"figures": self.figures, "failed": self.failed}, indent=2,
                                 ensure_ascii=False), encoding="utf-8")
        lines = ["# Figure QA", "", "| figure | result | problems |", "|---|---|---|"]
        for n, e in self.figures.items():
            res = "FAIL" if e["problems"] else "ok"
            lines.append(f"| {n} | {res} | {'; '.join(e['problems']) or '—'} |")
        notes = [(n, x) for n, e in self.figures.items() for x in e["notes"]]
        if notes:
            lines += ["", "## Notes", ""] + [f"- **{n}**: {x}" for n, x in notes]
        md = folder / "qa.md"
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return js, md

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""One visual style for every paper figure (stage 10).

Sizes are in millimetres and match the Elsevier CAS single-column page the
manuscript is set on (cas-sc, 164.6 mm text block). Full-width figures are
drawn at 164 mm and inserted at width=1; one-column figures at 90 mm,
inserted at width=0.55. A figure is drawn at its final size, so 7 pt here is
7 pt on the page. Palettes are colour-blind safe (Okabe-Ito, viridis samples)
and every category also differs in lightness, so a figure reads in grayscale.
"""

from __future__ import annotations

MM = 1 / 25.4
SINGLE_MM = 90.0
DOUBLE_MM = 164.0
# A diagram stays under a third of the ~240 mm text block, a map or chart under
# ~40 %, so a figure never forces a page break that leaves white space behind.
MAX_HEIGHT_MM = {"diagram": 80.0, "chart": 100.0, "map": 110.0, "single": 100.0}

# Travel-time classes (minutes), light to dark = good to poor access.
TIME_BINS = [0, 30, 60, 120, float("inf")]
TIME_LABELS = ["≤30 min", "30–60 min", "60–120 min", ">120 min"]
TIME_COLORS = ["#ffffcc", "#a1dab4", "#41b6c4", "#225ea8"]

# Altitude bands (m), fixed in analysis plan v14; viridis samples, ordered.
ALT_BINS = [-float("inf"), 500, 2500, 3500, float("inf")]
ALT_LABELS = ["<500 m", "500–2,500 m", "2,500–3,500 m", "≥3,500 m"]
ALT_COLORS = ["#fde725", "#35b779", "#31688e", "#440154"]

# Agreement between two deficient-access classifications.
AGREE = {
    "both": ("Deficient by both", "#222222"),
    "time_only": ("Travel time only", "#D55E00"),
    "distance_only": ("Straight line only", "#0072B2"),
    "neither": ("Neither", "#E6E6E6"),
}

# Need x access quadrants (stage 05 labels).
QUADRANT = {
    "high_need_poor_access": ("High need, deficient access", "#D55E00"),
    "low_need_poor_access": ("Low need, deficient access", "#E69F00"),
    "high_need_good_access": ("High need, adequate access", "#56B4E9"),
    "low_need_good_access": ("Low need, adequate access", "#E6E6E6"),
}

MAP_NOTE = ("Map lines delineate study areas and do not necessarily depict "
            "accepted national boundaries.")


def setup():
    """matplotlib with the paper style; Agg, so it runs headless on Colab."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"],
        "font.size": 7, "axes.labelsize": 7, "axes.titlesize": 7,
        "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "axes.grid": False, "axes.axisbelow": True,
        "legend.frameon": False,
        "mathtext.default": "regular", "figure.dpi": 150, "savefig.dpi": 300,
        # Elsevier wants embedded TrueType fonts in vector files.
        "pdf.fonttype": 42, "ps.fonttype": 42,
        "figure.constrained_layout.use": True,
        "figure.constrained_layout.h_pad": 2 / 72, "figure.constrained_layout.w_pad": 2 / 72,
    })
    return plt


def figure(plt, width_mm: float, height_mm: float, **kw):
    return plt.subplots(figsize=(width_mm * MM, height_mm * MM), **kw)


def panel_letter(ax, letter: str, x: float = -0.02, y: float = 1.02) -> None:
    """Bold (a), (b)... at the top left, outside the data."""
    ax.text(x, y, f"({letter})", transform=ax.transAxes, fontsize=8, fontweight="bold",
            ha="right", va="bottom")


def map_axes(ax) -> None:
    """A map panel: equal aspect, no ticks or frame."""
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)

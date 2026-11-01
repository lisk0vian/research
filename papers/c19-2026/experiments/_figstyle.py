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

# Altitude bands (m), fixed in analysis plan v14. Viridis at 0.80/0.55/0.30/0.00:
# L* 76/58/39/15, evenly spaced and without the pale-yellow end that vanishes on white.
ALT_BINS = [-float("inf"), 500, 2500, 3500, float("inf")]
ALT_LABELS = ["<500 m", "500–2,500 m", "2,500–3,500 m", "≥3,500 m"]
ALT_COLORS = ["#7ad151", "#1e9c89", "#355f8d", "#440154"]

# Agreement between two deficient-access classifications.
AGREE = {
    "both": ("Deficient by both", "#222222"),
    "time_only": ("Travel time only", "#D55E00"),
    "distance_only": ("Straight line only", "#0072B2"),
    "neither": ("Neither", "#E6E6E6"),
}

# Need x access quadrants (stage 05 labels): the 2 x 2 bivariate scheme of
# J. Stevens, L* 34/55/75/92, so the high-need, deficient class is the darkest and
# the order survives grayscale and deuteranopia.
QUADRANT = {
    "high_need_poor_access": ("High need, deficient access", "#3b4994"),
    "low_need_poor_access": ("Low need, deficient access", "#be64ac"),
    "high_need_good_access": ("High need, adequate access", "#5ac8c8"),
    "low_need_good_access": ("Low need, adequate access", "#e8e8e8"),
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
    """A map panel: equal aspect, no ticks, frame or axis labels.

    Call it after plotting: geopandas labels lon/lat axes from the CRS
    ("Geodetic longitude [degree]"), which a map panel without ticks must not show.
    """
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)


def degrees_for_km(km: float, lat: float) -> float:
    """East-west length in degrees of `km` at latitude `lat` (spherical Earth)."""
    import math
    return km / (111.32 * math.cos(math.radians(lat)))


def map_furniture(ax, km: float = 200.0, x: float = 0.04, y: float = 0.96) -> None:
    """Scale bar (true at the map's mid-latitude) and north arrow, top left.

    On these lon/lat maps the top-left corner is outside Peru (Ecuador), so the
    furniture never covers data. The scale holds within about 4 % across Peru.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    ax.set_xlim(x0, x1)  # freeze the view: the bar must not move the autoscale
    ax.set_ylim(y0, y1)
    length = degrees_for_km(km, (y0 + y1) / 2)
    bx, by = x0 + x * (x1 - x0), y0 + y * (y1 - y0)
    ax.plot([bx, bx + length], [by, by], color="#333333", lw=1.2, solid_capstyle="butt",
            zorder=6)
    ax.text(bx + length / 2, by - 0.012 * (y1 - y0), f"{km:,.0f} km", ha="center", va="top",
            fontsize=6, color="#333333", zorder=6)
    ax_x = (bx + length - x0) / (x1 - x0) + 0.07
    ax.annotate("", xy=(ax_x, y), xytext=(ax_x, y - 0.06), xycoords="axes fraction",
                arrowprops={"arrowstyle": "-|>", "color": "#333333", "lw": 0.8,
                            "mutation_scale": 6}, zorder=6)
    ax.text(ax_x, y + 0.004, "N", transform=ax.transAxes, ha="center", va="bottom",
            fontsize=6.5, color="#333333", zorder=6)


def plain_log_axis(axis) -> None:
    """Log axis labelled 1, 10, 100, 1,000 instead of 10^0, 10^1 ..."""
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
    axis.set_major_locator(LogLocator(base=10))
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}"))
    axis.set_minor_formatter(NullFormatter())

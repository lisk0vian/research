# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""One visual style for every paper figure (stage 11).

Sizes are in millimetres and match the page the manuscript is set on: the
Elsevier CAS single-column class (cas-sc, required by EAAI) has a 164.6 mm
text block (192 mm paper, 13.7 mm side margins). Full-width figures are drawn
at 164 mm and inserted at width=1 (	extwidth); one-column figures at 90 mm,
inserted at width=0.55. A figure is drawn at its final size, so nothing is
rescaled in layout and 7 pt here is 7 pt on the page.

Hierarchy is by colour weight, not by legend order: the systems the paper is
about (the CFSv2 hybrid, M*2) are saturated and drawn thicker; references and
single models are muted. Each model also has its own marker, so a figure still
reads in grayscale or with a colour-vision deficiency.
"""

from __future__ import annotations

MM = 1 / 25.4
SINGLE_MM = 90.0
DOUBLE_MM = 164.0   # cas-sc text width (164.6 mm)
# Max heights: a diagram stays under a third of the ~240 mm text block, so it
# never pushes a page break that leaves white space behind it.
MAX_HEIGHT_MM = {"diagram": 80.0, "chart": 90.0, "single": 80.0}

HORIZONS = ["W1", "W2", "W3_4"]
HORIZON_LABEL = {"W1": "Week 1", "W2": "Week 2", "W3_4": "Weeks 3–4"}
# Sequential tones for horizons when a figure colours by lead time.
HORIZON_TONE = {"W1": "#9ecae1", "W2": "#4292c6", "W3_4": "#08519c"}

LABEL = {
    "Ridge_LG@CFS": "Hybrid (Ridge LG + CFSv2)",
    "Ridge_LG@cfsrows": "Hybrid control (no CFSv2)",
    "GBM_LG@CFS": "Hybrid GBM (GBM LG + CFSv2)",
    "Blend_CFS_Mstar": "Blend (CFSv2 + M*)",
    "Mstar2": "M*$_2$ (calibrated ensemble)",
    "Ensemble": "M* (ensemble)",
    "Ensemble+k": "M* + spread factor",
    "CFS_BC": "CFSv2 (bias-corrected)",
    "Ridge_LG": "Ridge LG",
    "Ridge_L": "Ridge L",
    "GBM_LG": "GBM LG",
    "GBM_L": "GBM L",
    "LSTM_LG": "LSTM LG",
    "Chronos": "Chronos (raw)",
    "Chronos@abs": "Chronos (absolute context)",
    "ChronosBolt": "Chronos-Bolt",
    "Damp": "Damped persistence",
    "M* (reference)": "M* (reference)",
    "Clim": "Climatology",
}

# Okabe-Ito plus Tol's wine/indigo; vermillion and blue carry the message.
COLOR = {
    "Ridge_LG@CFS": "#D55E00",
    "Mstar2": "#0072B2",
    "Ensemble": "#56B4E9",
    "Ensemble+k": "#6FA8D6",
    "Blend_CFS_Mstar": "#AA4499",
    "CFS_BC": "#882255",
    "Ridge_LG": "#009E73",
    "Ridge_L": "#4DAF8C",
    "GBM_LG": "#E69F00",
    "GBM_L": "#C58A00",
    "GBM_LG@CFS": "#B07800",
    "Ridge_LG@cfsrows": "#BBBBBB",
    "LSTM_LG": "#CC79A7",
    "Chronos": "#BBBBBB",
    "Chronos@abs": "#999933",
    "ChronosBolt": "#44AA99",
    "Damp": "#777777",
    "Clim": "#AAAAAA",
}
# No left/right triangles: on a line across horizons they read as arrows.
# The L variants share their LG family's marker; colour and dashes tell them apart.
MARKER = {
    "Ridge_LG@CFS": "o", "Mstar2": "s", "Ensemble": "D", "Ensemble+k": "d",
    "Blend_CFS_Mstar": "8", "CFS_BC": "^", "Ridge_LG": "v", "Ridge_L": "v",
    "GBM_LG": "P", "GBM_L": "P", "GBM_LG@CFS": "X", "Ridge_LG@cfsrows": "x",
    "LSTM_LG": "X", "Chronos": "H", "Chronos@abs": "h", "ChronosBolt": "p",
    "Damp": "*", "Clim": ".",
}
HERO = {"Ridge_LG@CFS", "Mstar2"}
REFERENCE = {"Damp", "Clim", "CFS_BC"}


def label(model: str) -> str:
    return LABEL.get(model, model)


def color(model: str) -> str:
    return COLOR.get(model, "#555555")


def weight(model: str) -> dict:
    """Line/marker weight by role: heroes stand out, the rest recede."""
    if model in HERO:
        return {"lw": 1.8, "ms": 5.5, "alpha": 1.0, "zorder": 5}
    if model in REFERENCE:
        return {"lw": 1.0, "ms": 4.0, "alpha": 0.95, "zorder": 3}
    return {"lw": 0.9, "ms": 3.6, "alpha": 0.85, "zorder": 2}


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
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#E6E6E6",
        "grid.linewidth": 0.5, "axes.axisbelow": True,
        "legend.frameon": False,
        # Subscripts ($_2$) in the text font, not in a mathtext face.
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


def spread(values: list[float], min_gap: float) -> list[float]:
    """Positions for direct labels: same order as `values`, at least `min_gap` apart.

    Exact, not iterative: sorted labels are pushed apart in one forward pass,
    then the whole column is shifted so its mean displacement is zero, which
    keeps a crowded group centred on its data.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    want = [values[i] for i in order]
    pos = list(want)
    for k in range(1, len(pos)):
        pos[k] = max(pos[k], pos[k - 1] + min_gap)
    shift = sum(w - p for w, p in zip(want, pos)) / max(len(pos), 1)
    out = [0.0] * len(values)
    for k, i in enumerate(order):
        out[i] = pos[k] + shift
    return out

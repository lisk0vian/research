# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 10: the manuscript's figures and tables, from outputs/ only.

Figures (PNG at 300 dpi + vector PDF + the CSV of what each one plots):
  Fig1_workflow     data, measurement, checks and the three questions (Graphviz;
                    skipped with a note when `dot` is not installed)
  Fig2_access       travel time over populated cells + population within t minutes
  Fig3_methods      where straight-line distance and travel time disagree, and why
  Fig4_need_access  need x access quadrant membership
  Fig5_rq3          odds ratios per +60 min: H3a, sensitivities, cause groups
  FigA1_osrm        friction travel time vs OSRM routing time, by stratum
Tables (CSV + ready-to-paste Markdown, so no number is typed by hand):
  table2_equity, table3_engine, table4_rq2, tableA2_simulation, tableA3_ml,
  tableA4_h3b, tableA4b_unknown_cause

Every figure goes through the automatic checks in `_figqa.py` (size, text,
clipping, legend overlap, glyphs, dpi, margins) and gets deuteranopia and
grayscale copies plus a contact sheet. A cosmetic finding is listed in qa.md
for the visual review; only a figure or table that cannot be produced at all
fails the stage.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _figqa as qa  # noqa: E402
import _figstyle as st  # noqa: E402
from _access import _kappa, _matched_flags, bootstrap_spearman  # noqa: E402
from _paths import OUTPUTS, SEED_BASE, normalizar_cadena  # noqa: E402

RESULTS_VERSION = 3  # v3: Fig 1 need node inside RQ1 (v2: map labels/scale bar, bivariate key, tables)

IN2 = OUTPUTS / "02_geo_inputs"
REG = OUTPUTS / "02_regions"
IN3 = OUTPUTS / "03_access_travel_time"
IN4 = OUTPUTS / "04_access_sensitivity"
IN5 = OUTPUTS / "05_need_priority"
IN8 = OUTPUTS / "08_validation_models"
IN9 = OUTPUTS / "09_ml_checks"
OUT = OUTPUTS / "10_figures_tables"
TABLES = OUT / "tables"
QA_DIR = OUT / "qa"
AMAZON_DEPTS = {"AMAZONAS", "LORETO", "MADRE DE DIOS", "SAN MARTIN", "UCAYALI"}  # G1 proxy
THRESHOLD = 60.0
# Drawing only: 0.005 deg (~0.5 km) is ~0.03 mm on the printed maps and shrinks the
# vector PDFs from ~13 MB; every number comes from the tables, never from geometry.
SIMPLIFY_DEG = 0.005


# --- pure helpers (tested in tests/test_c19_figures.py) -----------------------------------

def altitude_band(altitude) -> pd.Series:
    """Altitude bands fixed in analysis plan v14."""
    return pd.cut(pd.Series(altitude, dtype=float), st.ALT_BINS, labels=st.ALT_LABELS,
                  right=False)


def equity_table(access: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    """Person-weighted access by Amazon basin x altitude band, with totals."""
    d = access.merge(regions[["ubigeo", "mean_altitude", "amazon"]], on="ubigeo", how="left")
    d = d[d["population"] > 0].copy()
    d["band"] = altitude_band(d["mean_altitude"]).astype(str).to_numpy()
    d["basin"] = np.where(d["amazon"].fillna(False).astype(bool), "Amazon basin", "Outside basin")

    def row(g: pd.DataFrame, basin: str, band: str) -> dict:
        p = g["population"].sum()
        return {"basin": basin, "altitude_band": band, "districts": int(len(g)),
                "population_millions": p / 1e6,
                "mean_min": float((g["mean_min"] * g["population"]).sum() / p),
                "pct_over_60": 100 * float((g["share_over_60"] * g["population"]).sum() / p),
                "pct_over_120": 100 * float((g["share_over_120"] * g["population"]).sum() / p)}

    rows = []
    for basin in ("Outside basin", "Amazon basin"):
        sub = d[d["basin"] == basin]
        if not len(sub):
            continue
        for band in st.ALT_LABELS:
            g = sub[sub["band"] == band]
            if len(g):
                rows.append(row(g, basin, band))
        rows.append(row(sub, basin, "All"))
    rows.append(row(d, "Peru", "All"))
    return pd.DataFrame(rows)


def agreement_classes(main_min, variant, threshold: float = THRESHOLD):
    """Deficient by travel time (> threshold) vs the variant flagging as many districts.

    Returns the class per district and the variant's cut value (e.g. the km
    distance that flags as many districts as 60 minutes does).
    """
    a = np.asarray(main_min, dtype=float)
    b = np.asarray(variant, dtype=float)
    da = a > threshold
    db = _matched_flags(b, int(da.sum()))
    cut = float(b[db].min()) if db.any() else float("nan")
    cls = np.select([da & db, da & ~db, ~da & db], ["both", "time_only", "distance_only"],
                    "neither")
    return cls, cut


def weighted_cdf(times, weights, t_grid) -> np.ndarray:
    """Share (%) of the weight with travel time <= t, for every t in t_grid."""
    t = np.asarray(times, dtype=float)
    w = np.asarray(weights, dtype=float)
    order = np.argsort(t)
    t, w = t[order], np.cumsum(w[order])
    idx = np.searchsorted(t, t_grid, side="right")
    return 100.0 * np.where(idx > 0, w[np.maximum(idx - 1, 0)], 0.0) / w[-1]


def to_markdown(df: pd.DataFrame, formats: dict | None = None) -> str:
    """Pipe table for Quarto; `formats` maps a column to a format spec or a callable."""
    formats = formats or {}

    def cell(col, v):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return "—"
        f = formats.get(col)
        if callable(f):
            return f(v)
        if f:
            return format(v, f)
        return str(v)

    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(cell(c, v) for c, v in zip(df.columns, r)) + " |"
            for r in df.itertuples(index=False)]
    return "\n".join([head, sep, *body]) + "\n"


def ci_text(value, lo, hi, digits: int = 3) -> str:
    return f"{value:.{digits}f} ({lo:.{digits}f}–{hi:.{digits}f})"


LATEX_SAFE = {"≥": r"$\geq$", "≤": r"$\leq$", "κ": r"$\kappa$", "Δ": r"$\Delta$"}


def latex_safe(text: str) -> str:
    """Symbols pdfLaTeX cannot typeset from UTF-8 become inline math (CSV keeps them)."""
    for k, v in LATEX_SAFE.items():
        text = text.replace(k, v)
    return text


# --- inputs -------------------------------------------------------------------------------------

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_inputs() -> dict:
    import geopandas as gpd
    g = np.load(IN2 / "grid.npz")
    gdf = gpd.read_file(IN2 / "districts.gpkg")
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)  # the travel-time raster is on a lon/lat grid
    outline = gdf.dissolve().boundary.simplify(SIMPLIFY_DEG)  # dissolve first: no slivers
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_DEG, preserve_topology=True)
    return {
        "grid": {k: g[k] for k in g.files},
        "times": np.load(IN3 / "access_times.npz")["times"],
        "gdf": gdf,
        "outline": outline,
        "access": pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str}),
        "regions": pd.read_csv(REG / "districts_regions.csv", dtype={"ubigeo": str}),
        "osm_strata": pd.read_csv(REG / "osm_stratified.csv"),
        "hospitals": pd.read_csv(IN3 / "hospitals_audit.csv", dtype={"ubigeo": str}),
        "pilot": pd.read_csv(IN3 / "osm_pilot.csv", dtype={"ubigeo": str}),
        "variants": pd.read_csv(IN4 / "district_variants.csv", dtype={"ubigeo": str}),
        "stability": pd.read_csv(IN4 / "stability.csv"),
        "priority": pd.read_csv(IN5 / "district_priority.csv", dtype={"ubigeo": str}),
        "s8": read_json(IN8 / "summary.json"),
        "unknown": pd.read_csv(IN8 / "unknown_cause_by_place_time.csv"),
        "calibration": read_json(IN9 / "calibration.json"),
        "predictive": read_json(IN9 / "predictive.json"),
    }


# --- figures -------------------------------------------------------------------------------------

class Fig:
    """A drawn figure plus what QA needs to judge it."""

    def __init__(self, name, fig=None, data=None, kind="chart", width=st.DOUBLE_MM,
                 problems=None, notes=None, image=None):
        self.name, self.fig, self.data, self.kind, self.width = name, fig, data, kind, width
        self.problems, self.notes = list(problems or []), list(notes or [])
        self.image = image  # (png bytes, pdf bytes) for figures not drawn by matplotlib


def _legend_patches(items):
    from matplotlib.patches import Patch
    return [Patch(facecolor=c, edgecolor="#999999", linewidth=0.3, label=l) for l, c in items]


WORKFLOW_DOT = r"""
digraph G {
  graph [rankdir=LR, fontname="Helvetica", fontsize=9, nodesep=0.18, ranksep=0.3,
         size="6.4,2.1!", ratio=compress, margin=0, pad=0.02, dpi=300];
  node  [shape=box, style="rounded,filled", fillcolor="#F2F2F2", color="#888888",
         fontname="Helvetica", fontsize=8, margin="0.06,0.03", height=0.3];
  edge  [color="#666666", arrowsize=0.5, penwidth=0.7];
  subgraph cluster_data { label="Data"; fontsize=8; color="#BBBBBB"; style=rounded;
    ren [label="RENIPRESS 2026\npublic complex hospitals"];
    pop [label="Census 2025 +\nWorldPop 2025"];
    fri [label="MAP friction 2020\n(motorized, walking)"];
    sin [label="SINADEF deaths\n2022–2025"]; }
  subgraph cluster_measure { label="Measurement (RQ1)"; fontsize=8; color="#BBBBBB"; style=rounded;
    grid [label="30-arcsec grid:\ncensus-scaled population"];
    dij  [label="Multi-source Dijkstra:\nminutes per cell"];
    dis  [label="Person-weighted\ndistrict travel time", fillcolor="#FCE3D2"];
    need [label="Need × access quadrants\n(census 60+, disability)"];
    {rank=same; dis; need;} }
  subgraph cluster_checks { label="Checks and sensitivity (RQ2)"; fontsize=8; color="#BBBBBB"; style=rounded;
    osrm [label="OSRM routing\n(convergent check)"];
    var  [label="Straight line, centre cell,\n2SFCA, destinations, walking"]; }
  subgraph cluster_out { label="External test (RQ3)"; fontsize=8; color="#BBBBBB"; style=rounded;
    glm [label="Logistic GLM, department FE,\ndistrict-cluster SEs"];
    sim [label="Placebo, GEE,\nknown-truth simulation"]; }
  pop -> grid; fri -> dij; ren -> dij; grid -> dij; dij -> dis; dis -> need;
  dis -> osrm; dis -> var; dis -> glm; sin -> glm; glm -> sim;
}
"""


def fig1_workflow() -> Fig:
    """Graphviz diagram; rendered only where `dot` exists (Colab ships it)."""
    (OUT / "Fig1_workflow.dot").write_text(WORKFLOW_DOT, encoding="utf-8")
    dot = shutil.which("dot")
    if not dot:
        return Fig("Fig1_workflow", kind="diagram",
                   notes=["`dot` not installed: only Fig1_workflow.dot was written"])
    png = subprocess.run([dot, "-Tpng"], input=WORKFLOW_DOT.encode(), capture_output=True,
                         check=True).stdout
    pdf = subprocess.run([dot, "-Tpdf"], input=WORKFLOW_DOT.encode(), capture_output=True,
                         check=True).stdout
    import io

    from PIL import Image
    with Image.open(io.BytesIO(png)) as im:
        w_mm, h_mm = (v / 300 * 25.4 for v in im.size)
        buf = io.BytesIO()
        im.save(buf, format="PNG", dpi=(300, 300))
    problems = []
    if w_mm > st.DOUBLE_MM + 0.5:
        problems.append(f"width {w_mm:.0f} mm exceeds {st.DOUBLE_MM:.0f} mm")
    if h_mm > st.MAX_HEIGHT_MM["diagram"] + 0.5:
        problems.append(f"height {h_mm:.0f} mm exceeds {st.MAX_HEIGHT_MM['diagram']:.0f} mm")
    data = pd.DataFrame({"width_mm": [round(w_mm, 1)], "height_mm": [round(h_mm, 1)]})
    return Fig("Fig1_workflow", data=data, kind="diagram", problems=problems,
               image=(buf.getvalue(), pdf))


def fig2_access(plt, x: dict) -> Fig:
    from matplotlib.colors import ListedColormap
    g, times = x["grid"], np.asarray(x["times"], dtype=float)
    pop, dist = np.asarray(g["population"], float), np.asarray(g["districts"])
    populated = (pop > 0) & (dist > 0)
    # right=True: <=30, (30, 60], (60, 120], >120, the same cut as the ">60 min" shares
    classes = np.digitize(np.where(np.isfinite(times), times, np.inf), [30, 60, 120],
                          right=True).astype(float)
    img = np.where(populated, classes, np.nan)
    west, north, res = float(g["west"]), float(g["north"]), float(g["res"])
    h, w = int(g["height"]), int(g["width"])
    extent = [west, west + w * res, north - h * res, north]

    fig, (ax, ax2) = st.figure(plt, st.DOUBLE_MM, 96, ncols=2,
                               gridspec_kw={"width_ratios": [1.0, 1.1]})
    cmap = ListedColormap(st.TIME_COLORS)
    cmap.set_bad((1, 1, 1, 0))
    ax.imshow(img, cmap=cmap, vmin=-0.5, vmax=3.5, extent=extent, interpolation="nearest")
    x["outline"].plot(ax=ax, color="#777777", linewidth=0.35)
    hosp = x["hospitals"][x["hospitals"]["status"] != "gross"]
    ax.scatter(hosp["lon"], hosp["lat"], s=2.5, c="#000000", linewidths=0, zorder=4)
    st.map_axes(ax)
    st.map_furniture(ax)
    from matplotlib.lines import Line2D
    handles = _legend_patches(list(zip(st.TIME_LABELS, st.TIME_COLORS)))
    handles.append(Line2D([], [], marker="o", color="none", markerfacecolor="#000000",
                          markersize=2.5, label="Public complex hospital"))
    ax.legend(handles=handles, loc="lower left", fontsize=6, handlelength=1.0)
    st.panel_letter(ax, "a", x=0.02)

    # (b) population within t minutes, by altitude band of the district
    alt = x["regions"].set_index("district_id")["mean_altitude"]
    band_of_id = altitude_band(alt.to_numpy()).astype(str)
    lookup = pd.Series(band_of_id.to_numpy(), index=alt.index)
    cell_band = pd.Series(dist[populated].astype(np.int64)).map(lookup).to_numpy()
    t_cells, w_cells = times[populated], pop[populated]
    t_grid = np.arange(0, 241, 1.0)
    rows = []
    ax2.plot(t_grid, weighted_cdf(t_cells, w_cells, t_grid), color="#000000", lw=1.6,
             label="Peru", zorder=5)
    rows += [{"band": "Peru", "t": t, "pct": v}
             for t, v in zip(t_grid, weighted_cdf(t_cells, w_cells, t_grid))]
    for label, color in zip(st.ALT_LABELS, st.ALT_COLORS):
        m = cell_band == label
        if not m.any():
            continue
        cdf = weighted_cdf(t_cells[m], w_cells[m], t_grid)
        ax2.plot(t_grid, cdf, color=color, lw=1.0, label=label)
        rows += [{"band": label, "t": t, "pct": v} for t, v in zip(t_grid, cdf)]
    for v in (60, 120):
        ax2.axvline(v, color="#999999", lw=0.6, ls="--", zorder=1)
    ax2.set_xlim(0, 240)
    ax2.set_ylim(0, 100)
    ax2.set_xticks([0, 30, 60, 120, 180, 240])
    ax2.set_xlabel("Travel time to the nearest public complex hospital (min)")
    ax2.set_ylabel("Population within that time (%)")
    ax2.grid(axis="y", color="#E6E6E6", lw=0.5)
    ax2.legend(loc="lower right")
    st.panel_letter(ax2, "b")
    return Fig("Fig2_access", fig=fig, data=pd.DataFrame(rows), kind="map",
               notes=[st.MAP_NOTE])


def fig3_methods(plt, x: dict) -> Fig:
    v = x["variants"].merge(x["regions"][["ubigeo", "mean_altitude"]], on="ubigeo", how="left")
    v = v[np.isfinite(v["main_min"]) & np.isfinite(v["popweighted_km"])].copy()
    cls, cut = agreement_classes(v["main_min"], v["popweighted_km"])
    v["agreement"] = cls
    v["band"] = altitude_band(v["mean_altitude"]).astype(str).to_numpy()

    fig, (ax, ax2) = st.figure(plt, st.DOUBLE_MM, 96, ncols=2,
                               gridspec_kw={"width_ratios": [1.0, 1.1]})
    gdf = x["gdf"].merge(v[["ubigeo", "agreement"]], on="ubigeo", how="left")
    gdf["agreement"] = gdf["agreement"].fillna("neither")
    for key, (label, color) in st.AGREE.items():
        part = gdf[gdf["agreement"] == key]
        if len(part):
            part.plot(ax=ax, color=color, linewidth=0)
    x["outline"].plot(ax=ax, color="#777777", linewidth=0.35)
    counts = v["agreement"].value_counts()
    ax.legend(handles=_legend_patches(
        [(f"{label} ({int(counts.get(key, 0))})", color) for key, (label, color) in st.AGREE.items()]),
        loc="lower left", fontsize=6, handlelength=1.0)
    st.map_axes(ax)
    st.map_furniture(ax)
    st.panel_letter(ax, "a", x=0.02)

    for label, color in zip(st.ALT_LABELS, st.ALT_COLORS):
        m = v["band"] == label
        ax2.scatter(v.loc[m, "popweighted_km"].clip(lower=0.1), v.loc[m, "main_min"].clip(lower=0.1),
                    s=3, color=color, alpha=0.8, linewidths=0, label=label)
    ax2.axhline(THRESHOLD, color="#999999", lw=0.6, ls="--")
    ax2.axvline(cut, color="#999999", lw=0.6, ls=":")
    ax2.set_xscale("log")
    ax2.set_yscale("log")
    st.plain_log_axis(ax2.xaxis)
    st.plain_log_axis(ax2.yaxis)
    ax2.annotate(f"{THRESHOLD:.0f} min", xy=(0, THRESHOLD), xycoords=("axes fraction", "data"),
                 xytext=(2, 2), textcoords="offset points", fontsize=6, color="#555555")
    ax2.annotate(f"{cut:.1f} km (matched)", xy=(cut, 1), xycoords=("data", "axes fraction"),
                 xytext=(2, -2), textcoords="offset points", ha="left", va="top", fontsize=6,
                 color="#555555")
    ax2.set_xlabel("Population-weighted straight-line distance (km, log scale)")
    ax2.set_ylabel("Person-weighted travel time (min, log scale)")
    ax2.legend(loc="lower right", markerscale=2.5, title="District mean altitude",
               title_fontsize=6.5)
    st.panel_letter(ax2, "b")
    data = v[["ubigeo", "main_min", "popweighted_km", "agreement", "band"]].assign(km_cut=cut)
    return Fig("Fig3_methods", fig=fig, data=data, kind="map",
               notes=[st.MAP_NOTE, f"matched straight-line cut: {cut:.1f} km"])


def bivariate_key(ax, cells: dict, rect=(0.11, 0.03, 0.27, 0.20)):
    """2 x 2 legend over the Pacific: need (rows) x travel time (columns).

    `cells` maps a quadrant key to (districts, % of people), printed in its square.
    The default box (lon ~-80.0 to -76.6, lat ~-17.8 to -14.2 on the Peru map) stays
    off the coast and leaves room inside the figure for the "Need" labels on its left.
    """
    from matplotlib.patches import Rectangle
    k = ax.inset_axes(rect)
    for row, need in enumerate(("low", "high")):          # bottom row: low need
        for col, acc in enumerate(("good", "poor")):      # right column: deficient access
            key = f"{need}_need_{acc}_access"
            _, color = st.QUADRANT[key]
            k.add_patch(Rectangle((col, row), 1, 1, facecolor=color, edgecolor="white", lw=0.8))
            n, pct = cells.get(key, (0, 0.0))
            k.text(col + 0.5, row + 0.5, f"{n:,}\n{pct:.1f} %", ha="center", va="center",
                   fontsize=6, linespacing=1.1,
                   color="white" if key == "high_need_poor_access" else "#222222")
    k.set_xlim(0, 2)
    k.set_ylim(0, 2)
    k.set_aspect("equal")
    k.set_xticks([0.5, 1.5], ["≤60", ">60"])
    k.set_yticks([0.5, 1.5], ["Low", "High"])
    k.set_xlabel("Travel time (min)", fontsize=6.5, labelpad=1)
    k.set_ylabel("Need", fontsize=6.5, labelpad=1)
    k.tick_params(length=0, labelsize=6, pad=1)
    for side in k.spines.values():
        side.set_visible(False)
    return k


def fig4_need_access(plt, x: dict) -> Fig:
    pr = x["priority"]
    width = 75.0  # Peru's lon/lat aspect at 108 mm high: no empty side margins
    fig, ax = st.figure(plt, width, 108)
    gdf = x["gdf"].merge(pr[["ubigeo", "quadrant"]], on="ubigeo", how="left")
    for key, (label, color) in st.QUADRANT.items():
        part = gdf[gdf["quadrant"] == key]
        if len(part):
            part.plot(ax=ax, color=color, linewidth=0)
    missing = gdf[gdf["quadrant"].isna()]
    if len(missing):  # no census need data (the one polygon without a census row)
        missing.plot(ax=ax, color="#FFFFFF", edgecolor="#BBBBBB", linewidth=0.2)
    x["outline"].plot(ax=ax, color="#777777", linewidth=0.35)
    total = pr["population"].sum()
    rows, cells = [], {}
    for key in st.QUADRANT:
        sub = pr[pr["quadrant"] == key]
        share = 100 * sub["population"].sum() / total
        rows.append({"quadrant": key, "districts": len(sub), "population_pct": share})
        cells[key] = (len(sub), share)
    st.map_axes(ax)
    st.map_furniture(ax)
    bivariate_key(ax, cells)
    return Fig("Fig4_need_access", fig=fig, data=pd.DataFrame(rows), kind="map",
               width=width, notes=[st.MAP_NOTE, "key cells: districts and % of people"])


def forest_rows(s8: dict) -> pd.DataFrame:
    """Odds ratios per +60 min in plotting order, from the stage-08 summary."""
    by = {r["cause_group"]: r for r in s8["h3b"]["by_cause"]}
    spec = [
        ("H3a: amenable causes (pre-specified)", s8["main"], "H3a"),
        ("  GEE, exchangeable (50,000-death sample)", s8["sensitivity_gee"], "H3a"),
        ("  Excluding low-completeness districts", s8["completeness_sensitivity"], "H3a"),
        ("  Excluding place 'other'", s8["exclude_otro"], "H3a"),
        ("  Period 2020–2021", s8["period_2020_2021"], "H3a"),
        ("H3b: amenable, acute", by.get("amenable_acute"), "H3b"),
        ("H3b: amenable, chronic", by.get("amenable_chronic"), "H3b"),
        ("Cancer (negative control)", by.get("cancer"), "Other groups"),
        ("External causes", by.get("external"), "Other groups"),
        ("Other causes", by.get("other"), "Other groups"),
        ("Unknown cause", by.get("unknown"), "Other groups"),
        ("All causes (exploratory)", s8["exploratory_all_causes"], "Exploratory"),
    ]
    rows = [{"label": lab, "group": grp, "n": int(r["n"]), "or_per_60": r["or_per_60"],
             "ci_low": r["ci_low"], "ci_high": r["ci_high"]}
            for lab, r, grp in spec if r and "or_per_60" in r]
    return pd.DataFrame(rows)


def fig5_rq3(plt, x: dict) -> Fig:
    s8 = x["s8"]
    rows = forest_rows(s8)
    planted = {p["or_planted"]: p for p in s8["simulation"]["planted"]}
    fig, (ax, axt) = st.figure(plt, st.DOUBLE_MM, 78, ncols=2, sharey=True,
                               gridspec_kw={"width_ratios": [3.0, 1.2]})
    y = np.arange(len(rows))[::-1]
    colors = {"H3a": "#D55E00", "H3b": "#0072B2", "Other groups": "#555555",
              "Exploratory": "#999999"}
    for yi, r in zip(y, rows.itertuples()):
        c = colors[r.group]
        ax.plot([r.ci_low, r.ci_high], [yi, yi], color=c, lw=1.0)
        ax.plot(r.or_per_60, yi, "o", color=c, ms=3.5)
        axt.text(0.0, yi, f"{ci_text(r.or_per_60, r.ci_low, r.ci_high)}   n = {r.n:,}",
                 transform=axt.get_yaxis_transform(), ha="left", va="center", fontsize=6)
    axt.axis("off")
    ax.axvline(1.0, color="#444444", lw=0.6)
    if 1.1 in planted:
        ax.axvline(1.1, color="#999999", lw=0.6, ls="--")
        ax.text(1.098, y.max() + 0.7, f"planted OR 1.10 (power {planted[1.1]['power']:.2f})",
                ha="right", va="bottom", fontsize=6, color="#555555")  # left of the line, not across it
    ax.set_yticks(y)
    ax.set_yticklabels(rows["label"])
    ax.set_ylim(-0.7, y.max() + 1.4)
    lo = min(0.94, rows["ci_low"].min() - 0.01)
    hi = max(1.12, rows["ci_high"].max() + 0.01)
    ax.set_xlim(lo, hi)
    ax.set_xlabel("Odds ratio of dying outside a health facility per +60 min of travel time")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    return Fig("Fig5_rq3", fig=fig, data=rows, kind="chart")


def figA1_osrm(plt, x: dict) -> Fig:
    p = x["pilot"].dropna(subset=["friction_min", "osm_min"]).merge(
        x["regions"][["ubigeo", "mean_altitude", "amazon"]], on="ubigeo", how="left")
    p["stratum"] = np.where(~p["amazon"].fillna(False).astype(bool), "Outside basin",
                            np.where(p["mean_altitude"] < 500, "Amazon basin, <500 m",
                                     "Amazon basin, ≥500 m"))
    p["sample"] = np.where(p["phase"] == "remote", "enriched", "pre-specified")
    fig, ax = st.figure(plt, st.SINGLE_MM, 82)
    # Colour and marker both differ, so the strata survive grayscale and deuteranopia.
    style = {"Outside basin": ("#0072B2", "o"), "Amazon basin, <500 m": ("#D55E00", "s"),
             "Amazon basin, ≥500 m": ("#E69F00", "^")}
    pos = p[(p["friction_min"] > 0) & (p["osm_min"] > 0)]  # a log axis cannot show zero
    for stratum, (color, marker) in style.items():
        for sample, face in (("pre-specified", color), ("enriched", "none")):
            m = (pos["stratum"] == stratum) & (pos["sample"] == sample)
            ax.scatter(pos.loc[m, "friction_min"], pos.loc[m, "osm_min"], s=7, marker=marker,
                       facecolors=face, edgecolors=color, linewidths=0.6,
                       label=f"{stratum}" if sample == "pre-specified" else None)
    lim = [float(min(pos["friction_min"].min(), pos["osm_min"].min())) / 1.5,
           float(max(pos["friction_min"].max(), pos["osm_min"].max())) * 1.5]
    ax.plot(lim, lim, color="#999999", lw=0.6, ls="--")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    st.plain_log_axis(ax.xaxis)
    st.plain_log_axis(ax.yaxis)
    ax.set_xlabel("Friction-surface travel time (min)")
    ax.set_ylabel("OSRM routing time (min)")
    ax.legend(loc="upper left", fontsize=6.5, title="Filled: pre-specified sample;\nhollow: enriched",
              title_fontsize=6.5, alignment="left")
    notes = [f"{len(p) - len(pos)} centroid(s) with a zero time are not drawn"] if len(pos) < len(p) else []
    return Fig("FigA1_osrm", fig=fig, data=p[["ubigeo", "phase", "stratum", "friction_min",
                                              "osm_min"]], kind="single", width=st.SINGLE_MM,
               notes=notes)


def save_and_check(f: Fig, report) -> list[Path]:
    png, pdf, csv = (OUT / f"{f.name}.{ext}" for ext in ("png", "pdf", "csv"))
    problems = list(f.problems)
    if f.data is not None:
        f.data.to_csv(csv, index=False)
    if f.fig is not None:
        import warnings

        import matplotlib.pyplot as plt
        limit = st.MAX_HEIGHT_MM.get(f.kind, st.MAX_HEIGHT_MM["chart"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            problems += qa.check_size(f.fig, f.width, limit)
            problems += qa.check_text(f.fig)
            problems += qa.check_clipping(f.fig)
            if f.kind != "map":  # map legends sit over empty ocean by design
                problems += qa.check_legend_overlap(f.fig)
            f.fig.savefig(png, dpi=300)
            f.fig.savefig(pdf)
        problems += qa.check_glyphs(caught)
        plt.close(f.fig)
    elif f.image is not None:
        png.write_bytes(f.image[0])
        pdf.write_bytes(f.image[1])
    else:
        report.add(f.name, [], [], f.notes)
        return []
    problems += qa.check_image(png)
    cvd = qa.simulate_cvd(png, QA_DIR / f"{f.name}_deuteranopia.png")
    gray = qa.grayscale(png, QA_DIR / f"{f.name}_grayscale.png")
    report.add(f.name, problems, [p.name for p in (png, pdf, csv) if p.exists()], f.notes)
    return [png, cvd, gray]


# --- tables -------------------------------------------------------------------------------------

def write_table(name: str, df: pd.DataFrame, formats: dict | None = None, note: str = "") -> None:
    df.to_csv(TABLES / f"{name}.csv", index=False)
    text = to_markdown(df, formats)
    if note:
        text += f"\n{note}\n"
    (TABLES / f"{name}.md").write_text(latex_safe(text), encoding="utf-8")


def table2(x: dict) -> None:
    t = equity_table(x["access"], x["regions"])
    t.columns = ["Basin", "Altitude band", "Districts", "Population (millions)",
                 "Mean travel time (min)", "Population >60 min (%)", "Population >120 min (%)"]
    write_table("table2_equity", t, {"Districts": ",", "Population (millions)": ".2f",
                                     "Mean travel time (min)": ".1f",
                                     "Population >60 min (%)": ".1f",
                                     "Population >120 min (%)": ".1f"},
                note="Person-weighted values over populated grid cells; post hoc and descriptive (plan v13/v14).")


def _spearman_row(label: str, d: pd.DataFrame) -> dict:
    from scipy.stats import spearmanr
    lo, hi = bootstrap_spearman(d["friction_min"], d["osm_min"], n_boot=1000, seed=SEED_BASE)
    return {"Sample and stratum": label, "n": int(len(d)),
            "Spearman": float(spearmanr(d["friction_min"], d["osm_min"]).statistic),
            "CI low": lo, "CI high": hi,
            "Median OSRM/friction": float((d["osm_min"] / d["friction_min"]).median())}


def table3(x: dict) -> None:
    p = x["pilot"].dropna(subset=["friction_min", "osm_min"]).merge(
        x["regions"][["ubigeo", "mean_altitude", "amazon"]], on="ubigeo", how="left")
    p["dept"] = p["department"].map(normalizar_cadena)
    pre, rem = p[p["phase"] != "remote"], p[p["phase"] == "remote"]
    basin = pre["amazon"].fillna(False).astype(bool)
    rem_basin = rem["amazon"].fillna(False).astype(bool)
    strata = x["osm_strata"].set_index(["sample", "subset"])

    def from_02(sample, subset, label, d):
        """Spearman and CI as stage 02 wrote them; the median ratio from the same rows."""
        r = strata.loc[(sample, subset)]
        return {"Sample and stratum": label, "n": int(r["n"]), "Spearman": float(r["spearman"]),
                "CI low": float(r["ci_low"]), "CI high": float(r["ci_high"]),
                "Median OSRM/friction": float((d["osm_min"] / d["friction_min"]).median())}

    rows = [
        from_02("pre_registered", "all", "Pre-specified: all", pre),
        _spearman_row("Pre-specified: outside Amazon departments (G1 proxy, pre-specified rule)",
                      pre[~pre["dept"].isin(AMAZON_DEPTS)]),
        from_02("pre_registered", "non_amazon", "Pre-specified: outside Amazon basin (post hoc)",
                pre[~basin]),
        from_02("pre_registered", "amazon", "Pre-specified: Amazon basin (post hoc)", pre[basin]),
        _spearman_row("Pre-specified: Amazon basin, <500 m (post hoc)",
                      pre[basin & (pre["mean_altitude"] < 500)]),
        _spearman_row("Pre-specified: Amazon basin, ≥500 m (post hoc)",
                      pre[basin & (pre["mean_altitude"] >= 500)]),
        from_02("enriched", "all", "Enriched remote sample: all", rem),
        from_02("enriched", "non_amazon", "Enriched remote sample: outside basin", rem[~rem_basin]),
        from_02("enriched", "amazon", "Enriched remote sample: Amazon basin", rem[rem_basin]),
    ]
    t = pd.DataFrame(rows)
    # Stage 02 and this table must count the same centroids, or a median describes other
    # rows than its Spearman: say so loudly in the note instead of failing the stage.
    mismatch = [f"{r['Sample and stratum']} ({len(d)} vs {r['n']})"
                for r, d in zip(rows, (pre, None, pre[~basin], pre[basin], None, None, rem,
                                       rem[~rem_basin], rem[rem_basin]))
                if d is not None and len(d) != r["n"]]
    note = ("Bootstrap 95 % CIs over centroids. The 0.80 rule applies to the pre-specified "
            "sample outside the Amazon.")
    if mismatch:
        print(f"[check] table3 median rows differ from stage 02: {mismatch}")
        note += " CHECK: median ratio rows differ from stage 02 for " + "; ".join(mismatch) + "."
    write_table("table3_engine", t,
                {"Spearman": ".3f", "CI low": ".3f", "CI high": ".3f", "Median OSRM/friction": ".2f"},
                note=note)


VARIANT_LABEL = {
    "centroid_km": "Straight line from district centre (km)",
    "popweighted_km": "Straight line, population-weighted (km)",
    "centre_cell_min": "Travel time at the district centre cell (min)",
    "calibrated_min": "Travel time × OSRM/friction band ratio (min)",
    "public_essalud_min": "Destinations: public + EsSalud (min)",
    "all_min": "Destinations: all complex hospitals (min)",
    "all_uncat_min": "Destinations: all + uncategorised hospital-like (min)",
    "walking_min": "Walking time (min)",
    "fca_60": "2SFCA, 60-min catchment (hospitals per 10,000)",
    "fca_120": "2SFCA, 120-min catchment (hospitals per 10,000)",
}


def rq2_table(s: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Table 4 rows (main measure first, as the reference) and its note, from stability.csv."""
    def count(v):
        return f"{int(v):,}" if pd.notna(v) else "—"

    first = s.iloc[0]
    rows = [{"Variant": "Travel time, person-weighted (main measure, min)",
             "Spearman (95 % CI)": None, "Kendall": np.nan, "Top-100 Jaccard": np.nan,
             "κ at 60 min": np.nan, "κ at 120 min": np.nan,
             "Districts flagged (60 / 120 min)":
                 f"{count(first['flagged_main_60'])} / {count(first['flagged_main_120'])}"}]
    for r in s.itertuples():
        rows.append({"Variant": VARIANT_LABEL.get(r.variant, r.variant),
                     "Spearman (95 % CI)": ci_text(r.spearman, r.spearman_ci_low, r.spearman_ci_high),
                     "Kendall": r.kendall, "Top-100 Jaccard": r.jaccard_top,
                     "κ at 60 min": r.kappa_60, "κ at 120 min": r.kappa_120,
                     "Districts flagged (60 / 120 min)":
                         f"{count(r.flagged_variant_60)} / {count(r.flagged_variant_120)}"})
    note = ("κ: variants in minutes use the same thresholds; km and 2SFCA flag as many districts "
            "as the main measure (quantile matching; scores tied at the cut are all flagged). "
            "Top-100 Jaccard is undefined (—) when tied scores straddle the 100th district.")
    fca = s[s["variant"].astype(str).str.startswith("fca_")].set_index("variant")
    if {"fca_60", "fca_120"} <= set(fca.index) and "kappa_natural" in fca:
        a, b = fca.loc["fca_60"], fca.loc["fca_120"]
        note += (f" 2SFCA, no hospital in the catchment (score 0) against >60 min: κ = "
                 f"{a['kappa_natural']:.3f} with the 60-min catchment ({100 * a['zero_share_districts']:.1f} % "
                 f"of districts and {100 * a['zero_share_population']:.1f} % of people score 0) and "
                 f"{b['kappa_natural']:.3f} with the 120-min catchment "
                 f"({100 * b['zero_share_districts']:.1f} % and {100 * b['zero_share_population']:.1f} %).")
    return pd.DataFrame(rows), note


def table4(x: dict) -> None:
    out, note = rq2_table(x["stability"])
    write_table("table4_rq2", out, {"Kendall": ".3f", "Top-100 Jaccard": ".3f",
                                    "κ at 60 min": ".3f", "κ at 120 min": ".3f"}, note=note)


def tableA2(x: dict) -> None:
    sim = x["s8"]["simulation"]
    rows = [{"Planted OR": 1.0, "Replications": sim["reps_null"], "Mean OR": np.nan,
             "Bias (%)": np.nan, "Coverage (%)": np.nan, "Coverage MCSE": np.nan,
             "Power or FP rate (%)": 100 * sim["false_positive_rate"],
             "FP MCSE": 100 * sim.get("false_positive_mcse", np.nan)}]
    for p in sim["planted"]:
        rows.append({"Planted OR": p["or_planted"], "Replications": p.get("reps", sim["reps_planted"]),
                     "Mean OR": p["mean_or"], "Bias (%)": 100 * p["bias"],
                     "Coverage (%)": 100 * p["coverage"],
                     "Coverage MCSE": 100 * p.get("coverage_mcse", np.nan),
                     "Power or FP rate (%)": 100 * p["power"], "FP MCSE": np.nan})
    write_table("tableA2_simulation", pd.DataFrame(rows),
                {"Planted OR": ".2f", "Mean OR": ".3f", "Bias (%)": ".1f", "Coverage (%)": ".1f",
                 "Coverage MCSE": ".1f", "Power or FP rate (%)": ".1f", "FP MCSE": ".1f"},
                note=f"Cells: {sim['cells']:,}; deaths: {sim['deaths']:,}; district SD {sim['district_sd']:.3f}. "
                     f"Pre-specified limits: FP ≤ 7 %, bias ≤ 10 %, coverage 92–97 %.")


MODEL_LABEL = {"ridge_regularized_linear": "Ridge (regularized linear)",
               "isotonic_on_friction": "Isotonic on friction time",
               "gradient_boosting_monotone": "Gradient boosting (monotone)"}
VERDICT_LABEL = {"not_refuted": "Contribution not refuted",
                 "no_positive_contribution": "No positive contribution"}
CAUSE_LABEL = {"amenable_acute": "Amenable, acute", "amenable_chronic": "Amenable, chronic",
               "cancer": "Cancer (negative control)", "external": "External causes",
               "other": "Other causes", "unknown": "Unknown cause"}
BAND_LABEL = {"<=30": "≤30 min", "30-60": "30–60 min", "60-120": "60–120 min", ">120": ">120 min"}


def p_text(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def tableA3(x: dict) -> None:
    c = x["calibration"]
    rows = [{"Model": "Constant ratio (baseline)", **c["baseline_metrics"]},
            {"Model": "Band ratios", **c["band_metrics"]}]
    rows += [{"Model": MODEL_LABEL.get(k, k.replace("_", " ")), **v}
             for k, v in c["candidates"].items()]
    t = pd.DataFrame(rows)[["Model", "mape", "remote_spearman", "kappa_60", "kappa_120"]]
    t["mape"] = 100 * t["mape"]
    t.columns = ["Model", "MAPE (%)", "Remote Spearman", "κ at 60 min", "κ at 120 min"]
    write_table("tableA3_ml_calibration", t,
                {"MAPE (%)": ".1f", "Remote Spearman": ".3f", "κ at 60 min": ".3f",
                 "κ at 120 min": ".3f"},
                note=f"Leave-one-department-out; selected: "
                     f"{MODEL_LABEL.get(c['winner'], c['winner'])}.")
    p = x["predictive"]
    rows = []
    for key, label in (("all_causes", "All causes"), ("amenable", "Amenable causes")):
        r = p[key]
        rows.append({"Population": label, "Deaths": r["n_rows"],
                     "ΔBrier": r["delta_brier"], "CI low": r["delta_brier_ci"][0],
                     "CI high": r["delta_brier_ci"][1], "Permutation drop": r["permutation_brier_drop"],
                     "Verdict": VERDICT_LABEL.get(r["verdict"], r["verdict"])})
    write_table("tableA3_ml_predictive", pd.DataFrame(rows),
                {"Deaths": ",", "ΔBrier": ".5f", "CI low": ".5f", "CI high": ".5f",
                 "Permutation drop": ".5f"})


def tableA4(x: dict) -> None:
    s8 = x["s8"]
    t = pd.DataFrame(s8["h3b"]["by_cause"])[["cause_group", "n", "or_per_60", "ci_low",
                                              "ci_high", "p_value"]]
    t["cause_group"] = t["cause_group"].map(CAUSE_LABEL).fillna(t["cause_group"])
    t.columns = ["Cause group", "Deaths", "OR per +60 min", "CI low", "CI high", "p"]
    inter = s8["h3b"].get("interaction_p", {})
    acute_chronic = next((v for k, v in inter.items() if "amenable_chronic" in k), np.nan)
    write_table("tableA4_h3b", t, {"Deaths": ",", "OR per +60 min": ".3f", "CI low": ".3f",
                                   "CI high": ".3f", "p": p_text},
                note=f"Time × cause interaction, chronic vs acute: p = {p_text(acute_chronic)}.")
    u = x["unknown"].copy()
    outside = u["outside"].astype(str).str.lower().eq("true")  # CSV booleans come back as text
    u["order"] = u["band"].map({k: i for i, k in enumerate(BAND_LABEL)})
    u["outside"] = np.where(outside, "Outside a facility", "In a facility")
    u = u.sort_values(["order", "outside"]).drop(columns="order")  # "In a ..." before "Outside ..."
    u["band"] = u["band"].map(BAND_LABEL).fillna(u["band"])
    u = u.rename(columns={"band": "Travel time", "outside": "Place of death",
                          "share_unknown": "Unknown cause (%)", "deaths": "Deaths"})
    u["Unknown cause (%)"] = 100 * u["Unknown cause (%)"]
    write_table("tableA4b_unknown_cause", u, {"Unknown cause (%)": ".1f", "Deaths": ","},
                note="Deaths 2022–2025 with the district of residence resolved by name, all causes; "
                     "travel time is the person-weighted mean of that district.")


# --- main ---------------------------------------------------------------------------------------

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        write_table("smoke", pd.DataFrame({"a": [1]}))
        (OUT / "qa.md").write_text("# smoke\n", encoding="utf-8")
        print("smoke: synthetic figures/tables")
        return 0

    x = load_inputs()
    plt = st.setup()
    broken: list[str] = []
    for name, build in (("table2_equity", table2), ("table3_engine", table3),
                        ("table4_rq2", table4), ("tableA2_simulation", tableA2),
                        ("tableA3_ml", tableA3), ("tableA4_h3b", tableA4)):
        try:
            build(x)
            print(f"[ok] {name}")
        except Exception as exc:  # noqa: BLE001 - one broken table must not hide the rest
            broken.append(name)
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")

    report, sheet = qa.Report(), []
    builders = {"Fig1": fig1_workflow, "Fig2": lambda: fig2_access(plt, x),
                "Fig3": lambda: fig3_methods(plt, x), "Fig4": lambda: fig4_need_access(plt, x),
                "Fig5": lambda: fig5_rq3(plt, x), "FigA1": lambda: figA1_osrm(plt, x)}
    for key, build in builders.items():
        try:
            f = build()
            files = save_and_check(f, report)
            if files:
                sheet.append((f.name, files))
            res = "check" if report.figures[f.name]["problems"] else "ok"
            print(f"[{res}] {f.name}")
            for p in report.figures[f.name]["problems"]:
                print(f"       - {p}")
        except Exception as exc:  # noqa: BLE001
            broken.append(key)
            report.add(key, [f"could not be drawn: {type(exc).__name__}: {exc}"],
                       notes=[traceback.format_exc(limit=3)])
            print(f"[FAIL] {key}: {type(exc).__name__}: {exc}")
    report.write(OUT)
    if sheet:
        qa.contact_sheet(sheet, OUT / "contact_sheet.png")
    (OUT / "manifest.json").write_text(json.dumps({
        "figures": {n: e["files"] for n, e in report.figures.items()},
        "tables": sorted(p.name for p in TABLES.glob("*")),
        "qa_findings": report.failed, "broken": broken}, indent=2), encoding="utf-8")
    if broken:
        print(f"could not produce: {', '.join(broken)}")
        return 1
    print("Stage 10 done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

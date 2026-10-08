# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""The paper's figures, drawn from outputs/ only, each checked before it is saved.

Stage 10 writes the pipeline's contract figures (F1-F6): views of single
tables, kept as they are. This stage writes the figures the manuscript uses,
one message each, at their final size on the CAS page (90 mm, or the 164 mm text width):

  Fig01 study area: the stations on the map of Peru and their annual cycles
  Fig02 workflow: the whole system in one diagram (Graphviz)
  Fig03 validation design: folds, embargo, freeze point, CFSv2 archive, ENSO
  Fig04 blind skill by horizon (CRPSS vs Clim and vs Damp), the main result
  Fig05 the hybrid's paired tests (H6, amendment A5) as a forest plot
  Fig06 calibration: 90 % coverage by horizon and PIT at Weeks 3-4
  Fig07 adapting the foundation model: skill, coverage and width of Chronos variants
  Fig08 windows of opportunity: M* by ENSO phase, season and MJO activity
  Fig09 transfer: skill lost at a station left out of training, by elevation
  Fig10 case study: Weeks 3-4 forecasts at the median station of the hybrid
  FigS1 seed variability, FigS2 dev vs blind, FigS3 predictability budget

Every figure is written as PNG (300 dpi), PDF (vector, embedded fonts) and the
CSV of exactly what it plots, then checked by `_figqa` (data, rendering, image;
see that module). Deuteranopia and grayscale versions and a contact sheet go to
`outputs/figures/paper/qa/` for the visual review. Any failed check makes the
stage exit 1 after writing everything, so the run shows it in errors.log.

`--probe` (notebook cell 2): imports the map and diagram stack and downloads the
Natural Earth layers, so a missing dependency stops the notebook in seconds.
"""

from __future__ import annotations

import argparse
import importlib
import json
import traceback

import numpy as np
import pandas as pd

import _figqa as qa
import _figstyle as st
from _common import FIGURES, PROCESSED, TABLES, load_config, normalize_ubigeo, paths_report, \
    primary_target, read_station_keyed, write_manifest
from _panel import MODELS_DIR, qcols, quantile_levels, read_eval_index
from _scores import cdf_from_quantiles

# v1: first version.
RESULTS_VERSION = 1

TARGET = primary_target()
OUT = FIGURES / "paper"
QA_DIR = OUT / "qa"
HYBRID = "Ridge_LG@CFS"
BLEND = "Blend_CFS_Mstar"
# Natural Earth layers the map needs: (resolution, category, name).
NE_LAYERS = [("50m", "cultural", "admin_0_countries"),
             ("10m", "cultural", "admin_1_states_provinces"),
             ("50m", "physical", "geography_regions_polys")]
MAP_EXTENT = [-81.8, -68.4, -18.6, 0.4]


# --- inputs ------------------------------------------------------------------------------------

def table(name: str) -> pd.DataFrame:
    path = TABLES / f"{name}.csv"
    if not path.is_file():
        raise SystemExit(f"ERROR: {path} not found — run the pipeline first")
    return pd.read_csv(path)


def stations(cfg: dict) -> pd.DataFrame:
    rows = [{"station": normalize_ubigeo(s["ubigeo"]), "name": s.get("name", s["ubigeo"]),
             "lat": float(s["lat"]), "lon": float(s["lon"]), "elev_m": float(s["elev_m"])}
            for s in cfg.get("stations") or []]
    return pd.DataFrame(rows).sort_values("elev_m").reset_index(drop=True)


def enso_episodes(min_days: int = 60) -> list[tuple[pd.Timestamp, pd.Timestamp, str]]:
    """El Niño / La Niña spans: 91-day mean Niño 3.4 anomaly beyond ±0.5 °C.

    A 3-month mean, as the ONI uses, so a single warm week is not an episode.
    """
    path = PROCESSED / "largescale_daily.csv"
    if not path.is_file():
        return []
    d = pd.read_csv(path, parse_dates=["date"])[["date", "nino34_anom"]].dropna()
    d = d.set_index("date").asfreq("D")
    smooth = d["nino34_anom"].interpolate(limit=10).rolling(91, center=True, min_periods=60).mean()
    state = np.select([smooth >= 0.5, smooth <= -0.5], ["El Niño", "La Niña"], "")
    out, start, cur = [], None, ""
    for day, s in zip(smooth.index, state):
        if s != cur:
            if cur and start is not None and (day - start).days >= min_days:
                out.append((start, day, cur))
            start, cur = day, s
    if cur and start is not None and (smooth.index[-1] - start).days >= min_days:
        out.append((start, smooth.index[-1], cur))
    return out


def preds_with_obs(path, index: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    keys = ["station", "fold", "issue_date", "horizon"]
    p = read_station_keyed(path, parse_dates=["issue_date"])
    p = p[p["target"] == TARGET] if "target" in p.columns else p
    p = p.drop(columns=[c for c in ("obs", "role") if c in p.columns])
    return index[keys + ["role", "obs", "lag_start", "lag_end"]].merge(
        p[keys + ["mean"] + cols], on=keys, how="inner")


def pit_values(df: pd.DataFrame, cols: list[str], levels: list[float]) -> np.ndarray:
    return cdf_from_quantiles(df["obs"].to_numpy(float), df[cols].to_numpy(float), levels)


def pit_hist(pit: np.ndarray, bins: int = 10) -> np.ndarray:
    counts, _ = np.histogram(pit[np.isfinite(pit)], bins=bins, range=(0.0, 1.0))
    return counts / max(counts.sum(), 1)


# --- figure record ---------------------------------------------------------------------------------

class Fig:
    """A drawn figure plus what QA needs to judge it."""

    def __init__(self, name, fig=None, data=None, kind="chart", width=st.DOUBLE_MM,
                 values=None, axis="y", problems=None, notes=None, image=None):
        self.name, self.fig, self.data, self.kind, self.width = name, fig, data, kind, width
        self.values, self.axis = values, axis
        self.problems, self.notes = list(problems or []), list(notes or [])
        self.image = image  # (png bytes, pdf bytes) for figures not drawn by matplotlib


# --- Fig01 study area -----------------------------------------------------------------------------

def _ne(resolution, category, name):
    from cartopy.io import shapereader
    import geopandas as gpd
    gdf = gpd.read_file(shapereader.natural_earth(resolution=resolution, category=category,
                                                  name=name))
    gdf.columns = [c.lower() if c != "geometry" else c for c in gdf.columns]
    return gdf


def fig01_study_area(plt, cfg) -> Fig:
    import cartopy.crs as ccrs
    from matplotlib.colors import Normalize

    sts = stations(cfg)
    clim = read_station_keyed(PROCESSED / "daily_clim.csv", parse_dates=["date"])
    last = [f for f in cfg["validation"]["folds"]][-1]
    t0, t1 = (pd.Timestamp(x) for x in last["test"])
    cyc = clim[(clim["date"] >= t0) & (clim["date"] <= t1)][["station", "date", "C2"]].copy()
    cyc["doy"] = cyc["date"].dt.dayofyear
    cyc = cyc.groupby(["station", "doy"], as_index=False)["C2"].mean()

    countries = _ne(*NE_LAYERS[0])
    adm1 = _ne(*NE_LAYERS[1])
    regions = _ne(*NE_LAYERS[2])
    a3 = "adm0_a3" if "adm0_a3" in countries.columns else "iso_a3"
    peru = countries[countries[a3] == "PER"]
    others = countries[countries[a3] != "PER"]
    deps = adm1[adm1.get("adm0_a3", adm1.get("iso_a2")) == "PER"] if "adm0_a3" in adm1 else adm1.iloc[0:0]
    andes = regions[regions["name"].astype(str).str.upper() == "ANDES"]
    if len(andes) and len(peru):
        # The Natural Earth region is a coarse outline that spills over the
        # coast; only the part inside Peru is drawn.
        geo = peru.geometry
        outline = geo.union_all() if hasattr(geo, "union_all") else geo.unary_union
        andes = andes.assign(geometry=andes.geometry.intersection(outline))
        andes = andes[~andes.geometry.is_empty]
    problems = [] if len(andes) else ["Natural Earth has no ANDES polygon"]
    if peru.empty:
        problems.append("Natural Earth has no Peru polygon")

    norm = Normalize(vmin=2300, vmax=4600)
    cmap = plt.get_cmap("cividis")
    fig = plt.figure(figsize=(st.DOUBLE_MM * st.MM, 76 * st.MM))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.45])
    ax = fig.add_subplot(gs[0], projection=ccrs.PlateCarree())
    pc = ccrs.PlateCarree()
    ax.set_extent(MAP_EXTENT, crs=pc)
    ax.add_geometries(others.geometry, pc, facecolor="#F1F1F1", edgecolor="#C8C8C8", lw=0.4)
    ax.add_geometries(peru.geometry, pc, facecolor="white", edgecolor="none")
    if len(andes):
        ax.add_geometries(andes.geometry, pc, facecolor="#E9E2D3", edgecolor="none", alpha=0.9)
    if len(deps):
        ax.add_geometries(deps.geometry, pc, facecolor="none", edgecolor="#D0D0D0", lw=0.3)
    ax.add_geometries(peru.geometry, pc, facecolor="none", edgecolor="#4D4D4D", lw=0.7)
    ax.set_facecolor("#F4F8FB")
    ax.scatter(sts["lon"], sts["lat"], c=sts["elev_m"], cmap=cmap, norm=norm, marker="^", s=34,
               edgecolor="black", linewidth=0.5, transform=pc, zorder=6)
    # Callouts in the Pacific, ordered by latitude: no label ever sits on the map.
    # Two-line labels need ~2° of latitude each; the column is kept inside the map.
    ys = np.array(st.spread(list(sts["lat"]), 2.0))
    ys += max(0.0, (MAP_EXTENT[2] + 0.9) - ys.min())
    for (_, r), y in zip(sts.iterrows(), ys):
        ax.annotate(f"{r['name']}\n{r['elev_m']:.0f} m", xy=(r["lon"], r["lat"]),
                    xytext=(-81.3, y), textcoords="data", xycoords="data", fontsize=6.2,
                    ha="left", va="center", transform=pc,
                    arrowprops={"arrowstyle": "-", "lw": 0.4, "color": "#777777",
                                "shrinkA": 1, "shrinkB": 3, "relpos": (1.0, 0.5)}, zorder=7)
    ax.text(-74.6, -6.2, "PERU", fontsize=7, color="#555555", ha="center", transform=pc)
    ax.text(-80.9, -1.6, "Pacific\nOcean", fontsize=6.2, color="#7A8B99", style="italic",
            ha="left", transform=pc)
    gl = ax.gridlines(draw_labels=True, lw=0.3, color="#DDDDDD", x_inline=False, y_inline=False)
    gl.top_labels = gl.right_labels = False
    gl.xlabel_style = gl.ylabel_style = {"size": 6}
    # Inside the map, over the neighbouring countries (north-east), never over a
    # station, and without widening the figure.
    # No colour bar: every callout states its elevation, and the colours are the
    # ones panel (b) uses, so a bar would only repeat them over the map.
    st.panel_letter(ax, "a")

    bx = fig.add_subplot(gs[1])
    data = []
    ends = []
    for _, r in sts.iterrows():
        g = cyc[cyc["station"] == r["station"]].sort_values("doy")
        bx.plot(g["doy"], g["C2"], color=cmap(norm(r["elev_m"])), lw=1.3)
        ends.append(float(g["C2"].iloc[-1]) if len(g) else np.nan)
        data.append(g.assign(name=r["name"], elev_m=r["elev_m"]))
    # Direct labels to the right of the curves, inside the axes, so the layout
    # engine keeps them on the canvas; the x spine stops at the end of the year.
    for (_, r), y in zip(sts.iterrows(), st.spread(ends, 0.9)):
        bx.text(372, y, f"{r['name']} ({r['elev_m']:.0f} m)", fontsize=6.2, va="center",
                color=cmap(norm(r["elev_m"])))
    month_starts = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    bx.set_xticks(month_starts, list("JFMAMJJASOND"))
    bx.set_xlim(1, 470)
    bx.spines["bottom"].set_bounds(1, 366)
    bx.set_ylabel("Climatological daily mean (°C)")
    bx.set_xlabel("Month")
    bx.text(0.0, 1.02, f"Harmonic climatology (C2) of fold {last['id']}", transform=bx.transAxes,
            fontsize=6.2, ha="left", va="bottom", color="#555555")
    st.panel_letter(bx, "b")
    df = pd.concat(data, ignore_index=True)
    return Fig("Fig01_study_area", fig, df, kind="diagram", values=df["C2"], problems=problems,
               notes=["map labels are callouts in the Pacific, ordered by latitude",
                      "marker and line colour = station elevation (cividis, 2300-4600 m)"])


# --- Fig02 workflow (Graphviz) -----------------------------------------------------------------------

WORKFLOW_DOT = r"""
digraph G {
  // Every node is pinned (pos "x,y!" in inches, neato): the layout is the same
  // on every Graphviz version, which `dot`'s own ordering is not. Top row: data
  // and predictors, left to right; bottom row: the forecasting system; the
  // hybrid sits between the rows, under the CFSv2 forecast it uses.
  graph [layout=neato, splines=false, overlap=true, pad=0.0, dpi=300,
         size="6.40,2.70!", fontname="Helvetica", fontsize=10.5];
  // 10.5 pt nodes print at ~7.3 pt once the layout is scaled to the 164 mm width.
  node  [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10.5,
         margin="0.07,0.035", color="#7A7A7A", penwidth=0.6, fillcolor="#F4F4F4"];
  edge  [color="#5A5A5A", penwidth=0.7, arrowsize=0.45];

  frame [label="", shape=box, style="rounded", color="#C9C9C9", fillcolor="none",
         width=8.75, height=0.98, pos="4.25,2.02!"];
  title [label="Data and predictors", shape=plaintext, style="", fontcolor="#444444",
         pos="1.05,2.36!"];

  raw  [label="SENAMHI hourly\n5 stations · 2015–2024", pos="0.85,1.92!"];
  qc   [label="Quality control\n→ daily means", pos="2.50,1.92!"];
  anom [label="Anomalies vs\nharmonic climatology", pos="4.12,1.92!"];
  feat [label="Predictors\nlocal (L) · ENSO/MJO (G)", pos="6.02,1.92!"];
  cfs  [label="CFSv2 forecast\n4 members · 1°", fillcolor="#F3E1EA", color="#882255",
        pos="7.80,1.92!"];

  hyb  [label="Hybrid\nRidge LG + CFSv2", fillcolor="#FBE1D2", color="#D55E00",
        penwidth=1.1, pos="7.80,1.10!"];

  ml   [label="Ridge · GBM · LSTM\nChronos TSFM (abs. context, Bolt)", fillcolor="#E5F3EE",
        color="#009E73", pos="1.15,0.30!"];
  ens  [label="M* ensemble\ninverse-CRPS weights", fillcolor="#DDEFFA", color="#56B4E9",
        pos="3.35,0.30!"];
  cal  [label=<Conformal calibration<BR/>M*<SUB>2</SUB>>, fillcolor="#D4E6F4", color="#0072B2",
        penwidth=1.1, pos="5.20,0.30!"];
  eval [label="Blind evaluation B1–B2\nvs climatology, persistence, CFSv2\nblock bootstrap + Holm",
        fillcolor="#EDEDED", color="#4D4D4D", penwidth=0.9, pos="7.95,0.24!"];

  raw -> qc -> anom -> feat;
  feat -> ml; feat -> hyb; cfs -> hyb;
  ml -> ens; ens -> cal; cal -> eval; hyb -> eval;
}
"""


def fig02_workflow() -> Fig:
    import io

    import graphviz
    from PIL import Image

    src = graphviz.Source(WORKFLOW_DOT, engine="neato")
    png = src.pipe(format="png")
    pdf = src.pipe(format="pdf")
    with Image.open(io.BytesIO(png)) as im:
        w_mm, h_mm = (v / 300 * 25.4 for v in im.size)
        buf = io.BytesIO()
        im.save(buf, format="PNG", dpi=(300, 300))
    problems = []
    if w_mm > st.DOUBLE_MM + 0.5:
        problems.append(f"width {w_mm:.0f} mm exceeds {st.DOUBLE_MM:.0f} mm")
    if w_mm < 150:
        problems.append(f"width {w_mm:.0f} mm: the diagram is too small for the page")
    if h_mm > st.MAX_HEIGHT_MM["diagram"] + 0.5:
        problems.append(f"height {h_mm:.0f} mm exceeds {st.MAX_HEIGHT_MM['diagram']:.0f} mm")
    data = pd.DataFrame({"width_mm": [round(w_mm, 1)], "height_mm": [round(h_mm, 1)]})
    return Fig("Fig02_workflow", data=data, kind="diagram", problems=problems,
               image=(buf.getvalue(), pdf))


# --- Fig03 validation design --------------------------------------------------------------------------

def fig03_design(plt, cfg) -> Fig:
    import matplotlib.dates as mdates
    from matplotlib.patches import Patch

    val = cfg["validation"]
    start = pd.Timestamp(val.get("train_start", "2015-01-01"))
    embargo = pd.Timedelta(days=int(val.get("embargo_days", 28)))
    folds = val["folds"]
    cfs0 = pd.Timestamp((cfg.get("dynamical") or {}).get("start", "2018-10-31"))
    end = max(pd.Timestamp(f["test"][1]) for f in folds)
    fig, ax = st.figure(plt, st.DOUBLE_MM, 54)
    n = len(folds)
    rows = []
    span = lambda a, b: (mdates.date2num(a), mdates.date2num(b) - mdates.date2num(a))  # noqa: E731
    for i, f in enumerate(folds):
        y = n - i
        t0, t1 = pd.Timestamp(f["test"][0]), pd.Timestamp(f["test"][1])
        blind = f.get("role") == "blind"
        ax.broken_barh([span(start, t0 - embargo)], (y - 0.3, 0.6), color="#C7C7C7", lw=0)
        ax.broken_barh([span(t0 - embargo, t0)], (y - 0.3, 0.6), facecolor="white",
                       edgecolor="#8A8A8A", hatch="/////", lw=0.4)
        ax.broken_barh([span(t0, t1)], (y - 0.3, 0.6), color="#0072B2" if blind else "#9ECAE1",
                       lw=0)
        rows += [{"fold": f["id"], "segment": "train", "start": start, "end": t0 - embargo},
                 {"fold": f["id"], "segment": "embargo", "start": t0 - embargo, "end": t0},
                 {"fold": f["id"], "segment": "test", "start": t0, "end": t1}]
    ax.broken_barh([span(cfs0, end)], (-0.25, 0.5), color="#882255", alpha=0.85, lw=0)
    rows.append({"fold": "CFSv2", "segment": "archive", "start": cfs0, "end": end})
    for a, b, kind in enso_episodes():
        a, b = max(a, start), min(b, end)
        if b <= a:
            continue
        ax.axvspan(a, b, color="#F4B9A0" if kind == "El Niño" else "#BBD5EC", alpha=0.35, lw=0,
                   zorder=0)
        rows.append({"fold": "ENSO", "segment": kind, "start": a, "end": b})
    freeze = min(pd.Timestamp(f["test"][0]) for f in folds if f.get("role") == "blind")
    ax.axvline(freeze, color="#222222", lw=0.8, ls=(0, (3, 2)))
    ax.text(freeze, n + 0.62, "  M* and hyperparameters frozen", fontsize=6.2, va="center",
            ha="left")
    labels = [f"{f['id']} ({'blind' if f.get('role') == 'blind' else 'dev'})" for f in folds]
    ax.set_yticks([n - i for i in range(n)] + [0], labels + ["CFSv2 archive"])
    ax.set_ylim(-0.6, n + 0.95)
    ax.set_xlim(start - pd.Timedelta(days=20), end + pd.Timedelta(days=20))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    handles = [Patch(color="#C7C7C7", label="training (expanding)"),
               Patch(facecolor="white", edgecolor="#8A8A8A", hatch="/////", label="28-day embargo"),
               Patch(color="#9ECAE1", label="dev test year"),
               Patch(color="#0072B2", label="blind test year"),
               Patch(color="#882255", alpha=0.85, label="CFSv2 available"),
               Patch(color="#F4B9A0", alpha=0.6, label="El Niño"),
               Patch(color="#BBD5EC", alpha=0.6, label="La Niña")]
    fig.legend(handles=handles, loc="outside lower center", ncol=7, fontsize=6.2,
               handlelength=1.4, columnspacing=1.0)
    df = pd.DataFrame(rows)
    return Fig("Fig03_validation_design", fig, df, kind="diagram",
               notes=["ENSO spans: 91-day mean Niño 3.4 anomaly beyond ±0.5 °C, ≥ 60 days"])


# --- Fig04 main result ------------------------------------------------------------------------------

FIG4_MODELS = ["Damp", "Chronos@abs", "GBM_LG", "LSTM_LG", "Ridge_LG", "CFS_BC", "Ensemble",
               "Mstar2", HYBRID]


def skill_long(primary: str) -> pd.DataFrame:
    """CRPSS vs Clim and vs Damp with CIs for the Fig04 systems, from their tables."""
    t2 = table("T2_blind_skill")
    rows = []
    for m in FIG4_MODELS:
        if m in ("Mstar2", HYBRID):
            continue
        src = primary if m == "Ensemble" else m
        # Damped persistence has no skill against itself (0 by definition).
        for ref in (("clim",) if m == "Damp" else ("clim", "damp")):
            g = t2[(t2["model"] == src) & (t2["metric"] == f"CRPSS_{ref}")]
            for _, r in g.iterrows():
                rows.append({"model": m, "ref": ref, "horizon": r["horizon"], "value": r["value"],
                             "lo": r["ci_low"], "hi": r["ci_high"], "source": "T2"})
    t14, t16 = table("T14_mstar2_blind"), table("T16_hybrid_cfs")
    for ref in ("clim", "damp"):
        for _, r in t14.iterrows():
            rows.append({"model": "Mstar2", "ref": ref, "horizon": r["horizon"],
                         "value": r[f"CRPSS_{ref}"], "lo": r[f"CRPSS_{ref}_low"],
                         "hi": r[f"CRPSS_{ref}_high"], "source": "T14"})
        for _, r in t16[t16["system"] == HYBRID].iterrows():
            rows.append({"model": HYBRID, "ref": ref, "horizon": r["horizon"],
                         "value": r[f"CRPSS_{ref}"], "lo": r[f"CRPSS_{ref}_low"],
                         "hi": r[f"CRPSS_{ref}_high"], "source": "T16"})
    return pd.DataFrame(rows)


def fig04_skill(plt, primary: str) -> Fig:
    d = skill_long(primary)
    problems = qa.check_count(d, (len(FIG4_MODELS) * 2 - 1) * 3,
                              "model x reference x horizon rows")
    problems += qa.check_finite(d, ["value", "lo", "hi"])
    # 09 and 09f score the same systems on the same rows independently.
    t2, t16 = table("T2_blind_skill"), table("T16_hybrid_cfs")
    for m in ("CFS_BC", "Ridge_LG", "GBM_LG", primary):
        a = t2[(t2["model"] == m) & (t2["metric"] == "CRPSS_clim")][["horizon", "value"]]
        b = t16[t16["system"] == m][["horizon", "CRPSS_clim"]]
        problems += qa.check_agree(a, b, ["horizon"], "value", "CRPSS_clim", 5e-4,
                                   f"T2 vs T16, {m}")
    fig, axes = st.figure(plt, st.DOUBLE_MM, 84, ncols=2, sharex=True)
    offs = np.linspace(-0.26, 0.26, len(FIG4_MODELS))
    for ax, ref, letter in zip(axes, ("clim", "damp"), "ab"):
        for off, m in zip(offs, FIG4_MODELS):
            if m == "Damp" and ref == "damp":
                continue
            g = d[(d["model"] == m) & (d["ref"] == ref)].set_index("horizon").reindex(st.HORIZONS)
            x = np.arange(3) + off
            w = st.weight(m)
            if m in st.HERO:  # a line only where the trend is the message
                ax.plot(x, g["value"], color=st.color(m), lw=w["lw"] * 0.6, alpha=0.6,
                        zorder=w["zorder"] - 1)
            ax.errorbar(x, g["value"], yerr=[g["value"] - g["lo"], g["hi"] - g["value"]],
                        fmt="none", ecolor=st.color(m), elinewidth=w["lw"] * 0.6, capsize=0,
                        alpha=w["alpha"], zorder=w["zorder"])
            sig = (g["lo"] > 0).to_numpy()
            for xi, yi, s in zip(x, g["value"], sig):
                ax.plot([xi], [yi], marker=st.MARKER.get(m, "o"), ms=w["ms"],
                        color=st.color(m), mfc=st.color(m) if s else "white",
                        mew=0.8, zorder=w["zorder"] + 1, ls="none",
                        label=st.label(m) if xi == x[0] else None)
        ax.axhline(0, color="#444444", lw=0.6, zorder=1)
        ax.set_xticks(range(3), [st.HORIZON_LABEL[h] for h in st.HORIZONS])
        ax.set_ylabel("CRPSS vs " + ("climatology" if ref == "clim" else "damped persistence"))
        ax.set_xlim(-0.5, 2.5)
        st.panel_letter(ax, letter)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=5, fontsize=6.2,
               handletextpad=0.4, columnspacing=1.1)
    return Fig("Fig04_blind_skill", fig, d, values=d["value"], problems=problems,
               notes=["filled marker: 95 % interval above 0; hollow: interval includes 0"])


# --- Fig05 hybrid tests (forest plot) ----------------------------------------------------------------

FIG5_TESTS = [(HYBRID, "a_vs_CFS_BC", "Hybrid vs CFSv2"),
              (HYBRID, "b_vs_Mstar", "Hybrid vs M*"),
              (HYBRID, "c_vs_control", "Hybrid vs control\n(same rows, no CFSv2)"),
              (BLEND, "a_vs_CFS_BC", "Blend vs CFSv2"),
              (BLEND, "b_vs_Mstar", "Blend vs M*")]


def fig05_hybrid_tests(plt) -> Fig:
    t = table("T16b_hybrid_tests")
    rows = []
    for k, (system, test, lab) in enumerate(FIG5_TESTS):
        g = t[(t["system"] == system) & (t["test"] == test)]
        for _, r in g.iterrows():
            rows.append({"row": k, "label": lab, "system": system, "test": test,
                         "horizon": r["horizon"], "dCRPS": r["dCRPS_ref_minus_system"],
                         "lo": r["ci_low"], "hi": r["ci_high"], "p_holm": r["p_holm"]})
    d = pd.DataFrame(rows)
    problems = qa.check_count(d, len(FIG5_TESTS) * 3, "test x horizon rows")
    fig, ax = st.figure(plt, st.SINGLE_MM, 74)
    offs = {"W1": 0.24, "W2": 0.0, "W3_4": -0.24}
    for h in st.HORIZONS:
        g = d[d["horizon"] == h]
        y = len(FIG5_TESTS) - 1 - g["row"].to_numpy() + offs[h]
        ax.errorbar(g["dCRPS"], y, xerr=[g["dCRPS"] - g["lo"], g["hi"] - g["dCRPS"]], fmt="none",
                    ecolor=st.HORIZON_TONE[h], elinewidth=1.0, capsize=0)
        sig = (g["p_holm"] < 0.05).to_numpy()
        ax.scatter(g["dCRPS"][sig], y[sig], s=16, color=st.HORIZON_TONE[h], zorder=3,
                   label=st.HORIZON_LABEL[h])
        ax.scatter(g["dCRPS"][~sig], y[~sig], s=16, facecolor="white",
                   edgecolor=st.HORIZON_TONE[h], linewidth=0.9, zorder=3)
    ax.axvline(0, color="#444444", lw=0.6)
    ax.set_yticks(range(len(FIG5_TESTS)), [lab for _, _, lab in FIG5_TESTS][::-1])
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel("ΔCRPS, reference − system (°C, summed over stations)")
    lo, hi = float(d["lo"].min()), float(d["hi"].max())
    pad = 0.08 * (hi - lo)
    ax.set_xlim(min(lo, 0) - pad, max(hi, 0) + 2 * pad)
    ax.set_ylim(-0.6, len(FIG5_TESTS) - 0.15)
    ax.text(0.99, 1.0, "system better →", transform=ax.transAxes, ha="right", va="bottom",
            fontsize=6.2, color="#555555")
    ax.text(0.0, 1.0, "← reference better", transform=ax.get_xaxis_transform(), ha="right",
            va="bottom", fontsize=6.2, color="#555555")
    fig.legend(*ax.get_legend_handles_labels(), loc="outside lower center", ncol=3,
               fontsize=6.2, handletextpad=0.2, columnspacing=0.9)
    return Fig("Fig05_hybrid_tests", fig, d, width=st.SINGLE_MM, kind="single",
               values=d["dCRPS"], axis="x", problems=problems,
               notes=["filled: p_holm < 0.05 (Holm over the three horizons within each test)"])


# --- Fig06 calibration --------------------------------------------------------------------------------

def fig06_calibration(plt, cfg, primary: str) -> Fig:
    levels, cols = quantile_levels(cfg), qcols(cfg)
    t9, t14, t16, t15 = (table(n) for n in ("T9_calibration", "T14_mstar2_blind",
                                            "T16_hybrid_cfs", "T15_pit_reliability"))
    cov = []
    for variant, m in ((primary, "Ensemble"), (f"{primary}+k", "Ensemble+k")):
        g = t9[(t9["variant"] == variant) & (t9["role"] == "blind")]
        cov += [{"model": m, "horizon": r["horizon"], "cov90": r["cov90"]} for _, r in g.iterrows()]
    cov += [{"model": "Mstar2", "horizon": r["horizon"], "cov90": r["cov90_mstar2"]}
            for _, r in t14.iterrows()]
    for m in ("CFS_BC", HYBRID):
        cov += [{"model": m, "horizon": r["horizon"], "cov90": r["cov90"]}
                for _, r in t16[t16["system"] == m].iterrows()]
    cov = pd.DataFrame(cov)
    problems = qa.check_count(cov, 5 * 3, "model x horizon coverage rows")
    problems += qa.check_agree(cov[cov["model"] == "Ensemble"], t16[t16["system"] == primary],
                               ["horizon"], "cov90", "cov90", 1e-3, "T9 vs T16 coverage of M*")

    index = read_eval_index("temporal")
    index = index[(index["target"] == TARGET) & (index["role"] == "blind")
                  & np.isfinite(index["obs"])]
    sources = {"Ensemble": MODELS_DIR / f"preds_temporal_{primary}.csv",
               "Mstar2": MODELS_DIR / "mstar2_preds.csv",
               HYBRID: MODELS_DIR / "hybrid" / f"preds_temporal_{HYBRID}.csv"}
    hists = []
    for m, path in sources.items():
        p = preds_with_obs(path, index, cols)
        p = p[p["horizon"] == "W3_4"]
        h = pit_hist(pit_values(p, cols, levels))
        hists.append(pd.DataFrame({"model": m, "bin": np.arange(10), "share": h, "n": len(p)}))
    hists = pd.concat(hists, ignore_index=True)
    ref = t15[(t15["role"] == "blind") & (t15["horizon"] == "W3_4") & (t15["series"] == "pit_hist")]
    mine = hists[hists["model"] == "Ensemble"].assign(bin_low=lambda x: x["bin"] / 10)
    ref = ref.assign(bin_low=ref["bin_low"].round(2))
    mine["bin_low"] = mine["bin_low"].round(2)
    problems += qa.check_agree(mine, ref, ["bin_low"], "share", "value", 5e-4,
                               "PIT of M* recomputed vs T15")

    fig = plt.figure(figsize=(st.DOUBLE_MM * st.MM, 62 * st.MM))
    gs = fig.add_gridspec(1, 4, width_ratios=[1.5, 1, 1, 1])
    ax = fig.add_subplot(gs[0])
    # Band and nominal line stop at the last horizon, so the labels sit on white.
    ax.fill_between([-0.2, 2.05], 0.85, 0.95, color="#E8E8E8", lw=0, zorder=0)
    ax.hlines(0.90, -0.2, 2.05, color="#777777", lw=0.6, ls=(0, (3, 2)))
    order = ["Ensemble", "Ensemble+k", "CFS_BC", HYBRID, "Mstar2"]
    for m in order:
        g = cov[cov["model"] == m].set_index("horizon").reindex(st.HORIZONS)
        w = st.weight(m)
        ax.plot(range(3), g["cov90"], marker=st.MARKER.get(m, "o"), ms=w["ms"] * 0.9,
                lw=w["lw"] * 0.8, color=st.color(m), zorder=w["zorder"])
    ends = [float(cov[(cov["model"] == m) & (cov["horizon"] == "W3_4")]["cov90"].iloc[0])
            for m in order]
    for m, y in zip(order, st.spread(ends, 0.05)):
        ax.text(2.12, y, st.label(m), fontsize=6.2, va="center", color=st.color(m))
    ax.set_xticks(range(3), [st.HORIZON_LABEL[h] for h in st.HORIZONS])
    ax.set_xlim(-0.2, 3.55)
    ax.spines["bottom"].set_bounds(0, 2)
    lo = min(0.4, float(cov["cov90"].min()) - 0.04)
    ax.set_ylim(lo, 1.0)
    ax.set_ylabel("90 % interval coverage (blind)")
    ax.text(-0.15, 0.955, "nominal 0.85–0.95", fontsize=6.2, color="#666666", va="bottom")
    st.panel_letter(ax, "a")
    top = float(hists["share"].max()) * 1.15
    for k, m in enumerate(["Ensemble", "Mstar2", HYBRID]):
        bx = fig.add_subplot(gs[k + 1])
        g = hists[hists["model"] == m]
        bx.bar(g["bin"] / 10 + 0.05, g["share"], width=0.092, color=st.color(m), lw=0)
        bx.axhline(0.1, color="#444444", lw=0.6, ls=(0, (3, 2)))
        bx.set_xlim(0, 1)
        bx.set_ylim(0, top)
        bx.set_xticks([0, 0.5, 1], ["0", "0.5", "1"])
        bx.set_xlabel("PIT")
        if k == 0:
            bx.set_ylabel("Share of forecasts, Weeks 3–4")
            st.panel_letter(bx, "b")
        else:
            bx.tick_params(labelleft=False)
        bx.text(0.5, 1.01, st.label(m), transform=bx.transAxes, ha="center", va="bottom",
                fontsize=6.2, color=st.color(m))
    data = pd.concat([cov.assign(panel="a"), hists.assign(panel="b")], ignore_index=True)
    values = pd.concat([cov["cov90"], hists["share"]])
    return Fig("Fig06_calibration", fig, data, values=values, problems=problems,
               notes=["dashed line in (b): a flat PIT (0.1 per bin) is a calibrated forecast"])


# --- Fig07 Chronos ------------------------------------------------------------------------------------

def fig07_chronos(plt, primary: str) -> Fig:
    """Skill, coverage and interval width of the three Chronos variants.

    One story across the panels: raw Chronos is over-confident (intervals ~4x too
    narrow), the absolute-temperature context restores the spread, and Bolt
    reaches nominal coverage only with much wider intervals, which costs it CRPS.
    """
    t2 = table("T2_blind_skill")
    m = pd.read_csv(TABLES / "metrics_long.csv", dtype={"scope": "string"})
    variants = ["Chronos", "ChronosBolt", "Chronos@abs"]
    keep = variants + [primary]
    d = t2[(t2["metric"] == "CRPSS_clim") & t2["model"].isin(keep)]
    ml = m[(m["experiment"] == "temporal") & (m["scope"] == "pooled") & (m["target"] == TARGET)
           & (m["role"] == "blind") & m["model"].isin(keep)][
        ["model", "horizon", "CRPSS_clim", "cov90", "width90"]]
    problems = qa.check_count(d, 4 * 3, "Chronos x horizon rows (T2)")
    problems += qa.check_count(ml, 4 * 3, "Chronos x horizon rows (metrics_long)")
    problems += qa.check_finite(ml, ["cov90", "width90"])
    # 08 and 09 score the same forecasts independently.
    problems += qa.check_agree(d.rename(columns={"value": "crpss"}), ml, ["model", "horizon"],
                               "crpss", "CRPSS_clim", 1e-3, "T2 vs metrics_long, CRPSS")

    fig = plt.figure(figsize=(st.DOUBLE_MM * st.MM, 62 * st.MM))
    gs = fig.add_gridspec(1, 3)
    offs = dict(zip(variants, (-0.08, 0.0, 0.08)))
    ref_label = "M* (reference)"

    def panel(ax, frame, col, ylabel, letter, gap, lo=None, ci=False):
        # A shared legend below the panels instead of label columns: at the
        # 164 mm text width three panels have no room for direct labels.
        g = frame[frame["model"] == primary].set_index("horizon").reindex(st.HORIZONS)
        ax.plot(range(3), g[col], color="#9A9A9A", lw=0.8, ls=(0, (3, 2)), zorder=1,
                label=ref_label)
        for v in variants:
            g = frame[frame["model"] == v].set_index("horizon").reindex(st.HORIZONS)
            x = np.arange(3) + offs[v]
            yerr = ([g[col] - g["ci_low"], g["ci_high"] - g[col]] if ci else None)
            ax.errorbar(x, g[col], yerr=yerr, color=st.color(v), marker=st.MARKER[v], ms=4.2,
                        lw=1.0, elinewidth=0.7, capsize=0, zorder=4, label=st.label(v))
        ax.set_xticks(range(3), [st.HORIZON_LABEL[h] for h in st.HORIZONS])
        ax.set_xlim(-0.35, 2.35)
        if lo is not None:
            ax.set_ylim(bottom=lo)
        ax.set_ylabel(ylabel)
        st.panel_letter(ax, letter)

    ax = fig.add_subplot(gs[0])
    ax.axhline(0, color="#444444", lw=0.6)
    panel(ax, d.rename(columns={"value": "crpss"}), "crpss", "CRPSS vs climatology (blind)", "a",
          0.04, ci=True)
    bx = fig.add_subplot(gs[1])
    bx.fill_between([-0.35, 2.35], 0.85, 0.95, color="#E8E8E8", lw=0, zorder=0)
    bx.hlines(0.90, -0.35, 2.35, color="#777777", lw=0.6, ls=(0, (3, 2)))
    panel(bx, ml, "cov90", "90 % interval coverage (blind)", "b", 0.07, lo=0.0)
    bx.set_ylim(0, 1.0)
    cx = fig.add_subplot(gs[2])
    panel(cx, ml, "width90", "90 % interval width (°C)", "c", 0.3, lo=0.0)
    handles, labels = cx.get_legend_handles_labels()
    order = [labels.index(st.label(v)) for v in variants] + [labels.index(ref_label)]
    fig.legend([handles[i] for i in order], [labels[i] for i in order],
               loc="outside lower center", ncol=4, fontsize=6.2)
    data = pd.concat([d.assign(panel="a")[["panel", "model", "horizon", "value", "ci_low",
                                           "ci_high"]],
                      ml.assign(panel="b,c")], ignore_index=True)
    values = pd.concat([d["value"], ml["cov90"], ml["width90"]])
    return Fig("Fig07_chronos", fig, data, values=values, problems=problems,
               notes=["raw Chronos daily diagnostic (T10) is quoted in the text, not plotted"])


# --- Fig08 windows of opportunity ----------------------------------------------------------------------

def fig08_conditional(plt, primary: str) -> Fig:
    t7 = table("T7_conditional_skill")
    d = t7[(t7["model"] == primary) & (t7["condition"] != "unknown")].copy()
    panels = (("enso", ["La Niña", "neutral", "El Niño"], "ENSO phase at issuance"),
              ("season", ["DJF", "MAM", "JJA", "SON"], "Season"),
              ("mjo", ["MJO inactive", "MJO active"], "MJO at issuance"))
    fig = plt.figure(figsize=(st.DOUBLE_MM * st.MM, 60 * st.MM))
    gs = fig.add_gridspec(1, 3, width_ratios=[3, 4, 2.3])
    width = 0.26
    axes = []
    for k, (split, cats, title) in enumerate(panels):
        ax = fig.add_subplot(gs[k], sharey=axes[0] if axes else None)
        axes.append(ax)
        for i, h in enumerate(st.HORIZONS):
            g = d[(d["split"] == split) & (d["horizon"] == h)].set_index("condition").reindex(cats)
            ax.bar(np.arange(len(cats)) + (i - 1) * width, g["CRPSS_clim"], width=width * 0.94,
                   color=st.HORIZON_TONE[h], lw=0, label=st.HORIZON_LABEL[h] if k == 0 else None)
        ns = d[(d["split"] == split) & (d["horizon"] == "W1")].set_index("condition")["n"]
        ax.set_xticks(range(len(cats)), [f"{c}\nn = {int(ns.get(c, 0))}" for c in cats])
        ax.axhline(0, color="#444444", lw=0.6)
        ax.set_xlabel(title)
        if k == 0:
            ax.set_ylabel(f"CRPSS vs climatology, M* (blind)")
        else:
            ax.tick_params(labelleft=False)
        st.panel_letter(ax, "abc"[k])
    fig.legend(*axes[0].get_legend_handles_labels(), loc="outside lower center", ncol=3,
               fontsize=6.2)
    problems = qa.check_finite(d, ["CRPSS_clim"])
    return Fig("Fig08_conditional_skill", fig, d, values=d["CRPSS_clim"], problems=problems,
               notes=["n = blind forecasts (stations x issuances) in each condition, Week 1"])


# --- Fig09 LOSO -----------------------------------------------------------------------------------------

def fig09_loso(plt, primary: str) -> Fig:
    t5 = read_station_keyed(TABLES / "T5_loso_gap.csv")
    models = [primary, "LSTM_LG", "GBM_LG"]
    d = t5[t5["model"].isin(models) & (t5["static_variant"] == "all")].copy()
    fig, axes = st.figure(plt, st.DOUBLE_MM, 60, ncols=3, sharey=True)
    # Stations as ordered categories (by elevation): two stations 140 m apart
    # would otherwise put their markers on top of each other.
    elevs = sorted(d["elev_m"].unique())
    xpos = {e: i for i, e in enumerate(elevs)}
    offs = dict(zip(models, (0.0, -0.22, 0.22)))
    for ax, h, letter in zip(axes, st.HORIZONS, "abc"):
        ax.axhline(0, color="#444444", lw=0.6)
        for m in models:
            g = d[(d["model"] == m) & (d["horizon"] == h)].sort_values("elev_m")
            key = "Ensemble" if m == primary else m
            w = st.weight(key)
            ax.errorbar(g["elev_m"].map(xpos) + offs[m], g["dCRPS_loso_minus_temporal"],
                        yerr=[g["dCRPS_loso_minus_temporal"] - g["ci_low"],
                              g["ci_high"] - g["dCRPS_loso_minus_temporal"]],
                        fmt=st.MARKER[key], ms=3.8, color=st.color(key), elinewidth=0.7,
                        capsize=0, lw=0, label=st.label(key) if h == "W1" else None,
                        zorder=w["zorder"])
        ax.set_xticks(range(len(elevs)), [f"{e:.0f}" for e in elevs])
        ax.set_xlim(-0.6, len(elevs) - 0.4)
        ax.set_xlabel("Held-out station, by elevation (m)")
        ax.text(0.5, 1.01, st.HORIZON_LABEL[h], transform=ax.transAxes, ha="center",
                va="bottom", fontsize=7)
        st.panel_letter(ax, letter)
    axes[0].set_ylabel("Skill lost when unseen\n(ΔCRPS, LOSO − temporal, °C)")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="outside lower center", ncol=3,
               fontsize=6.2)
    problems = qa.check_count(d, len(models) * 3 * 5, "model x horizon x station rows")
    return Fig("Fig09_loso", fig, d, values=d["dCRPS_loso_minus_temporal"], problems=problems,
               notes=["positive: the model forecasts worse at a station it was not trained on"])


# --- Fig10 case study ------------------------------------------------------------------------------------

def fig10_case(plt, cfg, primary: str) -> Fig:
    levels, cols = quantile_levels(cfg), qcols(cfg)
    index = read_eval_index("temporal")
    index = index[(index["target"] == TARGET) & (index["role"] == "blind")
                  & np.isfinite(index["obs"]) & (index["horizon"] == "W3_4")]
    hyb = preds_with_obs(MODELS_DIR / "hybrid" / f"preds_temporal_{HYBRID}.csv", index, cols)
    from _scores import crps_quantile
    hyb["crps"] = crps_quantile(hyb["obs"].to_numpy(float), hyb[cols].to_numpy(float), levels)
    per = hyb.groupby("station")["crps"].mean().sort_values()
    station = per.index[len(per) // 2]
    sts = stations(cfg).set_index("station")
    name = sts.loc[station, "name"] if station in sts.index else station
    def pick(df):
        """The station's weekly series with missing weeks as NaN rows, so lines and
        bands break at a data gap instead of joining across it."""
        g = df[df["station"] == station].sort_values("issue_date").set_index("issue_date")
        if g.empty:
            return g.reset_index()
        full = pd.date_range(g.index.min(), g.index.max(), freq="7D")
        g = g[~g.index.duplicated()].reindex(full)
        g[["lag_start", "lag_end"]] = g[["lag_start", "lag_end"]].ffill().bfill()
        return g.rename_axis("issue_date").reset_index()
    h = pick(hyb)
    m2 = pick(preds_with_obs(MODELS_DIR / "mstar2_preds.csv", index, cols))
    cfs = pick(preds_with_obs(MODELS_DIR / "preds_temporal_CFS_BC.csv", index, cols))
    mid = lambda df: df["issue_date"] + pd.to_timedelta((df["lag_start"] + df["lag_end"]) / 2,  # noqa: E731
                                                        unit="D")
    fig, ax = st.figure(plt, st.DOUBLE_MM, 66)
    t_lo, t_hi = mid(h).min(), mid(h).max()
    for a, b, kind in enso_episodes():
        a, b = max(a, t_lo), min(b, t_hi)
        if b > a:
            ax.axvspan(a, b, color="#F4B9A0" if kind == "El Niño" else "#BBD5EC", alpha=0.3,
                       lw=0, zorder=0)
    ax.fill_between(mid(h), h["q05"], h["q95"], color=st.color(HYBRID), alpha=0.22, lw=0,
                    label="Hybrid 90 % interval")
    ax.plot(mid(m2), m2["q05"], color=st.color("Mstar2"), lw=0.6, alpha=0.8,
            label="M*$_2$ 90 % interval")
    ax.plot(mid(m2), m2["q95"], color=st.color("Mstar2"), lw=0.6, alpha=0.8)
    ax.plot(mid(h), h["q50"], color=st.color(HYBRID), lw=1.3, label="Hybrid median")
    ax.plot(mid(cfs), cfs["q50"], color=st.color("CFS_BC"), lw=0.8, ls=(0, (1, 1)),
            label="CFSv2 (bias-corrected) median")
    ax.plot(mid(h), h["obs"], color="black", lw=0.9, marker="o", ms=1.8, label="Observed")
    ax.axhline(0, color="#999999", lw=0.5, zorder=1)
    # Fold boundaries inside the window: the forecasts just before one are
    # missing by design (their Weeks 3-4 target would fall in the next fold's
    # test year), so the gap is labelled instead of looking like lost data.
    for f in cfg["validation"]["folds"]:
        b = pd.Timestamp(f["test"][0])
        if t_lo < b < t_hi:
            prev = [g["id"] for g in cfg["validation"]["folds"]
                    if pd.Timestamp(g["test"][1]) < b][-1]
            ax.axvline(b, color="#555555", lw=0.6, ls=(0, (1, 1.5)), zorder=2)
            ax.text(b, 1.0, f"{prev} | {f['id']}", transform=ax.get_xaxis_transform(),
                    ha="center", va="bottom", fontsize=6.2, color="#555555")
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_xlim(t_lo - pd.Timedelta(days=7), t_hi + pd.Timedelta(days=7))
    ax.set_ylabel("Weeks 3–4 mean anomaly (°C)")
    ax.text(0.0, 1.0, f"{name} ({sts.loc[station, 'elev_m']:.0f} m), blind period", fontsize=6.5,
            transform=ax.transAxes, ha="left", va="bottom")
    from matplotlib.patches import Patch
    handles, labels = ax.get_legend_handles_labels()
    handles += [Patch(color="#F4B9A0", alpha=0.5), Patch(color="#BBD5EC", alpha=0.5)]
    labels += ["El Niño", "La Niña"]
    fig.legend(handles, labels, loc="outside lower center", ncol=7, fontsize=6.2,
               columnspacing=1.0, handlelength=1.6)
    data = pd.concat([h.assign(series="hybrid"), m2.assign(series="mstar2"),
                      cfs.assign(series="cfs_bc")], ignore_index=True)
    data["target_mid"] = mid(data)
    values = pd.concat([h["q50"], h["obs"], cfs["q50"]])
    return Fig("Fig10_case_study", fig, data, values=values,
               notes=[f"station chosen a priori: median hybrid CRPS of the five ({name}, "
                      f"rank {len(per) // 2 + 1} of {len(per)})",
                      "gap before the dotted line: Weeks 3-4 issuances whose target would "
                      "cross into the next fold's test year are not evaluated (by design)"])


# --- supplementary ----------------------------------------------------------------------------------------

def figS1_seeds(plt) -> Fig:
    t = table("T12_seed_variability")
    d = t[t["role"] == "blind"].copy()
    models = ["GBM_L", "GBM_LG", "LSTM_LG"]
    fig, ax = st.figure(plt, st.SINGLE_MM, 62)
    offs = dict(zip(models, (-0.18, 0, 0.18)))
    for m in models:
        g = d[d["model"] == m].set_index("horizon").reindex(st.HORIZONS)
        x = np.arange(3) + offs[m]
        ax.errorbar(x, g["CRPSS_clim_mean"], yerr=[g["CRPSS_clim_mean"] - g["CRPSS_clim_min"],
                                                    g["CRPSS_clim_max"] - g["CRPSS_clim_mean"]],
                    fmt=st.MARKER[m], ms=3.8, color=st.color(m), elinewidth=1.0, capsize=1.5,
                    lw=0, label=st.label(m), mfc="white" if m.endswith("_L") else st.color(m))
    ax.set_xticks(range(3), [st.HORIZON_LABEL[h] for h in st.HORIZONS])
    ax.set_ylabel("CRPSS vs climatology (blind),\nmean and range over 5 seeds")
    fig.legend(*ax.get_legend_handles_labels(), loc="outside lower center", ncol=3, fontsize=6.2)
    vals = pd.concat([d["CRPSS_clim_mean"]])
    return Fig("FigS1_seed_variability", fig, d, width=st.SINGLE_MM, kind="single", values=vals,
               problems=qa.check_count(d[d["model"].isin(models)], 9, "model x horizon rows"))


def figS2_dev_blind(plt) -> Fig:
    """Dev vs blind skill as a dumbbell plot: one row per model, one panel per horizon.

    A scatter of 24 points crowded into one corner hid which model was which; a
    row per model keeps every pair readable and shows the shift directly.
    """
    m = pd.read_csv(TABLES / "metrics_long.csv", dtype={"scope": "string"})
    models = ["Damp", "Chronos", "ChronosBolt", "Chronos@abs", "GBM_LG", "LSTM_LG", "Ridge_LG",
              "Ensemble"]
    d = m[(m["experiment"] == "temporal") & (m["scope"] == "pooled") & (m["target"] == TARGET)
          & m["model"].isin(models)]
    p = d.pivot_table(index=["model", "horizon"], columns="role", values="CRPSS_clim").dropna()
    p = p.reset_index()
    present = [x for x in models if x in set(p["model"])]
    # Rows ordered by blind skill at Weeks 3-4, best on top.
    w34 = p[p["horizon"] == "W3_4"].set_index("model")["blind"]
    present = sorted(present, key=lambda x: w34.get(x, -9))
    rows = {x: i for i, x in enumerate(present)}
    fig, axes = st.figure(plt, st.DOUBLE_MM, 66, ncols=3, sharey=True)
    lo = float(min(p["dev"].min(), p["blind"].min())) - 0.03
    hi = float(max(p["dev"].max(), p["blind"].max())) + 0.03
    for ax, h, letter in zip(axes, st.HORIZONS, "abc"):
        g = p[p["horizon"] == h]
        ax.axvline(0, color="#444444", lw=0.6)
        for _, r in g.iterrows():
            y, c = rows[r["model"]], st.color(r["model"])
            ax.plot([r["dev"], r["blind"]], [y, y], color=c, lw=1.0, alpha=0.6, zorder=2)
            ax.plot([r["dev"]], [y], ls="none", marker="o", ms=4.0, mfc="white", mec=c,
                    mew=0.9, zorder=3)
            ax.plot([r["blind"]], [y], ls="none", marker="o", ms=4.0, color=c, zorder=4)
        ax.set_xlim(lo, hi)
        ax.set_ylim(-0.6, len(present) - 0.4)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", visible=True)
        ax.tick_params(axis="y", length=0)
        ax.set_xlabel("CRPSS vs climatology")
        ax.text(0.5, 1.01, st.HORIZON_LABEL[h], transform=ax.transAxes, ha="center",
                va="bottom", fontsize=7)
        st.panel_letter(ax, letter)
    axes[0].set_yticks(range(len(present)), [st.label(x) for x in present])
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], ls="none", marker="o", ms=4, mfc="white", mec="#555555",
                      label="dev folds D1–D3"),
               Line2D([], [], ls="none", marker="o", ms=4, color="#555555",
                      label="blind folds B1–B2")]
    fig.legend(handles=handles, loc="outside lower center", ncol=2, fontsize=6.2)
    values = pd.concat([p["dev"], p["blind"]])
    return Fig("FigS2_dev_vs_blind", fig, p, values=values, axis="x",
               problems=qa.check_finite(p, ["dev", "blind"])
               + qa.check_count(p, len(present) * 3, "model x horizon rows"))


def figS3_budget(plt) -> Fig:
    t2 = table("T2_blind_skill")
    models = ["Ridge_L", "Ridge_LG", "GBM_L", "GBM_LG"]
    d = t2[(t2["metric"] == "CRPSS_damp") & t2["model"].isin(models)].copy()
    fig, ax = st.figure(plt, st.SINGLE_MM, 64)
    offs = dict(zip(models, (-0.12, -0.04, 0.04, 0.12)))
    ends = []
    for m in models:
        g = d[d["model"] == m].set_index("horizon").reindex(st.HORIZONS)
        x = np.arange(3) + offs[m]
        ls = "-" if m.endswith("LG") else (0, (3, 2))
        ax.errorbar(x, g["value"], yerr=[g["value"] - g["ci_low"], g["ci_high"] - g["value"]],
                    color=st.color(m), marker=st.MARKER[m], ms=3.6, lw=1.0, ls=ls,
                    elinewidth=0.6, capsize=0, mfc="white" if m.endswith("_L") else st.color(m))
        ends.append(float(g["value"].iloc[-1]))
    for m, y in zip(models, st.spread(ends, 0.03)):
        ax.text(2.25, y, st.label(m), fontsize=6.2, va="center", color=st.color(m))
    ax.axhline(0, color="#444444", lw=0.6)
    ax.set_xticks(range(3), [st.HORIZON_LABEL[h] for h in st.HORIZONS])
    ax.set_xlim(-0.3, 3.0)
    ax.spines["bottom"].set_bounds(0, 2)
    ax.set_ylabel("CRPSS vs damped persistence (blind)")
    return Fig("FigS3_predictability_budget", fig, d, width=st.SINGLE_MM, kind="single",
               values=d["value"], problems=qa.check_count(d, 12, "model x horizon rows"))


# --- driver ------------------------------------------------------------------------------------------------

def save_and_check(f: Fig, report: qa.Report) -> list[str]:
    from PIL import Image  # noqa: F401  (fail early if Pillow is missing)

    png, pdf, csv = (OUT / f"{f.name}.{ext}" for ext in ("png", "pdf", "csv"))
    problems = list(f.problems)
    if f.data is not None:
        f.data.to_csv(csv, index=False)
    if f.fig is not None:
        import warnings

        import matplotlib.pyplot as plt
        limit = st.MAX_HEIGHT_MM[f.kind if f.kind in st.MAX_HEIGHT_MM else "chart"]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            problems += qa.check_size(f.fig, f.width, limit)
            problems += qa.check_text(f.fig)
            problems += qa.check_clipping(f.fig)
            problems += qa.check_legend_overlap(f.fig)
            if f.values is not None:
                problems += qa.check_drawn(f.fig, f.values, axis=f.axis)
            f.fig.savefig(png, dpi=300)
            f.fig.savefig(pdf)
        problems += qa.check_glyphs(caught)
        plt.close(f.fig)
    elif f.image is not None:
        png.write_bytes(f.image[0])
        pdf.write_bytes(f.image[1])
    problems += qa.check_image(png)
    cvd = qa.simulate_cvd(png, QA_DIR / f"{f.name}_deuteranopia.png")
    gray = qa.grayscale(png, QA_DIR / f"{f.name}_grayscale.png")
    report.add(f.name, problems, [str(p.relative_to(FIGURES.parent)) for p in (png, pdf, csv)],
               f.notes)
    return [png, cvd, gray]


def probe() -> int:
    import shutil
    import subprocess

    import cartopy  # noqa: F401
    import geopandas  # noqa: F401
    import graphviz  # noqa: F401
    for layer in NE_LAYERS:
        gdf = _ne(*layer)
        print(f"[ok] Natural Earth {'/'.join(layer)}: {len(gdf)} features")
    if not len(_ne(*NE_LAYERS[2]).query("name.str.upper() == 'ANDES'", engine="python")):
        print("ERROR: Natural Earth geography regions have no ANDES polygon")
        return 1
    dot = shutil.which("dot")
    if not dot:
        print("ERROR: Graphviz `dot` is not on PATH (apt-get install graphviz)")
        return 1
    print("[ok]", subprocess.run([dot, "-V"], capture_output=True, text=True).stderr.strip())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true", help="check the map/diagram stack and exit")
    ap.add_argument("--only", nargs="*", default=None, help="figure names (e.g. Fig04)")
    args = ap.parse_args()
    if args.probe:
        return probe()
    cfg = load_config()
    print(paths_report())
    OUT.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    plt = st.setup()
    primary = json.loads((MODELS_DIR / "primary_model.json").read_text(encoding="utf-8"))[
        "primary_model"]
    builders = {
        "Fig01": lambda: fig01_study_area(plt, cfg),
        "Fig02": fig02_workflow,
        "Fig03": lambda: fig03_design(plt, cfg),
        "Fig04": lambda: fig04_skill(plt, primary),
        "Fig05": lambda: fig05_hybrid_tests(plt),
        "Fig06": lambda: fig06_calibration(plt, cfg, primary),
        "Fig07": lambda: fig07_chronos(plt, primary),
        "Fig08": lambda: fig08_conditional(plt, primary),
        "Fig09": lambda: fig09_loso(plt, primary),
        "Fig10": lambda: fig10_case(plt, cfg, primary),
        "FigS1": lambda: figS1_seeds(plt),
        "FigS2": lambda: figS2_dev_blind(plt),
        "FigS3": lambda: figS3_budget(plt),
    }
    if args.only:
        builders = {k: v for k, v in builders.items() if k in set(args.only)}
    report, sheet = qa.Report(), []
    for key, build in builders.items():
        try:
            f = build()
            sheet.append((f.name, save_and_check(f, report)))
            res = "FAIL" if report.figures[f.name]["problems"] else "ok"
            print(f"[{res}] {f.name}")
            for p in report.figures[f.name]["problems"]:
                print(f"       - {p}")
        except Exception as exc:  # noqa: BLE001 - one broken figure must not hide the rest
            report.add(key, [f"could not be drawn: {type(exc).__name__}: {exc}"],
                       notes=[traceback.format_exc(limit=3)])
            print(f"[FAIL] {key}: {type(exc).__name__}: {exc}")
    js, md = report.write(OUT)
    if sheet:
        qa.contact_sheet(sheet, OUT / "contact_sheet.png")
    print(f"wrote {md} and {OUT / 'contact_sheet.png'}")
    write_manifest({"paper_figures_11": {
        "figures": {n: e["files"] for n, e in report.figures.items()},
        "qa": [str(js.relative_to(FIGURES.parent)), str(md.relative_to(FIGURES.parent))],
        "failed": report.failed}}, replace=("paper_figures_11",))
    if report.failed:
        print(f"QA failed for: {', '.join(report.failed)} (details in {md})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

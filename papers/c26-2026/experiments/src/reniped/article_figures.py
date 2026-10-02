"""Manuscript figures (Figs. 1-6) in Spanish (internal review) and English (submission).

The figures are built only from the tables in outputs/tables, the territory-month panel
(data/processed/panel_departamento_mes.csv, for Fig. 2) and the geometry of the 26 territorial
units, so they can be regenerated without rerunning the analysis.
Elsevier artwork guidelines: double-column width 190 mm; printed text of at least 7 pt (6 pt for
subscripts); TIFF at 1000 dpi for line art and 600 dpi for maps; PNG at 300 dpi for preview.
Every figure is drawn at its final size (190 mm wide), so the declared font size is the printed
size. Mandatory note for maps: "Map lines delineate study areas and do not necessarily depict
accepted national boundaries."
"""
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import patheffects
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch, Rectangle

W_FIG = 7.48      # 190 mm, double-column width
FS = 7.0          # minimum printed font size (pt)
FS_T = 8.0        # panel titles (pt)
AZUL, NARANJA, GRIS, GRIS_CLARO = "#2a78d6", "#eb6834", "#9a9a96", "#e4e3df"
TXT2 = "#52514e"
ESTADO_COLOR = {0: "#1f5fae", 1: "#8fb8e8", 2: "#f2a878", 3: "#d9531e"}
LIMA_AREA = ["LIMA METROPOLITANA", "CALLAO", "REGION LIMA"]
NOMBRES = {"ANCASH": "Áncash", "APURIMAC": "Apurímac", "HUANUCO": "Huánuco", "JUNIN": "Junín",
           "SAN MARTIN": "San Martín", "REGION LIMA": "Región Lima",
           "LIMA METROPOLITANA": "Lima Metropolitana", "MADRE DE DIOS": "Madre de Dios",
           "LA LIBERTAD": "La Libertad"}
VARS_E2 = ["ANOMALIA", "CAMBIO_12M", "NIVEL_PREV12"]

L = {
    "es": {
        "sup": "Tasa mayor que el resto del país", "inf": "Tasa menor que el resto del país",
        "nd": "No se distingue del resto del país",
        "f2a": "(a) Clasificación de los territorios", "f2b": "(b) Razón de tasas frente al resto del país",
        "rr": "Razón de tasas (IC 95 %)", "share": "% de las\ndenuncias", "inset": "Lima y Callao",
        "k": "Número de grupos (K)", "gap": "Estadístico gap", "f4a": "(a) Estadístico gap",
        "gapnote": "Máximo en K = 1\n(sin evidencia\nde grupos)",
        "rows": "Filas", "units": "Territorios", "blocks": "Bloques de 12 meses",
        "thr": "Umbral 0,80", "stab": "Estabilidad (ARI medio)", "f4b": "(b) Estabilidad",
        "sil": "Índice de silueta", "f4c": "(c) Separación", "silthr": "Estructura razonable (≥ 0,50)",
        "kchosen": "K elegido",
        "f4d": "(d) Perfil de los cuatro estados en el espacio mixto (E2)",
        "zlab": "Valor estandarizado",
        "vars": {"ANOMALIA": "Anomalía estacional (A)", "CAMBIO_12M": "Cambio frente al nivel previo (C)",
                 "NIVEL_PREV12": "Nivel previo (N)"},
        "state": "Estado {k}: {n} meses, {u} territorios, tasa media {r} por 10 000",
        "boxnote": "Caja: percentiles 25-75; línea: mediana; bigotes: percentiles 10-90",
        "anchor": "Especificación del análisis inicial",
        "ranked": "Especificaciones ordenadas por el resultado",
        "leak": ("Con fuga de identidad territorial", "Sin fuga de identidad territorial"),
        "nmi": "Información compartida\ncon el territorio (NMI)",
        "sig": ("Significativo (p bilateral < 0,05)", "No significativo"),
        "moran": "I de Moran global\nde las tasas",
        "m1rows": [("unidad", "panel", "Unidad: departamento-mes"),
                   ("unidad", "celda", "Unidad: celda del registro"),
                   ("espacio", "E1_relativo", "Variables: relativas (E1)"),
                   ("espacio", "E2_relativo_mas_nivel", "Variables: mixtas (E2)"),
                   ("espacio", "E3_nivel", "Variables: de nivel (E3)"),
                   ("espacio", "E2_mas_ID", "Variables: E2 + peso del territorio"),
                   ("espacio", "O_manuscrito", "Variables: nueve iniciales"),
                   ("escalador", "standard", "Escalado: estándar"),
                   ("escalador", "robust", "Escalado: robusto")],
        "m2rows": [("pesos", "queen", "Vecindad: contigüidad"),
                   ("pesos", "knn4_geodesico", "Vecindad: 4 vecinos"),
                   ("pesos", "knn5_geodesico", "Vecindad: 5 vecinos"),
                   ("pesos", "knn5_grados_manuscrito", "Vecindad: 5 vecinos (inicial)"),
                   ("pesos", "invdist_grados_manuscrito", "Vecindad: distancia inversa (inicial)"),
                   ("periodo", "2019_2024", "Periodo: 2019–2024"),
                   ("periodo", "2019_2025", "Periodo: 2019–2025")],
        "f3cb": "Razón de tasas frente al resto del país (escala logarítmica)",
        "f3leg": "Clasificación 2019–2025",
        "f3note": "* 2025 preliminar",
        "rep_a": "(a) Denuncias registradas por año y variación frente al año anterior (%)",
        "rep_b": "(b) Denuncias registradas por mes",
        "rep_ylab": "Denuncias por mes",
        "rep_gap": "ene. 2023: sin datos\nde 6 departamentos",
        "months": ["ene.", "feb.", "mar.", "abr.", "may.", "jun.", "jul.", "ago.", "sep.", "oct.", "nov.", "dic."],
        "years_above": "Años por\nencima",
        "f5a": "(a) Agrupamiento: información compartida con el territorio (108 especificaciones)",
        "f5b": "(b) Estructura espacial: I de Moran global de las tasas (40 especificaciones)",
        "dec": ",",
        "fw": {
            "in_title": "Entradas",
            "inputs": [("Registro RENIPED", "Denuncias mensuales por desaparición, MININTER, 2019–2025"),
                       ("Población INEI", "Proyecciones anuales por territorio"),
                       ("Límites", "Capa provincial agregada en 26 territorios")],
            "panel": ("Panel territorio-mes",
                      ["26 territorios × 84 meses", "Denuncias por 10 000 personas-año",
                       "Meses sin cobertura: faltantes, nunca cero",
                       "Exposición observada (principal) y total (sensibilidad)"]),
            "stages": [("(i) Territorios prioritarios",
                        ["Razón de tasas frente al resto del país",
                         "Bootstrap de bloques de 12 meses y FDR"], "Fig. 3 y Fig. 4"),
                       ("(ii) Estados espaciotemporales",
                        ["Espacios E1, E2 y E3; k-medias, Ward, mezcla gaussiana y HDBSCAN",
                         "K por gap y estabilidad"], "Fig. 5"),
                       ("(iii) Estructura espacial",
                        ["I de Moran global, LISA y Gi* con valores p exactos",
                         "Dos matrices de vecindad y FDR"], "Tabla 2"),
                       ("(iv) Dinámica temporal",
                        ["Transferencia de los estados a 2024 y 2025",
                         "ARI y distancia de Jensen–Shannon"], "Sección 5.4")],
            "val": ("(v) Validación multinivel",
                    ["Identidad territorial: NMI frente a permutaciones por año",
                     "Reproducción del análisis inicial",
                     "Multiverso: 108 especificaciones de agrupamiento y 240 espaciales"],
                    "Fig. 6 y Tabla 3"),
            "repro": ("Reproducibilidad",
                      "Plan de análisis congelado con huella SHA-256 · archivos de entrada verificados · "
                      "semilla 42 · versiones de librerías fijadas · pruebas automáticas · "
                      "todas las cifras leídas de un único archivo de resultados"),
        },
    },
    "en": {
        "sup": "Rate higher than the rest of the country", "inf": "Rate lower than the rest of the country",
        "nd": "Not distinguishable from the rest",
        "f2a": "(a) Classification of territories", "f2b": "(b) Rate ratio versus the rest of the country",
        "rr": "Rate ratio (95% CI)", "share": "% of\nreports", "inset": "Lima and Callao",
        "k": "Number of clusters (K)", "gap": "Gap statistic", "f4a": "(a) Gap statistic",
        "gapnote": "Maximum at K = 1\n(no evidence\nof clusters)",
        "rows": "Rows", "units": "Territories", "blocks": "12-month blocks",
        "thr": "Threshold 0.80", "stab": "Stability (mean ARI)", "f4b": "(b) Stability",
        "sil": "Silhouette index", "f4c": "(c) Separation", "silthr": "Reasonable structure (≥ 0.50)",
        "kchosen": "K chosen",
        "f4d": "(d) Profile of the four states in the mixed space (E2)",
        "zlab": "Standardized value",
        "vars": {"ANOMALIA": "Seasonal anomaly (A)", "CAMBIO_12M": "Change from prior level (C)",
                 "NIVEL_PREV12": "Prior level (N)"},
        "state": "State {k}: {n} months, {u} territories, mean rate {r} per 10,000",
        "boxnote": "Box: 25th-75th percentiles; line: median; whiskers: 10th-90th percentiles",
        "anchor": "Initial-analysis specification",
        "ranked": "Specifications ranked by outcome",
        "leak": ("Territorial identity leakage", "No identity leakage"),
        "nmi": "Information shared\nwith territory (NMI)",
        "sig": ("Significant (two-sided p < 0.05)", "Not significant"),
        "moran": "Global Moran's I\nof rates",
        "m1rows": [("unidad", "panel", "Unit: department-month"),
                   ("unidad", "celda", "Unit: register cell"),
                   ("espacio", "E1_relativo", "Features: relative (E1)"),
                   ("espacio", "E2_relativo_mas_nivel", "Features: mixed (E2)"),
                   ("espacio", "E3_nivel", "Features: level (E3)"),
                   ("espacio", "E2_mas_ID", "Features: E2 + territory share"),
                   ("espacio", "O_manuscrito", "Features: nine initial"),
                   ("escalador", "standard", "Scaler: standard"),
                   ("escalador", "robust", "Scaler: robust")],
        "m2rows": [("pesos", "queen", "Weights: contiguity"),
                   ("pesos", "knn4_geodesico", "Weights: 4 neighbours"),
                   ("pesos", "knn5_geodesico", "Weights: 5 neighbours"),
                   ("pesos", "knn5_grados_manuscrito", "Weights: 5 neighbours (initial)"),
                   ("pesos", "invdist_grados_manuscrito", "Weights: inverse distance (initial)"),
                   ("periodo", "2019_2024", "Period: 2019–2024"),
                   ("periodo", "2019_2025", "Period: 2019–2025")],
        "f3cb": "Rate ratio versus the rest of the country (log scale)",
        "f3leg": "Classification 2019–2025",
        "f3note": "* 2025 preliminary",
        "rep_a": "(a) Reports recorded per year and change from the previous year (%)",
        "rep_b": "(b) Reports recorded per month",
        "rep_ylab": "Reports per month",
        "rep_gap": "Jan 2023: no data\nfor 6 departments",
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "years_above": "Years\nabove",
        "f5a": "(a) Clustering: information shared with territory (108 specifications)",
        "f5b": "(b) Spatial structure: global Moran's I of rates (40 specifications)",
        "dec": ".",
        "fw": {
            "in_title": "Inputs",
            "inputs": [("RENIPED register", "Monthly missing-person reports, MININTER, 2019–2025"),
                       ("INEI population", "Annual projections by territory"),
                       ("Boundaries", "Provincial layer aggregated into 26 territories")],
            "panel": ("Territory-month panel",
                      ["26 territories × 84 months", "Reports per 10,000 person-years",
                       "Months without coverage: missing, never zero",
                       "Observed exposure (main) and total (sensitivity)"]),
            "stages": [("(i) Priority territories",
                        ["Rate ratio versus the rest of the country",
                         "12-month block bootstrap and FDR"], "Fig. 3 and Fig. 4"),
                       ("(ii) Spatiotemporal states",
                        ["Spaces E1, E2 and E3; k-means, Ward, Gaussian mixture and HDBSCAN",
                         "K by gap statistic and stability"], "Fig. 5"),
                       ("(iii) Spatial structure",
                        ["Global Moran's I, LISA and Gi* with exact p-values",
                         "Two weights matrices and FDR"], "Table 2"),
                       ("(iv) Temporal dynamics",
                        ["Transfer of the states to 2024 and 2025",
                         "ARI and Jensen–Shannon distance"], "Section 5.4")],
            "val": ("(v) Multilevel validation",
                    ["Territorial identity: NMI against within-year permutations",
                     "Reproduction of the initial analysis",
                     "Multiverse: 108 clustering and 240 spatial specifications"],
                    "Fig. 6 and Table 3"),
            "repro": ("Reproducibility",
                      "Frozen analysis plan with SHA-256 fingerprint · verified input files · "
                      "seed 42 · pinned library versions · automated tests · "
                      "every number read from a single results file"),
        },
    },
}


def nombre(k):
    return NOMBRES.get(k, k.title())


def _style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": FS, "axes.labelsize": FS,
                         "axes.titlesize": FS_T, "xtick.labelsize": FS, "ytick.labelsize": FS,
                         "legend.fontsize": FS, "legend.title_fontsize": FS,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
                         "xtick.major.width": 0.6, "ytick.major.width": 0.6,
                         "xtick.major.size": 2.5, "ytick.major.size": 2.5})


def _comma_axes(fig):
    from matplotlib.ticker import FuncFormatter
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            if axis.get_scale() == "linear" and axis.get_major_formatter().__class__.__name__ == "ScalarFormatter":
                axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",").replace("-", "\u2212")))


def _save(fig, out_dir, name, tiff_dpi):
    """Save PNG (preview) and TIFF (submission); warn if the width exceeds 190 mm."""
    if name.endswith("_es"):
        _comma_axes(fig)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kw = {"bbox_inches": "tight", "pad_inches": 0.03, "facecolor": "white"}
    fig.savefig(out_dir / f"{name}.png", dpi=300, **kw)
    fig.savefig(out_dir / f"{name}.tiff", dpi=tiff_dpi, pil_kwargs={"compression": "tiff_lzw"}, **kw)
    bb = fig.get_tightbbox(fig.canvas.get_renderer())
    if bb.width > W_FIG + 0.07:
        print(f"AVISO {name}: ancho {bb.width * 25.4:.0f} mm > 190 mm; la letra se reduciría al imprimir")
    plt.close(fig)


def _fmt(x, lang, nd=2):
    s = f"{x:.{nd}f}"
    return s.replace(".", ",") if L[lang]["dec"] == "," else s


def _int(n, lang):
    s = f"{int(n):,}"
    return s.replace(",", " ") if lang == "es" else s


# ---------------------------------------------------------------- Fig. 1 (framework diagram)
def _wrap(text, width_in, fs=FS, k=0.53):
    n = max(10, int(width_in * 72 / (fs * k)))
    return textwrap.wrap(text, n, break_on_hyphens=False)


def _box(ax, x, y, w, h, title, lines, fc, bar=None, ref=None, pad=0.08):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.04",
                                fc=fc, ec="0.45", lw=0.6))
    x0 = x + pad
    if bar:
        ax.add_patch(Rectangle((x, y), 0.05, h, fc=bar, ec="none"))
        x0 += 0.03
    yy = y + h - pad
    for tl in _wrap(title, w - (x0 - x) - pad, FS + 0.5, 0.64):
        ax.text(x0, yy, tl, fontsize=FS + 0.5, weight="bold", va="top")
        yy -= 0.135
    yy -= 0.02
    body = [ln for t in lines for ln in _wrap(t, w - (x0 - x) - pad)]
    for ln in body:
        ax.text(x0, yy, ln, fontsize=FS, va="top")
        yy -= 0.118
    if ref:
        ax.text(x + w - pad, y + pad * 0.7, "→ " + ref, fontsize=FS, va="bottom", ha="right",
                color=TXT2, style="italic")


def _arrow(ax, p0, p1):
    ax.annotate("", xy=p1, xytext=p0,
                arrowprops={"arrowstyle": "-|>", "lw": 0.7, "color": "0.35", "mutation_scale": 7,
                            "shrinkA": 0, "shrinkB": 0})


def figure1_framework(out_dir, lang):
    """Fig. 1: architecture of the framework (sources, panel, four analytical stages, validation)."""
    _style()
    t = L[lang]["fw"]
    H = 4.05
    Wi = W_FIG - 0.10                      # margin so that the tightly cropped TIFF does not exceed 190 mm
    fig = plt.figure(figsize=(Wi, H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, Wi); ax.set_ylim(0, H); ax.axis("off")
    ytop = 3.98
    xa, wa = 0.02, 1.40
    ax.text(xa, ytop, t["in_title"], fontsize=FS_T, weight="bold", va="top")
    hb, gap = 0.78, 0.13
    ys = [ytop - 0.22 - hb - i * (hb + gap) for i in range(3)]
    for (ti, tx), y in zip(t["inputs"], ys):
        _box(ax, xa, y, wa, hb, ti, [tx], fc="#f3f2ef")
    xb, wb = 1.66, 1.36
    yb0, yb1 = ys[-1], ys[0] + hb
    _box(ax, xb, yb0, wb, yb1 - yb0, t["panel"][0], t["panel"][1], fc="#e8f0fb", ref="Fig. 2")
    for y in ys:
        _arrow(ax, (xa + wa, y + hb / 2), (xb, y + hb / 2))
    xc, wc = 3.26, 2.42
    hs, gs = 0.72, 0.09
    yc = [ytop - hs - i * (hs + gs) for i in range(4)]
    bars = [NARANJA, AZUL, "#3d9a6a", "#8a6bbd"]
    for (ti, ln, ref), y, bc in zip(t["stages"], yc, bars):
        _box(ax, xc, y, wc, hs, ti, ln, fc="white", bar=bc, ref=ref)
        _arrow(ax, (xb + wb, y + hs / 2), (xc, y + hs / 2))
    xd, wd = 5.92, Wi - 5.92 - 0.02
    yd0, yd1 = yc[3], yc[1] + hs
    _box(ax, xd, yd0, wd, yd1 - yd0, t["val"][0], t["val"][1], fc="#fdf0e9", ref=t["val"][2])
    for y in yc[1:]:
        _arrow(ax, (xc + wc, y + hs / 2), (xd, y + hs / 2))
    _box(ax, 0.02, 0.05, Wi - 0.04, 0.56, t["repro"][0], [t["repro"][1]], fc="#f3f2ef")
    _save(fig, out_dir, f"Fig1_framework_{lang}", 1000)


# ---------------------------------------------------------------- Fig. 2 (reports per year and month)
def _pct(x, lang):
    s = (f"{x:+.1f} %" if lang == "es" else f"{x:+.1f}%").replace("-", "−")
    return s.replace(".", ",") if lang == "es" else s


def figure2_reports(panel, out_dir, lang):
    """Fig. 2: national reports per year with the change from the previous year (a) and per
    month (b). Months without source rows count as missing, so January 2023 is marked."""
    _style()
    t = L[lang]
    m = panel.groupby(["ANO", "MES"])["REPORTES"].sum(min_count=1).reset_index()
    years = sorted(m["ANO"].unique())
    annual = m.groupby("ANO")["REPORTES"].sum().reindex(years)
    change = annual.pct_change() * 100
    fig = plt.figure(figsize=(W_FIG, 4.6))

    # (a) annual totals; the preliminary last year is hatched
    ax = fig.add_axes([0.075, 0.62, 0.90, 0.29])
    x = list(range(len(years)))
    ax.bar(x, annual.values, width=0.62, color=[AZUL] * (len(years) - 1) + ["white"],
           edgecolor=AZUL, linewidth=0.8)
    ax.bar([x[-1]], [annual.values[-1]], width=0.62, color="none", edgecolor=AZUL, hatch="////",
           linewidth=0.8)
    top = annual.max()
    for i, (v, c) in enumerate(zip(annual.values, change.values)):
        ax.text(i, v + top * 0.03, _int(v, lang), ha="center", va="bottom", fontsize=FS)
        if i > 0:
            ax.text(i, v + top * 0.145, _pct(c, lang), ha="center", va="bottom", fontsize=FS, color=TXT2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{y}*" if y == years[-1] else str(y) for y in years])
    ax.set_xlim(-0.6, len(years) - 0.4)
    ax.set_ylim(0, top * 1.32)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="x", length=0)
    fig.text(0.01, 0.975, t["rep_a"], fontsize=FS_T, va="top")

    # (b) monthly totals; the preliminary last year is shaded
    bx = fig.add_axes([0.075, 0.10, 0.90, 0.36])
    xi = list(range(len(m)))
    y = m["REPORTES"].to_numpy()
    bx.axvspan((len(years) - 1) * 12 - 0.5, len(m) - 0.5, color=GRIS_CLARO, alpha=0.55, lw=0, zorder=0)
    for k in range(1, len(years)):
        bx.axvline(k * 12 - 0.5, color="0.85", lw=0.5, zorder=0)
    bx.plot(xi, y, color=AZUL, lw=1.2, zorder=3)
    bx.scatter(xi, y, s=6, color=AZUL, zorder=4, linewidths=0)
    for i, dy in ((int(np.nanargmax(y)), 0), (int(np.nanargmin(y)), -2)):
        label = f"{t['months'][int(m['MES'][i]) - 1]} {int(m['ANO'][i])}: {_int(y[i], lang)}"
        bx.annotate(label, (i, y[i]), xytext=(8, dy), textcoords="offset points", fontsize=FS,
                    color=TXT2, va="center")
    gap = m.index[(m["ANO"] == 2023) & (m["MES"] == 1)]
    if len(gap):
        g = int(gap[0])
        bx.scatter([g], [y[g]], s=22, facecolor="white", edgecolor=NARANJA, lw=1.0, zorder=5)
        bx.annotate(t["rep_gap"], (g, y[g]), xytext=(0, -22), textcoords="offset points", fontsize=FS,
                    color=TXT2, ha="center", va="top", arrowprops=dict(arrowstyle="-", color="0.6", lw=0.5))
    bx.set_xticks([k * 12 + 5.5 for k in range(len(years))])
    bx.set_xticklabels([f"{yy}*" if yy == years[-1] else str(yy) for yy in years])
    bx.tick_params(axis="x", length=0)
    bx.set_xlim(-0.8, len(m) - 0.2)
    bx.set_ylim(0, np.nanmax(y) * 1.12)
    bx.set_ylabel(t["rep_ylab"])
    bx.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _int(v, lang)))
    bx.grid(axis="y", color="0.9", lw=0.5)
    bx.set_axisbelow(True)
    fig.text(0.01, 0.525, t["rep_b"], fontsize=FS_T, va="top")
    fig.text(0.075, 0.005, t["f3note"], fontsize=FS, color=TXT2, va="bottom")
    _save(fig, out_dir, f"Fig2_reports_{lang}", 1000)


# ---------------------------------------------------------------- Fig. 3 (priority territories)
def _halo(color):
    other = "black" if color == "white" else "white"
    return [patheffects.withStroke(linewidth=1.6, foreground=other, alpha=0.55)]


def figure3_priority(units, prio, out_dir, lang):
    """Fig. 3: map of the priority classes (a) and forest plot of rate ratios with 95% CIs (b)."""
    _style()
    t = L[lang]
    d = prio.sort_values("RR_VS_RESTO", ascending=False).reset_index(drop=True)
    rank = {k: i + 1 for i, k in enumerate(d.DPTO_KEY)}
    g = units.merge(prio[["DPTO_KEY", "CLASE"]], on="DPTO_KEY", validate="one_to_one")
    color_clase = {"superior": NARANJA, "inferior": AZUL, "no_distinguible": GRIS_CLARO}
    fig = plt.figure(figsize=(W_FIG, 6.0))
    a = fig.add_axes([0.0, 0.08, 0.47, 0.85])
    b = fig.add_axes([0.665, 0.115, 0.26, 0.815])

    g.plot(ax=a, color=g.CLASE.map(color_clase), edgecolor="0.3", linewidth=0.35)
    offs = {"TUMBES": (-14, 6)}
    for _, r in g[~g.DPTO_KEY.isin(["LIMA METROPOLITANA", "CALLAO"])].iterrows():
        p = r.geometry.representative_point()
        col = "white" if r.CLASE == "inferior" else "black"
        kw = {"fontsize": FS + 0.5, "ha": "center", "va": "center", "weight": "bold"}
        if r.DPTO_KEY in offs:
            a.annotate(str(rank[r.DPTO_KEY]), (p.x, p.y), xytext=offs[r.DPTO_KEY], textcoords="offset points",
                       arrowprops={"arrowstyle": "-", "lw": 0.5, "color": "0.25", "shrinkA": 0, "shrinkB": 0},
                       color="black", **kw)
        else:
            a.annotate(str(rank[r.DPTO_KEY]), (p.x, p.y), color=col, path_effects=_halo(col), **kw)
    ins = a.inset_axes([0.0, 0.0, 0.33, 0.33])
    sub = g[g.DPTO_KEY.isin(LIMA_AREA)]
    sub.plot(ax=ins, color=sub.CLASE.map(color_clase), edgecolor="0.3", linewidth=0.35)
    geo = {r.DPTO_KEY: r.geometry.representative_point() for _, r in sub.iterrows()}
    x0, y0, x1, y1 = sub.total_bounds
    ins.annotate(str(rank["REGION LIMA"]), (geo["REGION LIMA"].x, y0 + 0.70 * (y1 - y0)),
                 fontsize=FS + 0.5, weight="bold", ha="center", va="center")
    for key, dy in (("LIMA METROPOLITANA", -0.14), ("CALLAO", 0.08)):
        ins.annotate(str(rank[key]), (geo[key].x, geo[key].y),
                     xytext=(x0 - 0.08 * (x1 - x0), geo[key].y + dy * (y1 - y0)),
                     fontsize=FS + 0.5, weight="bold", ha="right", va="center",
                     arrowprops={"arrowstyle": "-", "lw": 0.5, "color": "0.25"})
    ins.set_xlim(x0 - 0.45 * (x1 - x0), x1 + 0.05 * (x1 - x0))
    ins.set_title(t["inset"], fontsize=FS, pad=2)
    ins.set_xticks([]); ins.set_yticks([])
    for sp in ins.spines.values():
        sp.set_visible(True); sp.set_linewidth(0.5)
    a.set_axis_off()
    fig.text(0.005, 0.975, t["f2a"], fontsize=FS_T, va="top")

    y = np.arange(len(d))[::-1]
    for yi, (_, r) in zip(y, d.iterrows()):
        c = color_clase[r.CLASE] if r.CLASE != "no_distinguible" else GRIS
        b.plot([r.RR_IC95_INF, r.RR_IC95_SUP], [yi, yi], color=c, lw=1.3, solid_capstyle="butt")
        b.plot(r.RR_VS_RESTO, yi, "o", color=c, ms=4.0, mec="white", mew=0.5)
        b.text(2.30, yi, _fmt(r.CUOTA_REPORTES_PCT, lang, 1), fontsize=FS, va="center", ha="right",
               color=TXT2)
    b.axvline(1.0, color="0.2", lw=0.7, ls=(0, (4, 2)))
    b.set_yticks(y)
    b.set_yticklabels([nombre(k) + "\u2007\u2007" + f"{rank[k]:>2}".replace(" ", "\u2007") for k in d.DPTO_KEY])
    b.tick_params(axis="y", length=0, pad=3)
    b.set_xlim(0.35, 2.32)
    b.set_xticks([0.5, 1.0, 1.5, 2.0])
    b.set_ylim(-0.7, len(d) - 0.3)
    b.set_xlabel(t["rr"])
    b.text(2.30, len(d) - 0.2, t["share"], fontsize=FS, ha="right", va="bottom", color=TXT2)
    fig.text(0.47, 0.975, t["f2b"], fontsize=FS_T, va="top")
    from matplotlib.ticker import FuncFormatter
    dec = "," if lang == "es" else "."
    b.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}".replace(".", dec)))
    fig.legend(handles=[Patch(fc=NARANJA, ec="0.3", lw=0.3, label=t["sup"]),
                        Patch(fc=GRIS_CLARO, ec="0.3", lw=0.3, label=t["nd"]),
                        Patch(fc=AZUL, ec="0.3", lw=0.3, label=t["inf"])],
               loc="lower center", bbox_to_anchor=(0.5, -0.005), frameon=False, ncol=3,
               handlelength=1.4, columnspacing=1.2)
    _save(fig, out_dir, f"Fig3_priority_{lang}", 600)


# ---------------------------------------------------------------- Fig. 4 (persistence)
def figure4_persistence(anual, prio, out_dir, lang):
    """Fig. 4 heat map: annual rate ratio of each territory versus the rest of the country."""
    from matplotlib.colors import LinearSegmentedColormap, LogNorm
    _style()
    t = L[lang]
    order = prio.sort_values("RR_VS_RESTO", ascending=False)["DPTO_KEY"].tolist()
    piv = anual.pivot(index="DPTO_KEY", columns="ANO", values="RR_VS_RESTO").loc[order]
    years = list(piv.columns)
    cmap = LinearSegmentedColormap.from_list("div", [AZUL, "#f0efec", NARANJA])
    norm = LogNorm(vmin=0.4, vmax=2.5)
    color_clase = {"superior": NARANJA, "inferior": AZUL, "no_distinguible": GRIS_CLARO}
    fig = plt.figure(figsize=(W_FIG, 6.3))
    ax = fig.add_axes([0.19, 0.155, 0.60, 0.80])
    ax.imshow(piv.values, cmap=cmap, norm=norm, aspect="auto")
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            ax.text(j, i, _fmt(v, lang, 2), ha="center", va="center", fontsize=FS,
                    color="white" if (v >= 1.9 or v <= 0.55) else "black")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels([f"{y}*" if y == max(years) else str(y) for y in years])
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([nombre(k) for k in order])
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    p = prio.set_index("DPTO_KEY").loc[order]
    for i, (cl, n_up) in enumerate(zip(p["CLASE"], p["ANIOS_SOBRE_RESTO"])):
        ax.add_patch(plt.Rectangle((len(years) - 0.5 + 0.15, i - 0.38), 0.28, 0.76, fc=color_clase[cl],
                                   clip_on=False, ec="0.3", lw=0.3))
        ax.text(len(years) + 0.85, i, f"{int(n_up)}/{len(years)}", fontsize=FS, va="center", ha="center",
                color=TXT2)
    ax.text(len(years) + 0.85, -0.75, t["years_above"], fontsize=FS, ha="center", va="bottom", color=TXT2)
    cax = fig.add_axes([0.19, 0.075, 0.36, 0.016])
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    ticks = [0.5, 0.75, 1, 1.5, 2]
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal", ticks=ticks)
    cb.ax.set_xticklabels([_fmt(v, lang, 2 if v == 0.75 else (1 if v in (0.5, 1.5) else 0)) for v in ticks])
    cb.ax.minorticks_off()
    cb.outline.set_linewidth(0.4)
    cb.ax.set_title(t["f3cb"], fontsize=FS, pad=3)
    fig.text(0.19, 0.012, t["f3note"], fontsize=FS, color=TXT2)
    fig.legend(handles=[Patch(fc=NARANJA, ec="0.3", lw=0.3, label=t["sup"]),
                        Patch(fc=GRIS_CLARO, ec="0.3", lw=0.3, label=t["nd"]),
                        Patch(fc=AZUL, ec="0.3", lw=0.3, label=t["inf"])],
               loc="lower right", bbox_to_anchor=(0.995, 0.0), frameon=False, ncol=1,
               title=t["f3leg"], handlelength=1.4, alignment="left")
    _save(fig, out_dir, f"Fig4_persistence_{lang}", 1000)


# ---------------------------------------------------------------- Fig. 5 (spatiotemporal states)
def figure5_states(ktab, gap, k_star, prof, dist, out_dir, lang):
    """Fig. 5: choice of K (gap, stability, silhouette) and standardized profile of each state."""
    _style()
    t = L[lang]
    gap = gap[gap.K <= ktab.K.max()]
    fig = plt.figure(figsize=(W_FIG, 5.3))
    gsp = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.15], hspace=0.48, wspace=0.42,
                           left=0.085, right=0.99, top=0.95, bottom=0.135)
    a, b, c = (fig.add_subplot(gsp[0, i]) for i in range(3))
    a.errorbar(gap.K, gap.gap, yerr=gap.s_k, color=AZUL, marker="o", ms=3.5, lw=1.3, capsize=2)
    a.plot(gap.K.iloc[0], gap.gap.iloc[0], "o", ms=8, mfc="none", mec=NARANJA, mew=1.3)
    a.annotate(t["gapnote"], (gap.K.iloc[0], gap.gap.iloc[0]), xytext=(2.6, gap.gap.iloc[0] - 0.02),
               fontsize=FS, color=TXT2, va="top",
               arrowprops={"arrowstyle": "-", "lw": 0.5, "color": TXT2})
    a.set_xlabel(t["k"]); a.set_ylabel(t["gap"]); a.set_title(t["f4a"], loc="left")
    a.set_xticks(range(1, int(ktab.K.max()) + 1))
    for col, lab, cc, ls, mk in (("ari_media_fila", t["rows"], GRIS, ":", "s"),
                                 ("ari_media_unidad", t["units"], AZUL, "-", "o"),
                                 ("ari_media_bloque_temporal", t["blocks"], NARANJA, "--", "^")):
        b.plot(ktab.K, ktab[col], color=cc, ls=ls, marker=mk, ms=3.5, lw=1.3, label=lab)
    b.axhline(0.80, color="0.2", lw=0.7, ls=(0, (4, 2)))
    b.text(8.2, 0.81, t["thr"], fontsize=FS, color=TXT2, ha="right", va="bottom")
    b.set_ylim(0.2, 1.0)
    b.set_xlabel(t["k"]); b.set_ylabel(t["stab"]); b.set_title(t["f4b"], loc="left")
    b.legend(frameon=False, loc="lower left", handlelength=2.2, borderaxespad=0.2, labelspacing=0.3)
    c.plot(ktab.K, ktab.silhouette, color=AZUL, marker="o", ms=3.5, lw=1.3)
    c.set_ylim(0, 0.6)
    c.axhline(0.5, color="0.2", lw=0.7, ls=(0, (4, 2)))
    c.text(1.8, 0.515, t["silthr"], fontsize=FS, color=TXT2, va="bottom",
           bbox={"fc": "white", "ec": "none", "pad": 0.5}, zorder=5)
    c.set_xlabel(t["k"]); c.set_ylabel(t["sil"]); c.set_title(t["f4c"], loc="left")
    for x in (b, c):
        x.axvline(k_star, color="0.5", lw=0.6, ls=":")
        x.set_xticks(range(int(ktab.K.min()), int(ktab.K.max()) + 1))
    b.text(k_star + 0.15, 0.985, t["kchosen"], fontsize=FS, color=TXT2, va="top")

    dd = fig.add_subplot(gsp[1, :])
    states = sorted(prof.CLUSTER.unique())
    offs = np.linspace(-0.3, 0.3, len(states))
    for gi, var in enumerate(VARS_E2):
        for off, k in zip(offs, states):
            r = dist[(dist.CLUSTER == k) & (dist.VARIABLE == var)].iloc[0]
            x = gi + off
            col = ESTADO_COLOR.get(k, GRIS)
            dd.plot([x, x], [r["10%"], r["25%"]], color="0.3", lw=0.7)
            dd.plot([x, x], [r["75%"], r["90%"]], color="0.3", lw=0.7)
            dd.add_patch(Rectangle((x - 0.075, r["25%"]), 0.15, r["75%"] - r["25%"], fc=col, ec="0.3", lw=0.5))
            dd.plot([x - 0.075, x + 0.075], [r["50%"], r["50%"]], color="black", lw=1.0)
    dd.axhline(0, color="0.5", lw=0.5, ls=":")
    dd.set_xticks(range(len(VARS_E2)))
    dd.set_xticklabels([t["vars"][v] for v in VARS_E2])
    dd.set_xlim(-0.55, len(VARS_E2) - 0.45)
    dd.set_ylabel(t["zlab"])
    dd.tick_params(axis="x", length=0)
    dd.set_title(t["f4d"], loc="left")
    dd.text(0.995, 0.98, t["boxnote"], transform=dd.transAxes, ha="right", va="top", fontsize=FS, color=TXT2)
    hand = []
    for k in states:
        r = prof[prof.CLUSTER == k].iloc[0]
        hand.append(Patch(fc=ESTADO_COLOR.get(k, GRIS), ec="0.3", lw=0.4,
                          label=t["state"].format(k=int(k), n=_int(r.N, lang), u=int(r.UNIDADES),
                                                  r=_fmt(r.TASA_10K_MENSUAL_MEDIA, lang, 2))))
    fig.legend(handles=hand, loc="lower center", bbox_to_anchor=(0.53, 0.0), ncol=2, frameon=False,
               handlelength=1.4, columnspacing=1.5, labelspacing=0.4)
    _save(fig, out_dir, f"Fig5_states_{lang}", 1000)


# ---------------------------------------------------------------- Fig. 6 (multilevel validation)
def _curve(a, b, spec, y, flag, flag_labels, rows, ylab, anchor_col, t):
    s = spec.sort_values(y).reset_index(drop=True)
    x = np.arange(len(s))
    a.scatter(x, s[y], c=np.where(s[flag], NARANJA, GRIS), s=11, lw=0)
    anc = s.index[s[anchor_col]]
    a.scatter(anc, s.loc[anc, y], s=70, facecolors="none", edgecolors="black", lw=1.1)
    a.set_ylabel(ylab)
    a.legend(handles=[Line2D([], [], ls="", marker="o", ms=4, mfc=NARANJA, mec=NARANJA, label=flag_labels[0]),
                      Line2D([], [], ls="", marker="o", ms=4, mfc=GRIS, mec=GRIS, label=flag_labels[1]),
                      Line2D([], [], ls="", marker="o", ms=8, mfc="none", mec="black", label=t["anchor"])],
             frameon=False, loc="upper left", borderaxespad=0.2)
    plt.setp(a.get_xticklabels(), visible=False)
    ticks, labels = [], []
    for r, (col, val, lab) in enumerate(rows):
        m = s[col].astype(str) == str(val)
        b.scatter(x[m], np.full(m.sum(), -r), marker="|", s=18, color="0.25", lw=0.9)
        ticks.append(-r); labels.append(lab)
    b.set_yticks(ticks); b.set_yticklabels(labels)
    b.set_ylim(-len(rows) + 0.4, 0.6)
    b.set_xlabel(t["ranked"])
    b.spines["left"].set_visible(False); b.tick_params(axis="y", length=0)


def figure6_validation(m1, m2, out_dir, lang):
    """Fig. 6: two specification curves; only the most influential decisions are displayed."""
    _style()
    t = L[lang]
    n1, n2 = len(t["m1rows"]), len(t["m2rows"])
    fig = plt.figure(figsize=(W_FIG, 8.2))
    gs = fig.add_gridspec(5, 1, height_ratios=[1.8, 0.16 * n1, 0.5, 1.8, 0.16 * n2], hspace=0.10,
                          top=0.965, bottom=0.06, left=0.29, right=0.99)
    a1 = fig.add_subplot(gs[0]); b1 = fig.add_subplot(gs[1], sharex=a1)
    a2 = fig.add_subplot(gs[3]); b2 = fig.add_subplot(gs[4], sharex=a2)
    _curve(a1, b1, m1, "NMI_unidad", "fuga_identidad", t["leak"], t["m1rows"], t["nmi"],
           "es_manuscrito_original", t)
    d = m2[(m2.variable != "conteo") & (m2.tipo_p == "bilateral") & (m2.correccion_local == "ninguna")].copy()
    d["sig"] = d.p_global < 0.05
    d["ancla"] = (d.winsor.astype(bool) & (d.periodo == "2019_2025")
                  & (d.variable == "tasa_exposicion_total") & (d.pesos == "knn5_grados_manuscrito"))
    _curve(a2, b2, d, "moran_I", "sig", t["sig"], t["m2rows"], t["moran"], "ancla", t)
    fig.text(0.005, 0.992, t["f5a"], fontsize=FS_T, va="top")
    pos = a2.get_position()
    fig.text(0.005, pos.y1 + 0.032, t["f5b"], fontsize=FS_T, va="bottom")
    _save(fig, out_dir, f"Fig6_validation_{lang}", 1000)


def build_all(tables_dir, units, k_star, out_dir, panel, langs=("es", "en")):
    """Build Figs. 1-6 in every language from the saved tables and the territory-month panel;
    return the list of files."""
    tables_dir = Path(tables_dir)
    prio = pd.read_csv(tables_dir / "T14_territorios_prioritarios.csv")
    anual = pd.read_csv(tables_dir / "T14b_razon_tasas_anual.csv")
    ktab = pd.read_csv(tables_dir / "T02_seleccion_K.csv")
    gap = pd.read_csv(tables_dir / "T02b_gap_desde_K1.csv")
    prof = pd.read_csv(tables_dir / "T04_perfiles_cluster.csv")
    dist = pd.read_csv(tables_dir / "T04c_distribucion_estandarizada_por_estado.csv")
    m1 = pd.read_csv(tables_dir / "T12_multiverso_M1_especificaciones.csv")
    m2 = pd.read_csv(tables_dir / "T13_multiverso_M2_especificaciones.csv")
    for lang in langs:
        figure1_framework(out_dir, lang)
        figure2_reports(panel, out_dir, lang)
        figure3_priority(units, prio, out_dir, lang)
        figure4_persistence(anual, prio, out_dir, lang)
        figure5_states(ktab, gap, k_star, prof, dist, out_dir, lang)
        figure6_validation(m1, m2, out_dir, lang)
    return sorted(p.name for p in Path(out_dir).iterdir())

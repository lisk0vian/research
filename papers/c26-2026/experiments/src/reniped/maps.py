"""Supplementary maps (300 dpi, no embedded title).
Mandatory caption note: "Map lines delineate study areas and do not necessarily
depict accepted national boundaries."
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

from .figures import save

LIMA_AREA = ["LIMA METROPOLITANA", "CALLAO", "REGION LIMA"]
NOMBRES = {"ANCASH": "Áncash", "APURIMAC": "Apurímac", "HUANUCO": "Huánuco",
           "JUNIN": "Junín", "SAN MARTIN": "San Martín", "REGION LIMA": "Región Lima",
           "LIMA METROPOLITANA": "Lima Metropolitana", "MADRE DE DIOS": "Madre de Dios",
           "LA LIBERTAD": "La Libertad"}


def display_name(key):
    return NOMBRES.get(key, key.title())


def _inset_lima(ax, units, column=None, **kw):
    # inset outside the main map so that it does not cover the central coast
    ins = inset_axes(ax, width="42%", height="42%", loc="lower left",
                     bbox_to_anchor=(-0.46, 0.02, 1, 1), bbox_transform=ax.transAxes,
                     borderpad=0)
    sub = units[units.DPTO_KEY.isin(LIMA_AREA)]
    if column is None:
        sub.plot(ax=ins, **kw)
    else:
        sub.plot(ax=ins, column=column, **kw)
    sub.boundary.plot(ax=ins, color="0.2", linewidth=0.4)
    ins.set_title("Lima Metropolitana, Callao\ny Región Lima", fontsize=5.5, pad=2)
    ins.set_xticks([]); ins.set_yticks([])
    for s in ins.spines.values():
        s.set_visible(True)
        s.set_linewidth(0.5)
    return ins


def study_area_map(units, figures_dir, name):
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    colors = {"LIMA METROPOLITANA": "#d95f02", "CALLAO": "#b2182b", "REGION LIMA": "#1b9e77"}
    units.assign(C=units.DPTO_KEY.map(colors).fillna("0.88")).plot(
        ax=ax, color=units.DPTO_KEY.map(colors).fillna("0.88"), edgecolor="0.3", linewidth=0.3)
    for _, r in units[~units.DPTO_KEY.isin(LIMA_AREA)].iterrows():
        pt = r.geometry.representative_point()
        ax.annotate(display_name(r.DPTO_KEY), (pt.x, pt.y), fontsize=4.2, ha="center")
    _inset_lima(ax, units, color=units[units.DPTO_KEY.isin(LIMA_AREA)]
                .DPTO_KEY.map(colors).tolist(), edgecolor="0.3", linewidth=0.3)
    ax.legend(handles=[Patch(color=c, label=display_name(k)) for k, c in colors.items()],
              loc="upper right", fontsize=6, frameon=False)
    ax.set_axis_off()
    return save(fig, figures_dir, name)


def choropleth(units, column, figures_dir, name, label):
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    units.plot(ax=ax, column=column, cmap="cividis", edgecolor="0.3", linewidth=0.3,
               legend=True, legend_kwds={"label": label, "shrink": 0.6})
    _inset_lima(ax, units, column=column, cmap="cividis",
                vmin=units[column].min(), vmax=units[column].max())
    ax.set_axis_off()
    return save(fig, figures_dir, name)


def gi_map(units, local_df, figures_dir, name, class_col="Gi_clase_FDR"):
    colors = {"Hotspot": "#b2182b", "Coldspot": "#2166ac", "n.s.": "0.88"}
    g = units.merge(local_df[["DPTO_KEY", class_col]], on="DPTO_KEY")
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    g.plot(ax=ax, color=g[class_col].map(colors), edgecolor="0.3", linewidth=0.3)
    _inset_lima(ax, g, color=g[g.DPTO_KEY.isin(LIMA_AREA)][class_col].map(colors).tolist(),
                edgecolor="0.3", linewidth=0.3)
    ax.legend(handles=[Patch(color=c, label=k) for k, c in colors.items()],
              loc="upper right", fontsize=6, frameon=False)
    ax.set_axis_off()
    return save(fig, figures_dir, name)

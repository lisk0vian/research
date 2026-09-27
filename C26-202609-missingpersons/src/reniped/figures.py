"""Supplementary diagnostic figures: no embedded title, 300 dpi, PNG + TIFF."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DPI = 300
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})


def save(fig, figures_dir, name):
    paths = []
    for ext, kw in (("png", {}), ("tiff", {"pil_kwargs": {"compression": "tiff_lzw"}})):
        p = figures_dir / f"{name}.{ext}"
        fig.savefig(p, dpi=DPI, bbox_inches="tight", **kw)
        paths.append(p)
    plt.close(fig)
    return paths


def k_selection_figure(tab, k_star, figures_dir, name):
    """Gap (with standard error), stability by units and by temporal blocks, and silhouette."""
    fig, axes = plt.subplots(1, 3, figsize=(7.48, 2.4))
    ax = axes[0]
    ax.errorbar(tab["K"], tab["gap"], yerr=tab["s_k"], marker="o", capsize=2, color="0.2")
    ax.set_xlabel("K"); ax.set_ylabel("Gap statistic")
    ax = axes[1]
    for col, lab, ls in (("unidad", "Unit bootstrap", "-"), ("bloque_temporal", "Block bootstrap", "--")):
        ax.plot(tab["K"], tab[f"ari_media_{col}"], marker="o", ls=ls, color="0.2", label=lab)
        ax.fill_between(tab["K"], tab[f"ari_p2_5_{col}"], tab[f"ari_p97_5_{col}"], color="0.85")
    ax.set_xlabel("K"); ax.set_ylabel("Bootstrap ARI"); ax.legend(frameon=False, fontsize=7)
    ax = axes[2]
    ax.plot(tab["K"], tab["silhouette"], marker="o", color="0.2")
    ax.set_xlabel("K"); ax.set_ylabel("Silhouette")
    for a in axes:
        a.axvline(k_star, ls=":", lw=0.9, color="#b2182b")
    fig.tight_layout()
    return save(fig, figures_dir, name)


def profile_figure(profile, features, figures_dir, name):
    fig, ax = plt.subplots(figsize=(3.54, 2.6))
    for _, r in profile.iterrows():
        ax.plot(features, [r[f] for f in features], marker="o", label=f"C{int(r['CLUSTER'])}")
    ax.axhline(0, lw=0.6, color="0.5")
    ax.set_ylabel("Centroid (standardised units)")
    ax.legend(frameon=False, fontsize=8)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    fig.tight_layout()
    return save(fig, figures_dir, name)


def specification_curve(spec, outcome, factors, flag_col, anchor_col, figures_dir, name,
                        ylabel, hline=None):
    """Specification curve: sorted outcome (top) and active decisions (bottom)."""
    d = spec.sort_values(outcome).reset_index(drop=True)
    levels = [(f, lv) for f in factors for lv in sorted(d[f].astype(str).unique())]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.48, 5.2), sharex=True,
                                   gridspec_kw={"height_ratios": [1.1, 1.6]})
    x = np.arange(len(d))
    ok = d[flag_col].astype(bool).to_numpy()
    ax1.scatter(x[~ok], d.loc[~ok, outcome], s=9, color="0.6", label=f"{flag_col} = False")
    ax1.scatter(x[ok], d.loc[ok, outcome], s=9, color="#b2182b", label=f"{flag_col} = True")
    anc = d[anchor_col].astype(bool).to_numpy()
    if anc.any():
        ax1.scatter(x[anc], d.loc[anc, outcome], s=60, facecolors="none", edgecolors="k",
                    linewidths=1.2, label="Original manuscript specification")
    if hline is not None:
        ax1.axhline(hline, ls="--", lw=0.8, color="0.3")
    ax1.set_ylabel(ylabel)
    ax1.legend(frameon=False, fontsize=6.5, loc="upper left")
    for j, (f, lv) in enumerate(levels):
        on = d[f].astype(str).to_numpy() == lv
        ax2.scatter(x[on], np.full(on.sum(), j), s=3, marker="|", color="0.2")
    ax2.set_yticks(range(len(levels)))
    ax2.set_yticklabels([f"{f}: {lv}" for f, lv in levels], fontsize=5.5)
    ax2.set_xlabel("Specification (ranked by outcome)")
    ax2.invert_yaxis()
    fig.tight_layout()
    return save(fig, figures_dir, name)

"""Contract tables and figures (design §9), read from outputs/ only.

Tables: T1 completeness (00), T2 blind skill + 95 % CI (09), T3 hypotheses (09),
T4 Murphy decomposition, T5 LOSO gap (09), T6 secondary targets and frost index.
Figures:
  F1 CRPSS vs Clim by horizon, every model, blind, with 95 % intervals
  F2 PIT histogram and tercile reliability of M*, blind
  F3 M* CRPSS vs Clim by quarter and by ENSO phase at issuance (descriptive)
  F4 dev vs blind CRPSS vs Clim (robustness)
  F5 LOSO: skill lost when the station is left out, against elevation
  F6 predictability budget: CRPSS vs Damp of the L and LG variants

No number is computed here that a table does not also hold; the figures are
views of `metrics_long.csv`, `T2`, `T5` and the scored rows.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from _common import (
    FIGURES,
    TABLES,
    atomic_write_csv,
    ensure_dirs,
    load_config,
    paths_report,
    read_station_keyed,
    write_manifest,
)
from _panel import MODELS_DIR

TARGET = "TT_mean"
ORDER = ["Clim", "Pers", "Damp", "Ridge_L", "Ridge_LG", "GBM_L", "GBM_LG",
         "LSTM_LG", "Chronos", "Ensemble"]
# Colour-blind-safe (Okabe-Ito), fixed per model across every figure.
COLORS = {"Clim": "#999999", "Pers": "#000000", "Damp": "#E69F00", "Ridge_L": "#56B4E9",
          "Ridge_LG": "#0072B2", "GBM_L": "#8FD3B6", "GBM_LG": "#009E73",
          "LSTM_LG": "#CC79A7", "Chronos": "#D55E00", "Ensemble": "#332288"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 300, "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False})
    return plt


def _save(fig, name: str) -> str:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{name}.png"
    fig.savefig(path, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return f"figures/{name}.png"


def _models(present) -> list[str]:
    return [m for m in ORDER if m in set(present)] + sorted(set(present) - set(ORDER))


def fig_skill_by_horizon(t2: pd.DataFrame, horizons: list[str]) -> str:
    plt = _plt()
    d = t2[t2["metric"] == "CRPSS_clim"]
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    models = _models(d["model"].unique())
    width = 0.8 / max(len(models), 1)
    for i, m in enumerate(models):
        g = d[d["model"] == m].set_index("horizon").reindex(horizons)
        x = np.arange(len(horizons)) + (i - len(models) / 2) * width + width / 2
        ax.errorbar(x, g["value"], yerr=[g["value"] - g["ci_low"], g["ci_high"] - g["value"]],
                    fmt="o", ms=4, capsize=2, color=COLORS.get(m), label=m)
    ax.axhline(0, color="#444", lw=0.8)
    ax.set_xticks(range(len(horizons)), horizons)
    ax.set_ylabel("CRPSS vs Clim (blind)")
    ax.legend(ncol=3, fontsize=7, frameon=False)
    return _save(fig, "F1_skill_by_horizon")


def fig_calibration(scored: pd.DataFrame, primary: str, horizons: list[str]) -> str:
    plt = _plt()
    s = scored[(scored["model"] == primary) & (scored["role"] == "blind")]
    fig, axes = plt.subplots(2, len(horizons), figsize=(2.6 * len(horizons), 4.8))
    for j, h in enumerate(horizons):
        g = s[s["horizon"] == h]
        ax = axes[0, j]
        ax.hist(g["pit"].dropna(), bins=10, range=(0, 1), density=True, color=COLORS.get(primary, "#555"))
        ax.axhline(1, color="#444", lw=0.8, ls="--")
        ax.set_title(f"{h} PIT")
        ax = axes[1, j]
        for col, cat, label in (("p_below", 0, "lower"), ("p_above", 2, "upper")):
            ok = g[col].notna() & (g["obs_cat"] >= 0)
            p, o = g.loc[ok, col].to_numpy(), (g.loc[ok, "obs_cat"] == cat).to_numpy(float)
            bins = np.linspace(0, 1, 6)
            k = np.clip(np.digitize(p, bins) - 1, 0, 4)
            xs = [p[k == b].mean() for b in range(5) if (k == b).sum() >= 5]
            ys = [o[k == b].mean() for b in range(5) if (k == b).sum() >= 5]
            ax.plot(xs, ys, "o-", ms=3, label=label)
        ax.plot([0, 1], [0, 1], color="#444", lw=0.8, ls="--")
        ax.set_xlabel("forecast probability")
        if j == 0:
            ax.set_ylabel("observed frequency")
            ax.legend(frameon=False, fontsize=7)
    fig.suptitle(f"{primary}, blind folds")
    fig.tight_layout()
    return _save(fig, "F2_calibration")


def fig_conditional(scored: pd.DataFrame, primary: str, horizons: list[str]) -> str:
    plt = _plt()
    s = scored[scored["role"] == "blind"]
    keys = ["station", "issue_date", "horizon"]
    m = s[s["model"] == primary][keys + ["crps", "quarter", "nino34_anom"]].merge(
        s[s["model"] == "Clim"][keys + ["crps"]], on=keys, suffixes=("", "_clim"))
    m["enso"] = np.select([m["nino34_anom"] >= 0.5, m["nino34_anom"] <= -0.5],
                          ["El Niño", "La Niña"], "neutral")
    m["season"] = m["quarter"].map({0: "DJF", 1: "MAM", 2: "JJA", 3: "SON"})
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 3.2), sharey=True)
    for ax, col, cats in ((axes[0], "season", ["DJF", "MAM", "JJA", "SON"]),
                          (axes[1], "enso", ["La Niña", "neutral", "El Niño"])):
        for i, h in enumerate(horizons):
            g = m[m["horizon"] == h].groupby(col)[["crps", "crps_clim"]].sum().reindex(cats)
            ax.bar(np.arange(len(cats)) + (i - 1) * 0.27, 1 - g["crps"] / g["crps_clim"],
                   width=0.27, label=h)
        ax.axhline(0, color="#444", lw=0.8)
        ax.set_xticks(range(len(cats)), cats)
    axes[0].set_ylabel(f"CRPSS vs Clim ({primary})")
    axes[1].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return _save(fig, "F3_conditional_skill")


def fig_dev_vs_blind(metrics: pd.DataFrame) -> str:
    plt = _plt()
    d = metrics[(metrics["experiment"] == "temporal") & (metrics["scope"] == "pooled")
                & (metrics["target"] == TARGET)]
    p = d.pivot_table(index=["model", "horizon"], columns="role", values="CRPSS_clim").dropna()
    fig, ax = plt.subplots(figsize=(4, 4))
    for (model, h), row in p.iterrows():
        ax.scatter(row.get("dev"), row.get("blind"), color=COLORS.get(model, "#555"), s=18)
    lim = [np.nanmin(p.to_numpy()) - 0.02, np.nanmax(p.to_numpy()) + 0.02] if len(p) else [-0.1, 0.1]
    ax.plot(lim, lim, color="#444", lw=0.8, ls="--")
    ax.set_xlabel("CRPSS vs Clim, dev (D1-D3)")
    ax.set_ylabel("CRPSS vs Clim, blind (B1-B2)")
    return _save(fig, "F4_dev_vs_blind")


def fig_loso(gaps: pd.DataFrame, horizons: list[str]) -> str | None:
    if gaps.empty:
        return None
    plt = _plt()
    fig, axes = plt.subplots(1, len(horizons), figsize=(2.8 * len(horizons), 3), sharey=True)
    for ax, h in zip(np.atleast_1d(axes), horizons):
        g = gaps[gaps["horizon"] == h]
        for model, gm in g.groupby("model"):
            gm = gm.sort_values("elev_m")
            ax.errorbar(gm["elev_m"], gm["dCRPS_loso_minus_temporal"],
                        yerr=[gm["dCRPS_loso_minus_temporal"] - gm["ci_low"],
                              gm["ci_high"] - gm["dCRPS_loso_minus_temporal"]],
                        fmt="o-", ms=3, capsize=2, color=COLORS.get(model), label=model)
        ax.axhline(0, color="#444", lw=0.8)
        ax.set_title(h)
        ax.set_xlabel("held-out station elevation (m)")
    np.atleast_1d(axes)[0].set_ylabel("ΔCRPS (LOSO − temporal)")
    np.atleast_1d(axes)[-1].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return _save(fig, "F5_loso_vs_elevation")


def fig_budget(t2: pd.DataFrame, horizons: list[str]) -> str:
    plt = _plt()
    d = t2[t2["metric"] == "CRPSS_damp"]
    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    for fam, ls in (("Ridge", "-"), ("GBM", "--")):
        for var in ("L", "LG"):
            g = d[d["model"] == f"{fam}_{var}"].set_index("horizon").reindex(horizons)
            ax.plot(horizons, g["value"], ls, marker="o", ms=4,
                    color=COLORS.get(f"{fam}_{var}"), label=f"{fam}_{var}")
            ax.fill_between(horizons, g["ci_low"], g["ci_high"], alpha=0.12,
                            color=COLORS.get(f"{fam}_{var}"))
    ax.axhline(0, color="#444", lw=0.8)
    ax.set_ylabel("CRPSS vs Damp (blind)")
    ax.legend(frameon=False, fontsize=7, ncol=2)
    return _save(fig, "F6_predictability_budget")


def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    horizons = list(cfg["target"]["horizons"].keys())
    metrics_path = TABLES / "metrics_long.csv"
    if not metrics_path.is_file():
        raise SystemExit(f"ERROR: {metrics_path} not found — run 08 and 09 first")
    metrics = pd.read_csv(metrics_path, dtype={"scope": "string"})
    t2 = pd.read_csv(TABLES / "T2_blind_skill.csv")
    gaps = pd.read_csv(TABLES / "T5_loso_gap.csv") if (TABLES / "T5_loso_gap.csv").stat().st_size > 2 \
        else pd.DataFrame()
    scored = read_station_keyed(MODELS_DIR / "scored_temporal.csv", parse_dates=["issue_date"])
    scored = scored[scored["target"] == TARGET]
    primary = json.loads((MODELS_DIR / "primary_model.json").read_text(encoding="utf-8"))["primary_model"]

    pooled = metrics[(metrics["scope"] == "pooled") & (metrics["experiment"] == "temporal")]
    t4 = pooled[(pooled["target"] == TARGET) & (pooled["role"] == "blind")][
        ["model", "horizon", "n", "MSE", "murphy_r", "murphy_cond_bias",
         "murphy_uncond_bias", "msss_sample", "MSSS_clim", "MSSS_damp"]]
    atomic_write_csv(t4, TABLES / "T4_murphy.csv")
    t6 = pooled[(pooled["target"] != TARGET) & (pooled["role"] == "blind")][
        ["target", "model", "horizon", "n", "CRPS", "CRPSS_clim", "CRPSS_damp", "MSSS_damp",
         "brier_frost", "frost_rate", "BSS_frost_clim"]]
    atomic_write_csv(t6, TABLES / "T6_secondary_targets.csv")

    figures = {
        "F1": fig_skill_by_horizon(t2, horizons),
        "F2": fig_calibration(scored, primary, horizons),
        "F3": fig_conditional(scored, primary, horizons),
        "F4": fig_dev_vs_blind(metrics),
        "F5": fig_loso(gaps, horizons),
        "F6": fig_budget(t2, horizons),
    }
    figures = {k: v for k, v in figures.items() if v}
    for k, v in figures.items():
        print(f"  {k}: outputs/{v}")
    write_manifest({"figures": figures,
                    "tables": {"T4_murphy": "tables/T4_murphy.csv",
                               "T6_secondary_targets": "tables/T6_secondary_targets.csv"}})


if __name__ == "__main__":
    main()

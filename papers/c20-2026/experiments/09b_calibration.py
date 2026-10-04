# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Amendment A2 (post hoc, after unblinding): calibration of the ensemble M*.

H3's secondary criterion failed: M*'s 90 % intervals covered 63-75 % of the
blind outcomes against a pre-registered 85-95 %. This stage does not change
H3 or M*; it adds three analyses declared post hoc in METHODOLOGY.md, A2:

- **Spread recalibration.** Each forecast's quantiles are stretched around its
  median by a factor k per horizon, chosen so that the central 90 % interval
  covers 90 % of the outcomes it was fitted on. k is fitted on the dev folds
  only: cross-fitted on D1-D3 (each dev fold scored with k from the other two)
  and fitted on all of D1-D3 for the blind folds, so the blind folds never
  choose their own k.
- **Ensemble without Chronos.** The frozen dev weights, renormalised over the
  remaining members, as a sensitivity analysis: Chronos is the narrowest member
  by far and Vincentization averages widths.
- **Chronos itself,** as the diagnostic row it is.

Writes `outputs/tables/T9_calibration.csv`: variant x role x horizon with n,
coverage (50/90), 90 % width, CRPS, CRPSS against Clim on the same rows, and
the k used. Pooled stations, TT_mean, temporal experiment.
"""

from __future__ import annotations

import importlib
import json

import numpy as np
import pandas as pd

from _common import TABLES, atomic_write_csv, ensure_dirs, load_config, paths_report, \
    primary_target, write_manifest
from _panel import MODELS_DIR, qcols, quantile_levels, read_eval_index, read_preds
from _scores import crps_quantile, rearrange

KEYS = ["station", "fold", "issue_date", "horizon"]
TARGET = primary_target()
COVERAGE = 0.90


def level_index(levels: list[float], level: float) -> int:
    return int(np.argmin(np.abs(np.asarray(levels) - level)))


def exceedance(obs: np.ndarray, q: np.ndarray, i_lo: int, i_mid: int, i_hi: int) -> np.ndarray:
    """How far each outcome sits outside its central interval, in half-widths.

    z <= k means the outcome falls inside the interval stretched by k around
    the median, side by side, so an asymmetric interval stays asymmetric.
    """
    med = q[:, i_mid]
    below, above = med - q[:, i_lo], q[:, i_hi] - med
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(obs >= med, (obs - med) / above, (med - obs) / below)
    return np.where(np.isfinite(z), z, np.inf)


def fit_k(obs: np.ndarray, q: np.ndarray, levels: list[float], coverage: float = COVERAGE) -> float:
    """Stretch factor that makes the central `coverage` interval cover `coverage`."""
    lo, hi = (1 - coverage) / 2, 1 - (1 - coverage) / 2
    z = exceedance(obs, q, level_index(levels, lo), level_index(levels, 0.5),
                   level_index(levels, hi))
    return float(np.quantile(z, coverage)) if len(z) else 1.0


def stretch(q: np.ndarray, k: float, levels: list[float]) -> np.ndarray:
    """Quantiles stretched by k around the median, then re-sorted."""
    med = q[:, [level_index(levels, 0.5)]]
    return rearrange(med + k * (q - med))


def recalibrated(frame: pd.DataFrame, cols: list[str], levels: list[float],
                 dev_folds: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Stretched quantiles for every row, and the k each row got.

    Dev rows use k cross-fitted on the other dev folds; every other row uses k
    fitted on all dev folds. One k per horizon.
    """
    out = frame[cols].to_numpy(float).copy()
    ks = np.full(len(frame), np.nan)
    for h in frame["horizon"].unique():
        in_h = (frame["horizon"] == h).to_numpy()
        dev_h = in_h & frame["fold"].isin(dev_folds).to_numpy()
        for f in dev_folds:
            rows = dev_h & (frame["fold"] == f).to_numpy()
            fit = dev_h & ~(frame["fold"] == f).to_numpy()
            if rows.any() and fit.any():
                k = fit_k(frame["obs"].to_numpy(float)[fit], out[fit], levels)
                out[rows], ks[rows] = stretch(out[rows], k, levels), k
        rest = in_h & ~dev_h
        if rest.any() and dev_h.any():
            k = fit_k(frame["obs"].to_numpy(float)[dev_h], frame[cols].to_numpy(float)[dev_h], levels)
            out[rest], ks[rest] = stretch(out[rest], k, levels), k
    return out, ks


def summarise(frame: pd.DataFrame, q: np.ndarray, levels: list[float], clim_crps: pd.Series,
              variant: str, k: np.ndarray | None = None) -> pd.DataFrame:
    obs = frame["obs"].to_numpy(float)
    i05, i25, i75, i95 = (level_index(levels, x) for x in (0.05, 0.25, 0.75, 0.95))
    rows = frame[KEYS + ["role"]].assign(
        crps=crps_quantile(obs, q, levels),
        in50=(obs >= q[:, i25]) & (obs <= q[:, i75]),
        in90=(obs >= q[:, i05]) & (obs <= q[:, i95]),
        width90=q[:, i95] - q[:, i05],
        k=np.nan if k is None else k)
    rows = rows.merge(clim_crps.rename("crps_clim").reset_index(), on=KEYS, how="left")
    out = []
    for (role, h), g in rows.groupby(["role", "horizon"]):
        both = g.dropna(subset=["crps_clim"])
        out.append({
            "variant": variant, "role": role, "horizon": h, "n": len(g),
            "cov50": g["in50"].mean(), "cov90": g["in90"].mean(),
            "width90": g["width90"].mean(), "crps": g["crps"].mean(),
            "crpss_clim": 1 - both["crps"].sum() / both["crps_clim"].sum() if len(both) else np.nan,
            "k": g["k"].mean(),
        })
    return pd.DataFrame(out)


def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    levels, cols = quantile_levels(cfg), qcols(cfg)
    dev_folds = [f["id"] for f in cfg["validation"]["folds"] if f.get("role") == "dev"]

    index = read_eval_index("temporal")
    index = index[index["target"] == TARGET][KEYS + ["obs"]]
    preds = read_preds("temporal")
    preds = preds[preds["target"] == TARGET].merge(index, on=KEYS)
    preds = preds[np.isfinite(preds["obs"]) & preds[cols].notna().all(axis=1)]

    def model(name: str) -> pd.DataFrame:
        return preds[preds["model"] == name].sort_values(KEYS).reset_index(drop=True)

    clim = model("Clim")
    clim_crps = pd.Series(crps_quantile(clim["obs"].to_numpy(float), clim[cols].to_numpy(float),
                                        levels), index=pd.MultiIndex.from_frame(clim[KEYS]))

    primary = json.loads((MODELS_DIR / "primary_model.json").read_text(encoding="utf-8"))
    weights = primary["ensemble_weights"]
    tables = []

    ens = model("Ensemble")
    tables.append(summarise(ens, ens[cols].to_numpy(float), levels, clim_crps, "Ensemble"))
    q, k = recalibrated(ens, cols, levels, dev_folds)
    tables.append(summarise(ens, q, levels, clim_crps, "Ensemble+k", k))

    m07c = importlib.import_module("07c_ensemble")
    no_chronos = {h: {m: v / sum(x for n, x in w.items() if n != "Chronos")
                      for m, v in w.items() if m != "Chronos"} for h, w in weights.items()}
    rows, qn, mu = m07c.combine(preds.drop(columns="obs"), no_chronos, cols)
    if len(rows):
        alt = rows[KEYS + ["role"]].assign(mean=mu).merge(index, on=KEYS)
        alt[cols] = qn
        alt = alt.sort_values(KEYS).reset_index(drop=True)
        q_alt = alt[cols].to_numpy(float)
        tables.append(summarise(alt, q_alt, levels, clim_crps, "Ensemble-Chronos"))
        q2, k2 = recalibrated(alt, cols, levels, dev_folds)
        tables.append(summarise(alt, q2, levels, clim_crps, "Ensemble-Chronos+k", k2))

    chron = model("Chronos")
    if len(chron):
        tables.append(summarise(chron, chron[cols].to_numpy(float), levels, clim_crps, "Chronos"))

    table = pd.concat(tables, ignore_index=True)
    path = atomic_write_csv(table.round(4), TABLES / "T9_calibration.csv")
    print(table.round(3).to_string(index=False))
    write_manifest({"tables": {"T9_calibration": "tables/T9_calibration.csv"},
                    "calibration_09b": {
        "amendment": "A2, post hoc (after unblinding); H3 and M* unchanged",
        "table": "outputs/tables/T9_calibration.csv", "coverage_target": COVERAGE,
        "k_fit": "per horizon; dev folds cross-fitted on the other dev folds, "
                 "blind folds on all dev folds",
        "weights_without_chronos": no_chronos,
    }}, replace=("calibration_09b",))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

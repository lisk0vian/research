# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Deterministic and probabilistic verification (design §7).

Per row (`outputs/models/scored_<experiment>.csv`): squared and absolute error
of the mean, CRPS on the shared quantile grid, tercile probabilities and RPS,
PIT, 50/90 % interval hit and width, and for TT_min the frost-index probability
and Brier score. Pers is deterministic: its probabilistic columns stay empty.

Aggregated (`outputs/tables/metrics_long.csv`), by experiment x target x model x
horizon x role x scope (pooled or a station): MAE, RMSE, ACC, CRPS, RPS,
coverage and width, Brier, Murphy terms, and the skill scores MSSS / CRPSS /
RPSS / BSS against Clim and Damp. Skill scores are ratios of sums over the
rows both models share, never means of per-row ratios.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from _common import (
    OUTPUTS,
    TABLES,
    atomic_write_csv,
    ensure_dirs,
    load_config,
    paths_report,
    primary_target,
    rel_path,
    write_manifest,
)
from _panel import MODELS_DIR, qcols, quantile_levels, read_eval_index, read_preds
from _scores import (
    cdf_from_quantiles,
    crps_quantile,
    murphy,
    rps_terciles,
    tercile_probs,
)

KEYS = ["experiment", "target", "station", "fold", "issue_date", "horizon"]
TARGET = primary_target()
DETERMINISTIC_ONLY = {"Pers"}
REFERENCES = ("Clim", "Damp")


def score_rows(preds: pd.DataFrame, index: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    levels = quantile_levels(cfg)
    cols = qcols(cfg)
    idx_cols = KEYS + ["role", "obs", "clim", "t1", "t2", "quarter", "nino34_anom", "romi_amp"]
    m = preds.drop(columns=["role"], errors="ignore").merge(
        index[[c for c in idx_cols if c in index.columns]], on=KEYS, how="inner")
    m = m[np.isfinite(m["obs"]) & np.isfinite(m["mean"])].reset_index(drop=True)
    y, f = m["obs"].to_numpy(float), m["mean"].to_numpy(float)
    q = m[cols].to_numpy(float)
    prob = ~m["model"].isin(DETERMINISTIC_ONLY).to_numpy() & np.isfinite(q).all(axis=1)

    out = m[KEYS + ["role", "model", "obs", "mean", "quarter", "nino34_anom", "romi_amp"]].copy()
    out["se"] = (f - y) ** 2
    out["ae"] = np.abs(f - y)
    out["crps"] = np.where(prob, crps_quantile(y, np.nan_to_num(q), levels), np.nan)
    pit = cdf_from_quantiles(y, q, levels)
    out["pit"] = np.where(prob, pit, np.nan)

    lo50, hi50 = cols.index("q25"), cols.index("q75")
    lo90, hi90 = cols.index("q05"), cols.index("q95")
    for name, a, b in (("50", lo50, hi50), ("90", lo90, hi90)):
        out[f"in{name}"] = np.where(prob, ((y >= q[:, a]) & (y <= q[:, b])).astype(float), np.nan)
        out[f"width{name}"] = np.where(prob, q[:, b] - q[:, a], np.nan)

    t1, t2 = m["t1"].to_numpy(float), m["t2"].to_numpy(float)
    ok = prob & np.isfinite(t1) & np.isfinite(t2)
    probs = np.full((len(m), 3), np.nan)
    if ok.any():
        probs[ok] = tercile_probs(t1[ok], t2[ok], q[ok], levels)
    cat = np.where(y < t1, 0, np.where(y > t2, 2, 1))
    out["p_below"], out["p_normal"], out["p_above"] = probs[:, 0], probs[:, 1], probs[:, 2]
    out["obs_cat"] = np.where(ok, cat, -1)
    rps = np.full(len(m), np.nan)
    if ok.any():
        rps[ok] = rps_terciles(probs[ok], cat[ok])
    out["rps"] = rps

    # Frost index (TT_min only): P(C + A < threshold), from the anomaly quantiles.
    frost = cfg.get("metrics", {}).get("frost", {})
    thr = float(frost.get("threshold_degC", 0.0))
    is_frost = (m["target"] == frost.get("target", "TT_min")).to_numpy() & prob \
        & np.isfinite(m["clim"].to_numpy(float))
    p_frost = np.full(len(m), np.nan)
    if is_frost.any():
        p_frost[is_frost] = cdf_from_quantiles(thr - m["clim"].to_numpy(float)[is_frost],
                                               q[is_frost], levels)
    event = ((m["clim"].to_numpy(float) + y) < thr).astype(float)
    out["p_frost"] = p_frost
    out["frost_obs"] = np.where(is_frost, event, np.nan)
    out["brier_frost"] = (p_frost - event) ** 2
    return out


def _agg(g: pd.DataFrame) -> dict:
    o, f = g["obs"].to_numpy(float), g["mean"].to_numpy(float)
    mur = murphy(f, o)
    acc = float(np.corrcoef(f, o)[0, 1]) if len(g) > 2 and np.std(f) > 0 and np.std(o) > 0 else np.nan
    return {
        "n": int(len(g)), "MAE": g["ae"].mean(), "RMSE": float(np.sqrt(g["se"].mean())),
        "MSE": g["se"].mean(), "ACC": acc, "CRPS": g["crps"].mean(), "RPS": g["rps"].mean(),
        "cov50": g["in50"].mean(), "cov90": g["in90"].mean(),
        "width50": g["width50"].mean(), "width90": g["width90"].mean(),
        "brier_frost": g["brier_frost"].mean(), "frost_rate": g["frost_obs"].mean(),
        "murphy_r": mur["r"], "murphy_cond_bias": mur["cond_bias"],
        "murphy_uncond_bias": mur["uncond_bias"], "msss_sample": mur["msss_sample"],
    }


def skill(scored: pd.DataFrame, group: list[str]) -> pd.DataFrame:
    """Ratio-of-sums skill of every model against each reference, matched rows."""
    rows = []
    keys = ["experiment", "target", "station", "fold", "issue_date", "horizon"]
    for ref in REFERENCES:
        r = scored[scored["model"] == ref][keys + ["se", "crps", "rps", "brier_frost"]]
        m = scored.merge(r, on=keys, suffixes=("", "_ref"))
        for key, g in m.groupby(group + ["model"], dropna=False):
            entry = dict(zip(group + ["model"], key if isinstance(key, tuple) else (key,)))
            for metric, col in (("MSSS", "se"), ("CRPSS", "crps"), ("RPSS", "rps"),
                                ("BSS_frost", "brier_frost")):
                a, b = g[col].to_numpy(float), g[f"{col}_ref"].to_numpy(float)
                ok = np.isfinite(a) & np.isfinite(b)
                entry[f"{metric}_{ref.lower()}"] = (1 - a[ok].sum() / b[ok].sum()
                                                   if ok.any() and b[ok].sum() > 0 else np.nan)
            rows.append(entry)
    out = pd.DataFrame(rows)
    return out.groupby(group + ["model"], as_index=False, dropna=False).first()


def aggregate(scored: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for scope_col in (None, "station"):
        s = scored.assign(scope="pooled") if scope_col is None else scored.assign(scope=scored["station"])
        group = ["experiment", "target", "horizon", "role", "scope"]
        base = s.groupby(group + ["model"]).apply(lambda g: pd.Series(_agg(g)),
                                                 include_groups=False).reset_index()
        sk = skill(s, group)
        frames.append(base.merge(sk, on=group + ["model"], how="left"))
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    all_scored, written = [], {}
    for experiment in ("temporal", "loso"):
        preds = read_preds(experiment)
        if preds.empty:
            print(f"[{experiment}] no predictions; skipped")
            continue
        index = read_eval_index(experiment)
        scored = score_rows(preds, index, cfg)
        if experiment == "loso":
            # LOSO is scored against the station's own references, which only
            # the temporal experiment has: borrow its Clim and Damp rows.
            t = read_preds("temporal")
            refs = t[t["model"].isin(REFERENCES) & t["fold"].isin(scored["fold"].unique())
                     & (t["target"] == TARGET)].assign(experiment="loso")
            if not refs.empty:
                scored = pd.concat([scored, score_rows(refs, index, cfg)], ignore_index=True)
        path = atomic_write_csv(scored, MODELS_DIR / f"scored_{experiment}.csv")
        written[experiment] = rel_path(path)
        all_scored.append(scored)
        print(f"[{experiment}] scored {len(scored)} rows, models: "
              f"{', '.join(sorted(scored['model'].unique()))}")
    if not all_scored:
        raise SystemExit("ERROR: nothing to score — run 07 first")

    table = aggregate(pd.concat(all_scored, ignore_index=True))
    out = atomic_write_csv(table, TABLES / "metrics_long.csv")
    show = table[(table["scope"] == "pooled") & (table["target"] == TARGET)]
    for (exp, role), g in show.groupby(["experiment", "role"]):
        print(f"\n== {exp} / {role} ({TARGET}, pooled) CRPSS vs Damp ==")
        print(g.pivot(index="model", columns="horizon", values="CRPSS_damp").round(3).to_string())
    print(f"\nwrote {out}")
    write_manifest({"metrics": {"table": rel_path(out), "scored_rows": written},
                    "tables": {"metrics_long": "tables/metrics_long.csv"}},
                   replace=("metrics",))


if __name__ == "__main__":
    main()

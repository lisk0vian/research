# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Quantile-averaged ensemble and the frozen choice of the primary model M*.

Ensemble: the members' quantiles are averaged level by level (Vincentization),
weighted per horizon by the inverse of each member's mean CRPS on the dev folds
D1-D3, pooled over stations. A member missing on a row drops out of that row and
the remaining weights are renormalised. Weights come from dev folds only, so the
blind folds see an ensemble fixed before they were opened; on the dev folds the
weights are in-sample, which is stated rather than hidden.

M*: the candidate in `models.primary_model_selection.among` with the lowest mean
dev CRPS (TT_mean, temporal, all horizons pooled). Written to
`outputs/models/primary_model.json` before any blind score is computed, and read
by 08-10 instead of being re-derived from numbers that include the blind folds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from _common import atomic_write_json, ensure_dirs, load_config, paths_report, write_manifest
from _panel import (
    MODELS_DIR,
    pred_frame,
    qcols,
    quantile_levels,
    read_eval_index,
    read_preds,
    write_preds,
)
from _scores import crps_quantile, rearrange

KEYS = ["station", "fold", "issue_date", "horizon"]
TARGET = "TT_mean"


def dev_crps(preds: pd.DataFrame, index: pd.DataFrame, levels: list[float]) -> pd.DataFrame:
    """Mean dev-fold CRPS per (model, horizon)."""
    cols = [f"q{int(round(q * 100)):02d}" for q in levels]
    m = preds.merge(index[KEYS + ["obs"]], on=KEYS)
    m = m[m["role"] == "dev"]
    m = m[np.isfinite(m["obs"]) & m[cols].notna().all(axis=1)]
    m = m.assign(crps=crps_quantile(m["obs"].to_numpy(), m[cols].to_numpy(), levels))
    return m.groupby(["model", "horizon"], as_index=False)["crps"].mean()


def inverse_crps_weights(scores: pd.DataFrame, members: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for h, g in scores[scores["model"].isin(members)].groupby("horizon"):
        inv = {r.model: 1.0 / r.crps for r in g.itertuples() if r.crps > 0}
        total = sum(inv.values())
        out[str(h)] = {k: v / total for k, v in inv.items()}
    return out


def combine(preds: pd.DataFrame, weights: dict[str, dict[str, float]], cols: list[str]
            ) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Weighted level-wise average across members, renormalised per row."""
    preds = preds[preds["model"].isin({m for w in weights.values() for m in w})]
    w = preds.apply(lambda r: weights.get(str(r["horizon"]), {}).get(r["model"], 0.0), axis=1)
    preds = preds.assign(_w=w.to_numpy())
    preds = preds[(preds["_w"] > 0) & preds[cols].notna().all(axis=1)]
    rows, qs, ms = [], [], []
    for key, g in preds.groupby(KEYS, sort=True):
        wt = g["_w"].to_numpy() / g["_w"].sum()
        qs.append(wt @ g[cols].to_numpy(float))
        ms.append(float(wt @ g["mean"].to_numpy(float)))
        rows.append(g.iloc[0])
    if not rows:
        return pd.DataFrame(), np.zeros((0, len(cols))), np.zeros(0)
    return pd.DataFrame(rows).reset_index(drop=True), rearrange(np.vstack(qs)), np.array(ms)


def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    levels = quantile_levels(cfg)
    cols = qcols(cfg)
    ens_cfg = cfg["models"].get("ensemble", {})
    members = list(ens_cfg.get("members", []))

    index = read_eval_index("temporal")
    index = index[index["target"] == TARGET]
    preds = read_preds("temporal")
    if preds.empty:
        raise SystemExit("ERROR: no temporal predictions — run 07 and 07b first")
    preds = preds[(preds["target"] == TARGET) & (preds["model"] != "Ensemble")]
    present = sorted(preds["model"].unique())
    members = [m for m in members if m in present]
    missing = sorted(set(ens_cfg.get("members", [])) - set(members))
    if missing:
        print(f"WARNING: ensemble members without predictions, dropped: {missing}")
    if len(members) < 2:
        raise SystemExit(f"ERROR: ensemble needs two members, have {members}")

    scores = dev_crps(preds, index, levels)
    weights = inverse_crps_weights(scores, members)
    print("dev CRPS (pooled stations):")
    print(scores.pivot(index="model", columns="horizon", values="crps").round(4).to_string())
    print(f"ensemble weights: {weights}")

    rows, q, mu = combine(preds, weights, cols)
    write_preds([pred_frame(rows, "temporal", TARGET, "Ensemble", q, mu, cfg)],
                "temporal", "Ensemble")
    loso = read_preds("loso")
    if not loso.empty:
        loso = loso[loso["model"] != "Ensemble"]
        rows_l, q_l, mu_l = combine(loso, weights, cols)
        if len(rows_l):
            write_preds([pred_frame(rows_l, "loso", TARGET, "Ensemble", q_l, mu_l, cfg)],
                        "loso", "Ensemble")

    # M*: chosen on dev folds only, then frozen for 08-10.
    among = cfg["models"]["primary_model_selection"]["among"]
    scores_all = dev_crps(pd.concat([preds, read_preds("temporal").query("model == 'Ensemble'")]),
                          index, levels)
    mean_dev = scores_all.groupby("model")["crps"].mean()
    candidates = mean_dev[mean_dev.index.isin(among)].sort_values()
    if candidates.empty:
        raise SystemExit(f"ERROR: none of {among} has dev predictions")
    primary = str(candidates.index[0])
    payload = {
        "primary_model": primary,
        "criterion": "mean dev-fold CRPS, TT_mean, temporal, stations and horizons pooled",
        "dev_crps": {k: round(float(v), 5) for k, v in candidates.items()},
        "ensemble_weights": weights,
        "frozen_before_blind": True,
    }
    atomic_write_json(payload, MODELS_DIR / "primary_model.json")
    print(f"M* = {primary}  (dev CRPS {candidates.iloc[0]:.4f})")
    write_manifest({"primary_model": payload}, replace=("primary_model",))


if __name__ == "__main__":
    main()

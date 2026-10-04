# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Amendment A3.2: how much of a difference between models is training noise.

GBM_L, GBM_LG and LSTM_LG are re-fitted with four more seeds (base seed + 1..4)
in the temporal experiment, TT_mean, every fold, with every other setting as in
07 / 07b. The base seed is not re-fitted: its predictions are the ones 07 and
07b wrote with the same code. Descriptive only; M* and M*2 keep the base seed.

Writes, per model, horizon and role, the mean, SD, min and max over the five
seeds of CRPSS_clim and CRPSS_damp (Clim and Damp on the same rows), and for
each pair of these models in how many seeds one beats the other:
`outputs/tables/T12_seed_variability.csv` and `T12b_seed_pairs.csv`. The extra
seeds' predictions go to `outputs/models/seeds/` (not read by 08-10).
"""

from __future__ import annotations

import importlib
import itertools
import time

import numpy as np
import pandas as pd

from _common import (
    TABLES,
    atomic_write_csv,
    checkpoints,
    ensure_dirs,
    load_config,
    paths_report,
    primary_target,
    read_station_keyed,
    write_manifest,
)
from _panel import (
    MODELS_DIR,
    feature_sets,
    load_panel,
    pred_frame,
    qcols,
    quantile_levels,
    read_eval_index,
    read_preds,
    target_rows,
)
from _scores import crps_quantile

TARGET = primary_target()
KEYS = ["station", "fold", "issue_date", "horizon"]
EXTRA_SEEDS = (1, 2, 3, 4)
SEED_KEY = {"GBM_L": "gbm_local", "GBM_LG": "gbm_largescale", "LSTM_LG": "lstm"}
SEED_DIR = MODELS_DIR / "seeds"


def skill_by_seed(scored: pd.DataFrame) -> pd.DataFrame:
    """CRPSS_clim / CRPSS_damp per (model, seed, role, horizon), ratio of sums."""
    rows = []
    for (model, seed, role, h), g in scored.groupby(["model", "seed", "role", "horizon"]):
        rows.append({"model": model, "seed": seed, "role": role, "horizon": h, "n": len(g),
                     "crps": g["crps"].mean(),
                     "CRPSS_clim": 1 - g["crps"].sum() / g["crps_clim"].sum(),
                     "CRPSS_damp": 1 - g["crps"].sum() / g["crps_damp"].sum()})
    return pd.DataFrame(rows)


def summarise_seeds(skill: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (model, role, h), g in skill.groupby(["model", "role", "horizon"]):
        row = {"model": model, "role": role, "horizon": h, "n_seeds": len(g)}
        for m in ("CRPSS_clim", "CRPSS_damp"):
            row.update({f"{m}_mean": g[m].mean(), f"{m}_sd": g[m].std(ddof=1),
                        f"{m}_min": g[m].min(), f"{m}_max": g[m].max()})
        out.append(row)
    return pd.DataFrame(out)


def pair_wins(skill: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """For each pair, in how many seed indices A has a lower CRPS than B."""
    out = []
    for a, b in itertools.combinations(models, 2):
        for (role, h), g in skill.groupby(["role", "horizon"]):
            pa = g[g["model"] == a].set_index("seed_index")["crps"]
            pb = g[g["model"] == b].set_index("seed_index")["crps"]
            common = pa.index.intersection(pb.index)
            out.append({"model_a": a, "model_b": b, "role": role, "horizon": h,
                        "n_seeds": len(common), "a_better": int((pa[common] < pb[common]).sum())})
    return pd.DataFrame(out)


def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    m07 = importlib.import_module("07_models")
    m07b = importlib.import_module("07b_deep")
    levels, cols = quantile_levels(cfg), qcols(cfg)
    seeds_cfg = cfg.get("seeds", {})
    horizons = list(cfg["target"]["horizons"].keys())
    panel = load_panel(cfg)
    fs = feature_sets(panel)
    gbm_cols = {"GBM_L": fs["L"] + fs["static"], "GBM_LG": fs["L"] + fs["G"] + fs["static"]}
    folds = {f["id"]: f for f in cfg["validation"]["folds"]}
    index = read_eval_index("temporal")
    index = index[index["target"] == TARGET]
    ck = checkpoints("07f_seed_variability")
    SEED_DIR.mkdir(parents=True, exist_ok=True)

    preds: list[pd.DataFrame] = []
    base = read_preds("temporal")
    base = base[(base["target"] == TARGET) & base["model"].isin(SEED_KEY)]
    for model in SEED_KEY:
        preds.append(base[base["model"] == model].assign(seed=int(seeds_cfg.get(SEED_KEY[model], 0)),
                                                         seed_index=0))

    seqs = None
    for model in SEED_KEY:
        for k in EXTRA_SEEDS:
            seed = int(seeds_cfg.get(SEED_KEY[model], 0)) + k
            frames = []
            for fid in folds:
                unit = f"{model}__s{k}__{fid}"
                if ck.has(unit):
                    frames.append(ck.load(unit))
                    continue
                block = panel[panel["fold"] == fid]
                t0 = time.perf_counter()
                if model.startswith("GBM"):
                    train = target_rows(block, TARGET, "train")
                    evals = target_rows(block, TARGET, "eval").reset_index(drop=True)
                    if evals.empty or train.empty:
                        continue
                    q, mu = m07.predict_gbm(train, evals, gbm_cols[model], TARGET, levels,
                                            m07.gbm_params(cfg, seed))
                    frame = pred_frame(evals, "temporal", TARGET, model, q, mu, cfg)
                else:
                    if seqs is None:
                        daily = read_station_keyed(m07b.DAILY_CSV, parse_dates=["date"])
                        stations = sorted(panel["station"].unique())
                        seqs = {f: {st: m07b.station_daily_anomalies(
                                    daily[daily["station"] == st], m07b.load_fold_meta(st, f),
                                    folds[f], cfg) for st in stations} for f in folds}
                    tr = m07b.issue_samples(block, "train", horizons)
                    ev = m07b.issue_samples(block, "eval", horizons)
                    q, mu = m07b.fit_predict_lstm(tr, ev, seqs[fid], horizons, levels, cfg, seed)
                    rows, qq, mm = m07b.explode(ev, q, mu, horizons, index[index["fold"] == fid])
                    frame = pred_frame(rows, "temporal", TARGET, model, qq, mm, cfg)
                ck.save(unit, frame, elapsed_s=time.perf_counter() - t0)
                frames.append(frame)
                print(f"[{model} seed {seed}/{fid}] {len(frame)} rows")
            part = pd.concat(frames, ignore_index=True).assign(seed=seed, seed_index=k)
            part.to_csv(SEED_DIR / f"preds_temporal_{model}_seed{seed}.csv", index=False)
            preds.append(part)

    allp = pd.concat(preds, ignore_index=True).merge(index[KEYS + ["obs"]], on=KEYS)
    allp = allp[np.isfinite(allp["obs"]) & allp[cols].notna().all(axis=1)]
    allp["crps"] = crps_quantile(allp["obs"].to_numpy(float), allp[cols].to_numpy(float), levels)
    scored = allp.merge(base_refs(index, cols, levels), on=KEYS)
    skill = skill_by_seed(scored)
    skill = skill.merge(scored[["model", "seed", "seed_index"]].drop_duplicates(),
                        on=["model", "seed"])
    t12 = summarise_seeds(skill)
    pairs = pair_wins(skill, list(SEED_KEY))
    atomic_write_csv(t12.round(4), TABLES / "T12_seed_variability.csv")
    atomic_write_csv(pairs, TABLES / "T12b_seed_pairs.csv")
    print(t12.round(3).to_string(index=False))
    print(pairs.to_string(index=False))
    write_manifest({"tables": {"T12_seed_variability": "tables/T12_seed_variability.csv",
                               "T12b_seed_pairs": "tables/T12b_seed_pairs.csv"},
                    "seed_variability_07f": {
        "amendment": "A3.2, descriptive", "models": list(SEED_KEY),
        "extra_seeds": list(EXTRA_SEEDS),
        "tables": ["outputs/tables/T12_seed_variability.csv", "outputs/tables/T12b_seed_pairs.csv"],
    }}, replace=("seed_variability_07f",))


def base_refs(index: pd.DataFrame, cols: list[str], levels: list[float]) -> pd.DataFrame:
    """Clim and Damp CRPS on every eval row, the references for the skill scores."""
    refs = read_preds("temporal")
    refs = refs[(refs["target"] == TARGET) & refs["model"].isin(["Clim", "Damp"])]
    refs = refs.merge(index[KEYS + ["obs"]], on=KEYS)
    refs = refs[np.isfinite(refs["obs"]) & refs[cols].notna().all(axis=1)]
    refs["crps"] = crps_quantile(refs["obs"].to_numpy(float), refs[cols].to_numpy(float), levels)
    wide = refs.pivot_table(index=KEYS, columns="model", values="crps").reset_index()
    return wide.rename(columns={"Clim": "crps_clim", "Damp": "crps_damp"})


if __name__ == "__main__":
    main()

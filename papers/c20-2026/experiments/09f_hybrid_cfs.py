# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Amendment A5 (post hoc): the CFSv2 hybrid on the blind folds.

Registered in METHODOLOGY.md (A5) before this code was written. The blind
scores put CFS_BC ahead of M* at W1 and behind it at W3_4; A5 asks whether the
dynamical forecast and the observation-based models are worth more together.
Blind folds only (CFSv2 starts 2018-10-31, so no dev fold can train a hybrid),
TT_mean, temporal experiment. Nothing is selected or tuned: every choice is
fixed in A5.

Systems
-------
- `Ridge_LG@CFS`, `GBM_LG@CFS`  Ridge_LG / GBM_LG of stage 07 with `cfs_anom`
  (the CFS window mean minus its own harmonic climatology, step 1 of CFS_BC)
  as one more predictor; every hyperparameter as in 07.
- `Ridge_LG@cfsrows`, `GBM_LG@cfsrows`  the same models without `cfs_anom`, on
  exactly the same training rows (the Mondays with a CFS forecast), so a gain
  over the control is the predictor's and not the weekly sample's.
- `Blend_CFS_Mstar`  equal-weight Vincentization of CFS_BC and M*.

Reported on the common blind rows: T16 (skill per system and horizon, with
CFS_BC, M*, Ridge_LG and GBM_LG as references) and T16b (H6: each hybrid
against CFS_BC and M*, each trained hybrid against its control; Holm over the
three horizons within each test).

Predictions are written to `outputs/models/hybrid/`, outside the folder stages
08-10 read (`preds_*.csv` in `outputs/models/`), so no A5 model can enter
`metrics_long.csv`, T2 or M*.
"""

from __future__ import annotations

import importlib
import json

import numpy as np
import pandas as pd

from _common import (
    PROCESSED,
    TABLES,
    atomic_write_csv,
    ensure_dirs,
    load_config,
    paths_report,
    primary_target,
    progress,
    read_station_keyed,
    rel_path,
    write_manifest,
)
from _harmonic import doy_fractional, eval_harmonic, fit_harmonic
from _panel import (
    MODELS_DIR,
    fast_mode,
    feature_sets,
    load_panel,
    pred_frame,
    qcols,
    quantile_levels,
    read_eval_index,
    read_preds,
    target_rows,
)
from _scores import crps_quantile, rearrange

# v1: first version (A5).
RESULTS_VERSION = 1

TARGET = primary_target()
WINDOWS_CSV = PROCESSED / "cfs_windows.csv"
HYBRID_DIR = MODELS_DIR / "hybrid"
KEYS = ["station", "fold", "issue_date", "horizon"]
CFS = "CFS_BC"
BLEND = "Blend_CFS_Mstar"
# (name, base model, uses cfs_anom); the controls share the hybrids' rows.
TRAINED = [
    ("Ridge_LG@CFS", "ridge", True),
    ("Ridge_LG@cfsrows", "ridge", False),
    ("GBM_LG@CFS", "gbm", True),
    ("GBM_LG@cfsrows", "gbm", False),
]
CONTROL = {"Ridge_LG@CFS": "Ridge_LG@cfsrows", "GBM_LG@CFS": "GBM_LG@cfsrows"}
HYBRIDS = ["Ridge_LG@CFS", "GBM_LG@CFS", BLEND]


# --- the CFS predictor ------------------------------------------------------------------

def cfs_anomaly(tr: pd.DataFrame, ev: pd.DataFrame, k: int, period: float, min_train: int
                ) -> tuple[np.ndarray, np.ndarray] | None:
    """CFS window mean minus its harmonic climatology fitted on `tr` only.

    The same construction as step 1 of CFS_BC (07d): the climatology is fitted on
    the CFS forecasts of the training Mondays, so it removes the model's mean
    bias and its own seasonal cycle. None when `tr` is too thin to fit it.
    """
    tr = tr[tr["F_mean"].notna()]
    if len(tr) < min_train:
        return None
    doy_tr = doy_fractional(tr["target_mid"])
    coef = fit_harmonic(doy_tr, tr["F_mean"].to_numpy(float), k, period)
    f_tr = tr["F_mean"].to_numpy(float) - eval_harmonic(coef, doy_tr, period)
    f_ev = ev["F_mean"].to_numpy(float) - eval_harmonic(coef, doy_fractional(ev["target_mid"]),
                                                        period)
    return f_tr, f_ev


def add_cfs_anom(train: pd.DataFrame, evals: pd.DataFrame, k: int, period: float,
                 min_train: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`cfs_anom` per station and horizon; rows without one are dropped.

    A cell whose training Mondays are too few gets no hybrid prediction at all,
    the rule CFS_BC follows, rather than a model fitted on a handful of rows.
    """
    tr_parts, ev_parts = [], []
    for (st, h), ev in evals.groupby(["station", "horizon"]):
        tr = train[(train["station"] == st) & (train["horizon"] == h)]
        tr = tr[tr["F_mean"].notna()]
        ev = ev[ev["F_mean"].notna()]
        res = cfs_anomaly(tr, ev, k, period, min_train)
        if res is None or ev.empty:
            continue
        tr_parts.append(tr.assign(cfs_anom=res[0]))
        ev_parts.append(ev.assign(cfs_anom=res[1]))
    if not ev_parts:
        return train.iloc[0:0].assign(cfs_anom=[]), evals.iloc[0:0].assign(cfs_anom=[])
    return (pd.concat(tr_parts, ignore_index=True),
            pd.concat(ev_parts, ignore_index=True))


# --- combination and alignment -------------------------------------------------------------

def vincent_blend(qa: np.ndarray, qb: np.ndarray) -> np.ndarray:
    """Equal-weight quantile average, rearranged (A5: no fold to fit weights on)."""
    return rearrange(0.5 * qa + 0.5 * qb)


def align(index: pd.DataFrame, preds: dict[str, pd.DataFrame], cols: list[str]) -> dict:
    """Eval rows where every system has a complete forecast, as aligned arrays."""
    rows = index[KEYS + ["obs"]]
    for name, p in preds.items():
        p = p[KEYS + ["mean"] + cols]
        p = p[p[cols].notna().all(axis=1)]
        rows = rows.merge(p.rename(columns={c: f"{name}|{c}" for c in ["mean"] + cols}),
                          on=KEYS, how="inner")
    rows = rows.sort_values(KEYS).reset_index(drop=True).copy()
    return {
        "rows": rows, "obs": rows["obs"].to_numpy(float),
        "horizon": rows["horizon"].astype(str).to_numpy(),
        "Q": {n: rows[[f"{n}|{c}" for c in cols]].to_numpy(float) for n in preds},
        "MU": {n: rows[f"{n}|mean"].to_numpy(float) for n in preds},
    }


def coverage90(obs: np.ndarray, q: np.ndarray, levels: list[float]) -> float:
    lo = int(np.argmin(np.abs(np.asarray(levels) - 0.05)))
    hi = int(np.argmin(np.abs(np.asarray(levels) - 0.95)))
    return float(np.mean((obs >= q[:, lo]) & (obs <= q[:, hi])))


# --- scores and tests ------------------------------------------------------------------------

def by_date(rows: pd.DataFrame, crps: dict[str, np.ndarray], horizon: str) -> pd.DataFrame:
    """CRPS summed over stations per issue date: the bootstrap's unit (as 09)."""
    frame = rows[["issue_date", "horizon"]].assign(**crps)
    g = frame[frame["horizon"].astype(str) == horizon]
    return g.groupby("issue_date")[list(crps)].sum().sort_index()


def skill_table(data: dict, systems: list[str], refs: dict[str, str], levels: list[float],
                block: int, B: int, seed: int, m09) -> pd.DataFrame:
    crps = {n: crps_quantile(data["obs"], data["Q"][n], levels) for n in systems + list(refs.values())}
    out = []
    for h in sorted(np.unique(data["horizon"])):
        d = by_date(data["rows"], crps, h)
        sel = data["horizon"] == h
        for n in systems:
            rec = {"system": n, "horizon": h, "n_dates": len(d), "n_rows": int(sel.sum()),
                   "crps": float(crps[n][sel].mean()),
                   "cov90": coverage90(data["obs"][sel], data["Q"][n][sel], levels)}
            for label, ref in refs.items():
                pt, rp = m09.bootstrap_ratio(d[n].to_numpy(), d[ref].to_numpy(), block, B, seed)
                rec.update({f"CRPSS_{label}": pt,
                            f"CRPSS_{label}_low": float(np.percentile(rp, 2.5)),
                            f"CRPSS_{label}_high": float(np.percentile(rp, 97.5))})
            out.append(rec)
    return pd.DataFrame(out)


def h6_pairs(primary: str, present: set[str]) -> list[tuple[str, str, str]]:
    """H6: (system, reference, test label); a positive difference favours the system."""
    pairs = []
    for h in HYBRIDS:
        if h not in present:
            continue
        pairs.append((h, CFS, "a_vs_CFS_BC"))
        pairs.append((h, primary, "b_vs_Mstar"))
        if h in CONTROL and CONTROL[h] in present:
            pairs.append((h, CONTROL[h], "c_vs_control"))
    return pairs


def h6_tests(data: dict, pairs: list[tuple[str, str, str]], levels: list[float], block: int,
             B: int, seed: int, m09) -> pd.DataFrame:
    names = sorted({n for p in pairs for n in p[:2]})
    crps = {n: crps_quantile(data["obs"], data["Q"][n], levels) for n in names}
    out = []
    for system, ref, label in pairs:
        recs = []
        for h in sorted(np.unique(data["horizon"])):
            d = by_date(data["rows"], crps, h)
            diff = (d[ref] - d[system]).to_numpy()
            point, reps = m09.bootstrap_mean(diff, block, B, seed)
            recs.append({"system": system, "reference": ref, "test": label, "horizon": h,
                         "n_dates": len(d), "dCRPS_ref_minus_system": point,
                         "ci_low": float(np.percentile(reps, 2.5)),
                         "ci_high": float(np.percentile(reps, 97.5)),
                         "p_value": m09.one_sided_p(reps, point)})
        holm = m09.holm([r["p_value"] for r in recs])
        for r, p in zip(recs, holm):
            r["p_holm"] = p
        out.extend(recs)
    return pd.DataFrame(out)


# --- driver ------------------------------------------------------------------------------------

def fit_hybrids(panel: pd.DataFrame, windows: pd.DataFrame, cfg: dict, folds: list[str],
                k: int, period: float, min_train: int) -> dict[str, pd.DataFrame]:
    m07 = importlib.import_module("07_models")
    levels = quantile_levels(cfg)
    fs = feature_sets(panel)
    lg = fs["L"] + fs["G"]
    alphas = [float(x) for x in cfg["models"]["ridge"]["alphas"]]
    embargo = int(cfg["validation"].get("embargo_days", 28))
    seed = int(cfg.get("seeds", {}).get("gbm_largescale", 0))
    keys = ["station", "issue_date", "horizon"]
    frames: dict[str, list[pd.DataFrame]] = {name: [] for name, _, _ in TRAINED}
    for fold in progress(folds, desc="09f hybrid", unit="fold", level="fold"):
        block = panel[panel["fold"] == fold]
        if block.empty:
            print(f"[{fold}] not in the panel; skipped")
            continue
        train = target_rows(block, TARGET, "train").merge(windows, on=keys, how="inner")
        evals = target_rows(block, TARGET, "eval").merge(windows, on=keys, how="inner")
        train, evals = add_cfs_anom(train, evals, k, period, min_train)
        if evals.empty:
            print(f"[{fold}] no cell has {min_train} training Mondays with CFS; skipped")
            continue
        print(f"[{fold}] train Mondays with CFS: {len(train)} | eval: {len(evals)}")
        for name, base, with_cfs in TRAINED:
            cols = lg + (["cfs_anom"] if with_cfs else [])
            if base == "ridge":
                q, mu, _ = m07.predict_ridge(train, evals, cols, TARGET, levels, alphas, embargo)
            else:
                q, mu = m07.predict_gbm(train, evals, cols + fs["static"], TARGET, levels,
                                        m07.gbm_params(cfg, seed))
            frames[name].append(pred_frame(evals, "temporal", TARGET, name, q, mu, cfg))
    return {n: pd.concat(f, ignore_index=True) for n, f in frames.items() if f}


def main() -> None:
    cfg = load_config()
    dyn = cfg.get("dynamical") or {}
    if not dyn.get("enabled", False):
        print("dynamical.enabled is false; nothing to do")
        return
    ensure_dirs()
    print(paths_report())
    if not WINDOWS_CSV.is_file():
        raise SystemExit(f"ERROR: {WINDOWS_CSV} not found — run 06b_dynamical.py first")
    m09 = importlib.import_module("09_inference")

    levels, cols = quantile_levels(cfg), qcols(cfg)
    k = int(dyn.get("clim_harmonics_K", 2))
    min_train = int(dyn.get("min_train", 40))
    boot = cfg["inference"]["bootstrap"]
    block = int(boot["block_weeks"])
    B = int(boot["B"])
    if fast_mode():
        fast = dyn.get("fast") or {}
        k = int(fast.get("clim_harmonics_K", 1))
        min_train = int(fast.get("min_train", 8))
        B = int(cfg["models"]["fast"]["bootstrap_B"])
        print(f"FAST MODE: K={k}, min_train={min_train}, B={B}; numbers are not citable")
    seed = int(cfg.get("seeds", {}).get("bootstrap_crpss", 0))
    period = float(cfg["climatology"].get("period_days", 365.25))
    folds = [str(f) for f in dyn.get("folds", ["B1", "B2"])]
    primary = json.loads((MODELS_DIR / "primary_model.json").read_text(encoding="utf-8"))[
        "primary_model"]

    windows = read_station_keyed(WINDOWS_CSV, parse_dates=["issue_date"])[
        ["station", "issue_date", "horizon", "F_mean"]]
    hybrid = fit_hybrids(load_panel(cfg), windows, cfg, folds, k, period, min_train)
    for name, frame in hybrid.items():
        atomic_write_csv(frame, HYBRID_DIR / f"preds_temporal_{name}.csv")

    refs = [CFS, primary, "Ridge_LG", "GBM_LG", "Clim", "Damp"]
    base = read_preds("temporal")
    base = base[(base["target"] == TARGET) & base["model"].isin(refs)]
    missing = [m for m in (CFS, primary, "Clim", "Damp") if m not in set(base["model"])]
    if missing:
        raise SystemExit(f"ERROR: no predictions for {missing} — run 07-07d first")
    index = read_eval_index("temporal")
    index = index[(index["target"] == TARGET) & (index["role"] == "blind")
                  & np.isfinite(index["obs"])]
    preds = {m: base[base["model"] == m] for m in refs if m in set(base["model"])}
    preds.update(hybrid)
    data = align(index, preds, cols)
    if len(data["rows"]) == 0:
        raise SystemExit("ERROR: no blind row has a forecast from every system")
    data["Q"][BLEND] = vincent_blend(data["Q"][CFS], data["Q"][primary])
    data["MU"][BLEND] = 0.5 * (data["MU"][CFS] + data["MU"][primary])

    systems = [s for s in [*hybrid, BLEND, CFS, primary, "Ridge_LG", "GBM_LG"] if s in data["Q"]]
    t16 = skill_table(data, systems, {"clim": "Clim", "damp": "Damp"}, levels, block, B, seed, m09)
    t16b = h6_tests(data, h6_pairs(primary, set(data["Q"])), levels, block, B, seed, m09)
    atomic_write_csv(t16.round(5), TABLES / "T16_hybrid_cfs.csv")
    atomic_write_csv(t16b.round(5), TABLES / "T16b_hybrid_tests.csv")

    blend = data["rows"][KEYS + ["obs"]].assign(model=BLEND, mean=data["MU"][BLEND])
    for j, c in enumerate(cols):
        blend[c] = data["Q"][BLEND][:, j]
    atomic_write_csv(blend, HYBRID_DIR / f"preds_temporal_{BLEND}.csv")

    print(f"common blind rows: {len(data['rows'])} | M* = {primary} | B = {B} | block = {block}")
    print(t16[["system", "horizon", "n_dates", "crps", "cov90", "CRPSS_clim", "CRPSS_clim_low",
               "CRPSS_clim_high"]].round(3).to_string(index=False))
    print()
    print(t16b.round(4).to_string(index=False))
    write_manifest({"tables": {"T16_hybrid_cfs": "tables/T16_hybrid_cfs.csv",
                               "T16b_hybrid_tests": "tables/T16b_hybrid_tests.csv"},
                    "hybrid_cfs_09f": {
        "amendment": "A5", "post_hoc": True, "folds": folds, "primary_model": primary,
        "systems": systems, "common_blind_rows": int(len(data["rows"])),
        "clim_harmonics_K": k, "min_train": min_train, "bootstrap_B": B,
        "predictions": rel_path(HYBRID_DIR),
        "tables": [rel_path(TABLES / "T16_hybrid_cfs.csv"),
                   rel_path(TABLES / "T16b_hybrid_tests.csv")],
        "fast_mode": fast_mode()}}, replace=("hybrid_cfs_09f",))


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Reference and statistical/ML models, direct per horizon (design §5).

Models
------
- `Clim`  empirical distribution of training period-mean anomalies within
          +/-15 days of the target midpoint, same station and horizon; point 0.
- `Damp`  damped persistence: OLS of the target on A0_7d by station x horizon x
          quarter (with intercept), Gaussian with that cell's residual SD. The
          main skill reference.
- `Pers`  deterministic persistence of A0_7d (degenerate distribution; scored
          for deterministic metrics only).
- `Ridge_L` / `Ridge_LG`  standardised ridge per station and horizon; alpha by
          inner temporal validation (last year of training, embargoed);
          Gaussian with the inner-validation residual SD by quarter.
- `GBM_L` / `GBM_LG`  LightGBM pooled over the five stations per horizon, with
          the static descriptors (elevation, lat, lon); one quantile model per
          grid level plus an L2 model for the mean; crossings fixed by
          rearrangement.

Sensitivity models (named `<model>@<variant>`, never candidates for M* or
members of the ensemble):
- `Ridge_LG@EC`, `GBM_LG@EC`  ENSO described by Takahashi's E/C indices instead
  of Niño 1+2/3.4 (R4 in LITERATURE_REVIEW.md), TT_mean only.
- In LOSO, `GBM_<L|LG>@elev` and `@none`  the same pooled model with elevation
  only or no static descriptor (R2): with four training stations, lat/lon act as
  station identifiers.

Experiments
-----------
- `temporal` every fold, every station; the primary analysis.
- `loso` blind folds only: pooled models refitted without the held-out station
  (training dates are already before the test window), scored on that station.
  Station-specific models (Damp, Ridge) need the station's own history and do
  not enter LOSO; the comparison is the same model with and without the station.

Anti-leakage: every fit uses `kind == "train"` rows of its own fold, which 04
already embargoed (a training target never reaches the test window); scalers,
alphas and residual SDs are all computed on those rows only. Nothing here reads
an evaluation target except to write it into the eval index.
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from _common import (
    atomic_write_csv,
    ensure_dirs,
    load_config,
    paths_report,
    progress,
    write_manifest,
)
from _panel import (
    MODELS_DIR,
    TARGETS,
    build_eval_index,
    eval_index_path,
    fast_mode,
    feature_sets,
    load_panel,
    pred_frame,
    quantile_levels,
    target_rows,
    write_preds,
)
from _scores import gaussian_quantiles, rearrange

PRIMARY_TARGET = "TT_mean"
MIN_CELL = 20  # rows below which a station x horizon x quarter cell falls back


# --- references ---------------------------------------------------------------

def predict_clim(train: pd.DataFrame, evals: pd.DataFrame, target: str,
                 levels: list[float], window: int = 15) -> tuple[np.ndarray, np.ndarray]:
    from _panel import climatology_sample
    sample = climatology_sample(train, evals, target, window)
    q = np.array([np.quantile(s, levels) if len(s) >= 10 else np.full(len(levels), np.nan)
                  for s in sample])
    return q.reshape(len(evals), len(levels)), np.zeros(len(evals))


def predict_damp(train: pd.DataFrame, evals: pd.DataFrame, target: str,
                 levels: list[float]) -> tuple[np.ndarray, np.ndarray]:
    a = TARGETS[target][0]
    mu = np.full(len(evals), np.nan)
    sd = np.full(len(evals), np.nan)
    evals = evals.reset_index(drop=True)
    for (st, h), idx in evals.groupby(["station", "horizon"]).groups.items():
        pool = train[(train["station"] == st) & (train["horizon"] == h)]
        for qtr in evals.loc[idx, "quarter"].unique():
            cell = pool[pool["quarter"] == qtr]
            if len(cell) < MIN_CELL:
                cell = pool
            x = cell["A0_7d"].fillna(0.0).to_numpy(float)
            y = cell[a].to_numpy(float)
            if len(y) < 3:
                continue
            X = np.column_stack([np.ones_like(x), x])
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid_sd = float(np.std(y - X @ beta, ddof=2))
            sel = [i for i in idx if evals.at[i, "quarter"] == qtr]
            xe = evals.loc[sel, "A0_7d"].fillna(0.0).to_numpy(float)
            mu[sel] = beta[0] + beta[1] * xe
            sd[sel] = resid_sd
    return gaussian_quantiles(mu, sd, levels), mu


def predict_pers(evals: pd.DataFrame, levels: list[float]) -> tuple[np.ndarray, np.ndarray]:
    mu = evals["A0_7d"].fillna(0.0).to_numpy(float)
    return np.repeat(mu[:, None], len(levels), axis=1), mu


# --- ridge --------------------------------------------------------------------

def _standardise(train_x: np.ndarray, *others: np.ndarray):
    mean = np.nanmean(train_x, axis=0)
    sd = np.nanstd(train_x, axis=0)
    sd[~np.isfinite(sd) | (sd == 0)] = 1.0
    mean[~np.isfinite(mean)] = 0.0

    def tf(x):
        z = (x - mean) / sd
        return np.where(np.isfinite(z), z, 0.0)  # missing -> training mean
    return (tf(train_x), *[tf(o) for o in others])


def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    Xb = np.column_stack([np.ones(len(X)), X])
    pen = alpha * np.eye(Xb.shape[1])
    pen[0, 0] = 0.0  # intercept unpenalised
    return np.linalg.solve(Xb.T @ Xb + pen, Xb.T @ y)


def _ridge_predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return beta[0] + X @ beta[1:]


def predict_ridge(train: pd.DataFrame, evals: pd.DataFrame, cols: list[str], target: str,
                  levels: list[float], alphas: list[float], embargo: int
                  ) -> tuple[np.ndarray, np.ndarray, dict]:
    a = TARGETS[target][0]
    mu = np.full(len(evals), np.nan)
    sd = np.full(len(evals), np.nan)
    chosen: dict[str, float] = {}
    evals = evals.reset_index(drop=True)
    for (st, h), idx in evals.groupby(["station", "horizon"]).groups.items():
        pool = train[(train["station"] == st) & (train["horizon"] == h)].sort_values("issue_date")
        if len(pool) < 60:
            continue
        # Inner validation: the last year of training, separated by the embargo.
        cut = pool["issue_date"].max() - pd.Timedelta(days=365)
        inner_tr = pool[pool["issue_date"] < cut - pd.Timedelta(days=embargo)]
        inner_va = pool[pool["issue_date"] >= cut]
        if len(inner_tr) < 30 or len(inner_va) < 30:
            inner_tr, inner_va = pool.iloc[: len(pool) // 2], pool.iloc[len(pool) // 2:]
        Xtr, Xva = _standardise(inner_tr[cols].to_numpy(float), inner_va[cols].to_numpy(float))
        ytr, yva = inner_tr[a].to_numpy(float), inner_va[a].to_numpy(float)
        scores = {al: float(np.mean((yva - _ridge_predict(_ridge_fit(Xtr, ytr, al), Xva)) ** 2))
                  for al in alphas}
        alpha = min(scores, key=scores.get)
        chosen[f"{st}/{h}"] = alpha
        resid_va = yva - _ridge_predict(_ridge_fit(Xtr, ytr, alpha), Xva)
        pooled_sd = float(np.std(resid_va, ddof=1))
        q_va = inner_va["quarter"].to_numpy()

        Xall, Xev = _standardise(pool[cols].to_numpy(float), evals.loc[idx, cols].to_numpy(float))
        beta = _ridge_fit(Xall, pool[a].to_numpy(float), alpha)
        mu[idx] = _ridge_predict(beta, Xev)
        for i, qtr in zip(idx, evals.loc[idx, "quarter"]):
            r = resid_va[q_va == qtr]
            sd[i] = float(np.std(r, ddof=1)) if len(r) >= MIN_CELL else pooled_sd
    return gaussian_quantiles(mu, sd, levels), mu, chosen


# --- gradient boosting ----------------------------------------------------------

def gbm_params(cfg: dict, seed: int) -> dict:
    p = dict(cfg["models"]["gbm"])
    if fast_mode():
        p["n_estimators"] = int(cfg["models"]["fast"]["gbm_n_estimators"])
    p.update(random_state=seed, verbose=-1, n_jobs=-1)
    return p


def predict_gbm(train: pd.DataFrame, evals: pd.DataFrame, cols: list[str], target: str,
                levels: list[float], params: dict) -> tuple[np.ndarray, np.ndarray]:
    import lightgbm as lgb

    a = TARGETS[target][0]
    q = np.full((len(evals), len(levels)), np.nan)
    mu = np.full(len(evals), np.nan)
    evals = evals.reset_index(drop=True)
    for h, idx in evals.groupby("horizon").groups.items():
        pool = train[train["horizon"] == h]
        if len(pool) < 100:
            continue
        X, y = pool[cols].to_numpy(float), pool[a].to_numpy(float)
        Xe = evals.loc[idx, cols].to_numpy(float)
        mu[idx] = lgb.LGBMRegressor(objective="regression", **params).fit(X, y).predict(Xe)
        for j, tau in enumerate(levels):
            model = lgb.LGBMRegressor(objective="quantile", alpha=tau, **params)
            q[idx, j] = model.fit(X, y).predict(Xe)
    return rearrange(q), mu


# --- driver ---------------------------------------------------------------------

def run_temporal(panel: pd.DataFrame, cfg: dict, targets: list[str]) -> dict:
    levels = quantile_levels(cfg)
    fs = feature_sets(panel)
    sets = {"L": fs["L"], "LG": fs["L"] + fs["G"]}
    gbm_sets = {k: v + fs["static"] for k, v in sets.items()}
    embargo = int(cfg["validation"].get("embargo_days", 28))
    alphas = [float(x) for x in cfg["models"]["ridge"]["alphas"]]
    secondary_models = set(cfg["models"].get("secondary_target_models",
                                             ["Clim", "Damp", "Pers", "Ridge_LG", "GBM_LG"]))
    seeds = cfg.get("seeds", {})
    print(f"features L={len(fs['L'])} G={len(fs['G'])} static={len(fs['static'])}: "
          f"G={fs['G']}")

    preds: dict[str, list[pd.DataFrame]] = {}
    ridge_alphas: dict[str, dict] = {}
    index_frames = []
    for target in targets:
        if TARGETS[target][0] not in panel.columns:
            print(f"[{target}] no target column in the panel; skipped")
            continue
        index_frames.append(build_eval_index(panel, "temporal", target))
        wanted = None if target == PRIMARY_TARGET else secondary_models
        for fold in progress(list(panel["fold"].unique()), desc=f"07 {target}",
                             unit="fold", level="fold"):
            block = panel[panel["fold"] == fold]
            train = target_rows(block, target, "train")
            evals = target_rows(block, target, "eval").reset_index(drop=True)
            if evals.empty or train.empty:
                continue
            t0 = time.perf_counter()

            def emit(model, q, mu):
                if wanted is not None and model not in wanted:
                    return
                preds.setdefault(model, []).append(
                    pred_frame(evals, "temporal", target, model, q, mu, cfg))

            emit("Clim", *predict_clim(train, evals, target, levels))
            emit("Damp", *predict_damp(train, evals, target, levels))
            emit("Pers", *predict_pers(evals, levels))
            for name, cols in sets.items():
                model = f"Ridge_{name}"
                if wanted is None or model in wanted:
                    q, mu, chosen = predict_ridge(train, evals, cols, target, levels, alphas, embargo)
                    emit(model, q, mu)
                    ridge_alphas[f"{target}/{fold}/{model}"] = chosen
            for name, cols in gbm_sets.items():
                model = f"GBM_{name}"
                if wanted is None or model in wanted:
                    seed = int(seeds.get("gbm_largescale" if name == "LG" else "gbm_local", 0))
                    emit(model, *predict_gbm(train, evals, cols, target, levels,
                                             gbm_params(cfg, seed)))
            # R4 sensitivity: E/C replace the Niño pair (primary target only).
            if target == PRIMARY_TARGET and fs["G_EC"] and _ec_enabled(cfg):
                ec_cols = fs["L"] + fs["G_EC"]
                q, mu, _ = predict_ridge(train, evals, ec_cols, target, levels, alphas, embargo)
                emit("Ridge_LG@EC", q, mu)
                seed = int(seeds.get("gbm_largescale", 0))
                emit("GBM_LG@EC", *predict_gbm(train, evals, ec_cols + fs["static"], target,
                                               levels, gbm_params(cfg, seed)))
            print(f"[temporal/{target}/{fold}] train={len(train)} eval={len(evals)} "
                  f"({time.perf_counter() - t0:.1f}s)")

    atomic_write_csv(pd.concat(index_frames, ignore_index=True), eval_index_path("temporal"))
    written = {m: str(write_preds(f, "temporal", m)) for m, f in preds.items()}
    return {"preds": written, "ridge_alphas": ridge_alphas}


def _ec_enabled(cfg: dict) -> bool:
    ec = ((cfg.get("predictors") or {}).get("large_scale") or {}).get("ec_indices") or {}
    return bool(ec.get("sensitivity", False))


def model_name(base: str, variant: str) -> str:
    """`GBM_LG` + `elev` -> `GBM_LG@elev`; the empty variant keeps the plain name."""
    return f"{base}@{variant}" if variant else base


def static_variants(cfg: dict, available: list[str]) -> dict[str, list[str]]:
    """LOSO static-descriptor variants from config, restricted to present columns."""
    loso = cfg["validation"].get("loso", {})
    variants = loso.get("static_variants") or {"": loso.get("static_features", available)}
    return {str(k or ""): [c for c in (v or []) if c in available] for k, v in variants.items()}


def run_loso(panel: pd.DataFrame, cfg: dict) -> dict:
    """Pooled GBM refitted without each station, blind folds, primary target."""
    levels = quantile_levels(cfg)
    fs = feature_sets(panel)
    variants = static_variants(cfg, fs["static"])
    loso_cfg = cfg["validation"].get("loso", {})
    folds = loso_cfg.get("folds", ["B1", "B2"])
    seeds = cfg.get("seeds", {})
    target = PRIMARY_TARGET
    stations = sorted(panel["station"].unique())
    preds: dict[str, list[pd.DataFrame]] = {}
    sub = panel[panel["fold"].isin(folds)]
    index = build_eval_index(sub, "loso", target)
    for fold in folds:
        block = sub[sub["fold"] == fold]
        train_all = target_rows(block, target, "train")
        evals_all = target_rows(block, target, "eval")
        for st in progress(stations, desc=f"07 loso {fold}", unit="st", level="fold"):
            train = train_all[train_all["station"] != st]
            evals = evals_all[evals_all["station"] == st].reset_index(drop=True)
            if evals.empty:
                continue
            for name, cols in {"L": fs["L"], "LG": fs["L"] + fs["G"]}.items():
                seed = int(seeds.get("gbm_largescale" if name == "LG" else "gbm_local", 0))
                for variant, static in variants.items():
                    model = model_name(f"GBM_{name}", variant)
                    q, mu = predict_gbm(train, evals, cols + static, target, levels,
                                        gbm_params(cfg, seed))
                    preds.setdefault(model, []).append(
                        pred_frame(evals, "loso", target, model, q, mu, cfg))
            print(f"[loso/{fold}] held out {st}: train={len(train)} eval={len(evals)}")
    atomic_write_csv(index, eval_index_path("loso"))
    return {"preds": {m: str(write_preds(f, "loso", m)) for m, f in preds.items()}}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--experiment", choices=["temporal", "loso", "all"], default="all")
    args = ap.parse_args(argv)

    cfg = load_config()
    ensure_dirs()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(paths_report())
    if fast_mode():
        print("FAST MODE: reduced budgets; numbers from this run are not citable")
    panel = load_panel(cfg)
    targets = [PRIMARY_TARGET, *cfg["data"].get("secondary_targets", [])]

    summary: dict = {"fast_mode": fast_mode()}
    if args.experiment in ("temporal", "all"):
        summary["temporal"] = run_temporal(panel, cfg, targets)
    if args.experiment in ("loso", "all"):
        summary["loso"] = run_loso(panel, cfg)
    write_manifest({"models_07": summary}, replace=("models_07",))
    print("done")


if __name__ == "__main__":
    main()

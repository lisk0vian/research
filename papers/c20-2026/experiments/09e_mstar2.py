# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Amendment A3.3: M*2, a second system selected on the dev folds only.

Registered in METHODOLOGY.md (A3) before this code was written. Candidates
(2 member sets x 2 combinations x 4 calibrations = 16):

- members: Ridge_LG, GBM_LG, LSTM_LG, with or without one Chronos, the variant
  among {Chronos, Chronos@abs, ChronosBolt} with the lowest mean dev CRPS;
- combination: Vincentization (quantile average, as 07c) or the linear pool
  (mixture of the members' distributions), inverse-dev-CRPS weights per horizon;
- calibration, per horizon: none, the spread factor k (09b), conformalised
  quantiles, or EMOS (normal, mean a + b·m, variance c + d·s²).

Selection on D1-D3 only, cross-fitted by fold (weights and calibration fitted
on two dev folds, scored on the third). The winner has the lowest cross-fitted
dev CRPS among the configurations whose cross-fitted dev 90 % coverage is in
0.85-0.95 at every horizon (else the one whose worst horizon is closest to
0.90, ties by CRPS). It is refitted on all of D1-D3 and written to
`outputs/models/mstar2.json` **before** any blind row is scored; only then are
B1-B2 opened. Every candidate's dev and blind numbers go to T13 so the choice
is visible; only the winner is tested (H5, T14).

Writes `T13_mstar2_selection.csv`, `T14_mstar2_blind.csv`,
`outputs/models/mstar2.json` and `outputs/models/mstar2_preds.csv`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import ndtr

from _common import TABLES, atomic_write_csv, atomic_write_json, ensure_dirs, load_config, \
    paths_report, write_manifest
from _panel import MODELS_DIR, fast_mode, qcols, quantile_levels, read_eval_index, read_preds
from _scores import crps_quantile, gaussian_quantiles, rearrange

TARGET = "TT_mean"
KEYS = ["station", "fold", "issue_date", "horizon"]
BASE_MEMBERS = ["Ridge_LG", "GBM_LG", "LSTM_LG"]
CHRONOS_VARIANTS = ["Chronos", "Chronos@abs", "ChronosBolt"]
COMBOS = ["vincent", "linpool"]
CALIBS = ["none", "k", "conformal", "emos"]
COV_RANGE = (0.85, 0.95)


# --- combination -------------------------------------------------------------------

def extend_tails(q: np.ndarray, levels: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Quantiles on [0, levels..., 1], the outer segments extended linearly."""
    q0 = q[:, :1] - (q[:, 1:2] - q[:, :1]) * levels[0] / (levels[1] - levels[0])
    q1 = q[:, -1:] + (q[:, -1:] - q[:, -2:-1]) * (1 - levels[-1]) / (levels[-1] - levels[-2])
    return np.hstack([q0, q, q1]), np.array([0.0, *levels, 1.0])


def linear_pool(qs: list[np.ndarray], w: np.ndarray, levels: list[float],
                grid: int = 400) -> np.ndarray:
    """Quantiles of the mixture sum_i w_i F_i, row by row (w: (n, M), rows sum to 1)."""
    ext = [extend_tails(q, levels) for q in qs]
    lv = ext[0][1]
    n = qs[0].shape[0]
    out = np.empty((n, len(levels)))
    for r in range(n):
        lo = min(e[0][r, 0] for e in ext)
        hi = max(e[0][r, -1] for e in ext)
        x = np.linspace(lo, hi, grid)
        cdf = sum(w[r, i] * np.interp(x, ext[i][0][r], lv) for i in range(len(qs)))
        out[r] = np.interp(levels, cdf, x)
    return rearrange(out)


def combine(Q: dict, MU: dict, members: list[str], weights: dict, horizon: np.ndarray,
            method: str, levels: list[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Combined quantiles, mean and between-member variance of the means."""
    W = np.column_stack([[weights[str(h)][m] for h in horizon] for m in members])
    W = W / W.sum(axis=1, keepdims=True)
    means = np.column_stack([MU[m] for m in members])
    mu = (W * means).sum(axis=1)
    s2 = (W * (means - mu[:, None]) ** 2).sum(axis=1)
    if method == "vincent":
        q = rearrange(sum(W[:, [i]] * Q[m] for i, m in enumerate(members)))
    else:
        q = linear_pool([Q[m] for m in members], W, levels)
    return q, mu, s2


def inverse_crps_weights(Q: dict, obs: np.ndarray, horizon: np.ndarray, rows: np.ndarray,
                         members: list[str], levels: list[float]) -> dict:
    out = {}
    for h in np.unique(horizon[rows]):
        sel = rows & (horizon == h)
        inv = {m: 1.0 / crps_quantile(obs[sel], Q[m][sel], levels).mean() for m in members}
        tot = sum(inv.values())
        out[str(h)] = {m: v / tot for m, v in inv.items()}
    return out


# --- calibration -------------------------------------------------------------------

def _idx(levels, x):
    return int(np.argmin(np.abs(np.asarray(levels) - x)))


def fit_k(obs, q, levels, coverage=0.90):
    lo, hi = _idx(levels, (1 - coverage) / 2), _idx(levels, 1 - (1 - coverage) / 2)
    med = q[:, _idx(levels, 0.5)]
    below, above = med - q[:, lo], q[:, hi] - med
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(obs >= med, (obs - med) / above, (med - obs) / below)
    z = np.where(np.isfinite(z), z, np.inf)
    return {"k": float(np.quantile(z, coverage))}


def apply_k(p, q, mu, s2, levels):
    med = q[:, [_idx(levels, 0.5)]]
    return rearrange(med + p["k"] * (q - med)), mu


def fit_conformal(obs, q, levels):
    """Per central pair (tau, 1 - tau): finite-sample conformal widening."""
    n = len(obs)
    deltas = {}
    for j, tau in enumerate(levels):
        if tau >= 0.5:
            break
        k = len(levels) - 1 - j
        score = np.maximum(q[:, j] - obs, obs - q[:, k])
        level = min(1.0, np.ceil((n + 1) * (1 - 2 * tau)) / n)
        deltas[str(round(tau, 2))] = float(np.quantile(score, level))
    return {"delta": deltas}


def apply_conformal(p, q, mu, s2, levels):
    out = q.copy()
    for j, tau in enumerate(levels):
        if tau >= 0.5:
            break
        k = len(levels) - 1 - j
        d = p["delta"][str(round(tau, 2))]
        out[:, j] -= d
        out[:, k] += d
    return rearrange(out), mu


def crps_normal(y, m, s):
    z = (y - m) / s
    return s * (z * (2 * ndtr(z) - 1) + 2 * np.exp(-0.5 * z * z) / np.sqrt(2 * np.pi)
                - 1 / np.sqrt(np.pi))


def fit_emos(obs, q, mu, s2):
    """Normal(a + b·mu, c + d·s2), c, d > 0, minimum mean CRPS."""
    def loss(t):
        a, b, lc, ld = t
        s = np.sqrt(np.exp(lc) + np.exp(ld) * s2)
        return crps_normal(obs, a + b * mu, s).mean()
    x0 = np.array([0.0, 1.0, np.log(max(np.var(obs - mu), 1e-3)), np.log(1.0)])
    res = minimize(loss, x0, method="L-BFGS-B")
    a, b, lc, ld = res.x
    return {"a": float(a), "b": float(b), "c": float(np.exp(lc)), "d": float(np.exp(ld))}


def apply_emos(p, q, mu, s2, levels):
    m = p["a"] + p["b"] * mu
    s = np.sqrt(p["c"] + p["d"] * s2)
    return gaussian_quantiles(m, s, levels), m


def fit_calibration(kind, obs, q, mu, s2, levels):
    if kind == "none":
        return {}
    if kind == "k":
        return fit_k(obs, q, levels)
    if kind == "conformal":
        return fit_conformal(obs, q, levels)
    return fit_emos(obs, q, mu, s2)


def apply_calibration(kind, p, q, mu, s2, levels):
    if kind == "none":
        return q, mu
    return {"k": apply_k, "conformal": apply_conformal, "emos": apply_emos}[kind](
        p, q, mu, s2, levels)


# --- one configuration ---------------------------------------------------------------

def run_config(data: dict, members, combo, calib, fit_rows, test_rows, levels):
    """Fit weights + calibration on fit_rows, return (q, mu) on test_rows and params."""
    Q, MU, obs, horizon = data["Q"], data["MU"], data["obs"], data["horizon"]
    w = inverse_crps_weights(Q, obs, horizon, fit_rows, members, levels)
    sub = lambda rows: ({m: Q[m][rows] for m in members}, {m: MU[m][rows] for m in members})  # noqa: E731
    qf, mf, sf = combine(*sub(fit_rows), members, w, horizon[fit_rows], combo, levels)
    qt, mt, st = combine(*sub(test_rows), members, w, horizon[test_rows], combo, levels)
    params = {}
    q_out, mu_out = qt.copy(), mt.copy()
    for h in np.unique(horizon[test_rows]):
        hf = horizon[fit_rows] == h
        ht = horizon[test_rows] == h
        p = fit_calibration(calib, obs[fit_rows][hf], qf[hf], mf[hf], sf[hf], levels)
        q_out[ht], mu_out[ht] = apply_calibration(calib, p, qt[ht], mt[ht], st[ht], levels)
        params[str(h)] = p
    return q_out, mu_out, {"weights": w, "calibration": params}


def score(obs, q, levels, horizon) -> dict:
    lo, hi = _idx(levels, 0.05), _idx(levels, 0.95)
    crps = crps_quantile(obs, q, levels)
    cov = {str(h): float(((obs >= q[:, lo]) & (obs <= q[:, hi]))[horizon == h].mean())
           for h in np.unique(horizon)}
    return {"crps": float(crps.mean()), "cov90": cov}


def select(results: list[dict]) -> dict:
    """A3's rule: lowest CRPS among configs in range at every horizon, else closest."""
    ok = [r for r in results if all(COV_RANGE[0] <= c <= COV_RANGE[1]
                                    for c in r["dev_cov90"].values())]
    if ok:
        return min(ok, key=lambda r: r["dev_crps"])
    return min(results, key=lambda r: (max(abs(c - 0.90) for c in r["dev_cov90"].values()),
                                       r["dev_crps"]))


# --- driver ---------------------------------------------------------------------------

def load_data(cfg, models: list[str]) -> dict:
    """Aligned arrays on the eval rows where every model in `models` has a forecast."""
    levels, cols = quantile_levels(cfg), qcols(cfg)
    index = read_eval_index("temporal")
    index = index[(index["target"] == TARGET) & np.isfinite(index["obs"])]
    preds = read_preds("temporal")
    preds = preds[(preds["target"] == TARGET) & preds["model"].isin(models)]
    rows = index[KEYS + ["role", "obs"]]
    for m in models:
        p = preds[preds["model"] == m][KEYS + ["mean"] + cols]
        p = p[p[cols].notna().all(axis=1)]
        rows = rows.merge(p.rename(columns={c: f"{m}|{c}" for c in ["mean"] + cols}), on=KEYS)
    # copy(): one merge per model leaves a fragmented frame.
    rows = rows.sort_values(KEYS).reset_index(drop=True).copy()
    return {
        "rows": rows, "obs": rows["obs"].to_numpy(float),
        "horizon": rows["horizon"].astype(str).to_numpy(), "fold": rows["fold"].to_numpy(),
        "role": rows["role"].to_numpy(),
        "Q": {m: rows[[f"{m}|{c}" for c in cols]].to_numpy(float) for m in models},
        "MU": {m: rows[f"{m}|mean"].to_numpy(float) for m in models},
        "levels": levels,
    }


def blind_tests(data, q2, primary, cfg, levels) -> pd.DataFrame:
    """H5(a) and the skill of M*2 on B1-B2, pooled stations, by issue date."""
    m09 = __import__("importlib").import_module("09_inference")
    boot = cfg["inference"]["bootstrap"]
    block = int(boot["block_weeks"])
    B = int(cfg["models"]["fast"]["bootstrap_B"]) if fast_mode() else int(boot["B"])
    seed = int(cfg.get("seeds", {}).get("bootstrap_crpss", 0))
    rows = data["rows"].assign(
        crps2=crps_quantile(data["obs"], q2, levels),
        crps1=crps_quantile(data["obs"], data["Q"][primary], levels),
        crps_clim=crps_quantile(data["obs"], data["Q"]["Clim"], levels),
        crps_damp=crps_quantile(data["obs"], data["Q"]["Damp"], levels))
    blind = rows[rows["role"] == "blind"]
    out = []
    for h, g in blind.groupby("horizon"):
        d = g.groupby("issue_date")[["crps1", "crps2", "crps_clim", "crps_damp"]].sum().sort_index()
        diff = (d["crps1"] - d["crps2"]).to_numpy()
        point, reps = m09.bootstrap_mean(diff, block, B, seed)
        rec = {"horizon": h, "n_dates": len(d), "crps_mstar": g["crps1"].mean(),
               "crps_mstar2": g["crps2"].mean(), "dCRPS_mstar_minus_mstar2": point,
               "ci_low": float(np.percentile(reps, 2.5)), "ci_high": float(np.percentile(reps, 97.5)),
               "p_value": m09.one_sided_p(reps, point)}
        for ref in ("clim", "damp"):
            pt, rp = m09.bootstrap_ratio(d["crps2"].to_numpy(), d[f"crps_{ref}"].to_numpy(),
                                         block, B, seed)
            rec.update({f"CRPSS_{ref}": pt, f"CRPSS_{ref}_low": float(np.percentile(rp, 2.5)),
                        f"CRPSS_{ref}_high": float(np.percentile(rp, 97.5))})
        out.append(rec)
    t = pd.DataFrame(out)
    t["p_holm"] = m09.holm(t["p_value"].tolist())
    return t


def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    levels = quantile_levels(cfg)
    dev_folds = [f["id"] for f in cfg["validation"]["folds"] if f.get("role") == "dev"]
    primary = json.loads((MODELS_DIR / "primary_model.json").read_text(encoding="utf-8"))["primary_model"]

    present = set(read_preds("temporal")["model"].unique())
    variants = [v for v in CHRONOS_VARIANTS if v in present]
    probe = load_data(cfg, BASE_MEMBERS + variants)
    dev = np.isin(probe["fold"], dev_folds)
    chronos_dev = {v: float(crps_quantile(probe["obs"][dev], probe["Q"][v][dev], levels).mean())
                   for v in variants}
    chronos = min(chronos_dev, key=chronos_dev.get)
    print(f"Chronos variant by dev CRPS: {chronos}  {chronos_dev}")

    data = load_data(cfg, BASE_MEMBERS + [chronos, primary, "Clim", "Damp"])
    fold, role = data["fold"], data["role"]
    dev = np.isin(fold, dev_folds)
    member_sets = {"with_chronos": BASE_MEMBERS + [chronos], "without_chronos": BASE_MEMBERS}

    # 1. Cross-fitted dev selection (no blind row is touched here).
    results = []
    for set_name, members in member_sets.items():
        for combo in COMBOS:
            for calib in CALIBS:
                obs_all, q_all, h_all = [], [], []
                for f in dev_folds:
                    test = fold == f
                    fit = dev & ~test
                    q, _, _ = run_config(data, members, combo, calib, fit, test, levels)
                    obs_all.append(data["obs"][test])
                    q_all.append(q)
                    h_all.append(data["horizon"][test])
                s = score(np.concatenate(obs_all), np.vstack(q_all), levels, np.concatenate(h_all))
                results.append({"members": set_name, "combination": combo, "calibration": calib,
                                "dev_crps": s["crps"], "dev_cov90": s["cov90"]})
                print(f"  {set_name:<16}{combo:<9}{calib:<10} dev CRPS {s['crps']:.4f} "
                      f"cov90 {s['cov90']}")
    win = select(results)

    # 2. Refit the winner on all dev folds and freeze it before opening the blind folds.
    q2, mu2, params = run_config(data, member_sets[win["members"]], win["combination"],
                                 win["calibration"], dev, np.ones(len(fold), bool), levels)
    frozen = {"configuration": {k: win[k] for k in ("members", "combination", "calibration")},
              "members": member_sets[win["members"]], "chronos_variant": chronos,
              "chronos_dev_crps": chronos_dev, "dev_crps": win["dev_crps"],
              "dev_cov90": win["dev_cov90"], "fitted_on": dev_folds, **params,
              "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "frozen_before_blind": True, "amendment": "A3.3"}
    atomic_write_json(frozen, MODELS_DIR / "mstar2.json")
    print(f"M*2 frozen: {frozen['configuration']}")

    # 3. Blind folds, opened once: every candidate (transparency) and the winner (H5).
    for r in results:
        qb, _, _ = run_config(data, member_sets[r["members"]], r["combination"],
                              r["calibration"], dev, ~dev, levels)
        sb = score(data["obs"][~dev], qb, levels, data["horizon"][~dev])
        r["blind_crps"], r["blind_cov90"] = sb["crps"], sb["cov90"]
        r["selected"] = r is win
    t13 = pd.DataFrame([{**{k: v for k, v in r.items() if not k.endswith("cov90")},
                         **{f"dev_cov90_{h}": c for h, c in r["dev_cov90"].items()},
                         **{f"blind_cov90_{h}": c for h, c in r["blind_cov90"].items()}}
                        for r in results])
    atomic_write_csv(t13.round(4), TABLES / "T13_mstar2_selection.csv")
    t14 = blind_tests(data, q2, primary, cfg, levels)
    lo, hi = _idx(levels, 0.05), _idx(levels, 0.95)
    blind = role == "blind"
    t14["cov90_mstar2"] = [float(((data["obs"] >= q2[:, lo]) & (data["obs"] <= q2[:, hi]))
                                 [blind & (data["horizon"] == h)].mean()) for h in t14["horizon"]]
    t14["cov90_in_range"] = t14["cov90_mstar2"].between(*COV_RANGE)
    atomic_write_csv(t14.round(5), TABLES / "T14_mstar2_blind.csv")

    out = data["rows"][KEYS + ["role", "obs"]].assign(model="Mstar2", mean=mu2)
    for j, c in enumerate(qcols(cfg)):
        out[c] = q2[:, j]
    atomic_write_csv(out, MODELS_DIR / "mstar2_preds.csv")
    print(t13.round(3).to_string(index=False))
    print(t14.round(4).to_string(index=False))
    write_manifest({"mstar2_09e": {
        "amendment": "A3.3", "selected": frozen["configuration"], "chronos_variant": chronos,
        "tables": ["outputs/tables/T13_mstar2_selection.csv",
                   "outputs/tables/T14_mstar2_blind.csv"],
        "frozen": "outputs/models/mstar2.json"}}, replace=("mstar2_09e",))


if __name__ == "__main__":
    main()

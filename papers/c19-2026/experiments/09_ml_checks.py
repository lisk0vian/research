# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 09_ml_checks: the two plan-v6 machine learning roles.

A (calibration): model log(OSRM minutes / friction minutes) on the G1 routes.
Candidates in simplicity order: regularized linear (Ridge), isotonic regression
on friction, monotone gradient boosting (used only if better than the simpler
ones). Validation: leave-one-department-out. The simplest candidate that beats
the constant-ratio baseline on all three metrics (MAPE on minutes, Spearman in
remote districts, kappa at 60 and 120 min) becomes the calibrated_min variant
for RQ2; otherwise A is refuted and the G1 band calibration stays.

B (predictive): HistGradientBoostingClassifier with a monotonic (non-decreasing)
constraint on access time, target death outside a health facility.
Populations: all deaths 2022-2025 (pre-registered, plan v6) and the H3a
amenable population (added once in plan v11 after seeing the all-causes B).
Validation: leave-one-department-out. Metrics: delta-Brier with a
district-block bootstrap CI and a within-department permutation of access.
Refuted if the delta-Brier CI includes 0 or the permutation leaves Brier
unchanged.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import OUTPUTS  # noqa: E402

RESULTS_VERSION = 4  # v4: three-state B verdict + calibrated person-weighted shares (plan v12)
IN2 = OUTPUTS / "02_geo_inputs"
IN3 = OUTPUTS / "03_access_travel_time"
IN7 = OUTPUTS / "07_outcome_sinadef"
INR = OUTPUTS / "02_regions"
OUT = OUTPUTS / "09_ml_checks"

REMOTE_MIN = 45.0          # plan: remote_sample min district mean minutes
BANDS = [0, 30, 60, np.inf]
BAND_LABELS = ["<30", "30-60", ">60"]
PERM_REPS = 100            # within-department permutations of access
BOOT_REPS = 400            # district-block bootstrap for the delta-Brier CI
SEED = 42


def prog(level: str, n: int, total, desc: str) -> None:
    print("#PROG " + json.dumps({"level": level, "n": n, "total": total,
                                 "desc": desc}), flush=True)


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def cohen_kappa(a: np.ndarray, b: np.ndarray) -> float:
    tab = np.array([[int(np.sum((a == i) & (b == j))) for j in (0, 1)]
                    for i in (0, 1)], dtype=float)
    n = tab.sum()
    if n == 0:
        return float("nan")
    po = np.trace(tab) / n
    pe = (tab.sum(0) @ tab.sum(1)) / n ** 2
    return float((po - pe) / (1 - pe)) if pe < 1 else float("nan")


def mape_min(pred: np.ndarray, true: np.ndarray) -> float:
    mask = true > 0
    return float(np.mean(np.abs(pred[mask] - true[mask]) / true[mask]))


def lodo_metrics(pred: np.ndarray, pilot: pd.DataFrame) -> dict:
    """MAPE, remote Spearman and kappa at 60/120 of out-of-fold predictions."""
    from scipy.stats import spearmanr
    true = pilot["osm_min"].to_numpy()
    remote = pilot["mean_min"].to_numpy() >= REMOTE_MIN
    return {
        "mape": mape_min(pred, true),
        "remote_spearman": float(spearmanr(pred[remote], true[remote]).statistic)
                            if remote.sum() >= 10 else float("nan"),
        "kappa_60": cohen_kappa(pred > 60, true > 60),
        "kappa_120": cohen_kappa(pred > 120, true > 120),
    }


def calibration_a() -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    pilot = pd.read_csv(IN3 / "osm_pilot.csv", dtype={"ubigeo": str}).dropna(
        subset=["friction_min", "osm_min"])
    access = pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str})
    regions = pd.read_csv(INR / "districts_regions.csv", dtype={"ubigeo": str})
    centroids = pd.read_csv(IN2 / "districts.csv", dtype={"ubigeo": str})
    hospitals = pd.read_csv(IN3 / "hospitals_audit.csv")
    hospitals = hospitals[hospitals["status"].astype(str).str.lower() == "ok"]

    data = pilot.merge(regions[["ubigeo", "mean_altitude", "amazon"]], on="ubigeo")
    data = data.merge(access[["ubigeo", "mean_min"]], on="ubigeo")
    data = data.merge(centroids[["ubigeo", "center_lat", "center_lon"]], on="ubigeo")
    dist = haversine_km(data["center_lat"].to_numpy(), data["center_lon"].to_numpy(),
                        hospitals["lat"].to_numpy()[:, None],
                        hospitals["lon"].to_numpy()[:, None])
    data["straight_line_km"] = dist.min(axis=0)
    data["log_friction"] = np.log(data["friction_min"].clip(lower=0.1))
    data["band"] = pd.cut(data["friction_min"], BANDS, labels=BAND_LABELS)
    data["amazon_f"] = data["amazon"].astype(float)
    data["target"] = np.log(data["osm_min"].clip(lower=0.1)) - data["log_friction"]
    data["remote"] = data["mean_min"] >= REMOTE_MIN
    assert data[["mean_altitude", "straight_line_km", "log_friction"]].notna().all().all(), \
        "A features contain NaN"

    # --- baselines -----------------------------------------------------------
    const_ratio = float((data["osm_min"] / data["friction_min"]).median())
    band_ratio = data.groupby("band", observed=True).apply(
        lambda d: (d["osm_min"] / d["friction_min"]).median(), include_groups=False)
    pred_const = (data["friction_min"] * const_ratio).to_numpy()
    pred_band = (data["friction_min"] * data["band"].map(band_ratio).astype(float)).to_numpy()
    base_metrics = lodo_metrics(pred_const, data)
    band_metrics = lodo_metrics(pred_band, data)

    # --- candidates, leave-one-department-out --------------------------------
    dummies = pd.get_dummies(data["band"], prefix="band", dtype=float)
    cols = (["mean_altitude", "amazon_f", "straight_line_km", "log_friction"]
            + [c for c in dummies.columns])
    X = pd.concat([data[["mean_altitude", "amazon_f", "straight_line_km",
                         "log_friction"]], dummies], axis=1).to_numpy()
    y = data["target"].to_numpy()
    depts = data["department"].unique()
    logf_index = cols.index("log_friction")
    mono = np.zeros(len(cols))
    mono[logf_index] = 1.0

    def lodo_fit(fit_predict) -> np.ndarray:
        pred = np.full(len(data), np.nan)
        for dep in depts:
            tr = data["department"].to_numpy() != dep
            te = ~tr
            pred[te] = fit_predict(X[tr], y[tr], X[te])
        assert np.isfinite(pred).all()
        return pred

    ridge = Ridge(alpha=1.0)

    def fit_ridge(xtr, ytr, xte):
        scaler = StandardScaler().fit(xtr)
        return ridge.fit(scaler.transform(xtr), ytr).predict(scaler.transform(xte))

    iso_models: dict = {}

    def fit_iso(xtr, ytr, xte):
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(xtr[:, logf_index], ytr)
        return iso.predict(xte[:, logf_index])

    def fit_hgb(xtr, ytr, xte):
        m = HistGradientBoostingRegressor(max_iter=100, learning_rate=0.1,
                                          monotonic_cst=mono, random_state=SEED)
        m.fit(xtr, ytr)
        return m.predict(xte)

    candidates = [
        ("ridge_regularized_linear", lodo_fit(fit_ridge)),
        ("isotonic_on_friction", lodo_fit(fit_iso)),
        ("gradient_boosting_monotone", lodo_fit(fit_hgb)),
    ]
    metrics = {}
    for name, pred_log in candidates:
        pred_min = data["friction_min"].to_numpy() * np.exp(pred_log)
        metrics[name] = lodo_metrics(pred_min, data)

    def beats(m: dict, ref: dict) -> bool:
        pairs = [("mape", -1), ("remote_spearman", 1), ("kappa_60", 1), ("kappa_120", 1)]
        return all((m[k] - ref[k]) * direction > 0 for k, direction in pairs)

    winner, verdict = None, "refuted"
    for name, _ in candidates:
        if beats(metrics[name], base_metrics):
            winner, verdict = name, "used"
            break

    # --- district-level calibrated_min if a model won ------------------------
    calib_rows = []
    if winner:
        all_rows = (access.merge(regions[["ubigeo", "mean_altitude", "amazon"]],
                                 on="ubigeo")
                    .merge(centroids[["ubigeo", "center_lat", "center_lon"]],
                           on="ubigeo")
                    .dropna(subset=["mean_min"]))
        d2 = haversine_km(all_rows["center_lat"].to_numpy(),
                          all_rows["center_lon"].to_numpy(),
                          hospitals["lat"].to_numpy()[:, None],
                          hospitals["lon"].to_numpy()[:, None])
        all_rows["straight_line_km"] = d2.min(axis=0)
        all_rows["amazon_f"] = all_rows["amazon"].astype(float)
        all_rows["log_friction"] = np.log(all_rows["mean_min"].clip(lower=0.1))
        all_rows["band"] = pd.cut(all_rows["mean_min"], BANDS, labels=BAND_LABELS)
        Xall = pd.concat(
            [all_rows[["mean_altitude", "amazon_f", "straight_line_km",
                       "log_friction"]],
             pd.get_dummies(all_rows["band"], prefix="band", dtype=float)],
            axis=1)[cols].to_numpy()
        # Refit on all routes (LODO only chooses the model; the final model
        # uses every route, like the G1 band ratios).
        if winner == "ridge_regularized_linear":
            pred_log_all = fit_ridge(X, y, Xall)
        elif winner == "isotonic_on_friction":
            pred_log_all = fit_iso(X, y, Xall)
        else:
            pred_log_all = fit_hgb(X, y, Xall)
        all_rows["calibrated_min"] = (all_rows["mean_min"] * np.exp(pred_log_all))
        calib_rows = all_rows[["ubigeo", "calibrated_min"]].to_dict("records")

    result = {
        "verdict": verdict,
        "winner": winner,
        "baseline_constant_ratio": const_ratio,
        "band_ratios": {str(k): float(v) for k, v in band_ratio.items()},
        "baseline_metrics": base_metrics,
        "band_metrics": band_metrics,
        "candidates": {k: v for k, v in metrics.items()},
        "remote_rows": int(data["remote"].sum()),
        "n_routes": int(len(data)),
    }
    (OUT / "calibration.json").write_text(json.dumps(result, indent=2),
                                          encoding="utf-8")
    if calib_rows:
        pd.DataFrame(calib_rows).to_csv(OUT / "calibrated_min.csv", index=False)
    return result


def predictive_b(frame: pd.DataFrame, label: str, fold_start: int,
                 fold_total: int) -> dict:
    """One B run: HGB with/without access, LODO, delta-Brier and permutation."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    cat = pd.get_dummies(frame[["age_group", "sex", "cause_group"]].astype(str),
                         dtype=float)
    X = pd.concat([frame[["mean_altitude", "amazon", "mean_min"]], cat], axis=1)
    access_index = X.columns.get_loc("mean_min")
    mono = np.zeros(X.shape[1])
    mono[access_index] = 1.0  # non-decreasing in access time (plan v6)
    y = frame["outside"].to_numpy(dtype=float)
    depts = sorted(frame["department"].dropna().unique())
    drop_access = np.ones(X.shape[1], dtype=bool)
    drop_access[access_index] = False
    Xn = X.to_numpy()
    dept_col = frame["department"].to_numpy()

    rows = np.empty(len(frame))
    rows_no = np.empty(len(frame))
    models_full: list = []
    for index, dep in enumerate(depts):
        te = (dept_col == dep)
        tr = ~te
        m_full = HistGradientBoostingClassifier(
            max_iter=100, learning_rate=0.1, monotonic_cst=mono,
            early_stopping=False, random_state=SEED)
        m_full.fit(Xn[tr], y[tr])
        models_full.append(m_full)
        m_no = HistGradientBoostingClassifier(
            max_iter=100, learning_rate=0.1, monotonic_cst=mono[drop_access],
            early_stopping=False, random_state=SEED)
        m_no.fit(Xn[tr][:, drop_access], y[tr])
        rows[te] = m_full.predict_proba(Xn[te])[:, 1]
        rows_no[te] = m_no.predict_proba(Xn[te][:, drop_access])[:, 1]
        prog("b", fold_start + index + 1, fold_total, f"LODO {label}: {dep}")
    brier_full = (rows - y) ** 2
    brier_no = (rows_no - y) ** 2
    delta = brier_no - brier_full  # positive: access reduces Brier
    frame_delta = pd.DataFrame({"ubigeo": frame["ubigeo"].to_numpy(),
                                "d": delta, "brier_full": brier_full})
    delta_brier = float(frame_delta["d"].mean())

    # district-block bootstrap of the delta-Brier: resample districts, then
    # average the drawn *rows* (deaths), not district means, so the CI and the
    # point estimate are the same estimand.
    rng = np.random.default_rng(SEED)
    blocks = frame_delta.set_index("ubigeo")["d"]
    ids = blocks.index.unique().to_numpy()
    boot = np.array([blocks.loc[rng.choice(ids, len(ids), replace=True)].mean()
                     for _ in range(BOOT_REPS)])
    ci = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]

    # within-department permutation of access, prediction-time; the drop is the
    # row-weighted Brier change, on the same scale as the delta-Brier.
    drops = []
    for rep in range(PERM_REPS):
        perm = Xn[:, access_index].copy()
        for dep in depts:
            mask = dept_col == dep
            perm[mask] = rng.permutation(perm[mask])
        Xp = Xn.copy()
        Xp[:, access_index] = perm
        brier_perm = np.empty(len(frame))
        for index, dep in enumerate(depts):
            te = dept_col == dep
            brier_perm[te] = (models_full[index].predict_proba(Xp[te])[:, 1]
                              - y[te]) ** 2
        drops.append(float((brier_perm - brier_full).mean()))
        if rep % 10 == 0:
            prog("perm", rep, PERM_REPS, "permutación intra-departamento")
    drop = float(np.mean(drops))
    drop_ci = [float(np.percentile(drops, 2.5)), float(np.percentile(drops, 97.5))]

    result = {
        "n_rows": int(len(frame)),
        "n_departments": int(len(depts)),
        "delta_brier": delta_brier,
        "delta_brier_ci": ci,
        "permutation_brier_drop": drop,
        "permutation_brier_drop_ci": drop_ci,
        "refuted": ci[0] <= 0 <= ci[1] or drop_ci[0] <= 0,
        # plan v12: the letter rule assumed a positive delta; a significantly
        # negative delta means access adds no positive predictive value.
        "verdict": ("refuted" if (ci[0] <= 0 <= ci[1] or drop_ci[0] <= 0)
                    else "no_positive_contribution" if delta_brier < 0
                    else "not_refuted"),
    }
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()
    prog("a", 0, 1, "A: calibración de fricción")
    a = calibration_a()
    prog("a", 1, 1, "A: calibración de fricción")

    frame = pd.read_parquet(IN7 / "model_frame.parquet")
    frame["ubigeo"] = frame["ubigeo"].astype(str)
    regions = pd.read_csv(INR / "districts_regions.csv", dtype={"ubigeo": str})
    frame = frame.merge(regions[["ubigeo", "mean_altitude", "amazon"]],
                        on="ubigeo", how="left")
    frame["mean_altitude"] = frame["mean_altitude"].fillna(
        frame["mean_altitude"].median())
    frame["amazon"] = frame["amazon"].fillna(False).astype(float)
    n_depts = sorted(frame["department"].dropna().unique())
    amenable = frame[frame["resolved_by_name"] & frame["cause_group"].isin(
        ["amenable_acute", "amenable_chronic"])].copy()
    fold_total = len(n_depts) + len(sorted(
        amenable["department"].dropna().unique()))

    prog("b", 0, 1, "B: chequeo predictivo")
    b_all = predictive_b(frame, "all_causes", 0, fold_total)
    b_am = predictive_b(amenable, "amenable", len(n_depts), fold_total)
    b = {"all_causes": b_all, "amenable": b_am, "refuted": b_all["refuted"]}
    prog("b", 1, 1, "B: chequeo predictivo")

    # --- calibrated variant: person-weighted shares for RQ2 (plan v12) ---------
    access = pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str})
    if (OUT / "calibrated_min.csv").exists():
        cal = pd.read_csv(OUT / "calibrated_min.csv", dtype={"ubigeo": str})
        joined = access.merge(cal, on="ubigeo", how="inner").dropna(
            subset=["population", "mean_min", "calibrated_min"])
        w = joined["population"]
        (OUT / "calibrated_share.json").write_text(json.dumps({
            "definition": "district-level person-weighted share (population column;"
                          " district mean vs Ridge-calibrated district mean)",
            "main_over_60": float((w * (joined["mean_min"] > 60)).sum() / w.sum()),
            "calibrated_over_60": float((w * (joined["calibrated_min"] > 60)).sum() / w.sum()),
            "main_over_120": float((w * (joined["mean_min"] > 120)).sum() / w.sum()),
            "calibrated_over_120": float((w * (joined["calibrated_min"] > 120)).sum() / w.sum()),
        }, indent=2), encoding="utf-8")

    (OUT / "predictive.json").write_text(json.dumps(b, indent=2),
                                         encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(
        {"plan": "v11 machine_learning", "a": a, "b": b}, indent=2),
        encoding="utf-8")
    print(json.dumps({"a_verdict": a["verdict"], "a_winner": a["winner"],
                      "b_all_causes": b_all,
                      "b_amenable": b_am}, indent=2))
    print("Stage 09_ml_checks done.")
    return 0


def synthetic() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    print("smoke: synthetic ml checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

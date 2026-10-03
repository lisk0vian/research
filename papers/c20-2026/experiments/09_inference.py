"""Hypothesis tests and skill intervals on the blind folds (design §8).

Population: blind folds B1-B2, temporal experiment, TT_mean. Stations are pooled
per issue date: every loss is summed over the stations that both models scored
on that date, giving one series per horizon ordered in time. The moving-block
bootstrap then resamples blocks of consecutive issue dates, so all five stations
move together and their cross-correlation (one ENSO, one MJO) is preserved
rather than counted as five independent samples.

- H1 (incremental value of large-scale forcing, per horizon):
  Ridge_L vs Ridge_LG by Clark-West MSPE-adjusted with Newey-West HAC;
  GBM_L vs GBM_LG by block bootstrap of the MSE difference; ΔCRPS by block
  bootstrap for both pairs. One-sided.
- H2: M* beats Damp at W3_4, MSSS_damp > 0 (bootstrap lower bound), plus CW
  against Damp when M* is a Ridge model (Ridge nests Damp).
- H3: M* probabilistic skill, CRPSS_clim > 0 per horizon; secondary criterion
  90 % coverage within the configured range.
Holm within each family; unadjusted and adjusted p are both reported. Block
length sensitivity (4/13 weeks) is reported next to the primary 8.

Also T2: every model's blind skill (MSSS/CRPSS vs Clim and Damp) with 95 %
percentile intervals, and the LOSO generalisation gap per held-out station.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from _common import (
    TABLES,
    atomic_write_csv,
    ensure_dirs,
    load_config,
    paths_report,
    read_station_keyed,
    rel_path,
    write_manifest,
)
from _panel import MODELS_DIR, fast_mode
from _scores import overlap_order

TARGET = "TT_mean"


# --- primitives (pure, unit-tested) -------------------------------------------

def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def moving_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Indices of one moving-block bootstrap resample of length n."""
    block = max(1, min(block, n))
    starts = rng.integers(0, n - block + 1, size=int(math.ceil(n / block)))
    return np.concatenate([np.arange(s, s + block) for s in starts])[:n]


def bootstrap_ratio(num: np.ndarray, den: np.ndarray, block: int, B: int, seed: int
                    ) -> tuple[float, np.ndarray]:
    """Skill 1 - sum(num)/sum(den) and its bootstrap replicates (ratio of sums)."""
    rng = np.random.default_rng(seed)
    point = 1.0 - num.sum() / den.sum()
    reps = np.empty(B)
    for b in range(B):
        i = moving_block_indices(len(num), block, rng)
        reps[b] = 1.0 - num[i].sum() / den[i].sum()
    return float(point), reps


def bootstrap_mean(x: np.ndarray, block: int, B: int, seed: int) -> tuple[float, np.ndarray]:
    rng = np.random.default_rng(seed)
    reps = np.array([x[moving_block_indices(len(x), block, rng)].mean() for _ in range(B)])
    return float(x.mean()), reps


def one_sided_p(reps: np.ndarray, point: float) -> float:
    """P(stat <= 0) under the bootstrap distribution recentred at zero.

    Shifting the replicates by -point imposes the null (no skill / no
    difference); the p-value is the share of null replicates at least as large
    as the observed statistic.
    """
    null = reps - point
    return float((np.sum(null >= point) + 1) / (len(reps) + 1))


def newey_west_se(x: np.ndarray, lags: int) -> float:
    """HAC standard error of the mean with Bartlett weights."""
    n = len(x)
    u = x - x.mean()
    s = u @ u / n
    for k in range(1, lags + 1):
        w = 1 - k / (lags + 1)
        s += 2 * w * (u[k:] @ u[:-k]) / n
    return math.sqrt(max(s, 0.0) / n)


def nw_bandwidth(n: int, overlap: int) -> int:
    return max(int(math.floor(4 * (n / 100) ** (2 / 9))), overlap)


def clark_west(y: np.ndarray, f_small: np.ndarray, f_big: np.ndarray) -> np.ndarray:
    """Per-observation CW adjusted loss differential (positive favours the big model)."""
    return (y - f_small) ** 2 - ((y - f_big) ** 2 - (f_small - f_big) ** 2)


def holm(pvalues: list[float]) -> list[float]:
    p = np.asarray(pvalues, dtype=float)
    order = np.argsort(p)
    adj = np.empty_like(p)
    running = 0.0
    m = len(p)
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj.tolist()


# --- data shaping ----------------------------------------------------------------

def paired_by_date(scored: pd.DataFrame, a: str, b: str, horizon: str,
                   cols: list[str]) -> pd.DataFrame:
    """Sum `cols` over stations per issue date, on rows both models scored."""
    keys = ["station", "issue_date"]
    sa = scored[(scored["model"] == a) & (scored["horizon"] == horizon)][keys + cols]
    sb = scored[(scored["model"] == b) & (scored["horizon"] == horizon)][keys + cols]
    m = sa.merge(sb, on=keys, suffixes=("_a", "_b")).dropna()
    return m.groupby("issue_date").sum(numeric_only=True).sort_index()


def cw_by_date(scored: pd.DataFrame, small: str, big: str, horizon: str) -> np.ndarray:
    keys = ["station", "issue_date"]
    s = scored[(scored["model"] == small) & (scored["horizon"] == horizon)][keys + ["obs", "mean"]]
    g = scored[(scored["model"] == big) & (scored["horizon"] == horizon)][keys + ["mean"]]
    m = s.merge(g, on=keys, suffixes=("_s", "_b")).dropna()
    m["cw"] = clark_west(m["obs"].to_numpy(), m["mean_s"].to_numpy(), m["mean_b"].to_numpy())
    return m.groupby("issue_date")["cw"].mean().sort_index().to_numpy()


# --- driver ----------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    ensure_dirs()
    print(paths_report())
    inf = cfg["inference"]
    boot = inf["bootstrap"]
    B = int(cfg["models"]["fast"]["bootstrap_B"]) if fast_mode() else int(boot["B"])
    block = int(boot["block_weeks"])
    blocks_sens = [int(x) for x in boot.get("block_sensitivity", [])]
    seed = int(cfg.get("seeds", {}).get("bootstrap_crpss", 0))
    horizons = {h: (int(v[0]), int(v[1])) for h, v in cfg["target"]["horizons"].items()}
    cov_lo, cov_hi = inf["secondary_calibration_criterion"]["coverage_range"]

    path = MODELS_DIR / "scored_temporal.csv"
    if not path.is_file():
        raise SystemExit(f"ERROR: {path} not found — run 08_metrics.py first")
    scored = read_station_keyed(path, parse_dates=["issue_date"])
    scored = scored[(scored["target"] == TARGET) & (scored["role"] == "blind")]
    primary_path = MODELS_DIR / "primary_model.json"
    import json
    primary = json.loads(primary_path.read_text(encoding="utf-8"))["primary_model"] \
        if primary_path.is_file() else "GBM_LG"
    print(f"blind rows: {len(scored)} | M* = {primary} | B = {B} | block = {block} weeks")

    # --- T2: blind skill with intervals, every model x horizon ----------------
    t2 = []
    for h in horizons:
        for model in sorted(scored["model"].unique()):
            for ref in ("Clim", "Damp"):
                if model == ref:
                    continue
                for metric, col in (("MSSS", "se"), ("CRPSS", "crps")):
                    if metric == "CRPSS" and model == "Pers":
                        continue
                    d = paired_by_date(scored, model, ref, h, [col])
                    if len(d) < 10:
                        continue
                    point, reps = bootstrap_ratio(d[f"{col}_a"].to_numpy(), d[f"{col}_b"].to_numpy(),
                                                  block, B, seed)
                    t2.append({"model": model, "horizon": h, "metric": f"{metric}_{ref.lower()}",
                               "value": point, "ci_low": float(np.percentile(reps, 2.5)),
                               "ci_high": float(np.percentile(reps, 97.5)),
                               "n_dates": int(len(d))})
    t2 = pd.DataFrame(t2)
    atomic_write_csv(t2, TABLES / "T2_blind_skill.csv")

    # --- T3: hypotheses --------------------------------------------------------
    tests = []

    def add(family, test, h, stat, p, extra=None):
        tests.append({"family": family, "test": test, "horizon": h, "statistic": stat,
                      "p_value": p, **(extra or {})})

    for h, (a, b) in horizons.items():
        ov = overlap_order(a, b)
        # H1 Ridge: Clark-West + HAC
        cw = cw_by_date(scored, "Ridge_L", "Ridge_LG", h)
        if len(cw) > 10:
            se = newey_west_se(cw, nw_bandwidth(len(cw), ov))
            z = cw.mean() / se if se > 0 else np.nan
            add("H1", "CW Ridge_L vs Ridge_LG", h, z, norm_sf(z) if np.isfinite(z) else np.nan,
                {"n_dates": len(cw), "hac_lags": nw_bandwidth(len(cw), ov)})
        # H1 GBM (MSE) and both pairs (CRPS): block bootstrap of the mean difference
        for small, big, col, name in (("GBM_L", "GBM_LG", "se", "dMSE GBM"),
                                      ("Ridge_L", "Ridge_LG", "crps", "dCRPS Ridge"),
                                      ("GBM_L", "GBM_LG", "crps", "dCRPS GBM")):
            d = paired_by_date(scored, small, big, h, [col])
            if len(d) < 10:
                continue
            diff = (d[f"{col}_a"] - d[f"{col}_b"]).to_numpy()
            point, reps = bootstrap_mean(diff, block, B, seed)
            sens = {f"p_block{bl}": one_sided_p(bootstrap_mean(diff, bl, B, seed)[1], point)
                    for bl in blocks_sens}
            add("H1", name, h, point, one_sided_p(reps, point),
                {"ci_low": float(np.percentile(reps, 2.5)),
                 "ci_high": float(np.percentile(reps, 97.5)), "n_dates": len(d), **sens})
        # H3: M* CRPSS vs Clim
        d = paired_by_date(scored, primary, "Clim", h, ["crps"])
        if len(d) >= 10:
            point, reps = bootstrap_ratio(d["crps_a"].to_numpy(), d["crps_b"].to_numpy(), block, B, seed)
            cov = scored[(scored["model"] == primary) & (scored["horizon"] == h)]["in90"].mean()
            add("H3", f"CRPSS_clim {primary}", h, point, one_sided_p(reps, point),
                {"ci_low": float(np.percentile(reps, 2.5)), "lower_95_one_sided":
                 float(np.percentile(reps, 5)), "coverage90": float(cov),
                 "coverage_ok": bool(cov_lo <= cov <= cov_hi), "n_dates": len(d)})

    # H2: M* vs Damp at the longest horizon
    h2 = "W3_4" if "W3_4" in horizons else list(horizons)[-1]
    d = paired_by_date(scored, primary, "Damp", h2, ["se"])
    if len(d) >= 10:
        point, reps = bootstrap_ratio(d["se_a"].to_numpy(), d["se_b"].to_numpy(), block, B, seed)
        add("H2", f"MSSS_damp {primary}", h2, point, one_sided_p(reps, point),
            {"lower_95_one_sided": float(np.percentile(reps, 5)), "n_dates": len(d)})
        if primary.startswith("Ridge"):
            cw = cw_by_date(scored, "Damp", primary, h2)
            se = newey_west_se(cw, nw_bandwidth(len(cw), overlap_order(*horizons[h2])))
            z = cw.mean() / se if se > 0 else np.nan
            add("H2-complement", f"CW Damp vs {primary}", h2, z, norm_sf(z))

    t3 = pd.DataFrame(tests)
    if not t3.empty:
        t3["p_holm"] = np.nan
        for (fam, test), g in t3.groupby(["family", "test"]):
            ok = g["p_value"].notna()
            if ok.any():
                t3.loc[g.index[ok], "p_holm"] = holm(g.loc[ok, "p_value"].tolist())
    atomic_write_csv(t3, TABLES / "T3_hypotheses.csv")

    # --- LOSO gap: same model with vs without the station ----------------------
    loso_path = MODELS_DIR / "scored_loso.csv"
    gap_rows = []
    if loso_path.is_file():
        lo = read_station_keyed(loso_path, parse_dates=["issue_date"])
        tm = read_station_keyed(path, parse_dates=["issue_date"])
        tm = tm[(tm["target"] == TARGET) & tm["fold"].isin(lo["fold"].unique())]
        elev = {str(s["ubigeo"]).zfill(6): s["elev_m"] for s in cfg["stations"]}
        keys = ["station", "issue_date", "horizon"]
        for model in sorted(set(lo["model"]) - {"Clim", "Damp"}):
            a = lo[lo["model"] == model][keys + ["crps"]]
            b = tm[tm["model"] == model][keys + ["crps"]]
            ref = tm[tm["model"] == "Clim"][keys + ["crps"]].rename(columns={"crps": "crps_clim"})
            m = a.merge(b, on=keys, suffixes=("_loso", "_temporal")).merge(ref, on=keys).dropna()
            for (st, h), g in m.groupby(["station", "horizon"]):
                gd = g.groupby("issue_date").sum(numeric_only=True).sort_index()
                point, reps = bootstrap_mean((gd["crps_loso"] - gd["crps_temporal"]).to_numpy(),
                                             block, B, seed)
                gap_rows.append({
                    "model": model, "station": st, "elev_m": elev.get(st), "horizon": h,
                    "crpss_clim_temporal": 1 - gd["crps_temporal"].sum() / gd["crps_clim"].sum(),
                    "crpss_clim_loso": 1 - gd["crps_loso"].sum() / gd["crps_clim"].sum(),
                    "dCRPS_loso_minus_temporal": point,
                    "ci_low": float(np.percentile(reps, 2.5)),
                    "ci_high": float(np.percentile(reps, 97.5)), "n_dates": len(gd)})
    gaps = pd.DataFrame(gap_rows)
    atomic_write_csv(gaps, TABLES / "T5_loso_gap.csv")

    print("\nT3 hypotheses (blind, pooled stations):")
    if not t3.empty:
        print(t3[["family", "test", "horizon", "statistic", "p_value", "p_holm"]]
              .round(4).to_string(index=False))
    write_manifest({"tables": {"T2_blind_skill": "tables/T2_blind_skill.csv",
                               "T3_hypotheses": "tables/T3_hypotheses.csv",
                               "T5_loso_gap": "tables/T5_loso_gap.csv"},
                    "inference": {"B": B, "block_weeks": block, "primary_model": primary,
                                  "fast_mode": fast_mode()}})
    print(f"wrote {rel_path(TABLES)}/T2_blind_skill.csv, T3_hypotheses.csv, T5_loso_gap.csv")


if __name__ == "__main__":
    main()

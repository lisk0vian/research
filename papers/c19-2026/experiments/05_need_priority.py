# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 05: need x access (M5, replaces the INVS).

Need = z-scores of the share aged 60+ and the share with disability, equal
weights; no PCA. Five weighting schemes test the stability of the priority
quadrant (high need and poor access), with Kendall tau and the share of
main-priority districts retained by at least four of the five schemes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, rankdata

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import OUTPUTS, RUTA_CENSO  # noqa: E402

RESULTS_VERSION = 2  # v2: drop districts without census need data before the stability tests
IN3 = OUTPUTS / "03_access_travel_time"
OUT = OUTPUTS / "05_need_priority"


def z(values) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    return (x - np.nanmean(x)) / np.nanstd(x)


def minmax(values) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    return (x - np.nanmin(x)) / (np.nanmax(x) - np.nanmin(x))


def rank01(values) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    return (rankdata(x) - 1) / (len(x) - 1)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()

    frame = pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str})
    census = pd.read_csv(RUTA_CENSO, dtype={"ubigeo": str})
    d = frame.merge(census[["ubigeo", "population_total", "pop_60_plus",
                            "pop5_total", "pop5_with_disability"]],
                    on="ubigeo", how="left")
    d["share_60"] = d["pop_60_plus"] / d["population_total"]
    d["share_disability"] = d["pop5_with_disability"] / d["pop5_total"]
    before = len(d)
    d = d.dropna(subset=["share_60", "share_disability"]).reset_index(drop=True)
    excluded = before - len(d)

    schemes = {
        "equal_z": z(d["share_60"]) + z(d["share_disability"]),
        "share60_only": z(d["share_60"]),
        "disability_only": z(d["share_disability"]),
        "equal_minmax": minmax(d["share_60"]) + minmax(d["share_disability"]),
        "equal_rank": rank01(d["share_60"]) + rank01(d["share_disability"]),
    }
    for name, values in schemes.items():
        d[f"need_{name}"] = z(values)

    d["poor_access_60"] = d["mean_min"] > 60
    d["priority_main"] = (d["need_equal_z"] > 0) & d["poor_access_60"]
    d["schemes_priority"] = sum(
        ((d[f"need_{name}"] > 0) & d["poor_access_60"]).astype(int) for name in schemes)
    d["stable_priority"] = d["priority_main"] & (d["schemes_priority"] >= 4)
    d["quadrant"] = np.select(
        [d["priority_main"], (d["need_equal_z"] > 0) & ~d["poor_access_60"],
         (d["need_equal_z"] <= 0) & d["poor_access_60"]],
        ["high_need_poor_access", "high_need_good_access", "low_need_poor_access"],
        default="low_need_good_access")
    d.to_csv(OUT / "district_priority.csv", index=False)

    taus = []
    for name in schemes:
        if name == "equal_z":
            continue
        taus.append({"scheme": name,
                     "kendall_vs_equal_z": float(kendalltau(d["need_equal_z"],
                                                            d[f"need_{name}"]).statistic)})
    pd.DataFrame(taus).to_csv(OUT / "stability_weights.csv", index=False)

    main_priority = int(d["priority_main"].sum())
    retained = float(d.loc[d["priority_main"], "stable_priority"].mean()) if main_priority else np.nan
    summary = {
        "districts": int(len(d)),
        "excluded_without_census": int(excluded),
        "priority_main": main_priority,
        "priority_population": float(d.loc[d["priority_main"], "population"].sum()),
        "priority_population_share": float(d.loc[d["priority_main"], "population"].sum()
                                           / d["population"].sum()),
        "membership_stability": retained,
        "threshold": 0.80,
        "passes": bool(retained >= 0.80),
        "kendall_min": float(min(t["kendall_vs_equal_z"] for t in taus)),
        "kendall_threshold": 0.80,
        "kendall_passes": bool(min(t["kendall_vs_equal_z"] for t in taus) >= 0.80),
        "quadrants": d["quadrant"].value_counts().to_dict(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("Stage 05 done.")
    return 0


def synthetic() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"district_id": [1, 2, 3], "priority_main": [True, False, False],
                  "schemes_priority": [5, 2, 1]}).to_csv(
        OUT / "district_priority.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    print("smoke: synthetic need")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

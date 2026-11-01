# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 06: spatial statistics of district access (M7).

Global Moran and local Moran (LISA) on district polygons with 9,999
permutations and Benjamini-Hochberg FDR control. Stability across three
neighbourhoods (queen, k=4, k=8): the global I must keep its sign and
significance, and the number of local clusters may vary by less than 25 %.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from esda.moran import Moran, Moran_Local
from libpysal.weights import KNN, Queen
from statsmodels.stats.multitest import multipletests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import OUTPUTS, SEED_BASE  # noqa: E402

RESULTS_VERSION = 1
IN3 = OUTPUTS / "03_access_travel_time"
IN2 = OUTPUTS / "02_geo_inputs"
OUT = OUTPUTS / "06_spatial_stats"
PERMUTATIONS = 9999
Q = 0.05


def weights_for(kind: str, gdf: gpd.GeoDataFrame):
    if kind == "queen":
        w = Queen.from_dataframe(gdf, use_index=False)
    else:
        w = KNN.from_dataframe(gdf, k=int(kind[1:]), use_index=False)
    w.transform = "r"
    return w


def run_one(kind: str, gdf: gpd.GeoDataFrame, y: np.ndarray):
    w = weights_for(kind, gdf)
    np.random.seed(SEED_BASE)
    global_m = Moran(y, w, permutations=PERMUTATIONS)
    local = Moran_Local(y, w, permutations=PERMUTATIONS)
    q = multipletests(local.p_sim, method="fdr_bh")[1]
    clusters = (np.isin(local.q, [1, 3])) & (q < Q)  # HH or LL, FDR-significant
    return {
        "kind": kind,
        "global_i": float(global_m.I),
        "global_p": float(global_m.p_sim),
        "global_z": float(global_m.z_sim),
        "local": pd.DataFrame({
            "ubigeo": gdf["ubigeo"].to_numpy(),
            "Ii": local.Is,
            "p_sim": local.p_sim,
            "q_fdr": q,
            "quadrant": local.q,
            "cluster": np.where(clusters, np.where(local.q == 1, "HH", "LL"), ""),
        }),
        "n_clusters": int(clusters.sum()),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()

    gdf = gpd.read_file(IN2 / "districts.gpkg")
    frame = pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str})
    gdf = gdf.merge(frame[["ubigeo", "mean_min"]], on="ubigeo", how="left")
    gdf = gdf[gdf["mean_min"].notna()].reset_index(drop=True)
    y = gdf["mean_min"].to_numpy(dtype=float)

    results = {kind: run_one(kind, gdf, y) for kind in ("queen", "k4", "k8")}
    moran = pd.DataFrame([{k: r[k] for k in ("kind", "global_i", "global_p", "global_z",
                                            "n_clusters")} for r in results.values()])
    moran.to_csv(OUT / "moran.csv", index=False)
    for kind, r in results.items():
        r["local"].to_csv(OUT / f"lisa_{kind}.csv", index=False)

    counts = [r["n_clusters"] for r in results.values()]
    variation = (max(counts) - min(counts)) / max(np.mean(counts), 1)
    signs = {np.sign(r["global_i"]) for r in results.values()}
    significant = all(r["global_p"] < Q for r in results.values())
    stability = {
        "global_i_same_sign": len(signs) == 1,
        "global_i_significant_all": significant,
        "cluster_counts": dict(zip(results.keys(), counts)),
        "cluster_variation": float(variation),
        "cluster_variation_max": 0.25,
        "passes": bool(len(signs) == 1 and significant and variation < 0.25),
    }
    (OUT / "stability.json").write_text(json.dumps(stability, indent=2), encoding="utf-8")
    print(json.dumps(stability, indent=2))
    print("Stage 06 done.")
    return 0


def synthetic() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"kind": ["queen", "k4", "k8"], "global_i": [0.3, 0.3, 0.3],
                  "global_p": [0.001, 0.001, 0.001], "n_clusters": [4, 5, 4]}).to_csv(
        OUT / "moran.csv", index=False)
    (OUT / "stability.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    print("smoke: synthetic spatial")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

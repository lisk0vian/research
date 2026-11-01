# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 04: RQ1 table and RQ2 method sensitivity.

Variants against the main travel-time measure (public MINSA + Gob. Regional,
II-1+): straight line from the district centroid, population-weighted straight
line, calibrated friction (OSRM/friction ratio by trip-length band from the G1
sample), three destination sets, and 2SFCA at 60/120 min on a coarse grid.

Outputs the district variant table, the stability metrics (worst-decile
overlap, kappa at 60/120, bootstrap CI) and a person-weighted summary.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _access import accumulated_cost, bootstrap_spearman, district_summary, stability  # noqa: E402
from _paths import DATA_DIR, OUTPUTS, PROCESSED, RUTA_CENSO, RUTA_RENIPRESS, SEED_BASE  # noqa: E402

RESULTS_VERSION = 2  # v2: invert 2SFCA (higher is better) before comparing with travel time

RAW = DATA_DIR / "raw"
IN3 = OUTPUTS / "03_access_travel_time"
IN2 = OUTPUTS / "02_geo_inputs"
OUT = OUTPUTS / "04_access_sensitivity"
GROSS_KM = 20.0


def load_all():
    g = np.load(IN2 / "grid.npz")
    t = np.load(IN3 / "access_times.npz")
    frame = pd.read_csv(IN3 / "district_access.csv", dtype={"ubigeo": str})
    districts = pd.read_csv(IN2 / "districts.csv", dtype={"ubigeo": str})
    return g, t["times"], frame, districts


def destinations():
    from _etl import load_or_build
    state = load_or_build(RUTA_RENIPRESS, RUTA_CENSO, PROCESSED, SEED_BASE)
    df = state["df_validas"]
    audit = pd.read_csv(IN3 / "hospitals_audit.csv", dtype={"ubigeo": str})
    gross = set(audit.loc[audit["status"] == "gross", "ubigeo"])
    base = df[(df["coord_valid"] == 1) & (~df["ubigeo"].isin(gross))].copy()
    sets = {
        "public": base[base["is_complex_hospital"]
                        & base["institution"].isin(["MINSA", "GOBIERNO REGIONAL"])],
        "public_essalud": base[base["is_complex_hospital"]
                               & base["institution"].isin(["MINSA", "GOBIERNO REGIONAL", "ESSALUD"])],
        "all": base[base["is_complex_hospital"]],
        "all_uncat": base[base["is_complex_hospital"] | base["is_hospital_like_uncategorized"]],
    }
    return {k: v.reset_index(drop=True) for k, v in sets.items()}


def xyz(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def nearest_km(lat, lon, dlat, dlon):
    tree = cKDTree(xyz(np.atleast_1d(dlat), np.atleast_1d(dlon)))
    chord, _ = tree.query(xyz(lat, lon), k=1)
    return 2 * 6371.0 * np.arcsin(np.clip(chord / 2.0, 0.0, 1.0))


def sources_from_points(points, transform, shape):
    import rasterio
    rows, cols = rasterio.transform.rowcol(transform, points["lon"].to_numpy(),
                                           points["lat"].to_numpy())
    rows, cols = np.asarray(rows), np.asarray(cols)
    ok = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
    return np.unique(rows[ok] * shape[1] + cols[ok])


def two_step_fca(cost, population, transform, lats, hosp, districts_df, pixel_m,
                 thresholds=(60, 120)):
    """2SFCA on a factor-4 coarse grid; supply = one hospital, demand = people."""
    factor = 4
    h, w = cost.shape
    H, W = h // factor, w // factor
    cost_c = np.nanmin(cost[:H * factor, :W * factor].reshape(H, factor, W, factor), axis=(1, 3))
    pop_c = population[:H * factor, :W * factor].reshape(H, factor, W, factor).sum(axis=(1, 3))
    transform_c = from_origin(transform.c, transform.f, transform.a * factor, transform.a * factor)
    lats_c = lats[::factor][:H]
    src = sources_from_points(hosp.rename(columns={"lat": "lat", "lon": "lon"}),
                              transform_c, (H, W))
    out = {}
    for thr in thresholds:
        acc = np.zeros(H * W, dtype="float32")
        for k, s in enumerate(src, start=1):
            if k % 10 == 0 or k == len(src):
                print(f"#PROG {json.dumps({'level': '2sfca', 'n': k, 'total': len(src), 'desc': f'hospitales {thr} min'})}", flush=True)
            t = accumulated_cost(cost_c, [s], pixel_m=pixel_m * factor, lats=lats_c).ravel()
            m = np.isfinite(t) & (t <= thr)
            demand = float(pop_c.ravel()[m].sum())
            if demand <= 0:
                continue
            acc[m] += 1.0 / demand
        grid_acc = acc.reshape(H, W)
        rows, cols = rasterio.transform.rowcol(transform, districts_df["center_lon"],
                                               districts_df["center_lat"])
        rows = np.clip(np.asarray(rows) // factor, 0, H - 1)
        cols = np.clip(np.asarray(cols) // factor, 0, W - 1)
        out[f"fca_{thr}"] = grid_acc[rows, cols] * 10_000.0
    return pd.DataFrame(out)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()

    g, times, frame, districts = load_all()
    districts_grid = g["districts"]
    population = g["population"]
    transform = from_origin(float(g["west"]), float(g["north"]),
                            float(g["res"]), float(g["res"]))
    height, width = int(g["height"]), int(g["width"])
    lats = transform.f - (np.arange(height) + 0.5) * transform.a
    pixel_m = float(g["pixel_m"])
    main = frame.set_index("district_id")["mean_min"]

    # --- straight-line variants -------------------------------------------------
    centroids = districts.set_index("ubigeo")
    dest = destinations()
    direct = nearest_km(centroids["center_lat"].to_numpy(), centroids["center_lon"].to_numpy(),
                        dest["public"]["lat"].to_numpy(), dest["public"]["lon"].to_numpy())
    rr, cc = np.indices((height, width))
    cell_km = nearest_km(lats[rr.ravel()], (transform.c + (cc.ravel() + 0.5) * transform.a),
                         dest["public"]["lat"].to_numpy(), dest["public"]["lon"].to_numpy())
    cell_km = cell_km.reshape(height, width)
    pw = district_summary(cell_km, population, districts_grid,
                          ids=frame["district_id"].tolist())
    variants = pd.DataFrame({
        "district_id": frame["district_id"],
        "main_min": main.values,
        "centroid_km": direct,
        "popweighted_km": pw.set_index("district")["mean_min"].reindex(frame["district_id"]).values,
    })

    # --- calibrated friction (G1 ratios by band) --------------------------------
    pilot = pd.read_csv(IN3 / "osm_pilot.csv").dropna(subset=["friction_min", "osm_min"])
    bands = pd.cut(pilot["friction_min"], [0, 30, 60, np.inf], labels=["<30", "30-60", ">60"])
    ratio = pilot.groupby(bands, observed=True).apply(
        lambda d: (d["osm_min"] / d["friction_min"]).median(), include_groups=False)
    band_of = pd.cut(variants["main_min"], [0, 30, 60, np.inf], labels=["<30", "30-60", ">60"])
    variants["calibrated_min"] = variants["main_min"] * band_of.map(ratio).astype(float)

    # --- destination sets -------------------------------------------------------
    cost = friction_from_stage3()
    for name, points in dest.items():
        if name == "public":
            continue
        src = sources_from_points(points, transform, (height, width))
        t = accumulated_cost(cost, src, pixel_m=pixel_m, lats=lats)
        d = district_summary(t, population, districts_grid, ids=frame["district_id"].tolist())
        variants[f"{name}_min"] = d.set_index("district")["mean_min"].reindex(
            frame["district_id"]).values

    # --- 2SFCA ------------------------------------------------------------------
    fca = two_step_fca(cost, population, transform, lats, dest["public"], districts, pixel_m)
    for c in fca.columns:
        variants[c] = fca[c].values

    variants = variants.merge(frame[["district_id", "ubigeo", "adm3_name", "department"]],
                              on="district_id", how="left")
    variants.to_csv(OUT / "district_variants.csv", index=False)

    # --- stability table --------------------------------------------------------
    rows = []
    for col in [c for c in variants.columns if c.endswith(("_min", "_km", "fca_60", "fca_120"))
                and c != "main_min"]:
        a = variants["main_min"].to_numpy()
        b = variants[col].to_numpy(dtype=float)
        if col.startswith("fca_"):
            b = -b  # higher 2SFCA means better access, like a lower travel time
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 3:
            continue
        s = stability(a[ok], b[ok])
        lo, hi = bootstrap_spearman(a[ok], b[ok], n_boot=500, seed=SEED_BASE)
        rows.append({"variant": col, **s, "spearman_ci_low": lo, "spearman_ci_high": hi})
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "stability.csv", index=False)

    person = frame["population"].sum()
    summary = {
        "districts": int(len(frame)),
        "person_weighted_mean_min": float((frame["mean_min"] * frame["population"]).sum() / person),
        "district_weighted_mean_min": float(frame["mean_min"].mean()),
        "share_pop_over_60": float((frame["share_over_60"] * frame["population"]).sum() / person),
        "share_pop_over_120": float((frame["share_over_120"] * frame["population"]).sum() / person),
        "calibration_ratios": {str(k): float(v) for k, v in ratio.items()},
        "variants": table.to_dict(orient="records"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("person_weighted_mean_min",
                                              "share_pop_over_60", "share_pop_over_120")}, indent=2))
    print("Stage 04 done.")
    return 0


def friction_from_stage3():
    """Reuse the friction cost grid written by stage 03 (cache in data/raw)."""
    import rasterio
    from rasterio.warp import Resampling, reproject
    src_path = RAW / ".cache" / "2020_motorized_friction_surface.geotiff"
    g = np.load(IN2 / "grid.npz")
    transform = from_origin(float(g["west"]), float(g["north"]),
                            float(g["res"]), float(g["res"]))
    with rasterio.open(src_path) as src:
        cost = np.full((int(g["height"]), int(g["width"])), np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), cost, dst_transform=transform,
                  dst_crs="EPSG:4326", resampling=Resampling.nearest,
                  src_nodata=src.nodata, dst_nodata=np.nan)
    cost[~np.isfinite(cost) | (cost <= 0)] = np.nan
    return cost


def synthetic() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"district_id": [1, 2, 3], "main_min": [10.0, 50.0, 90.0],
                  "centroid_km": [2.0, 20.0, 40.0], "popweighted_km": [2.0, 18.0, 35.0]}
                 ).to_csv(OUT / "district_variants.csv", index=False)
    pd.DataFrame({"variant": ["centroid_km"], "spearman": [0.9]}).to_csv(
        OUT / "stability.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    print("smoke: synthetic sensitivity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

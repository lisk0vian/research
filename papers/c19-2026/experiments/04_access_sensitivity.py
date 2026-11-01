# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 04: RQ1 table and RQ2 method sensitivity.

Variants against the main travel-time measure (public MINSA + Gob. Regional,
II-1+): straight line from the district centre, population-weighted straight
line, travel time read at the district centre cell (grid vs centroid, M2),
calibrated friction (OSRM/friction ratio by trip-length band from the G1
sample), three destination sets, walking time (MAP walking-only surface), and
2SFCA at 60/120 min on a coarse grid.

Outputs the district variant table, the stability metrics (Spearman with a
bootstrap CI, Kendall, top-100 overlap, kappa at 60 and 120 min), the
11-province exclusion check and a person-weighted summary.

Kappa: a variant in minutes uses the same 60/120-min thresholds; a variant in
another unit (km, 2SFCA) flags the same number of districts as the main
measure (quantile matching). Until v3 every variant was cut at "> 60", which
compared km with minutes and left 2SFCA (negated, never above 60) with a
constant class and a kappa of exactly 0.
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _access import (_kappa, accumulated_cost, bootstrap_spearman,  # noqa: E402
                     district_summary, stability, weighted_by_district)
from _paths import DATA_DIR, OUTPUTS, PROCESSED, RUTA_CENSO, RUTA_RENIPRESS, SEED_BASE  # noqa: E402

# v3: kappa at 60/120 with quantile matching for non-minute variants; 2SFCA
# supply counts hospitals per cell and is read person-weighted; M2 centre-cell
# variant, walking time and the 11-province exclusion check restored.
RESULTS_VERSION = 3

RAW = DATA_DIR / "raw"
IN3 = OUTPUTS / "03_access_travel_time"
IN2 = OUTPUTS / "02_geo_inputs"
OUT = OUTPUTS / "04_access_sensitivity"
MOTORIZED = "2020_motorized_friction_surface"
WALKING = "2020_walking_only_friction_surface"


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


def sources_from_points(points, transform, shape, counts=False):
    """Flat grid indices of the points; with counts, also hospitals per cell."""
    rows, cols = rasterio.transform.rowcol(transform, points["lon"].to_numpy(),
                                           points["lat"].to_numpy())
    rows, cols = np.asarray(rows), np.asarray(cols)
    ok = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
    flat = rows[ok] * shape[1] + cols[ok]
    return np.unique(flat, return_counts=True) if counts else np.unique(flat)


def two_step_fca(cost, population, transform, lats, hosp, districts_grid, ids, pixel_m,
                 thresholds=(60, 120)):
    """2SFCA on a factor-4 coarse grid; supply = hospitals per cell, demand = people.

    Each fine cell takes the score of its coarse cell, and the district value is
    the person-weighted mean over its fine cells (hospitals per 10,000 people).
    """
    factor = 4
    h, w = cost.shape
    H, W = h // factor, w // factor
    cost_c = np.nanmin(cost[:H * factor, :W * factor].reshape(H, factor, W, factor), axis=(1, 3))
    pop_c = population[:H * factor, :W * factor].reshape(H, factor, W, factor).sum(axis=(1, 3))
    transform_c = from_origin(transform.c, transform.f, transform.a * factor, transform.a * factor)
    lats_c = lats[::factor][:H]
    src, supply = sources_from_points(hosp, transform_c, (H, W), counts=True)
    out = {}
    for thr in thresholds:
        acc = np.zeros(H * W, dtype="float64")
        for k, (s, n) in enumerate(zip(src, supply), start=1):
            if k % 10 == 0 or k == len(src):
                print(f"#PROG {json.dumps({'level': '2sfca', 'n': k, 'total': len(src), 'desc': f'hospitales {thr} min'})}", flush=True)
            t = accumulated_cost(cost_c, [s], pixel_m=pixel_m * factor, lats=lats_c).ravel()
            m = np.isfinite(t) & (t <= thr)
            demand = float(pop_c.ravel()[m].sum())
            if demand <= 0:
                continue
            acc[m] += float(n) / demand
        coarse = acc.reshape(H, W)
        fine = np.repeat(np.repeat(coarse, factor, axis=0), factor, axis=1)
        fine = np.pad(fine, ((0, h - fine.shape[0]), (0, w - fine.shape[1])), mode="edge")
        out[f"fca_{thr}"] = weighted_by_district(fine, population, districts_grid, ids) * 10_000.0
    meta = {"source_cells": int(len(src)), "hospitals": int(supply.sum()),
            "cells_with_several_hospitals": int((supply > 1).sum())}
    return pd.DataFrame(out), meta


def friction_grid(name: str):
    """Friction surface `name` resampled onto the analysis grid (minutes per metre)."""
    from rasterio.warp import Resampling, reproject
    tif = RAW / ".cache" / f"{name}.geotiff"
    if not tif.exists():
        tif.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(RAW / f"{name}.zip") as z:
            member = next(m for m in z.namelist() if m.endswith(".geotiff"))
            with z.open(member) as src, tif.open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
    g = np.load(IN2 / "grid.npz")
    transform = from_origin(float(g["west"]), float(g["north"]),
                            float(g["res"]), float(g["res"]))
    with rasterio.open(tif) as src:
        cost = np.full((int(g["height"]), int(g["width"])), np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), cost, dst_transform=transform,
                  dst_crs="EPSG:4326", resampling=Resampling.nearest,
                  src_nodata=src.nodata, dst_nodata=np.nan)
    cost[~np.isfinite(cost) | (cost <= 0)] = np.nan
    return cost


def grid_shares(times, population, districts_grid) -> dict:
    """Share of people (populated district cells) beyond 60 and 120 minutes."""
    w = np.where(np.asarray(districts_grid) > 0, np.asarray(population, float), 0.0)
    total = float(w.sum())
    t = np.asarray(times, float)
    late = ~np.isfinite(t)
    return {"share_pop_over_60": float(w[late | (t > 60)].sum() / total),
            "share_pop_over_120": float(w[late | (t > 120)].sum() / total),
            "person_weighted_mean_min": float((np.where(late, 0, t) * w).sum()
                                              / w[~late].sum())}


def province_exclusion(frame: pd.DataFrame) -> dict:
    """National summary without the provinces that hold census districts with no polygon."""
    census = pd.read_csv(RUTA_CENSO, dtype={"ubigeo": str})
    missing = sorted(set(census["ubigeo"].dropna()) - set(frame["ubigeo"].dropna()))
    provinces = sorted({u[:4] for u in missing})
    keep = ~frame["ubigeo"].fillna("").str[:4].isin(provinces)
    sub = frame[keep & (frame["population"] > 0)]
    full = frame[frame["population"] > 0]

    def summary(d):
        p = d["population"].sum()
        return {"districts": int(len(d)), "population": float(p),
                "person_weighted_mean_min": float((d["mean_min"] * d["population"]).sum() / p),
                "share_pop_over_60": float((d["share_over_60"] * d["population"]).sum() / p),
                "share_pop_over_120": float((d["share_over_120"] * d["population"]).sum() / p)}

    return {"census_districts_without_polygon": len(missing),
            "missing_ubigeos": missing, "provinces_excluded": provinces,
            "all": summary(full), "without_those_provinces": summary(sub)}


def records(table: pd.DataFrame) -> list[dict]:
    """JSON-safe rows (NaN becomes null)."""
    return json.loads(table.to_json(orient="records"))


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
    ids = frame["district_id"].tolist()
    main = frame.set_index("district_id")["mean_min"]
    centres = districts.set_index("district_id").reindex(frame["district_id"])

    # --- straight-line variants -------------------------------------------------
    dest = destinations()
    direct = nearest_km(centres["center_lat"].to_numpy(), centres["center_lon"].to_numpy(),
                        dest["public"]["lat"].to_numpy(), dest["public"]["lon"].to_numpy())
    rr, cc = np.indices((height, width))
    cell_km = nearest_km(lats[rr.ravel()], (transform.c + (cc.ravel() + 0.5) * transform.a),
                         dest["public"]["lat"].to_numpy(), dest["public"]["lon"].to_numpy())
    cell_km = cell_km.reshape(height, width)
    pw = district_summary(cell_km, population, districts_grid, ids=ids)
    variants = pd.DataFrame({
        "district_id": frame["district_id"],
        "main_min": main.values,
        "centroid_km": direct,
        "popweighted_km": pw.set_index("district")["mean_min"].reindex(frame["district_id"]).values,
    })

    # --- M2: travel time read at the district centre cell (grid vs centroid) ---
    r0, c0 = rasterio.transform.rowcol(transform, centres["center_lon"].to_numpy(),
                                       centres["center_lat"].to_numpy())
    r0 = np.clip(np.asarray(r0), 0, height - 1)
    c0 = np.clip(np.asarray(c0), 0, width - 1)
    variants["centre_cell_min"] = np.asarray(times, float)[r0, c0]

    # --- calibrated friction (G1 ratios by band) --------------------------------
    pilot = pd.read_csv(IN3 / "osm_pilot.csv").dropna(subset=["friction_min", "osm_min"])
    bands = pd.cut(pilot["friction_min"], [0, 30, 60, np.inf], labels=["<30", "30-60", ">60"])
    ratio = pilot.groupby(bands, observed=True).apply(
        lambda d: (d["osm_min"] / d["friction_min"]).median(), include_groups=False)
    band_of = pd.cut(variants["main_min"], [0, 30, 60, np.inf], labels=["<30", "30-60", ">60"])
    variants["calibrated_min"] = variants["main_min"] * band_of.map(ratio).astype(float)

    # --- destination sets -------------------------------------------------------
    cost = friction_grid(MOTORIZED)
    for name, points in dest.items():
        if name == "public":
            continue
        src = sources_from_points(points, transform, (height, width))
        t = accumulated_cost(cost, src, pixel_m=pixel_m, lats=lats)
        d = district_summary(t, population, districts_grid, ids=ids)
        variants[f"{name}_min"] = d.set_index("district")["mean_min"].reindex(
            frame["district_id"]).values

    # --- walking time (pre-specified M4 variant) ------------------------------
    walking = None
    if (RAW / f"{WALKING}.zip").exists():
        cost_w = friction_grid(WALKING)
        src = sources_from_points(dest["public"], transform, (height, width))
        t_w = accumulated_cost(cost_w, src, pixel_m=pixel_m, lats=lats)
        d = district_summary(t_w, population, districts_grid, ids=ids)
        variants["walking_min"] = d.set_index("district")["mean_min"].reindex(
            frame["district_id"]).values
        walking = grid_shares(t_w, population, districts_grid)
        del cost_w, t_w
    else:
        print(f"walking surface {WALKING}.zip not found: walking variant skipped")

    # --- 2SFCA ------------------------------------------------------------------
    fca, fca_meta = two_step_fca(cost, population, transform, lats, dest["public"],
                                 districts_grid, ids, pixel_m)
    for c in fca.columns:
        variants[c] = fca[c].values

    variants = variants.merge(frame[["district_id", "ubigeo", "adm3_name", "department"]],
                              on="district_id", how="left")
    variants.to_csv(OUT / "district_variants.csv", index=False)

    # --- stability table --------------------------------------------------------
    pop = frame.set_index("district_id")["population"].reindex(variants["district_id"]).to_numpy()
    rows = []
    for col in [c for c in variants.columns if c.endswith(("_min", "_km")) or c.startswith("fca_")]:
        if col == "main_min":
            continue
        a = variants["main_min"].to_numpy(dtype=float)
        b = variants[col].to_numpy(dtype=float)
        is_fca = col.startswith("fca_")
        if is_fca:
            b = -b  # higher 2SFCA means better access, like a lower travel time
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 3:
            continue
        s = stability(a[ok], b[ok], b_minutes=col.endswith("_min"))
        lo, hi = bootstrap_spearman(a[ok], b[ok], n_boot=500, seed=SEED_BASE)
        row = {"variant": col, "unit": "minutes" if col.endswith("_min") else
               ("km" if col.endswith("_km") else "hospitals per 10,000"),
               **s, "spearman_ci_low": lo, "spearman_ci_high": hi}
        if is_fca:
            # natural class: no hospital within the catchment (score 0) vs main > catchment
            thr = int(col.split("_")[1])
            zero = variants[col].to_numpy(dtype=float) == 0
            row["kappa_natural"] = _kappa((a[ok] > thr).astype(int), zero[ok].astype(int))
            row["zero_share_districts"] = float(zero[ok].mean())
            w = np.nan_to_num(pop[ok])
            row["zero_share_population"] = float(w[zero[ok]].sum() / w.sum())
        rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "stability.csv", index=False)

    person = frame["population"].sum()
    summary = {
        "districts": int(len(frame)),
        "person_weighted_mean_min": float((frame["mean_min"] * frame["population"]).sum() / person),
        "district_weighted_mean_min": float(frame["mean_min"].mean()),
        "share_pop_over_60": float((frame["share_over_60"] * frame["population"]).sum() / person),
        "share_pop_over_120": float((frame["share_over_120"] * frame["population"]).sum() / person),
        "share_pop_in_districts_over_60": float(frame.loc[frame["mean_min"] > 60, "population"].sum() / person),
        "share_pop_in_districts_over_120": float(frame.loc[frame["mean_min"] > 120, "population"].sum() / person),
        "calibration_ratios": {str(k): float(v) for k, v in ratio.items()},
        "kappa_rule": "minutes: same threshold; km and 2SFCA: quantile-matched to the main measure",
        "two_step_fca": fca_meta,
        "walking": walking,
        "province_exclusion": province_exclusion(frame),
        "variants": records(table),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("person_weighted_mean_min",
                                              "share_pop_over_60", "share_pop_over_120")}, indent=2))
    print("Stage 04 done.")
    return 0


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

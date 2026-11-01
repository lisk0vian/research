# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 03: travel time to the nearest public complex hospital.

Reads the stage-02 grid (districts, allocated population, district polygons) and
the Malaria Atlas friction surface, runs a multi-source accumulated cost from the
located public destinations (MINSA + Gobierno Regional, II-1+), writes the
district summary and the G1 validation tables (hospital audit, OSM pilot, city
pairs).

Audit rule (plan v4): a hospital outside its own district polygon is
`boundary` (<= 20 km, kept and reported) or `gross` (> 20 km, excluded from the
main set and re-placed at its district centroid in a declared sensitivity). A
hospital whose ubigeo has no polygon is kept and reported as such.

Checks are blocking: population must be conserved, hospitals must be 0 minutes
and time must never beat distance / max speed.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree
from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _access import accumulated_cost, district_summary  # noqa: E402
from _paths import DATA_DIR, OUTPUTS, PROCESSED, RUTA_CENSO, RUTA_RENIPRESS, SEED_BASE  # noqa: E402

RESULTS_VERSION = 5  # v5: remote sample and post-G1 secondary metrics

RAW = DATA_DIR / "raw"
IN = OUTPUTS / "02_geo_inputs"
OUT = OUTPUTS / "03_access_travel_time"
FRICTION_ZIP = RAW / "2020_motorized_friction_surface.zip"
FRICTION_TIF = RAW / ".cache" / "2020_motorized_friction_surface.geotiff"
OSRM = "https://router.project-osrm.org/route/v1/driving/"
GROSS_KM = 20.0
AMAZON_DEPTS = {"AMAZONAS", "LORETO", "MADRE DE DIOS", "SAN MARTIN", "UCAYALI"}
CITY_PAIRS = [
    (("Lima", "Lima"), ("Ica", "Ica")),
    (("Trujillo", "Trujillo"), ("Chiclayo", "Chiclayo")),
    (("Cusco", "Cusco"), ("Puno", "Puno")),
    (("Arequipa", "Arequipa"), ("Moquegua", "Mariscal Nieto")),
    (("Huancayo", "Huancayo"), ("Ayacucho", "Huamanga")),
    (("Piura", "Piura"), ("Tumbes", "Tumbes")),
]


def load_grid():
    data = np.load(IN / "grid.npz")
    transform = from_origin(float(data["west"]), float(data["north"]),
                            float(data["res"]), float(data["res"]))
    height, width = int(data["height"]), int(data["width"])
    lats = transform.f - (np.arange(height) + 0.5) * transform.a
    return (data["districts"], data["population"], transform,
            height, width, float(data["pixel_m"]), lats)


def friction_cost(shape, transform) -> np.ndarray:
    if not FRICTION_TIF.exists():
        FRICTION_TIF.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(FRICTION_ZIP) as z:
            member = next(m for m in z.namelist() if m.endswith(".geotiff"))
            with z.open(member) as src, FRICTION_TIF.open("wb") as dst:
                dst.write(src.read())
    with rasterio.open(FRICTION_TIF) as src:
        cost = np.full(shape, np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), cost, dst_transform=transform,
                  dst_crs="EPSG:4326", resampling=Resampling.nearest,
                  src_nodata=src.nodata, dst_nodata=np.nan)
    cost[~np.isfinite(cost) | (cost <= 0)] = np.nan
    return cost


def public_hospitals():
    from _etl import load_or_build
    state = load_or_build(RUTA_RENIPRESS, RUTA_CENSO, PROCESSED, SEED_BASE)
    df = state["df_validas"]
    mask = (df["is_complex_hospital"]
            & df["institution"].isin(["MINSA", "GOBIERNO REGIONAL"])
            & (df["coord_valid"] == 1))
    return df.loc[mask, ["lat", "lon", "name", "ubigeo"]].reset_index(drop=True)


def hospital_audit(hosp: pd.DataFrame) -> pd.DataFrame:
    """Point-in-polygon audit of each destination against its own district."""
    districts = gpd.read_file(IN / "districts.gpkg")
    pts = gpd.GeoDataFrame(hosp.copy(),
                           geometry=gpd.points_from_xy(hosp["lon"], hosp["lat"]),
                           crs="EPSG:4326")
    own_poly = districts.set_index("ubigeo")["geometry"]
    pts_utm = pts.to_crs(32718)
    poly_utm = districts.to_crs(32718).set_index("ubigeo")["geometry"]
    rows = []
    for i, row in pts.iterrows():
        ub = row["ubigeo"]
        if ub not in own_poly.index:
            rows.append({"status": "no_polygon_for_ubigeo", "km_to_own": np.nan,
                         "inside_own": False})
            continue
        inside = bool(own_poly.loc[ub].contains(row.geometry))
        km = float(pts_utm.loc[i].geometry.distance(poly_utm.loc[ub]) / 1000.0)
        status = "ok" if inside else ("gross" if km > GROSS_KM else "boundary")
        rows.append({"status": status, "km_to_own": km, "inside_own": inside})
    audit = pd.concat([hosp.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    audit.to_csv(OUT / "hospitals_audit.csv", index=False)
    return audit


def sources_from_points(points: pd.DataFrame, transform, shape):
    rows, cols = rasterio.transform.rowcol(transform, points["lon"].to_numpy(),
                                           points["lat"].to_numpy())
    rows, cols = np.asarray(rows), np.asarray(cols)
    ok = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
    return np.unique(rows[ok] * shape[1] + cols[ok]), int(ok.sum())


def snap_sources(cost: np.ndarray, flat: np.ndarray) -> tuple[np.ndarray, int]:
    """Move sources on nodata cells to the nearest traversable cell."""
    finite = np.isfinite(cost)
    bad = ~finite.ravel()[flat]
    if not bad.any():
        return flat, 0
    if not finite.any():
        raise SystemExit("the friction surface has no traversable cell")
    _, (ri, ci) = distance_transform_edt(~finite, return_indices=True)
    rr, cc = np.unravel_index(flat[bad], cost.shape)
    snapped = flat.copy()
    snapped[bad] = ri[rr, cc] * cost.shape[1] + ci[rr, cc]
    return np.unique(snapped), int(bad.sum())


def osrm_minutes(a, b, cache: dict) -> float:
    key = f"{a[1]:.5f},{a[0]:.5f};{b[1]:.5f},{b[0]:.5f}"
    if key in cache:
        return cache[key]
    url = OSRM + urllib.parse.quote(key, safe=",;") + "?overview=false"
    req = urllib.request.Request(url, headers={"User-Agent": "c19-2026 research"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        value = float(payload["routes"][0]["duration"]) / 60.0
    except Exception as e:  # a failed route is data, not a crash
        print(f"OSRM failed for {key}: {e}")
        value = float("nan")
    cache[key] = value
    time.sleep(1.0)
    return value


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def osm_secondary(pilot: pd.DataFrame) -> pd.DataFrame:
    """Post-G1 metrics, declared post hoc in plan v5: no pass/fail attached."""
    p = pilot.dropna(subset=["friction_min", "osm_min"]).copy()
    p["dept"] = p["department"].str.upper()
    amazon = p["dept"].isin(AMAZON_DEPTS)
    rows = []

    def add(label, df):
        if len(df) < 5:
            return
        a = (df["friction_min"] > 60).astype(int)
        b = (df["osm_min"] > 60).astype(int)
        c = (df["friction_min"] > 120).astype(int)
        d = (df["osm_min"] > 120).astype(int)
        rows.append({"subset": label, "n": len(df), "post_hoc": "yes",
                     "spearman": float(spearmanr(df["friction_min"], df["osm_min"]).statistic),
                     "kappa_60": float(cohen_kappa_score(a, b)),
                     "kappa_120": float(cohen_kappa_score(c, d)),
                     "median_ratio": float((df["osm_min"] / df["friction_min"]).median())})

    add("all", p)
    add("outside_amazon", p[~amazon])
    add("amazon", p[amazon])
    add("osm_gt_30", p[p["osm_min"] > 30])
    add("osm_gt_60", p[p["osm_min"] > 60])
    base = p[~amazon]
    for dept in sorted(base["dept"].unique()):
        add(f"drop_{dept}", base[base["dept"] != dept])
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()

    districts, population, transform, height, width, pixel_m, lats = load_grid()
    districts_csv = pd.read_csv(IN / "districts.csv", dtype={"ubigeo": str})
    cost = friction_cost((height, width), transform)

    hosp = public_hospitals()
    audit = hospital_audit(hosp)
    keep = audit["status"] != "gross"
    destinations = audit.loc[keep].reset_index(drop=True)
    main_sources, n_in = sources_from_points(destinations, transform, (height, width))
    if len(main_sources) == 0:
        raise SystemExit("no public complex hospital falls inside the grid")
    main_sources, n_snap = snap_sources(cost, main_sources)
    print(f"public hospitals: {len(hosp)} located, {int(n_in)} in grid, "
          f"{int((audit['status'] == 'gross').sum())} gross excluded, {n_snap} snapped")

    times = accumulated_cost(cost, main_sources, pixel_m=pixel_m,
                             lats=lats).astype("float32")
    np.savez_compressed(OUT / "access_times.npz", times=times, height=height, width=width)

    frame = district_summary(times, population, districts,
                             ids=sorted(districts_csv["district_id"].astype(int)))
    frame = frame.merge(districts_csv[["district_id", "ubigeo", "adm3_name",
                                       "department", "population_census"]],
                        left_on="district", right_on="district_id", how="left")
    frame.to_csv(OUT / "district_access.csv", index=False)

    # --- M6 sensitivity: gross misplacements at their district centroid --------
    gross = audit[audit["status"] == "gross"]
    sens_rows = []
    if len(gross):
        centroids = districts_csv.set_index("ubigeo").loc[gross["ubigeo"]].reset_index()
        extra, _ = sources_from_points(centroids.rename(columns={"center_lon": "lon",
                                                                  "center_lat": "lat"}),
                                       transform, (height, width))
        extra, _ = snap_sources(cost, extra)
        sens_sources = np.unique(np.concatenate([main_sources, extra]))
        times_sens = accumulated_cost(cost, sens_sources, pixel_m=pixel_m, lats=lats)
        sens = district_summary(times_sens, population, districts,
                                ids=sorted(districts_csv["district_id"].astype(int)))
        merged = frame[["district", "mean_min"]].merge(
            sens[["district", "mean_min"]], on="district", suffixes=("", "_sens"))
        merged["class_main"] = merged["mean_min"] > 60
        merged["class_sens"] = merged["mean_min_sens"] > 60
        merged["changed"] = merged["class_main"] != merged["class_sens"]
        merged.to_csv(OUT / "sensitivity_misplaced.csv", index=False)
        sens_rows = merged["changed"].tolist()
    changed_share = float(np.mean(sens_rows)) if sens_rows else 0.0

    # --- blocking checks --------------------------------------------------------
    rr, cc = np.indices((height, width))
    finite = np.isfinite(times.ravel())
    points = np.column_stack([rr.ravel(), cc.ravel()])[finite]
    src_r, src_c = np.unravel_index(main_sources, (height, width))
    tree = cKDTree(np.column_stack([src_r, src_c]))
    straight_m = tree.query(points)[0] * pixel_m
    min_cost = float(np.nanmin(cost))
    ok_physical = bool(np.all(times.ravel()[finite] + 1e-6 >= straight_m * min_cost))
    zero = bool(np.all(times.ravel()[main_sources] == 0))
    total_alloc = float(population.sum())
    census_total = float(districts_csv["population_census"].fillna(0).sum())
    rel_error = abs(total_alloc - census_total) / max(census_total, 1.0)
    checks = {
        "hospitals_zero_minutes": zero,
        "physical_time_ge_distance_over_speed": ok_physical,
        "population_allocated": total_alloc,
        "population_census": census_total,
        "population_relative_error": rel_error,
        "unreachable_share": float((~finite).mean()),
        "sources": int(len(main_sources)),
        "hospitals_audited": int(len(audit)),
        "hospitals_inside_own": int((audit["status"] == "ok").sum()),
        "hospitals_boundary": int((audit["status"] == "boundary").sum()),
        "hospitals_gross": int((audit["status"] == "gross").sum()),
        "hospitals_no_polygon": int((audit["status"] == "no_polygon_for_ubigeo").sum()),
        "inside_own_share_raw": float((audit["status"] == "ok").mean()),
        "inside_own_share_after_exclusion": float(
            (audit["status"] == "ok").sum()
            / max(int(audit["status"].isin(["ok", "boundary"]).sum()), 1)),
        "sensitivity_changed_share": changed_share,
        "sources_snapped": n_snap,
    }
    if not zero or not ok_physical or rel_error > 1e-6:
        raise SystemExit(f"blocking check failed: {json.dumps(checks, indent=2)}")
    if changed_share > 0.05:
        print("WARNING: >5 % of districts change class when misplacements are moved")

    # --- OSM check (G1): pilot 20, then 200 (or 50) if the pilot is affordable --
    cache = json.loads((OUT / "osm_cache.json").read_text(encoding="utf-8")) \
        if (OUT / "osm_cache.json").exists() else {}
    merged = frame.merge(districts_csv[["district_id", "center_lat", "center_lon"]],
                         on="district_id", how="left")
    candidates = merged.dropna(subset=["mean_min", "center_lat", "center_lon"]).copy()
    candidates["bin"] = pd.qcut(candidates["mean_min"], 5, labels=False, duplicates="drop")

    def sample_by_bin(pool, per_bin, seed, limit=None):
        parts = [g.sample(min(per_bin, len(g)), random_state=seed)
                 for _, g in pool.groupby("bin")]
        out = pd.concat(parts) if parts else pool.head(0)
        return out.head(limit) if limit else out

    def route(rows, phase):
        out = []
        for _, row in rows.iterrows():
            r0, c0 = rasterio.transform.rowcol(transform, row["center_lon"], row["center_lat"])
            r0, c0 = int(r0), int(c0)
            if not (0 <= r0 < height and 0 <= c0 < width):
                continue
            friction = float(times[r0, c0])
            if not np.isfinite(friction):
                continue
            dist = haversine_km(row["center_lat"], row["center_lon"],
                                destinations["lat"], destinations["lon"])
            nearest = np.argsort(dist)[:3]
            osm_alts = [osrm_minutes((row["center_lat"], row["center_lon"]),
                                     (destinations.iloc[j]["lat"], destinations.iloc[j]["lon"]),
                                     cache)
                        for j in nearest]
            osm_alts = [v for v in osm_alts if np.isfinite(v)]
            out.append({"ubigeo": row["ubigeo"], "adm3_name": row["adm3_name"],
                        "department": row["department"], "friction_min": friction,
                        "osm_min": min(osm_alts) if osm_alts else np.nan,
                        "osrm_targets": len(osm_alts), "phase": phase})
        return out

    t0 = time.time()
    pilot = sample_by_bin(candidates, 4, SEED_BASE)
    rows = route(pilot, "pilot")
    elapsed = time.time() - t0
    import psutil
    rss_gb = psutil.Process().memory_info().rss / 1e9
    target = 200 if (elapsed < 600 and rss_gb < 2.0) else 50
    done = {r["ubigeo"] for r in rows}
    extra_n = max(0, target - len(rows))
    if extra_n:
        pool = candidates[~candidates["ubigeo"].isin(done)]
        rows += route(sample_by_bin(pool, max(1, extra_n // 5), SEED_BASE + 1, limit=extra_n),
                      "full")

    # plan v5 (post-G1): widen the remote tail where the engine discriminates worst
    have = {r["ubigeo"] for r in rows}
    remote_pool = candidates[(candidates["mean_min"] > 45)
                             & (~candidates["ubigeo"].isin(have))]
    remote = remote_pool.sample(min(150, len(remote_pool)), random_state=SEED_BASE + 2)
    rows += route(remote, "remote")

    pilot = pd.DataFrame(rows)
    pilot.to_csv(OUT / "osm_pilot.csv", index=False)
    osm_secondary(pilot).to_csv(OUT / "osm_secondary.csv", index=False)
    checks.update({"osm_sample": int(len(pilot)), "osm_target": int(target),
                   "osm_remote": int((pilot["phase"] == "remote").sum()),
                   "osm_pilot_seconds": round(elapsed, 1), "rss_gb": round(rss_gb, 2)})
    (OUT / "checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")

    # --- city pairs (G1) --------------------------------------------------------
    by_name = (districts_csv.drop_duplicates(subset=["adm3_name", "province"])
               .set_index(["adm3_name", "province"]))
    pair_rows = []
    for a, b in CITY_PAIRS:
        try:
            ra, rb = by_name.loc[a], by_name.loc[b]
        except KeyError:
            print(f"city pair skipped, district not found: {a} -> {b}")
            continue
        sa, _ = sources_from_points(
            pd.DataFrame({"lon": [ra["center_lon"]], "lat": [ra["center_lat"]]}),
            transform, (height, width))
        if not len(sa):
            continue
        single = accumulated_cost(cost, sa, pixel_m=pixel_m, lats=lats)
        r1, c1 = rasterio.transform.rowcol(transform, rb["center_lon"], rb["center_lat"])
        friction = float(single[int(r1), int(c1)])
        osm = osrm_minutes((ra["center_lat"], ra["center_lon"]),
                           (rb["center_lat"], rb["center_lon"]), cache)
        pair_rows.append({"from": f"{a[0]}/{a[1]}", "to": f"{b[0]}/{b[1]}",
                          "friction_min": friction, "osm_min": osm})
    pd.DataFrame(pair_rows).to_csv(OUT / "city_pairs.csv", index=False)
    (OUT / "osm_cache.json").write_text(json.dumps(cache, indent=1), encoding="utf-8")

    print(json.dumps({k: checks[k] for k in (
        "population_relative_error", "inside_own_share_raw",
        "inside_own_share_after_exclusion", "sensitivity_changed_share",
        "sources", "sources_snapped")}, indent=2))
    print("Stage 03 done.")
    return 0


def synthetic() -> int:
    """Smoke: 30x30 grid, uniform friction, two hospitals, no OSM."""
    districts, population, transform, height, width, pixel_m, lats = load_grid()
    cost = np.full((height, width), 1.0 / 1000.0, dtype="float32")
    sources = np.array([0, width - 1])
    times = accumulated_cost(cost, sources, pixel_m=pixel_m, lats=lats).astype("float32")
    np.savez_compressed(OUT / "access_times.npz", times=times, height=height, width=width)
    frame = district_summary(times, population, districts, ids=[1, 2, 3])
    frame.to_csv(OUT / "district_access.csv", index=False)
    checks = {"smoke": True, "sources": int(len(sources)),
              "population_allocated": float(population.sum())}
    (OUT / "checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    pd.DataFrame({"smoke": [True]}).to_csv(OUT / "osm_pilot.csv", index=False)
    pd.DataFrame({"smoke": [True]}).to_csv(OUT / "city_pairs.csv", index=False)
    pd.DataFrame({"smoke": [True]}).to_csv(OUT / "hospitals_audit.csv", index=False)
    print("smoke: synthetic access grid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

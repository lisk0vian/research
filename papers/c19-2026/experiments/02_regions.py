# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 02_regions: district altitude and the Amazon-basin flag (M9).

Altitude: Copernicus DEM GLO-30 tiles intersecting the district polygons are
downloaded to a temporary directory, averaged onto the stage-02 30 arcsec grid
and reduced to a district mean; raw tiles are deleted (they are ~4 GB).
Amazon: HydroBASINS level 4, the basin with the largest total area in South
America (the Amazon), with district centroids inside it.

Writes `districts_regions.csv`, `summary.json` and the G1 re-stratification
`osm_stratified.csv` (OSM check by Amazon and altitude quartile).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import DATA_DIR, OUTPUTS  # noqa: E402

RESULTS_VERSION = 2  # v2: bootstrap CIs persisted in osm_stratified.csv
IN = OUTPUTS / "02_geo_inputs"
IN3 = OUTPUTS / "03_access_travel_time"
OUT = OUTPUTS / "02_regions"
HYDRO = DATA_DIR / "raw" / "hybas_sa_lev01-12_v1c.zip"
DEM_BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"


def prog(level: str, n: int, total, desc: str) -> None:
    print("#PROG " + json.dumps({"level": level, "n": n, "total": total,
                                 "desc": desc}), flush=True)


def tiles_for(bounds) -> list[tuple[int, int]]:
    xmin, ymin, xmax, ymax = bounds
    lats = range(int(np.floor(ymin)), int(np.ceil(ymax)))
    lons = range(int(np.floor(xmin)), int(np.ceil(xmax)))
    return [(la, lo) for la in lats for lo in lons]


def tile_name(la: int, lo: int) -> str:
    ns = f"N{la:02d}" if la >= 0 else f"S{-la:02d}"
    ew = f"E{lo:03d}" if lo >= 0 else f"W{-lo:03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


def download_tile(name: str, dest: Path) -> bool:
    url = f"{DEM_BUCKET}/{name}/{name}.tif"
    try:
        with urllib.request.urlopen(url, timeout=120) as src, dest.open("wb") as fh:
            shutil.copyfileobj(src, fh, length=1 << 20)
        return True
    except Exception as e:
        print(f"tile {name} failed: {e}")
        return False


def build_dem(districts: gpd.GeoDataFrame, transform, height: int, width: int) -> np.ndarray:
    dem = np.full((height, width), np.nan, dtype="float32")
    union = districts.geometry.union_all()
    tiles = [(la, lo) for la, lo in tiles_for(districts.total_bounds)
             if shapely.box(lo, la, lo + 1, la + 1).intersects(union)]
    tmp = Path(tempfile.mkdtemp(prefix="c19_dem_"))
    try:
        for index, (la, lo) in enumerate(tiles, start=1):
            name = tile_name(la, lo)
            path = tmp / f"{name}.tif"
            prog("dem", index, len(tiles), f"DEM {name}")
            if not download_tile(name, path):
                continue
            with rasterio.open(path) as src:
                xs, ys = [src.bounds.left, src.bounds.right], [src.bounds.top, src.bounds.bottom]
                rows, cols = rasterio.transform.rowcol(transform, xs, ys)
                r0, r1 = sorted(rows)
                c0, c1 = sorted(cols)
                r0, c0 = max(r0, 0), max(c0, 0)
                r1, c1 = min(r1, height), min(c1, width)
                if r1 <= r0 or c1 <= c0:
                    continue
                dst = np.full((r1 - r0, c1 - c0), np.nan, dtype="float32")
                dst_transform = from_origin(transform.c + c0 * transform.a,
                                            transform.f - r0 * transform.a,
                                            transform.a, transform.a)
                reproject(rasterio.band(src, 1), dst, dst_transform=dst_transform,
                          dst_crs="EPSG:4326", resampling=Resampling.average,
                          src_nodata=src.nodata, dst_nodata=np.nan)
            block = dem[r0:r1, c0:c1]
            dem[r0:r1, c0:c1] = np.where(np.isfinite(dst), dst, block)
            path.unlink(missing_ok=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dem


def amazon_basin(districts: gpd.GeoDataFrame) -> pd.Series:
    tmp = Path(tempfile.mkdtemp(prefix="c19_hydro_"))
    try:
        with zipfile.ZipFile(HYDRO) as z:
            members = [m for m in z.namelist() if m.startswith("hybas_sa_lev04_v1c.")]
            z.extractall(tmp, members)
        basins = gpd.read_file(tmp / "hybas_sa_lev04_v1c.shp")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    main = basins.groupby("MAIN_BAS")["SUB_AREA"].sum().idxmax()
    amazon = basins.loc[basins["MAIN_BAS"] == main].geometry.union_all()
    centroids = districts.geometry.centroid
    inside = shapely.contains_xy(amazon, centroids.x, centroids.y)
    # shapely may return a Series indexed 0..n; passing that to pd.Series with a
    # new index would reindex it to NaN, so force the array first.
    return pd.Series(np.asarray(inside, dtype=bool),
                     index=districts["ubigeo"].to_numpy())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()

    grid = np.load(IN / "grid.npz")
    transform = from_origin(float(grid["west"]), float(grid["north"]),
                            float(grid["res"]), float(grid["res"]))
    height, width = int(grid["height"]), int(grid["width"])
    districts = gpd.read_file(IN / "districts.gpkg")
    ids = json.loads((IN / "district_ids.json").read_text(encoding="utf-8"))

    dem = build_dem(districts, transform, height, width)
    raster = grid["districts"]
    valid = np.isfinite(dem) & (raster > 0)
    max_id = max(int(k) for k in ids)
    sums = np.bincount(raster[valid].astype(int), weights=dem[valid], minlength=max_id + 1)
    counts = np.bincount(raster[valid].astype(int), minlength=max_id + 1)
    altitude = sums / np.maximum(counts, 1)

    amazon = amazon_basin(districts)
    id_of = {ub: int(k) for k, ub in ids.items()}
    table = pd.DataFrame({"ubigeo": districts["ubigeo"].to_numpy()})
    table["district_id"] = table["ubigeo"].map(id_of)
    table["mean_altitude"] = [float(altitude[int(i)]) if counts[int(i)] else np.nan
                              for i in table["district_id"]]
    table["amazon"] = table["ubigeo"].map(amazon)
    table = table.dropna(subset=["district_id"]).sort_values("district_id")
    # Peru has Amazon districts; zero means the basin join silently failed.
    assert table["amazon"].notna().all() and table["amazon"].sum() > 0, \
        "amazon flag is empty: basin join failed"
    table.to_csv(OUT / "districts_regions.csv", index=False)

    census = pd.read_csv(DATA_DIR / "raw" / "censo-2025-distrital.csv",
                         dtype={"ubigeo": str})
    merged = table.merge(census[["ubigeo", "department"]], on="ubigeo", how="left")
    agree = merged.groupby("department")["amazon"].mean().sort_values(ascending=False)
    summary = {
        "districts": int(len(table)),
        "with_altitude": int(table["mean_altitude"].notna().sum()),
        "amazon_districts": int(table["amazon"].sum()),
        "altitude_range": [float(table["mean_altitude"].min()),
                           float(table["mean_altitude"].max())],
        "amazon_share_by_department": agree.head(8).round(3).to_dict(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    pilot_path = IN3 / "osm_pilot.csv"
    if pilot_path.exists():
        pilot = pd.read_csv(pilot_path, dtype={"ubigeo": str}).dropna(
            subset=["friction_min", "osm_min"])
        pilot = pilot.merge(table[["ubigeo", "mean_altitude", "amazon"]], on="ubigeo",
                            how="left")
        # The pre-registered rule is evaluated on the representative 200-centroid
        # sample; the extra 150 remote centroids are an enriched, non-representative
        # sample and must not be pooled with it (G1 note, section 3b).
        samples = {"pre_registered": pilot[pilot["phase"].isin(["pilot", "full"])],
                   "enriched": pilot[pilot["phase"] == "remote"]}

        def spearman_ci(x, y, reps=5000, seed=42):
            rng = np.random.default_rng(seed)
            xa, ya = np.asarray(x), np.asarray(y)
            out = [spearmanr(xa[i], ya[i]).statistic
                   for i in (rng.integers(0, len(xa), len(xa)) for _ in range(reps))]
            return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))

        rows = []
        for sample_name, data in samples.items():
            for label, sub in [("all", data), ("amazon", data[data["amazon"] == True]),
                               ("non_amazon", data[data["amazon"] == False])]:
                if len(sub) >= 5:
                    lo, hi = spearman_ci(sub["friction_min"], sub["osm_min"])
                    rows.append({"sample": sample_name, "subset": label, "n": len(sub),
                                 "spearman": float(spearmanr(sub["friction_min"],
                                                             sub["osm_min"]).statistic),
                                 "ci_low": lo, "ci_high": hi})
            bands = pd.qcut(data["mean_altitude"], 4,
                            labels=["q1_low", "q2", "q3", "q4_high"])
            for band, sub in data.groupby(bands, observed=True):
                if len(sub) >= 5:
                    rows.append({"sample": sample_name, "subset": f"altitude_{band}",
                                 "n": len(sub),
                                 "spearman": float(spearmanr(sub["friction_min"],
                                                             sub["osm_min"]).statistic),
                                 "ci_low": None, "ci_high": None})
        pd.DataFrame(rows).to_csv(OUT / "osm_stratified.csv", index=False)

    print(json.dumps(summary, indent=2))
    print("Stage 02_regions done.")
    return 0


def synthetic() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ubigeo": ["010101"], "district_id": [1],
                  "mean_altitude": [2500.0], "amazon": [False]}).to_csv(
        OUT / "districts_regions.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    print("smoke: synthetic regions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 02: geo inputs.

District polygons (HDX COD-AB), the 1 km analysis grid, WorldPop rescaled to the
census 2025 district totals, and the district table the access stage reads.
The DEM (Copernicus GLO-30) is built later by the region stage: it is not an
input to the access engine.

The grid is 30 arcsec (1/120 deg, ~927 m per pixel at the equator); the true
pixel shrinks with latitude, so distances carry a <=5 % constant bias; a
metric CRS would be needed for absolute minutes.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _access import allocate_population  # noqa: E402
from _paths import DATA_DIR, OUTPUTS, RUTA_CENSO  # noqa: E402

RESULTS_VERSION = 4  # v4: seed districts smaller than a cell (La Punta had 0 pixels)

RAW = DATA_DIR / "raw"
OUT = OUTPUTS / "02_geo_inputs"
RES = 1.0 / 120.0          # 30 arcsec, the native grid of friction and WorldPop
PIXEL_M = 927.0            # metres per 30 arcsec at the equator
BOUNDARIES = RAW / "per_admin_boundaries.shp.zip"
WORLDPOP = RAW / "per_pop_2025_CN_1km_R2025A_UA_v1.tif"


def read_admin3() -> gpd.GeoDataFrame:
    tmp = Path(tempfile.mkdtemp(prefix="c19_admin3_"))
    try:
        with zipfile.ZipFile(BOUNDARIES) as z:
            members = [m for m in z.namelist() if m.startswith("per_admin3.")]
            z.extractall(tmp, members)
        frame = gpd.read_file(tmp / "per_admin3.shp")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    frame["ubigeo"] = frame["adm3_pcode"].astype(str).str[2:]
    if not frame["ubigeo"].str.fullmatch(r"\d{6}").all():
        raise SystemExit("HDX adm3_pcode does not map to a six-digit UBIGEO")
    return frame


def build_grid(frame: gpd.GeoDataFrame):
    """Global 30 arcsec grid: the friction and WorldPop rasters are 1:1, no loss."""
    xmin, ymin, xmax, ymax = frame.total_bounds
    x0 = np.floor(xmin * 120.0) / 120.0
    y1 = np.ceil(ymax * 120.0) / 120.0
    width = int(np.ceil((xmax - x0) * 120.0))
    height = int(np.ceil((y1 - ymin) * 120.0))
    return from_origin(x0, y1, RES, RES), height, width


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("EXP_FAST") == "1":
        return synthetic()

    frame = read_admin3()
    census = pd.read_csv(RUTA_CENSO, dtype={"ubigeo": str})
    frame = frame.merge(
        census[["ubigeo", "population_total", "department", "province", "district"]],
        on="ubigeo", how="left")
    by_ub = frame.set_index("ubigeo")

    transform, height, width = build_grid(frame)
    ids = {i + 1: ub for i, ub in enumerate(sorted(frame["ubigeo"]))}
    inv = {ub: i for i, ub in ids.items()}
    shapes = ((geom, inv[ub]) for geom, ub in zip(frame.geometry, frame["ubigeo"]))
    districts = rasterize(shapes, out_shape=(height, width), transform=transform,
                          fill=0, dtype="int32")

    # A district smaller than a cell would get no pixel and lose its people.
    seeded = []
    for ub in (u for u in inv if not np.any(districts == inv[u])):
        point = by_ub.loc[ub, "geometry"].representative_point()
        row, col = rasterio.transform.rowcol(transform, point.x, point.y)
        row = min(max(int(row), 0), height - 1)
        col = min(max(int(col), 0), width - 1)
        districts[row, col] = inv[ub]
        seeded.append(ub)
    if seeded:
        print(f"seeded {len(seeded)} district(s) with no cell: {seeded}")

    with rasterio.open(WORLDPOP) as src:
        grid = np.full((height, width), np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), grid, dst_transform=transform,
                  dst_crs="EPSG:4326", resampling=Resampling.average,
                  src_nodata=src.nodata, dst_nodata=np.nan)
    grid = np.nan_to_num(grid, nan=0.0, posinf=0.0, neginf=0.0)
    grid[grid < 0] = 0.0  # a negative average is nodata bleed, never people

    totals = {int(i): float(by_ub.loc[ub, "population_total"])
              for i, ub in ids.items()
              if pd.notna(by_ub.loc[ub, "population_total"])}
    population, report = allocate_population(grid, districts, totals)
    # Districts without a census row keep no raw WorldPop counts.
    for did in ids:
        if did not in totals:
            population[districts == did] = 0.0

    np.savez_compressed(OUT / "grid.npz", districts=districts, population=population,
                        height=height, width=width, res=RES, pixel_m=PIXEL_M,
                        west=transform.c, north=transform.f)
    (OUT / "district_ids.json").write_text(json.dumps({str(k): v for k, v in ids.items()},
                                                      indent=0), encoding="utf-8")

    rows = []
    for did, ub in ids.items():
        row = by_ub.loc[ub]
        rep = report.get(did, {"status": "no_polygon"})
        rows.append({
            "district_id": did, "ubigeo": ub, "adm3_name": row["adm3_name"],
            "department": row.get("department"), "province": row["adm2_name"],
            "population_census": row.get("population_total"),
            "pixels": int((districts == did).sum()),
            "raw_population": rep.get("raw"), "factor": rep.get("factor"),
            "status": rep.get("status"),
            "center_lat": row.get("center_lat"), "center_lon": row.get("center_lon"),
        })
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "districts.csv", index=False)
    frame[["ubigeo", "adm3_name", "adm2_name", "geometry"]].to_file(
        OUT / "districts.gpkg", driver="GPKG")

    no_census = int(table["population_census"].isna().sum())
    no_pixels = int((table["pixels"] == 0).sum())
    missing_polygon = sorted(set(census["ubigeo"]) - set(frame["ubigeo"]))
    summary = {
        "polygons": len(frame), "census_districts": len(census),
        "polygons_without_census": no_census, "polygons_without_pixels": no_pixels,
        "census_without_polygon": len(missing_polygon),
        "census_without_polygon_ubigeos": missing_polygon,
        "districts_seeded": seeded,
        "population_total": float(population.sum()),
        "census_total": float(census["population_total"].sum()),
        "census_total_with_polygon": float(sum(totals.values())),
        "grid": {"height": height, "width": width, "res": RES, "pixel_m": PIXEL_M},
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    allocated, census_poly = summary["population_total"], summary["census_total_with_polygon"]
    if census_poly and abs(allocated - census_poly) / census_poly > 1e-6:
        raise SystemExit(f"population not conserved: {allocated:.0f} vs {census_poly:.0f}")
    print("Stage 02 done.")
    return 0


def synthetic() -> int:
    """Smoke: three districts on a 30x30 grid, no files read."""
    rng = np.random.default_rng(42)
    districts = np.zeros((30, 30), dtype="int32")
    districts[:, :10], districts[:, 10:20], districts[:, 20:] = 1, 2, 3
    grid = rng.uniform(0, 5, size=(30, 30)).astype("float32")
    totals = {1: 1000.0, 2: 200.0, 3: 50.0}
    population, report = allocate_population(grid, districts, totals)
    np.savez_compressed(OUT / "grid.npz", districts=districts, population=population,
                        height=30, width=30, res=RES, pixel_m=PIXEL_M, west=-75.0, north=-10.0)
    (OUT / "district_ids.json").write_text(
        json.dumps({"1": "010101", "2": "010102", "3": "010103"}), encoding="utf-8")
    pd.DataFrame({"district_id": [1, 2, 3], "ubigeo": ["010101", "010102", "010103"],
                  "adm3_name": ["synthetic-a", "synthetic-b", "synthetic-c"],
                  "population_census": [1000.0, 200.0, 50.0],
                  "pixels": [300, 300, 300], "status": ["ok"] * 3,
                  "center_lat": [-10.0, -10.0, -10.0], "center_lon": [-75.0, -74.8, -74.6]}
                 ).to_csv(OUT / "districts.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    print("smoke: synthetic grid 30x30")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

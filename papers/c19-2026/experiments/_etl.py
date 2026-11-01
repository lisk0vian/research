# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""The c19-2026 ETL: raw RENIPRESS + INEI census 2025 -> analysis frames.

Adapted from the original monolithic notebook. The expensive part (haversine
distance to the nearest complex hospital, DBSCAN + IsolationForest + LOF
consensus anomalies) runs once and is cached as parquet; every later stage
reloads it instead of recomputing it at import.

Column names are the English names defined in `_schema.py`, which is also the
source of the data dictionary in `data/dictionary/`.

The cache key covers both raw files, this module and `_schema.py`, so a changed
rule or a replaced dataset rebuilds instead of silently reusing old numbers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import _paths
import _schema as schema
from _paths import REGION_NATURAL_MAP, atomic_write_json, hash_archivo, normalizar_cadena

PARQUET_FRAMES = ("df_activos", "df_validas")
LAT_RANGE = (-18.35, -0.02)
LON_RANGE = (-81.40, -68.60)
CENSUS_MERGE_COLUMNS = ["population_total", "pop_60_plus", "pop5_with_disability", "boundary_undefined"]


def _cache_key(renipress: Path, census: Path) -> str:
    h = hashlib.sha256()
    h.update(str(hash_archivo(renipress)).encode())
    h.update(str(hash_archivo(census)).encode())
    h.update(Path(__file__).read_bytes())
    h.update(Path(schema.__file__).read_bytes())
    h.update(Path(_paths.__file__).read_bytes())    # REGION_NATURAL_MAP lives there and ends up in the cached frames
    return h.hexdigest()


def _read_renipress_csv(path: Path) -> pd.DataFrame:
    """The October 2026 edition is UTF-8 with a BOM; the March 2026 cut was latin1."""
    kwargs = dict(sep=";", engine="python", on_bad_lines="skip", dtype=str)
    try:
        return pd.read_csv(path, encoding="utf-8-sig", **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin1", **kwargs)


def add_care_fields(df: pd.DataFrame) -> pd.DataFrame:
    """care_level, care_tier, is_complex_hospital, is_hospital_like_uncategorized.

    An unknown category on an active facility aborts: the previous code mapped
    anything unknown to level 1 and silently misclassified III-E hospitals and
    every facility without a category.
    """
    category = df["category"].fillna(schema.UNCATEGORIZED).str.strip().str.upper()
    category = category.where(category != "", schema.UNCATEGORIZED)
    level = category.map(schema.CARE_LEVEL_MAP)
    level = level.mask(category == schema.UNCATEGORIZED, 0)
    unknown = sorted(set(category[level.isna() & (df["status"] == "ACTIVO")]))
    if unknown:
        raise ValueError(f"unknown RENIPRESS categories on active facilities: {unknown}; add them to _schema.CARE_LEVEL_MAP")
    df["category"] = category
    df["care_level"] = level.fillna(0).astype(int)
    df["care_tier"] = df["care_level"].map(schema.CARE_TIER_BY_LEVEL)
    df["is_complex_hospital"] = df["care_level"] >= schema.COMPLEX_HOSPITAL_MIN_LEVEL
    classification = df["classification"].fillna("").str.upper()
    df["is_hospital_like_uncategorized"] = (category == schema.UNCATEGORIZED) & classification.str.startswith(
        schema.HOSPITAL_LIKE_CLASSIFICATIONS)
    return df


def _read_renipress(path: Path) -> pd.DataFrame:
    df = _read_renipress_csv(path)
    df.columns = df.columns.str.strip().str.upper()
    missing = sorted(set(schema.RENIPRESS_RENAME) - set(df.columns))
    if missing:
        raise ValueError(f"RENIPRESS file lacks expected columns {missing}; the schema changed, update _schema.py")
    extra = sorted(set(df.columns) - set(schema.RENIPRESS_RENAME))
    if extra:
        print(f"WARNING: RENIPRESS columns not in the schema, kept as published: {extra}")
    return df.rename(columns=schema.RENIPRESS_RENAME)


def _clean_renipress(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("institution", "classification", "facility_type", "department", "status"):
        df[col] = df[col].str.strip()
    df["ubigeo"] = df["ubigeo"].str.replace(r"\.0$", "", regex=True).str.strip().str.zfill(6)
    df["is_active"] = df["status"] == "ACTIVO"
    df["department_norm"] = df["department"].apply(normalizar_cadena)
    df["natural_region"] = df["department_norm"].map(
        {normalizar_cadena(k): v for k, v in REGION_NATURAL_MAP.items()}).fillna("Sierra")

    for col in ("lat_raw", "lon_raw"):
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ".", regex=False).str.strip(), errors="coerce")
    valid = df["lat_raw"].between(*LAT_RANGE) & df["lon_raw"].between(*LON_RANGE)
    df["lat"] = df["lat_raw"].where(valid)
    df["lon"] = df["lon_raw"].where(valid)
    df["coord_valid"] = valid.astype(int)
    return add_care_fields(df)


def _read_census(path: Path) -> pd.DataFrame:
    census = pd.read_csv(path, encoding="utf-8", dtype={"ubigeo": str})
    missing = [c for c in schema.CENSUS_REQUIRED if c not in census.columns]
    if missing:
        raise ValueError(f"census file lacks columns {missing}; rebuild it with census2025_prepare.py")
    census["ubigeo"] = census["ubigeo"].str.strip().str.zfill(6)
    if not census["ubigeo"].is_unique:
        raise ValueError("census UBIGEO must be unique")
    if census[schema.CENSUS_REQUIRED].isna().any().any():
        raise ValueError("census table has missing values")
    return census


def _read_sources(renipress: Path, census: Path) -> dict:
    hash_renipress = hash_archivo(renipress)
    hash_census = hash_archivo(census)

    df = _read_renipress(renipress)
    n_antes_dedup = len(df)
    df = df.drop_duplicates()
    n_despues_dedup = len(df)
    df = _clean_renipress(df)
    df_census = _read_census(census)

    n_activos = int(df["is_active"].sum())
    # Active facilities whose district has no census row (districts created after
    # the census cut-off). They are excluded from the analysis, never given population 0.
    sin_censo = df[df["is_active"] & ~df["ubigeo"].isin(df_census["ubigeo"])]
    return {
        "N_ACTIVOS_SIN_CENSO": len(sin_censo),
        "UBIGEO_SIN_CENSO": sorted(sin_censo["ubigeo"].unique().tolist()),
        "df": df,
        "df_census": df_census,
        "hash_renipress": hash_renipress,
        "hash_census": hash_census,
        "N_FILAS_CRUDAS_RENIPRESS": n_antes_dedup,
        "N_ANTES_DEDUP": n_antes_dedup,
        "N_DESPUES_DEDUP": n_despues_dedup,
        "N_ACTIVOS": n_activos,
        "N_INACTIVOS_EXCLUIDOS": len(df) - n_activos,
        "N_COORDS_VALIDAS": int(df["coord_valid"].sum()),
        "N_COORDS_INVALIDAS": int((df["coord_valid"] == 0).sum()),
    }


def _build_enriched(df: pd.DataFrame, df_census: pd.DataFrame, seed: int) -> dict:
    """The expensive frames: distance to the nearest complex hospital + anomalies."""
    from pyproj import Transformer
    from sklearn.cluster import DBSCAN
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors
    from sklearn.preprocessing import StandardScaler

    activos = df[df["is_active"]].copy().reset_index(drop=True)

    validas = activos[activos["coord_valid"] == 1].copy().reset_index(drop=True)
    hosp_c = validas[validas["is_complex_hospital"]].copy()
    if len(hosp_c) > 0:
        nn = NearestNeighbors(n_neighbors=1, metric="haversine")
        nn.fit(np.radians(hosp_c[["lat", "lon"]].values))
        dist_rad, _ = nn.kneighbors(np.radians(validas[["lat", "lon"]].values))
        validas["dist_km_nearest_complex"] = dist_rad[:, 0] * 6371.0
    else:
        validas["dist_km_nearest_complex"] = 0.0

    dist_district = validas.groupby("ubigeo")["dist_km_nearest_complex"].median().reset_index().rename(
        columns={"dist_km_nearest_complex": "dist_km_district_median"})
    activos_todos = activos.merge(dist_district, on="ubigeo", how="left")
    activos_todos["dist_km_complex_hospital"] = activos_todos["dist_km_district_median"].fillna(
        validas["dist_km_nearest_complex"].median() if len(validas) else 0.0)
    enriched = activos_todos.merge(df_census[["ubigeo", *CENSUS_MERGE_COLUMNS]], on="ubigeo", how="left")
    # No census row means no population: drop the facility instead of inventing 0.
    enriched = enriched[enriched["population_total"].notna()].reset_index(drop=True)

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32718", always_xy=True)
    try:
        utm_x, utm_y = transformer.transform(validas["lon"].values, validas["lat"].values)
        x_utm = StandardScaler().fit_transform(np.column_stack([utm_x, utm_y]))
        dbscan_labels = DBSCAN(eps=0.15, min_samples=3).fit_predict(x_utm)
        validas["spatial_anomaly"] = (
            (IsolationForest(contamination=0.08, random_state=seed).fit_predict(x_utm) == -1).astype(int)
            + (LocalOutlierFactor(n_neighbors=20, contamination=0.08).fit_predict(x_utm) == -1).astype(int)
            + (dbscan_labels == -1).astype(int) >= 2).astype(int)
    except Exception:
        validas["spatial_anomaly"] = 0

    anom_m = validas.groupby("ubigeo")["spatial_anomaly"].max().reset_index()
    enriched = enriched.merge(anom_m, on="ubigeo", how="left").fillna({"spatial_anomaly": 0})
    return {"df_activos": enriched, "df_validas": validas}


def load_or_build(renipress: Path, census: Path, cache_dir: Path, seed: int) -> dict:
    """Load the cached analysis frames, or rebuild and cache them."""
    renipress, census, cache_dir = Path(renipress), Path(census), Path(cache_dir)
    state = _read_sources(renipress, census)

    key = _cache_key(renipress, census)
    stamp = cache_dir / "state.json"
    frames = {name: cache_dir / f"{name}.parquet" for name in PARQUET_FRAMES}
    cached = False
    if stamp.is_file() and all(p.is_file() for p in frames.values()):
        try:
            if json.loads(stamp.read_text(encoding="utf-8")).get("key") == key:
                state.update({name: pd.read_parquet(p) for name, p in frames.items()})
                cached = True
        except Exception:
            cached = False

    if not cached:
        state.update(_build_enriched(state["df"], state["df_census"], seed))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            for name, p in frames.items():
                state[name].to_parquet(p, index=False)
            atomic_write_json({"key": key}, stamp)
        except Exception as e:
            print(f"state cache not written ({e}); later stages will rebuild it")

    state["N_FINAL_ANALISIS"] = len(state["df_activos"])
    print(f"state: {'cached' if cached else 'built'} — df_activos {state['df_activos'].shape}")
    return state

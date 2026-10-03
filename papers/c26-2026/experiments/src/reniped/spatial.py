# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Spatial layer (n = 26): geometry, weights, global/EB Moran, LISA and Gi* with FDR (Section 4.4).

p-value convention
------------------
* Global Moran: full permutation (esda.Moran, numpy generator); two-sided p = min(1, 2·p_sim).
* Local statistics (binary Gi* and LISA): p from EXACT CONDITIONAL RANDOMIZATION
  (Anselin, 1995). For each unit i, y_i is fixed and every subset of k_i neighbours drawn
  from the remaining n−1 values is considered. With binary (Gi*) or row-standardized (LISA)
  weights, both statistics are monotone functions of the sum of the neighbouring values, so
  they share the same conditional randomization distribution:
      p_superior = #{S >= S_obs} / N,   p_inferior = #{S <= S_obs} / N,
      p_plegado  = min(p_superior, p_inferior),  p_bilateral = min(1, 2·p_plegado),
  with N = C(n−1, k_i) and the observed configuration included in the count.
  If N exceeds `max_enum`, Monte Carlo with numpy.random.Generator(PCG64) is used and
  p = (#{S_sim >= S_obs} + 1) / (B + 1) in each tail.
  This removes the dependence on the esda version, on numba and on the number of CPUs
  (esda 2.9 with numba returned p = 0.0002 for a unit whose exact p is 0.08).
* With a single neighbour (k = 1), N = 25 and the smallest attainable two-sided p is
  2/25 = 0.08: those units cannot be significant at 5%. This is reported in the column
  `p_bilateral_min_alcanzable`.
"""
import warnings
from math import comb

import numpy as np
import pandas as pd

import esda
import geopandas as gpd
from libpysal.weights import Queen, W
from statsmodels.stats.multitest import multipletests

EARTH_RADIUS_KM = 6371.0088
MAX_ENUM = 1_000_000
MC_DRAWS = 99_999
_COMBOS_CACHE = {}


def two_sided(p_sim):
    return np.minimum(1.0, 2.0 * np.asarray(p_sim, float))


def unit_key_from_province(idpr, prefix_to_unit):
    idpr = str(idpr).zfill(4)
    if idpr == "1501":
        return "LIMA METROPOLITANA"
    if idpr.startswith("15"):
        return "REGION LIMA"
    return prefix_to_unit[idpr[:2]]


def load_units_geometry(path, pop_long, prov_code_field, crs_metric):
    """Dissolve provinces into the 26 units and return (units, audit of the layer)."""
    prov = gpd.read_file(path)
    if prov.crs is None:
        raise ValueError("La geometría no declara CRS")
    audit = {"provincias_en_capa": int(len(prov)), "crs_original": str(prov.crs),
             "vertices_totales": int(sum(len(g.exterior.coords) if g.geom_type == "Polygon"
                                         else sum(len(p.exterior.coords) for p in g.geoms)
                                         for g in prov.geometry)),
             "geometrias_invalidas_originales": int((~prov.is_valid).sum())}
    reglas = pop_long.drop_duplicates("DPTO_KEY")[["DPTO_KEY", "REGLA_UBIGEO"]]
    prefix_to_unit = {r.REGLA_UBIGEO[:2]: r.DPTO_KEY for r in reglas.itertuples()
                      if r.REGLA_UBIGEO.endswith("0000")}
    prov["DPTO_KEY"] = [unit_key_from_province(c, prefix_to_unit) for c in prov[prov_code_field]]
    units = prov.dissolve(by="DPTO_KEY", as_index=False)[["DPTO_KEY", "geometry"]]
    units = units.to_crs(crs_metric)
    units["geometry"] = units.geometry.make_valid()
    expected = set(pop_long["DPTO_KEY"])
    if set(units["DPTO_KEY"]) != expected:
        raise ValueError(f"Unidades geométricas no coinciden: faltan "
                         f"{sorted(expected - set(units.DPTO_KEY))}, sobran "
                         f"{sorted(set(units.DPTO_KEY) - expected)}")
    units["AREA_KM2"] = units.geometry.area / 1e6
    rp = units.geometry.representative_point()
    ll = gpd.GeoSeries(rp, crs=crs_metric).to_crs("EPSG:4326")
    units["LON"], units["LAT"] = ll.x.values, ll.y.values
    audit["unidades"] = int(len(units))
    audit["punto_de_referencia_knn"] = "representative_point() calculado en " + crs_metric
    return units.sort_values("DPTO_KEY").reset_index(drop=True), audit


def haversine_matrix(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def build_weights(units, kind, k=4):
    """queen: polygon contiguity. knn_geodesico: k nearest neighbours by haversine distance."""
    if kind == "queen":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            w = Queen.from_dataframe(units, use_index=False)
    elif kind == "knn_geodesico":
        d = haversine_matrix(units["LAT"].to_numpy(), units["LON"].to_numpy())
        np.fill_diagonal(d, np.inf)
        neigh = {i: [int(j) for j in np.argsort(d[i])[:k]] for i in range(len(units))}
        w = W(neigh, silence_warnings=True)
    else:
        raise ValueError(kind)
    if w.islands:
        raise ValueError(f"Unidades sin vecinos ({kind}): "
                         f"{[units.DPTO_KEY.iloc[i] for i in w.islands]}")
    w.transform = "r"
    return w


def neighbours_table(units, w):
    names = units["DPTO_KEY"].tolist()
    return pd.DataFrame({"DPTO_KEY": names,
                         "N_VECINOS": [len(w.neighbors[i]) for i in range(len(names))],
                         "VECINOS": ["; ".join(names[j] for j in w.neighbors[i])
                                     for i in range(len(names))]})


def global_moran(y, w, permutations, seed):
    """Global Moran's I with permutation inference and two-sided p."""
    np.random.seed(seed)
    m = esda.Moran(np.asarray(y, float), w, transformation="r", permutations=permutations)
    return {"I": float(m.I), "E_I": float(m.EI), "z_perm": float(m.z_sim),
            "p_sim_plegado": float(m.p_sim), "p_bilateral": float(two_sided(m.p_sim)),
            "p_normal_bilateral": float(m.p_norm)}


def eb_moran_rate(events, base, w, permutations, seed):
    """Empirical-Bayes Moran's I for rates (Assunção and Reis), robust to small populations."""
    np.random.seed(seed)
    m = esda.Moran_Rate(np.asarray(events, float), np.asarray(base, float), w,
                        adjusted=True, transformation="r", permutations=permutations)
    return {"I": float(m.I), "E_I": float(m.EI), "z_perm": float(m.z_sim),
            "p_sim_plegado": float(m.p_sim), "p_bilateral": float(two_sided(m.p_sim)),
            "p_normal_bilateral": None}


def leave_one_out_moran(units, y, kind, permutations, seed, k=4):
    """Global Moran's I recomputed after removing each territory in turn (influence check)."""
    rows = []
    for i, name in enumerate(units["DPTO_KEY"]):
        keep = np.arange(len(units)) != i
        sub = units.loc[keep].reset_index(drop=True)
        try:
            w = build_weights(sub, kind, k)
            rows.append({"EXCLUIDA": name, **global_moran(np.asarray(y)[keep], w,
                                                          permutations, seed), "nota": ""})
        except ValueError as e:
            rows.append({"EXCLUIDA": name, "I": None, "E_I": None, "z_perm": None,
                         "p_sim_plegado": None, "p_bilateral": None,
                         "p_normal_bilateral": None, "nota": str(e)[:160]})
    return pd.DataFrame(rows)


def _combinations_index(m, k):
    """Matrix (C(m,k) × k) with every subset of size k of the indices 0..m-1 (cached)."""
    key = (m, k)
    if key not in _COMBOS_CACHE:
        from itertools import combinations
        _COMBOS_CACHE[key] = np.fromiter(
            (j for c in combinations(range(m), k) for j in c), dtype=np.int16,
            count=comb(m, k) * k).reshape(-1, k)
    return _COMBOS_CACHE[key]


def conditional_randomization_p(y, neighbors, seed=42, max_enum=MAX_ENUM, draws=MC_DRAWS):
    """Local p-values by conditional randomization (exact if C(n−1,k) <= max_enum).

    `neighbors` is a dict {i: [j, ...]} that does not include i. Returns a DataFrame by unit
    with k, N, method, p_superior, p_inferior, p_plegado, p_bilateral and the smallest
    attainable two-sided p.
    """
    y = np.asarray(y, float)
    n = len(y)
    rows = []
    for i in range(n):
        nb = list(neighbors[i])
        k = len(nb)
        others = np.delete(y, i)
        s_obs = float(y[nb].sum())
        tol = 1e-9 * max(1.0, abs(s_obs))
        n_conf = comb(n - 1, k)
        if n_conf <= max_enum:
            sums = others[_combinations_index(n - 1, k)].sum(axis=1)
            up = float((sums >= s_obs - tol).mean())
            lo = float((sums <= s_obs + tol).mean())
            method, pmin = "exacto", min(1.0, 2.0 / n_conf)
        else:
            rng = np.random.default_rng(seed + i)
            idx = np.argsort(rng.random((draws, n - 1)), axis=1)[:, :k]
            sums = others[idx].sum(axis=1)
            up = float(((sums >= s_obs - tol).sum() + 1) / (draws + 1))
            lo = float(((sums <= s_obs + tol).sum() + 1) / (draws + 1))
            method, pmin = f"monte_carlo_B{draws}", min(1.0, 2.0 / (draws + 1))
        folded = min(up, lo)
        rows.append({"k": k, "N_configuraciones": n_conf, "metodo_p": method,
                     "p_superior": up, "p_inferior": lo, "p_plegado": folded,
                     "p_bilateral": min(1.0, 2.0 * folded),
                     "p_bilateral_min_alcanzable": pmin})
    return pd.DataFrame(rows)


def local_statistics(units, y, w_row, seed, alpha):
    """Gi* (binary, star) and LISA with exact conditional-randomization p and FDR (BH)."""
    names = units["DPTO_KEY"].to_numpy()
    y = np.asarray(y, float)
    lisa = esda.Moran_Local(y, w_row, transformation="r", permutations=0)
    w_bin = W(w_row.neighbors, id_order=w_row.id_order, silence_warnings=True)
    gi = esda.G_Local(y, w_bin, transform="B", star=True, permutations=0)
    cr = conditional_randomization_p(y, w_row.neighbors, seed)
    q = multipletests(cr["p_bilateral"], alpha=alpha, method="fdr_bh")[1]
    # v3.3.2: Benjamini-Yekutieli sensitivity (valid under any dependence between tests)
    q_by = multipletests(cr["p_bilateral"], alpha=alpha, method="fdr_by")[1]
    quad = {1: "Alto-Alto", 2: "Bajo-Alto", 3: "Bajo-Bajo", 4: "Alto-Bajo"}
    out = pd.DataFrame({
        "DPTO_KEY": names, "VALOR": y, "k_vecinos": cr["k"],
        "N_configuraciones": cr["N_configuraciones"], "metodo_p": cr["metodo_p"],
        "LISA_Ii": lisa.Is, "LISA_cuadrante": [quad[v] for v in lisa.q],
        "Gi_z": gi.Zs,
        "p_plegado": cr["p_plegado"], "p_bilateral": cr["p_bilateral"],
        "p_bilateral_min_alcanzable": cr["p_bilateral_min_alcanzable"], "q_FDR": q, "q_BY": q_by})
    out["LISA_clase_FDR"] = np.where(out.q_FDR < alpha, out.LISA_cuadrante, "n.s.")
    out["LISA_clase_sin_ajuste"] = np.where(out.p_bilateral < alpha, out.LISA_cuadrante, "n.s.")
    out["LISA_clase_BY"] = np.where(out.q_BY < alpha, out.LISA_cuadrante, "n.s.")
    for suf, pcol in (("FDR", "q_FDR"), ("sin_ajuste", "p_bilateral")):
        out[f"Gi_clase_{suf}"] = np.select(
            [(out[pcol] < alpha) & (out.Gi_z > 0), (out[pcol] < alpha) & (out.Gi_z < 0)],
            ["Hotspot", "Coldspot"], "n.s.")
    meta = {"gi_transform": gi.w.transform, "gi_star": True,
            "lisa_transform": lisa.w.transform,
            "p_locales": "aleatorización condicional exacta (Gi* y LISA comparten distribución)",
            "unidades_no_significables_al_5pct": out.loc[
                out.p_bilateral_min_alcanzable > alpha, "DPTO_KEY"].tolist()}
    return out.sort_values("Gi_z", ascending=False).reset_index(drop=True), meta

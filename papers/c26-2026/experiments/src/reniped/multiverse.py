# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Specification multiverse (Section 4.6, Fig. 5, Table 3B).

M1 (clustering): unit of analysis × winsorization × feature space × scaler, and for each
    combination three rules to choose K (maximum silhouette, row stability, and stability by
    units and temporal blocks): 108 specifications.
M2 (spatial): counts × exposure × period × variable × weights × p-value type × correction.

The specification of the initial (baseline) analysis is included as a reproduction anchor:
register cells, p99 winsorization, the 9 original features, robust scaler, K by silhouette
and, for the spatial part, Euclidean KNN-5 on hand-digitized centroids and one-sided upper p.
"""
import itertools
import time

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from libpysal.weights import W as PysalW
from libpysal.weights.util import full2W
from scipy.spatial.distance import cdist
from sklearn.metrics import silhouette_score
from statsmodels.stats.anova import anova_lm
from statsmodels.stats.multitest import multipletests

import esda

from .audit import identity_proxy_audit
from .clustering import bootstrap_stability, kmeans, make_scaler
from .features import build_fold_features
from .panel import build_panel, unit_rates
from .spatial import build_weights, conditional_randomization_p, two_sided

# Hand-digitized (lat, lon) centroids from the baseline notebook V1_C26_2026_FINALV2
CENTROIDES_MANUSCRITO = {
    "AMAZONAS": (-5.87, -78.09), "ANCASH": (-9.53, -77.53), "APURIMAC": (-13.64, -73.09),
    "AREQUIPA": (-15.84, -72.25), "AYACUCHO": (-13.16, -74.22), "CAJAMARCA": (-6.97, -78.61),
    "CALLAO": (-12.07, -77.12), "CUSCO": (-13.53, -71.97), "HUANCAVELICA": (-12.78, -74.97),
    "HUANUCO": (-9.93, -76.24), "ICA": (-14.06, -75.73), "JUNIN": (-11.16, -74.94),
    "LA LIBERTAD": (-7.97, -78.27), "LAMBAYEQUE": (-6.70, -79.91),
    "LIMA METROPOLITANA": (-12.05, -77.04), "REGION LIMA": (-11.30, -76.80),
    "LORETO": (-4.37, -76.13), "MADRE DE DIOS": (-12.59, -70.06), "MOQUEGUA": (-16.19, -71.34),
    "PASCO": (-10.47, -75.56), "PIURA": (-5.20, -80.62), "PUNO": (-15.84, -70.03),
    "SAN MARTIN": (-6.97, -76.36), "TACNA": (-17.60, -70.23), "TUMBES": (-3.57, -80.45),
    "UCAYALI": (-9.10, -74.00)}
SUR_ANDINO_MANUSCRITO = ["AREQUIPA", "MOQUEGUA", "TACNA", "CUSCO", "AYACUCHO"]
EDAD_ORD = {"0-5 ANOS": 0, "6-11 ANOS": 1, "12-17 ANOS": 2, "18-29 ANOS": 3,
            "30-59 ANOS": 4, "60 A MAS ANOS": 5}
COVID_PHASE = {2019: 0, 2020: 1, 2021: 1, 2022: 2, 2023: 2, 2024: 2, 2025: 3}


# ====================================================================== utilities
def winsorize_counts(df, apply):
    """p1–p99 winsorization of CANTIDAD over the whole file, as in the baseline analysis."""
    d = df.copy()
    if apply:
        lo, hi = d["CANTIDAD"].quantile(0.01), d["CANTIDAD"].quantile(0.99)
        d["CANTIDAD"] = d["CANTIDAD"].clip(lower=lo, upper=hi)
    return d


def _norm_age(s):
    import unicodedata
    return " ".join(unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore")
                    .decode().upper().split())


# ====================================================================== M1: data
def cell_features(df_w, panel_feats, pop, train_end):
    """Cell-level features (one CSV row) for the cut-off year `train_end`."""
    c = df_w[df_w["ANO"] <= train_end].copy()
    c = c.merge(pop[["DPTO_KEY", "ANO", "POBLACION"]], on=["DPTO_KEY", "ANO"], how="left",
                validate="many_to_one")
    c["LOG_TASA"] = np.log1p(c["CANTIDAD"] / c["POBLACION"] * 1e4)
    seas = c.groupby(["DPTO_KEY", "MES"])["LOG_TASA"].mean().rename("MED_EST")
    c = c.join(seas, on=["DPTO_KEY", "MES"])
    sd = (c["LOG_TASA"] - c["MED_EST"]).groupby(c["DPTO_KEY"]).std(ddof=1).rename("DE_RES")
    c = c.join(sd, on="DPTO_KEY")
    c["ANOMALIA"] = (c["LOG_TASA"] - c["MED_EST"]) / c["DE_RES"]
    ctx_cols = ["DPTO_KEY", "ANO", "MES", "NIVEL_PREV12"]
    c = c.merge(panel_feats[ctx_cols], on=["DPTO_KEY", "ANO", "MES"], how="left",
                validate="many_to_one")
    c["CAMBIO_12M"] = c["LOG_TASA"] - c["NIVEL_PREV12"]
    c["DPTO_ID"] = c["DPTO_KEY"].map(c["DPTO_KEY"].value_counts(normalize=True))  # DPTO_FREQ
    # --- the 9 features of the baseline analysis (definitions ported from V1) ---
    c["EDAD_ORD"] = c["RANGO_EDAD"].map(lambda v: EDAD_ORD.get(_norm_age(v), np.nan))
    c["MES_SEN"] = np.sin(2 * np.pi * c["MES"] / 12)
    c["MES_COS"] = np.cos(2 * np.pi * c["MES"] / 12)
    c["COVID_PHASE"] = c["ANO"].map(COVID_PHASE)
    y0, y1 = c["ANO"].min(), c["ANO"].max()
    c["TREND_INDEX"] = ((c["ANO"] - y0) * 12 + c["MES"]) / ((y1 - y0 + 1) * 12)
    lc = np.log1p(c["CANTIDAD"])
    st = lc.groupby([c["DPTO_KEY"], c["MES"]]).agg(["mean", "std"])
    mu = st["mean"].reindex(pd.MultiIndex.from_arrays([c["DPTO_KEY"], c["MES"]])).to_numpy()
    sg = st["std"].reindex(pd.MultiIndex.from_arrays([c["DPTO_KEY"], c["MES"]])).to_numpy()
    c["MONTHLY_ANOMALY"] = ((lc.to_numpy() - mu) / (np.nan_to_num(sg, nan=1.0) + 1e-6)).clip(-3, 3)
    dm = c.groupby(["DPTO_KEY", "ANO", "MES"])["CANTIDAD"].sum().rename("C_DM").reset_index()
    dm = dm.sort_values(["DPTO_KEY", "ANO", "MES"])
    dm["ROLLING_MEAN_12"] = dm.groupby("DPTO_KEY")["C_DM"].transform(
        lambda s: np.log1p(s).rolling(12, min_periods=1).mean())   # includes the current month (baseline definition)
    c = c.merge(dm[["DPTO_KEY", "ANO", "MES", "ROLLING_MEAN_12"]], on=["DPTO_KEY", "ANO", "MES"])
    c["LOG_RATE_10K"] = c["LOG_TASA"]
    c["DPTO_FREQ"] = c["DPTO_ID"]
    c["T_INDEX"] = (c["ANO"] - y0) * 12 + c["MES"]
    return c


def panel_train(panel_feats, train_end):
    p = panel_feats[panel_feats["ANO"] <= train_end].copy()
    rep = p.groupby("DPTO_KEY")["REPORTES"].sum()
    p["DPTO_ID"] = p["DPTO_KEY"].map(rep / rep.sum())    # volume share: identity proxy
    p["T_INDEX"] = (p["ANO"] - p["ANO"].min()) * 12 + p["MES"]
    return p


# ====================================================================== M1: core
def _k_table(X, meta, ks, B, seed, n_init, block, sil_n, rng):
    sil_idx = rng.choice(len(X), size=min(sil_n, len(X)), replace=False)
    rows = []
    for k in ks:
        lab = kmeans(k, seed, n_init).fit(X).labels_
        row = {"K": k, "silhouette": float(silhouette_score(X[sil_idx], lab[sil_idx]))}
        for sch in ("fila", "unidad", "bloque_temporal"):
            row[f"ari_{sch}"] = bootstrap_stability(X, meta, k, B, seed, n_init, sch, block)["ari_media"]
        rows.append(row)
    return pd.DataFrame(rows)


def _select(tab, rule, thr):
    if rule == "silhouette_max":
        return int(tab.sort_values(["silhouette", "K"], ascending=[False, True]).iloc[0]["K"])
    cols = ["ari_fila"] if rule == "estabilidad_filas" else ["ari_unidad", "ari_bloque_temporal"]
    stab = tab[cols].min(axis=1)
    ok = tab.loc[stab >= thr, "K"]
    if len(ok):
        return int(ok.min())
    return int(tab.loc[stab.idxmax(), "K"])


def run_m1(df, pop, plan, seed, log=print):
    """Clustering multiverse M1. Returns one row per specification (K, silhouette, NMI with
    territory, row and panel-aware stability, claim flags) and the per-K tables.
    This is the longest stage of the pipeline (about 25 min on a free Colab CPU)."""
    mv = plan["multiverso"]["m1"]
    train_end = plan["folds"][0]["train_end"]
    spaces_cell = dict(plan["multiverso"]["espacios_celda"])
    spaces_panel = dict(plan["multiverso"]["espacios_panel"])
    rng_master = np.random.default_rng(seed)
    rows, ktabs = [], []
    t0 = time.perf_counter()
    for wins in mv["winsorizacion"]:
        dw = winsorize_counts(df, wins)
        pw = build_panel(dw, pop, plan["datos"]["anios"], plan["huecos_documentados"])
        pf = build_fold_features(pw, train_end, train_end + 1, plan["features"]["min_prev_months"])
        data = {"panel": panel_train(pf, train_end),
                "celda": cell_features(dw, pf, pop, train_end)}
        for unidad in mv["unidad"]:
            base = data[unidad]
            spaces = spaces_panel if unidad == "panel" else spaces_cell
            for esp, feats in spaces.items():
                sub = base.dropna(subset=feats + ["DPTO_KEY"]).reset_index(drop=True)
                if unidad == "celda" and len(sub) > mv["submuestra_celdas"]:
                    idx = np.random.default_rng(seed).choice(len(sub), mv["submuestra_celdas"],
                                                             replace=False)
                    sub = sub.iloc[np.sort(idx)].reset_index(drop=True)
                for scaler in mv["escalador"]:
                    X = make_scaler(scaler).fit_transform(sub[feats].to_numpy(float))
                    tab = _k_table(X, sub[["DPTO_KEY", "T_INDEX"]], mv["ks"], mv["bootstrap_B"],
                                   seed, mv["n_init"], plan["seleccion_k"]["bloque_meses"],
                                   mv["silhouette_n"], rng_master)
                    tab = tab.assign(unidad=unidad, winsor=wins, espacio=esp, escalador=scaler)
                    ktabs.append(tab)
                    for rule in mv["reglas_k"]:
                        k = _select(tab, rule, plan["seleccion_k"]["estabilidad_min_ari"])
                        r = tab.set_index("K").loc[k]
                        lab = kmeans(k, seed, mv["n_init"]).fit(X).labels_
                        a = identity_proxy_audit(lab, sub["DPTO_KEY"].to_numpy(),
                                                 sub["ANO"].to_numpy(), mv["n_perm"], seed,
                                                 ("bloques_anuales",))
                        rows.append({
                            "unidad": unidad, "winsor": wins, "espacio": esp, "escalador": scaler,
                            "regla_k": rule, "n": int(len(X)), "K": k,
                            "silhouette": float(r["silhouette"]),
                            "ari_fila": float(r["ari_fila"]), "ari_unidad": float(r["ari_unidad"]),
                            "ari_bloque_temporal": float(r["ari_bloque_temporal"]),
                            "NMI_unidad": a["NMI_cluster_unidad"],
                            "p_NMI_bloques": a["p_perm_bloques_anuales"],
                            "fraccion_H_unidad": a["fraccion_H_asociada_a_unidad"],
                            "unidades_pureza_095": a["unidades_con_pureza_>=0.95"],
                            "es_manuscrito_original": bool(unidad == "celda" and wins and
                                                           esp == "O_manuscrito" and
                                                           scaler == "robust" and
                                                           rule == "silhouette_max")})
                    log(f"  M1 {unidad:<5} winsor={str(wins):<5} {esp:<22} {scaler:<8} "
                        f"n={len(X):>6} | {time.perf_counter() - t0:6.0f} s")
    spec = pd.DataFrame(rows)
    thr = plan["seleccion_k"]["estabilidad_min_ari"]
    spec["afirma_estructura_por_silhouette"] = spec["silhouette"] >= mv["umbral_silhouette"]
    spec["afirma_estructura_por_filas"] = spec["ari_fila"] >= thr
    spec["estructura_robusta_panel"] = spec[["ari_unidad", "ari_bloque_temporal"]].min(axis=1) >= thr
    spec["fuga_identidad"] = (spec["p_NMI_bloques"] < 0.05) & (spec["fraccion_H_unidad"] >= mv["umbral_fraccion_H"])
    return spec, pd.concat(ktabs, ignore_index=True)


# ====================================================================== M2
# Local p-values: exact conditional randomization (spatial.conditional_randomization_p).
# tipo_p "original" = folded p (one tail, like the esda p_sim used in the baseline);
# "bilateral" = min(1, 2·folded p).
def _dense_weights(units, kind):
    names = units["DPTO_KEY"].tolist()
    if kind in ("knn5_grados_manuscrito", "invdist_grados_manuscrito"):
        coords = np.array([CENTROIDES_MANUSCRITO[n] for n in names])
        D = cdist(coords, coords)
        np.fill_diagonal(D, np.inf)
        if kind == "knn5_grados_manuscrito":
            Wm = np.zeros_like(D)
            for i in range(len(names)):
                Wm[i, np.argsort(D[i])[:5]] = 1.0
        else:
            bw = np.percentile(D[D < np.inf], 50)
            Wm = np.where(D <= bw, 1.0 / (D + 1e-9), 0.0)
            np.fill_diagonal(Wm, 0)
        rs = Wm.sum(axis=1, keepdims=True)
        rs[rs == 0] = 1
        w = full2W(Wm / rs)
        w.transform = "r"
        return w
    if kind == "queen":
        return build_weights(units, "queen")
    if kind.startswith("knn") and kind.endswith("_geodesico"):
        return build_weights(units, "knn_geodesico", int(kind[3:kind.index("_")]))
    raise ValueError(kind)


def run_m2(df, pop, units, plan, seed):
    """Spatial multiverse M2: global Moran's I and local hot spots for every combination
    of counts, exposure, period, variable, weights, p-value type and correction."""
    mv = plan["multiverso"]["m2"]
    perm = plan["espacial"]["permutaciones"]
    alpha = plan["espacial"]["alpha"]
    Ws = {k: _dense_weights(units, k) for k in mv["pesos"]}
    rows = []
    for wins in mv["winsorizacion"]:
        pw = build_panel(winsorize_counts(df, wins), pop, plan["datos"]["anios"],
                         plan["huecos_documentados"])
        for per_name, yrs in mv["periodos"].items():
            r = units[["DPTO_KEY"]].merge(unit_rates(pw, yrs), on="DPTO_KEY", validate="one_to_one")
            vars_ = {"tasa_exposicion_observada": r["TASA_10K_EXPOSICION_OBSERVADA"],
                     "tasa_exposicion_total": r["TASA_10K_EXPOSICION_TOTAL"],
                     "conteo": r["REPORTES"].astype(float)}
            for var, y in vars_.items():
                y = y.to_numpy(float)
                for wn, w in Ws.items():
                    np.random.seed(seed)
                    m = esda.Moran(y, w, transformation="r", permutations=perm)
                    p_sup = float((np.sum(m.sim >= m.I) + 1) / (perm + 1))
                    wb = PysalW(w.neighbors, id_order=w.id_order, silence_warnings=True)
                    gi = esda.G_Local(y, wb, transform="B", star=True, permutations=0)
                    cr = conditional_randomization_p(y, w.neighbors, seed)
                    for ptype in mv["tipo_p"]:
                        p_glob = p_sup if ptype == "original" else float(two_sided(m.p_sim))
                        p_loc = (cr["p_plegado"] if ptype == "original"
                                 else cr["p_bilateral"]).to_numpy()
                        for corr in mv["correccion_local"]:
                            q = p_loc if corr == "ninguna" else multipletests(
                                p_loc, alpha=alpha, method="fdr_bh")[1]
                            hot = (q < alpha) & (gi.Zs > 0)
                            cold = (q < alpha) & (gi.Zs < 0)
                            names = units["DPTO_KEY"].to_numpy()
                            lima = int(np.where(names == "LIMA METROPOLITANA")[0][0])
                            rows.append({
                                "winsor": wins, "periodo": per_name, "variable": var,
                                "pesos": wn, "tipo_p": ptype, "correccion_local": corr,
                                "moran_I": float(m.I), "p_global": p_glob,
                                "moran_significativo": p_glob < alpha,
                                "n_hotspots": int(hot.sum()), "n_coldspots": int(cold.sum()),
                                "hotspots": ";".join(names[hot]),
                                "sur_andino_hotspots": int(sum(n in SUR_ANDINO_MANUSCRITO
                                                               for n in names[hot])),
                                "lima_hotspot": bool(hot[lima]),
                                "es_manuscrito_original": bool(
                                    wins and per_name == "2019_2025" and
                                    var == "tasa_exposicion_total" and
                                    wn == "knn5_grados_manuscrito" and ptype == "original" and
                                    corr == "ninguna")})
    return pd.DataFrame(rows)


# ====================================================================== summaries
def decision_importance(spec, outcome, factors):
    """Partial η² of each decision (type II ANOVA, main effects): how much of the outcome
    variance each analytical decision explains."""
    d = spec[[outcome] + factors].dropna().copy()
    for f in factors:
        d[f] = d[f].astype(str)
    use = [f for f in factors if d[f].nunique() > 1]
    model = smf.ols(f"{outcome} ~ " + " + ".join(f"C({f})" for f in use), data=d).fit()
    a = anova_lm(model, typ=2)
    ss_res = a.loc["Residual", "sum_sq"]
    out = [{"resultado": outcome, "decision": f,
            "eta2_parcial": float(a.loc[f"C({f})", "sum_sq"] / (a.loc[f"C({f})", "sum_sq"] + ss_res)),
            "F": float(a.loc[f"C({f})", "F"]), "p": float(a.loc[f"C({f})", "PR(>F)"])}
           for f in use]
    return pd.DataFrame(out).sort_values("eta2_parcial", ascending=False)


def claim_support(spec, claims, by=None):
    """Share of specifications that support each claim, overall or by decision level."""
    if by is None:
        return pd.DataFrame([{"afirmacion": c, "especificaciones": int(len(spec)),
                              "proporcion_que_la_sostiene": float(spec[c].mean())} for c in claims])
    return (spec.groupby(by)[claims].mean().reset_index()
            .melt(id_vars=by, var_name="afirmacion", value_name="proporcion_que_la_sostiene"))

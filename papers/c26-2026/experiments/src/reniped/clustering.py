# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Choice of K, bootstrap stability that respects the panel structure, and multi-algorithm
clustering (Sections 4.3 and 5.2)."""
import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN, AgglomerativeClustering, KMeans
from sklearn.metrics import (adjusted_rand_score, calinski_harabasz_score,
                             davies_bouldin_score, silhouette_score)
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler, StandardScaler

SCALERS = {"standard": StandardScaler, "robust": RobustScaler}


def make_scaler(name):
    return SCALERS[name]()


def kmeans(k, seed, n_init):
    return KMeans(n_clusters=k, n_init=n_init, random_state=seed)


def semantic_mapping(raw_labels, ref):
    """Map raw labels to semantic labels (0 = lowest mean of `ref`), so that state numbers are
    comparable across algorithms, folds and years. Noise (-1) is kept."""
    raw_labels = np.asarray(raw_labels)
    ref = np.asarray(ref, float)
    uniq = [c for c in np.unique(raw_labels) if c >= 0]
    order = sorted(uniq, key=lambda c: ref[raw_labels == c].mean())
    mapping = {int(old): new for new, old in enumerate(order)}
    mapping[-1] = -1
    return mapping


def apply_mapping(raw_labels, mapping):
    return np.array([mapping[int(c)] for c in raw_labels])


class LabeledKMeans:
    """K-means whose predictions ALWAYS use the semantic labels fixed at fit time."""

    def __init__(self, k, seed, n_init):
        self.k, self.seed, self.n_init = k, seed, n_init
        self.model_ = None
        self.mapping_ = None

    def fit(self, X, ref):
        self.model_ = kmeans(self.k, self.seed, self.n_init).fit(X)
        self.mapping_ = semantic_mapping(self.model_.labels_, ref)
        self.labels_ = apply_mapping(self.model_.labels_, self.mapping_)
        inv = {v: k for k, v in self.mapping_.items() if k >= 0}
        self.cluster_centers_ = self.model_.cluster_centers_[[inv[i] for i in range(self.k)]]
        return self

    def predict(self, X):
        return apply_mapping(self.model_.predict(X), self.mapping_)


def internal_indices(X, labels):
    mask = np.asarray(labels) >= 0
    n_cl = len(np.unique(np.asarray(labels)[mask]))
    out = {"cobertura_pct": float(100 * mask.mean())}
    if n_cl < 2:
        out.update(silhouette=None, davies_bouldin=None, calinski_harabasz=None)
        return out
    out.update(silhouette=float(silhouette_score(X[mask], labels[mask])),
               davies_bouldin=float(davies_bouldin_score(X[mask], labels[mask])),
               calinski_harabasz=float(calinski_harabasz_score(X[mask], labels[mask])))
    return out


def _log_wk(X, k, seed, n_init):
    if k == 1:
        return np.log(((X - X.mean(axis=0)) ** 2).sum())
    return np.log(kmeans(k, seed, n_init).fit(X).inertia_)


def gap_statistic(X, ks, B, seed, n_init):
    """Gap statistic (Tibshirani, Walther and Hastie, 2001) with a uniform reference in the
    principal-component box. Including K = 1 tests whether there is any cluster structure at all."""
    rng = np.random.default_rng(seed)
    mu = X.mean(axis=0)
    _, _, vt = np.linalg.svd(X - mu, full_matrices=False)
    Z = (X - mu) @ vt.T
    lo, hi = Z.min(axis=0), Z.max(axis=0)
    refs = [rng.uniform(lo, hi, size=Z.shape) @ vt + mu for _ in range(B)]
    rows = []
    for k in ks:
        lw = _log_wk(X, k, seed, n_init)
        ref = np.array([_log_wk(Xr, k, seed, n_init) for Xr in refs])
        rows.append({"K": k, "gap": float(ref.mean() - lw),
                     "s_k": float(ref.std(ddof=0) * np.sqrt(1 + 1 / B))})
    return pd.DataFrame(rows)


def tibshirani_k(gap_df, k_from):
    g = gap_df.set_index("K")
    for k in sorted(g.index):
        if k < k_from or k + 1 not in g.index:
            continue
        if g.loc[k, "gap"] >= g.loc[k + 1, "gap"] - g.loc[k + 1, "s_k"]:
            return int(k)
    return None


def _bootstrap_indices(meta, scheme, rng, block):
    n = len(meta)
    if scheme == "fila":
        return rng.integers(0, n, n)
    if scheme == "unidad":
        units = meta["DPTO_KEY"].unique()
        pick = rng.choice(units, size=len(units), replace=True)
        groups = meta.groupby("DPTO_KEY").indices
        return np.concatenate([groups[u] for u in pick])
    if scheme == "bloque_temporal":
        months = np.sort(meta["T_INDEX"].unique())
        n_blocks = int(np.ceil(len(months) / block))
        starts = rng.integers(0, max(1, len(months) - block + 1), n_blocks)
        chosen = np.concatenate([months[s:s + block] for s in starts])
        groups = meta.groupby("T_INDEX").indices
        return np.concatenate([groups[m] for m in chosen if m in groups])
    raise ValueError(scheme)


def bootstrap_stability(X, meta, k, B, seed, n_init, scheme, block=12):
    """ARI between the reference partition and partitions from models fitted on resamples.

    scheme = "fila" (i.i.d. rows), "unidad" (whole territories) or "bloque_temporal"
    (blocks of consecutive months). Row resampling ignores panel dependence and overstates
    stability; the unit and temporal-block schemes are the ones used to choose K."""
    rng = np.random.default_rng(seed)
    ref = kmeans(k, seed, n_init).fit(X).labels_
    aris = []
    for b in range(B):
        idx = _bootstrap_indices(meta, scheme, rng, block)
        lab = kmeans(k, seed + b + 1, n_init).fit(X[idx]).predict(X)
        aris.append(adjusted_rand_score(ref, lab))
    aris = np.asarray(aris)
    return {"ari_media": float(aris.mean()), "ari_de": float(aris.std(ddof=1)),
            "ari_p2_5": float(np.percentile(aris, 2.5)),
            "ari_p97_5": float(np.percentile(aris, 97.5))}


def k_selection_table(X, meta, cfg, seed):
    """Internal indices, gap statistic and bootstrap stability for every candidate K."""
    ks = list(range(cfg["k_min"], cfg["k_max"] + 1))
    gap = gap_statistic(X, [1] + ks + [cfg["k_max"] + 1], cfg["gap_B"], seed, cfg["n_init"])
    rows = []
    for k in ks:
        lab = kmeans(k, seed, cfg["n_init"]).fit(X).labels_
        row = {"K": k, **{kk: v for kk, v in internal_indices(X, lab).items()
                          if kk != "cobertura_pct"}}
        for sch in cfg["esquemas_bootstrap"]:
            st = bootstrap_stability(X, meta, k, cfg["bootstrap_B"], seed, cfg["n_init"],
                                     sch, cfg["bloque_meses"])
            row.update({f"{m}_{sch}": v for m, v in st.items()})
        rows.append(row)
    tab = pd.DataFrame(rows).merge(gap, on="K", how="left")
    return tab, gap


def select_k(tab, gap, cfg):
    """Pre-specified rule: among K whose minimum stability (unit and temporal-block ARI)
    reaches the threshold, take Tibshirani's K if it qualifies, otherwise the highest
    silhouette. Also reports whether the gap statistic supports any structure (K > 1)."""
    cols = [f"ari_media_{s}" for s in cfg["esquemas_para_regla"]]
    tab = tab.assign(ESTABILIDAD_MIN=tab[cols].min(axis=1))
    cand = tab[tab["ESTABILIDAD_MIN"] >= cfg["estabilidad_min_ari"]]
    k_tib = tibshirani_k(gap, k_from=cfg["k_min"])
    k_tib_1 = tibshirani_k(gap, k_from=1)
    if k_tib is not None and k_tib in set(cand["K"]):
        k, why = k_tib, "Tibshirani (K>=2) dentro de los candidatos estables"
    elif len(cand):
        best = cand.sort_values(["silhouette", "K"], ascending=[False, True]).iloc[0]
        k, why = int(best["K"]), "Mayor silhouette entre candidatos estables"
    else:
        best = tab.sort_values(["ESTABILIDAD_MIN", "K"], ascending=[False, True]).iloc[0]
        k, why = int(best["K"]), "Ningún K alcanzó el umbral; se eligió el de mayor estabilidad mínima"
    return {"K_elegido": int(k), "motivo": why,
            "K_tibshirani_desde_2": k_tib, "K_tibshirani_desde_1": k_tib_1,
            "evidencia_agrupabilidad_gap": bool(k_tib_1 is not None and k_tib_1 > 1),
            "candidatos_estables": [int(x) for x in cand["K"]]}, tab


def fit_algorithms(X, ref, k, cfg, seed):
    """Semantic labels (0 = lowest `ref`) for K-means, Ward and GMM at the same K, plus
    HDBSCAN (density-based: the number of clusters is not fixed and noise is allowed).

    HDBSCAN is taken from scikit-learn (>= 1.3), not from the standalone hdbscan package."""
    lk = LabeledKMeans(k, seed, cfg["n_init"]).fit(X, ref)
    raw = {
        "Ward": AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X),
        "GMM": GaussianMixture(n_components=k, covariance_type="full",
                               n_init=cfg["gmm_n_init"], random_state=seed).fit(X).predict(X),
        "HDBSCAN": HDBSCAN(min_cluster_size=max(5, int(cfg["hdbscan_min_frac"] * len(X))),
                           min_samples=cfg["hdbscan_min_samples"], copy=True).fit_predict(X),
    }
    labels = {"KMeans": lk.labels_}
    labels.update({n: apply_mapping(l, semantic_mapping(l, ref)) for n, l in raw.items()})
    rows = []
    for name, lab in labels.items():
        mask = lab >= 0
        rows.append({"algoritmo": name, "K_resultante": int(len(set(lab[mask]))),
                     "ruido_pct": float(100 * (~mask).mean()),
                     **internal_indices(X, lab),
                     "ARI_vs_KMeans_todas": float(adjusted_rand_score(labels["KMeans"], lab)),
                     "ARI_vs_KMeans_sin_ruido": float(adjusted_rand_score(
                         labels["KMeans"][mask], lab[mask])) if mask.sum() > 1 else None})
    tab = pd.DataFrame(rows)
    tab["nota"] = np.where(tab["ruido_pct"] > 0,
                           "Índices internos calculados solo sobre la cobertura (sin ruido); "
                           "no comparables con algoritmos de cobertura completa.", "")
    return labels, lk, tab

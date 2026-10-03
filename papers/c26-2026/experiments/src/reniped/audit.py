# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Audit of territorial-identity leakage (Section 4.6): does a clustering recover the states of the
phenomenon or merely the identity of each territory? Null models respect the panel structure."""
import numpy as np
import pandas as pd
from scipy.stats import entropy
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score


def _entropy_terms(labels, unit):
    ct = pd.crosstab(unit, labels)
    n = ct.values.sum()
    h_c = float(entropy(ct.sum(axis=0) / n, base=2))
    h_c_u = float(sum((ct.loc[u].sum() / n) * entropy(ct.loc[u] / ct.loc[u].sum(), base=2)
                      for u in ct.index))
    purity = ct.max(axis=1) / ct.sum(axis=1)
    return h_c, h_c_u, purity


def _null_nmi(labels, unit, year, scheme, n_perm, rng):
    """Null distribution of NMI(cluster, territory).

    filas           : permutes labels across all rows (ignores temporal dependence).
    bloques_anuales : within each year, randomly reassigns territory identities (the same
                      permutation for the 12 months), preserving the within-year sequence of
                      every series. This is the reference null used in the manuscript.
    """
    null = np.empty(n_perm)
    units = np.unique(unit)
    for b in range(n_perm):
        if scheme == "filas":
            null[b] = normalized_mutual_info_score(unit, rng.permutation(labels))
        elif scheme == "bloques_anuales":
            new_unit = np.empty(len(unit), dtype=object)
            for y in np.unique(year):
                m = year == y
                perm = dict(zip(units, rng.permutation(units)))
                new_unit[m] = [perm[u] for u in unit[m]]
            null[b] = normalized_mutual_info_score(new_unit.astype(str), labels)
        else:
            raise ValueError(scheme)
    return null


def identity_proxy_audit(labels, unit, year, n_perm=999, seed=42,
                         schemes=("bloques_anuales", "filas")):
    """NMI and ARI between clusters and territories, entropy decomposition, purity and
    permutation p-values. A high NMI above the within-year null indicates that the clusters
    encode territorial identity rather than states shared across territories (Table 3A)."""
    labels = np.asarray(labels)
    unit = np.asarray(unit).astype(str)
    year = np.asarray(year)
    h_c, h_c_u, purity = _entropy_terms(labels, unit)
    nmi = float(normalized_mutual_info_score(unit, labels))
    out = {"NMI_cluster_unidad": nmi,
           "ARI_cluster_unidad": float(adjusted_rand_score(unit, labels)),
           "H_cluster_bits": h_c, "H_cluster_dado_unidad_bits": h_c_u,
           "fraccion_H_asociada_a_unidad": float(1 - h_c_u / h_c) if h_c > 0 else None,
           "unidades_con_pureza_>=0.95": int((purity >= 0.95).sum()),
           "unidades_totales": int(len(purity)), "pureza_media": float(purity.mean())}
    rng = np.random.default_rng(seed)
    for sch in schemes:
        null = _null_nmi(labels, unit, year, sch, n_perm, rng)
        out[f"NMI_nulo_p95_{sch}"] = float(np.percentile(null, 95))
        out[f"p_perm_{sch}"] = float((np.sum(null >= nmi) + 1) / (n_perm + 1))
    return out


def unit_cluster_table(unit, labels):
    """Share of each territory's months in every cluster, modal cluster and purity."""
    ct = pd.crosstab(pd.Series(unit, name="DPTO_KEY"), pd.Series(labels, name="CLUSTER"),
                     normalize="index")
    ct.columns = [f"PROP_C{c}" for c in ct.columns]
    ct["CLUSTER_MODAL"] = ct.values.argmax(axis=1)
    ct["PUREZA"] = ct.filter(like="PROP_").max(axis=1)
    return ct.reset_index()

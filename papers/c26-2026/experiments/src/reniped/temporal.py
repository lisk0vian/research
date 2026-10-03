# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Temporal transfer (Section 4.5): the train model assigns states in a later year."""
import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon
from sklearn.metrics import adjusted_rand_score

from .clustering import LabeledKMeans, internal_indices


def evaluate_year(model, X_eval, ref_eval, train_labels, seed, n_init):
    """`model` is a LabeledKMeans fitted on train; semantic labels are returned.

    Compares the transferred labels with a refit on the evaluation year (ARI) and the state
    shares between years (Jensen-Shannon distance)."""
    assigned = model.predict(X_eval)
    refit = LabeledKMeans(model.k, seed, n_init).fit(X_eval, ref_eval).labels_
    k = model.k
    p_train = np.bincount(train_labels, minlength=k) / len(train_labels)
    p_eval = np.bincount(assigned, minlength=k) / len(assigned)
    js_dist = float(jensenshannon(p_train, p_eval, base=2))
    return assigned, {
        "n_eval": int(len(X_eval)),
        "ARI_transferido_vs_reajustado": float(adjusted_rand_score(assigned, refit)),
        "concordancia_etiquetas_semanticas": float((assigned == refit).mean()),
        "indices_internos_eval": internal_indices(X_eval, assigned),
        "proporciones_train": np.round(p_train, 4).tolist(),
        "proporciones_eval": np.round(p_eval, 4).tolist(),
        "JS_distancia_base2": js_dist,
        "JS_divergencia_bits": js_dist ** 2,
        "nota": "El ARI mide acuerdo entre la partición transferida y una reajustada en el "
                "año evaluado; no es exactitud predictiva de desapariciones.",
    }


def yearly_shares(df, label_col="CLUSTER"):
    t = pd.crosstab(df["ANO"], df[label_col], normalize="index")
    t.columns = [f"PROP_C{c}" for c in t.columns]
    return t.reset_index()

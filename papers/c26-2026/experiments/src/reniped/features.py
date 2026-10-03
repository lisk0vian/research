# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Panel features computed only with the information available in each fold (no leakage)."""
import numpy as np
import pandas as pd


def build_fold_features(panel, train_end_year, eval_year, min_prev_months=6):
    """Features of Table 1 for one temporal fold.

    NIVEL_PREV12 : mean LOG_TASA over the previous 12 months (current month excluded),
                   requiring at least `min_prev_months` observed months (prior level).
    CAMBIO_12M   : LOG_TASA − NIVEL_PREV12 (change relative to the prior level).
    ANOMALIA     : (LOG_TASA − territory×month seasonal mean) / residual SD of the territory,
                   with mean and SD estimated only with years <= train_end_year.
    """
    p = panel.sort_values(["DPTO_KEY", "FECHA"]).copy()
    g = p.groupby("DPTO_KEY")["LOG_TASA"]
    p["NIVEL_PREV12"] = g.transform(
        lambda s: s.shift(1).rolling(12, min_periods=min_prev_months).mean())
    p["N_PREV12_OBS"] = g.transform(lambda s: s.shift(1).rolling(12, min_periods=1).count())
    p["HISTORIA_COMPLETA_12M"] = p["N_PREV12_OBS"] >= 12
    p["CAMBIO_12M"] = p["LOG_TASA"] - p["NIVEL_PREV12"]

    train = p["ANO"] <= train_end_year
    seas = (p.loc[train].groupby(["DPTO_KEY", "MES"])["LOG_TASA"]
            .agg(MEDIA_ESTACIONAL="mean", N_ESTACIONAL="count").reset_index())
    p = p.merge(seas, on=["DPTO_KEY", "MES"], how="left", validate="many_to_one")
    resid = p["LOG_TASA"] - p["MEDIA_ESTACIONAL"]
    sd = resid[p["ANO"] <= train_end_year].groupby(
        p.loc[p["ANO"] <= train_end_year, "DPTO_KEY"]).std(ddof=1).rename("DE_RESIDUAL")
    p = p.merge(sd, left_on="DPTO_KEY", right_index=True, how="left")
    if p["DE_RESIDUAL"].isna().any() or (p["DE_RESIDUAL"] <= 0).any():
        raise ValueError("DE residual nula o faltante en algún departamento")
    p["ANOMALIA"] = resid / p["DE_RESIDUAL"]

    p["SPLIT"] = np.select([p["ANO"] <= train_end_year, p["ANO"] == eval_year],
                           ["TRAIN", "EVAL"], "FUERA")
    p["TRAIN_END"] = train_end_year
    p["EVAL_YEAR"] = eval_year
    return p.sort_values(["DPTO_KEY", "FECHA"]).reset_index(drop=True)


def model_matrix(fold_df, features, split):
    """Rows of the split with every feature observed (no imputation)."""
    sub = fold_df[fold_df["SPLIT"] == split]
    ok = sub[features].notna().all(axis=1)
    return sub.loc[ok].reset_index(drop=True), int((~ok).sum())


def design_diagnostics(X, features):
    """Rank and condition number of the standardized design matrix."""
    X = np.asarray(X, float)
    s = np.linalg.svd(X - X.mean(axis=0), compute_uv=False)
    rank = int(np.linalg.matrix_rank(X - X.mean(axis=0)))
    return {"variables": list(features), "rango": rank, "rango_completo": rank == len(features),
            "numero_condicion": float(s.max() / s.min()) if s.min() > 0 else float("inf"),
            "correlaciones": np.round(np.corrcoef(X, rowvar=False), 4).tolist()}

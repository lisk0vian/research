# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Priority territories (Sections 4.1 and 5.1; Figs. 2 and 3).

For each territory u the rate ratio RR_u = rate_u / rate of the rest of the country (the
other 25 territories) is computed with the reports and person-years of the same period. The
comparison is against the rest and not against the national total because a large territory
(Lima Metropolitana holds a third of the reports) weighs on the national mean and artificially
pulls its own RR towards 1. Uncertainty is estimated with a moving-block bootstrap of 12
consecutive months (Künsch, 1989): each replicate draws the same months for every territory,
so the correlation between territories is preserved, and the rate of the rest is recomputed
with those months. 95% percentile interval; two-sided p-value for RR = 1; false discovery
rate control (Benjamini-Hochberg) across the 26 territories.

Classes: 'superior' (q < alpha and RR > 1), 'inferior' (q < alpha and RR < 1) or
'no_distinguible'. The number of years in which the territory's annual rate exceeded that of
the rest of the country is also counted.
"""
import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests


def _matrices(panel, years, exposure):
    p = panel[panel["ANO"].isin(years)].copy()
    p["T"] = (p["ANO"] - min(years)) * 12 + p["MES"] - 1
    units = sorted(p["DPTO_KEY"].unique())
    n_months = len(years) * 12
    idx = {u: i for i, u in enumerate(units)}
    R = np.zeros((len(units), n_months))
    E = np.zeros((len(units), n_months))
    obs = p["COBERTURA"].eq("OBSERVADO").to_numpy()
    ui = p["DPTO_KEY"].map(idx).to_numpy()
    ti = p["T"].to_numpy()
    R[ui, ti] = np.nan_to_num(p["REPORTES"].to_numpy(float))
    pm = p["PERSONAS_MES"].to_numpy(float)
    if exposure == "observada":
        E[ui, ti] = np.where(obs, pm, 0.0)
    elif exposure == "total":
        E[ui, ti] = pm
    else:
        raise ValueError(exposure)
    return units, R, E


def priority_table(panel, years, exposure="observada", B=9999, block=12, seed=42, alpha=0.05):
    """Table by territory with rate, RR versus the rest of the country, 95% CI, p, q and class."""
    units, R, E = _matrices(panel, years, exposure)
    n_units, n_months = R.shape
    rate = R.sum(1) / E.sum(1) * 1e4
    nat = R.sum() / E.sum() * 1e4
    rest = (R.sum() - R.sum(1)) / (E.sum() - E.sum(1)) * 1e4
    rr = rate / rest

    # Sums over every block of 12 consecutive months, one block per possible start month
    starts_possible = n_months - block + 1
    cR = np.concatenate([np.zeros((n_units, 1)), np.cumsum(R, 1)], 1)
    cE = np.concatenate([np.zeros((n_units, 1)), np.cumsum(E, 1)], 1)
    bR = cR[:, block:block + starts_possible] - cR[:, :starts_possible]
    bE = cE[:, block:block + starts_possible] - cE[:, :starts_possible]
    n_blocks = int(np.ceil(n_months / block))
    rng = np.random.default_rng(seed)
    S = rng.integers(0, starts_possible, size=(B, n_blocks))
    Rs = bR[:, S].sum(-1)            # (units, B)
    Es = bE[:, S].sum(-1)
    rate_b = Rs / Es * 1e4
    rest_b = (Rs.sum(0) - Rs) / (Es.sum(0) - Es) * 1e4
    rr_b = rate_b / rest_b

    lo_rr, hi_rr = np.percentile(rr_b, [2.5, 97.5], axis=1)
    lo_rt, hi_rt = np.percentile(rate_b, [2.5, 97.5], axis=1)
    p_hi = ((rr_b <= 1).sum(1) + 1) / (B + 1)
    p_lo = ((rr_b >= 1).sum(1) + 1) / (B + 1)
    p = np.minimum(1.0, 2 * np.minimum(p_hi, p_lo))
    q = multipletests(p, alpha=alpha, method="fdr_bh")[1]
    clase = np.where((q < alpha) & (rr > 1), "superior",
                     np.where((q < alpha) & (rr < 1), "inferior", "no_distinguible"))

    # Years in which the territory's annual rate exceeded the rate of the rest of the country
    yearly = []
    for k, y in enumerate(years):
        sl = slice(k * 12, (k + 1) * 12)
        ry = R[:, sl].sum(1) / E[:, sl].sum(1)
        resty = (R[:, sl].sum() - R[:, sl].sum(1)) / (E[:, sl].sum() - E[:, sl].sum(1))
        yearly.append(ry > resty)
    years_above = np.vstack(yearly).sum(0)

    out = pd.DataFrame({
        "DPTO_KEY": units, "REPORTES": R.sum(1).astype(int),
        "CUOTA_REPORTES_PCT": 100 * R.sum(1) / R.sum(),
        "TASA_10K": rate, "TASA_IC95_INF": lo_rt, "TASA_IC95_SUP": hi_rt,
        "TASA_RESTO_10K": rest, "RAZON_VS_NACIONAL": rate / nat,
        "RR_VS_RESTO": rr, "RR_IC95_INF": lo_rr, "RR_IC95_SUP": hi_rr,
        "p_bilateral": p, "q_FDR": q, "CLASE": clase,
        "ANIOS_SOBRE_RESTO": years_above, "ANIOS_TOTAL": len(years)})
    out["PUESTO_TASA"] = out["TASA_10K"].rank(ascending=False, method="min").astype(int)
    out["PUESTO_VOLUMEN"] = out["REPORTES"].rank(ascending=False, method="min").astype(int)
    meta = {"tasa_nacional_10k": float(nat), "referencia_RR": "resto del país (25 territorios)",
            "exposicion": exposure,
            "periodo": f"{min(years)}-{max(years)}", "B": B, "bloque_meses": block,
            "bloques_por_replica": n_blocks, "alpha": alpha}
    return out.sort_values("TASA_10K", ascending=False).reset_index(drop=True), meta


def priority_summary(tables):
    """Agreement of the class between the main analysis and the sensitivity analyses."""
    main = tables["principal"].set_index("DPTO_KEY")["CLASE"]
    out = {}
    for name, t in tables.items():
        c = t.set_index("DPTO_KEY")["CLASE"].reindex(main.index)
        out[name] = {"superior": sorted(c[c == "superior"].index.tolist()),
                     "inferior": sorted(c[c == "inferior"].index.tolist()),
                     "coincidencia_con_principal": float((c == main).mean())}
    return out


def annual_rr_table(panel, years, exposure="observada"):
    """Annual rate of each territory and its ratio versus the rest of the country that year.

    Descriptive (no intervals): shows whether the full-period classification repeats year
    after year (Fig. 3). Long format: one row per territory and year.
    """
    units, R, E = _matrices(panel, years, exposure)
    rows = []
    for k, y in enumerate(years):
        sl = slice(k * 12, (k + 1) * 12)
        r_u, e_u = R[:, sl].sum(1), E[:, sl].sum(1)
        rate = r_u / e_u * 1e4
        rest = (r_u.sum() - r_u) / (e_u.sum() - e_u) * 1e4
        for i, u in enumerate(units):
            rows.append({"DPTO_KEY": u, "ANO": y, "REPORTES": int(r_u[i]), "TASA_10K": rate[i],
                         "TASA_RESTO_10K": rest[i], "RR_VS_RESTO": rate[i] / rest[i]})
    return pd.DataFrame(rows)

"""Territory-month panel (26 × 84) with a complete calendar, coverage flags and two exposures."""
import numpy as np
import pandas as pd


def build_panel(df, pop_long, years, coverage_gaps_documented=None):
    """Aggregate reports to territory-month, add INEI population and coverage flags.

    Months without source rows are treated as missing (coverage gaps), never as zero,
    and are excluded from the observed exposure."""
    units = sorted(df["DPTO_KEY"].unique())
    missing_pop = set(units) - set(pop_long["DPTO_KEY"])
    if missing_pop:
        raise ValueError(f"Unidades sin población: {sorted(missing_pop)}")

    grid = pd.MultiIndex.from_product([units, list(years), range(1, 13)],
                                      names=["DPTO_KEY", "ANO", "MES"])
    obs = df.groupby(["DPTO_KEY", "ANO", "MES"])["CANTIDAD"].sum()
    panel = obs.reindex(grid).rename("REPORTES").reset_index()
    panel["TIENE_FILAS_FUENTE"] = panel["REPORTES"].notna()   # no source rows = missing, not zero
    panel = panel.merge(pop_long[["DPTO_KEY", "ANO", "POBLACION"]],
                        on=["DPTO_KEY", "ANO"], how="left", validate="many_to_one")
    if panel["POBLACION"].isna().any():
        raise ValueError("Pares (unidad, año) sin población")

    panel["PERSONAS_MES"] = panel["POBLACION"] / 12.0
    panel["TASA_10K"] = panel["REPORTES"] / panel["POBLACION"] * 1e4   # monthly, per 10,000 inhabitants
    panel["LOG_TASA"] = np.log1p(panel["TASA_10K"])
    panel["FECHA"] = pd.to_datetime(dict(year=panel.ANO, month=panel.MES, day=1))

    gaps = {(g["DPTO_KEY"], g["ANO"], g["MES"]): g["FUENTE"]
            for g in (coverage_gaps_documented or [])}
    panel["COBERTURA"] = np.where(panel["TIENE_FILAS_FUENTE"], "OBSERVADO", "SIN_FILAS_FUENTE")
    panel["EVIDENCIA_HUECO"] = [gaps.get(k) for k in zip(panel.DPTO_KEY, panel.ANO, panel.MES)]
    panel["MES_NACIONAL_INCOMPLETO"] = panel.groupby(["ANO", "MES"])[
        "TIENE_FILAS_FUENTE"].transform(lambda s: not s.all())

    if int(panel["REPORTES"].sum()) != int(df["CANTIDAD"].sum()):
        raise ValueError("El panel no conserva el total de reportes")
    return panel.sort_values(["DPTO_KEY", "FECHA"]).reset_index(drop=True)


def unit_rates(panel, years):
    """Rate per 10,000 person-years with observed and total exposure."""
    p = panel[panel["ANO"].isin(years)]
    t = p.groupby("DPTO_KEY").agg(
        REPORTES=("REPORTES", "sum"),
        MESES_OBSERVADOS=("TIENE_FILAS_FUENTE", "sum"),
        PERSONAS_ANIO_TOTAL=("PERSONAS_MES", "sum"))
    t["PERSONAS_ANIO_OBSERVADA"] = p[p["TIENE_FILAS_FUENTE"]].groupby("DPTO_KEY")["PERSONAS_MES"].sum()
    t["TASA_10K_EXPOSICION_OBSERVADA"] = t.REPORTES / t.PERSONAS_ANIO_OBSERVADA * 1e4
    t["TASA_10K_EXPOSICION_TOTAL"] = t.REPORTES / t.PERSONAS_ANIO_TOTAL * 1e4
    t["REPORTES"] = t["REPORTES"].astype("int64")
    t["MESES_OBSERVADOS"] = t["MESES_OBSERVADOS"].astype("int64")
    return t.reset_index()


def national_rates(unit_table):
    rep = unit_table["REPORTES"].sum()
    return {"exposicion_observada": float(rep / unit_table["PERSONAS_ANIO_OBSERVADA"].sum() * 1e4),
            "exposicion_total": float(rep / unit_table["PERSONAS_ANIO_TOTAL"].sum() * 1e4)}

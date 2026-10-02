"""Official INEI denominators (Table No. 01, 2018-2026) for the 26 territorial units."""
import re

import numpy as np
import openpyxl
import pandas as pd

from .io_utils import norm_text

YEARS_XLSX = list(range(2018, 2027))


def _clean_name(s):
    return re.sub(r"\s*\d+\s*/.*$", "", str(s)).strip()


def read_inei(xlsx_path):
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    header = next(i for i, r in enumerate(rows) if r[2] == 2018 and r[10] == 2026)
    recs = []
    for r in rows[header + 1:]:
        code = str(r[0]).strip().replace("\xa0", "") if r[0] is not None else ""
        if re.fullmatch(r"\d{6}", code):
            vals = [float(v) if isinstance(v, (int, float)) else np.nan for v in r[2:11]]
            recs.append([code, _clean_name(r[1])] + vals)
    ine = pd.DataFrame(recs, columns=["UBIGEO", "NOMBRE"] + YEARS_XLSX)
    if ine["UBIGEO"].duplicated().any():
        raise ValueError("UBIGEO duplicado en el Excel INEI")
    return ine


def build_units(ine, years):
    """Lima Metropolitana = 150100; Región Lima = 150000 − 150100; Callao = 070000.

    Lima is split because the metropolitan province and the rest of the department differ
    sharply in population and report volume."""
    idx = ine.set_index("UBIGEO")
    deps = idx[idx.index.str.endswith("0000") & (idx.index != "000000")]
    rows = []
    for code, name in deps["NOMBRE"].items():
        if code == "150000":
            lm = idx.loc["150100", years]
            rows.append(["LIMA METROPOLITANA", "150100"] + list(lm))
            rows.append(["REGION LIMA", "150000-150100"] + list(idx.loc["150000", years] - lm))
        else:
            rows.append([norm_text(name), code] + list(deps.loc[code, years]))
    units = pd.DataFrame(rows, columns=["DPTO_KEY", "REGLA_UBIGEO"] + list(years))
    if len(units) != 26:
        raise ValueError(f"Se esperaban 26 unidades, hay {len(units)}")
    pais = idx.loc["000000", years].astype(float)
    if not np.allclose(units[list(years)].sum().values, pais.values):
        raise ValueError("La suma de las 26 unidades no coincide con el total nacional")
    long = units.melt(id_vars=["DPTO_KEY", "REGLA_UBIGEO"], value_vars=list(years),
                      var_name="ANO", value_name="POBLACION")
    long["ANO"] = long["ANO"].astype(int)
    long["POBLACION"] = long["POBLACION"].astype("int64")
    return long

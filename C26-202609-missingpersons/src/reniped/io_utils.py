"""Reading and validation of the official RENIPED CSV (MININTER, National Open Data Platform)."""
import hashlib
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

EXPECTED_COLUMNS = ["ANO", "MES", "UBIGEO_HECHO", "DPTO_HECHO", "PROV_HECHO",
                    "DIST_HECHO", "SEXO", "RANGO_EDAD", "NACIONALIDAD", "CANTIDAD"]
MISSING_TOKENS = {"", "NAN", "NA", "N/A", "NULL", "NONE", "-"}


def sha256_file(path, chunk=1 << 20):
    """SHA-256 of a file, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def norm_text(value):
    """Upper case, no diacritics and collapsed whitespace."""
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _norm_col(c):
    s = norm_text(c).replace(" ", "_")
    return {"AO": "ANO", "ANIO": "ANO"}.get(s, s)


def load_raw(path, expected_sha256=None, encoding="latin1"):
    """Read the CSV without transforming the counts and return (df, audit).

    The SHA-256 is checked first, so any change in the source file stops the run."""
    path = Path(path)
    digest = sha256_file(path)
    if expected_sha256 and digest != expected_sha256:
        raise ValueError(f"SHA-256 inesperado para {path.name}: {digest}")

    df = pd.read_csv(path, encoding=encoding, dtype=str, keep_default_na=False)
    df.columns = [_norm_col(c) for c in df.columns]
    missing_cols = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Faltan columnas: {sorted(missing_cols)}")
    df = df[EXPECTED_COLUMNS].copy()

    for c in EXPECTED_COLUMNS:
        df[c] = df[c].str.strip()
        df.loc[df[c].str.upper().isin(MISSING_TOKENS), c] = np.nan

    for c in ["ANO", "MES", "CANTIDAD"]:
        if df[c].isna().any():
            raise ValueError(f"Valores faltantes en {c}")
        df[c] = pd.to_numeric(df[c], errors="raise").astype("int64")

    if not df["MES"].between(1, 12).all():
        raise ValueError("MES fuera de 1-12")
    if not (df["CANTIDAD"] > 0).all():
        raise ValueError("CANTIDAD no positiva")

    # UBIGEO always as 6-digit text (keeps the leading zero)
    df["UBIGEO_HECHO"] = df["UBIGEO_HECHO"].str.zfill(6)
    df["DPTO_KEY"] = df["DPTO_HECHO"].map(norm_text)
    df["EDAD_DESCONOCIDA"] = df["RANGO_EDAD"].isna()
    df["SEXO_DESCONOCIDO"] = df["SEXO"].isna()

    key = ["UBIGEO_HECHO", "ANO", "MES", "RANGO_EDAD", "SEXO", "NACIONALIDAD"]
    dup = int(df.duplicated(key, keep=False).sum())

    audit = {
        "archivo": path.name,
        "sha256": digest,
        "bytes": path.stat().st_size,
        "filas": int(len(df)),
        "total_reportes": int(df["CANTIDAD"].sum()),
        "cobertura": f"{df.ANO.min()}-{df.loc[df.ANO == df.ANO.min(), 'MES'].min():02d} "
                     f"a {df.ANO.max()}-{df.loc[df.ANO == df.ANO.max(), 'MES'].max():02d}",
        "unidades_territoriales": int(df["DPTO_KEY"].nunique()),
        "clave_observacional": key,
        "filas_con_clave_duplicada": dup,
        "edad_desconocida": {"filas": int(df.EDAD_DESCONOCIDA.sum()),
                             "reportes": int(df.loc[df.EDAD_DESCONOCIDA, "CANTIDAD"].sum())},
        "sexo_desconocido": {"filas": int(df.SEXO_DESCONOCIDO.sum()),
                             "reportes": int(df.loc[df.SEXO_DESCONOCIDO, "CANTIDAD"].sum())},
        "reportes_por_anio": {int(k): int(v) for k, v in
                              df.groupby("ANO")["CANTIDAD"].sum().items()},
    }
    if dup:
        raise ValueError(f"La clave observacional no es única ({dup} filas)")
    return df, audit

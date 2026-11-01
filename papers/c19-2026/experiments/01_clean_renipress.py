# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Stage 01: RENIPRESS data-quality report.

Missingness of the key fields, duplicates dropped by the ETL, IQR outliers of
the raw coordinates and departmental coverage. Writes
outputs/01_clean_renipress/{data_quality_report,outliers_iqr}.csv and persists
the enriched active-facility frame for the later stages.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import *  # noqa: E402,F403  (paths, helpers and the ETL frames)

OUT = OUTPUTS / "01_clean_renipress"
OUT.mkdir(parents=True, exist_ok=True)
t0 = time.time()

quality = [{"Variable": col, "Faltantes_%": round(df[col].isna().mean() * 100, 2)}
           for col in ["ubigeo", "department", "status", "category", "lat_raw", "lon_raw"]
           if col in df.columns]
df_quality = pd.DataFrame(quality)
print(f"Duplicates dropped by the ETL: {N_ANTES_DEDUP - N_DESPUES_DEDUP}")
print(df_quality.to_string(index=False))


def outliers_iqr(serie):
    q1, q3 = serie.quantile(0.25), serie.quantile(0.75)
    iqr = q3 - q1
    return ((serie < q1 - 1.5 * iqr) | (serie > q3 + 1.5 * iqr)).mean() * 100


outliers = []
for col in ["lat_raw", "lon_raw"]:
    values = pd.to_numeric(df[col].astype(str).str.replace(",", ".", regex=False),
                           errors="coerce").dropna()
    pct = outliers_iqr(values)
    print(f"IQR outliers in {col}: {pct:.2f}%")
    outliers.append({"Variable": col, "Outliers_IQR_%": round(pct, 2)})

coverage = df["department"].nunique() if "department" in df.columns else np.nan
print(f"Departments represented in RENIPRESS: {coverage}")
df_quality.to_csv(OUT / "data_quality_report.csv", index=False)
pd.DataFrame(outliers).to_csv(OUT / "outliers_iqr.csv", index=False)
print(f"[data quality] {time.time() - t0:.2f}s")

try:
    save_df_activos()
except Exception as e:  # the frame is rebuilt from the cache if this fails
    print("persist failed:", e)

print("Stage 01_clean_renipress done.")

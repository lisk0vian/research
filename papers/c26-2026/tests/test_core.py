"""Tests of the critical components of the pipeline (synthetic data, < 1 min).

Run from the repository root:  python -m pytest -q papers/c26-2026/tests

The suite needs the paper's scientific stack (see experiments/requirements-
experiments.txt); per AGENTS.md §6 the repository test environment is stdlib +
pytest + numpy + pandas, so the module skips instead of failing to import when
that stack is absent.
"""
import json
import math
import sys
from pathlib import Path

import pytest

for _mod in ("scipy", "sklearn", "statsmodels", "matplotlib", "openpyxl",
             "geopandas", "shapely", "pyproj", "libpysal", "esda"):
    pytest.importorskip(_mod, reason="c26-2026 tests require the paper environment "
                                     "(experiments/requirements-experiments.txt)")

import numpy as np                                  # noqa: E402
import pandas as pd                                 # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "src"))

from reniped.clustering import LabeledKMeans                      # noqa: E402
from reniped.panel import build_panel                              # noqa: E402
from reniped.prioridad import priority_table                       # noqa: E402
from reniped.results import sanitize                               # noqa: E402
from reniped.spatial import conditional_randomization_p, two_sided  # noqa: E402


def test_p_exacto_con_un_vecino():
    """k = 1: the conditional distribution has n−1 equally likely atoms."""
    y = np.arange(26, dtype=float)                 # distinct values 0..25
    neigh = {i: [(i + 1) % 26] for i in range(26)}
    cr = conditional_randomization_p(y, neigh)
    i, j = 0, 1                                    # the neighbour of 0 is 1; others = 1..25
    others = np.delete(y, i)
    up = (others >= y[j]).mean()
    lo = (others <= y[j]).mean()
    assert math.isclose(cr.loc[i, "p_superior"], up)
    assert math.isclose(cr.loc[i, "p_inferior"], lo)
    assert math.isclose(cr.loc[i, "p_bilateral_min_alcanzable"], 2 / 25)
    assert (cr["metodo_p"] == "exacto").all()
    assert (cr["p_bilateral"] >= 2 / 25 - 1e-12).all()


def test_p_exacto_maximo_vecino():
    """If the only neighbour is the maximum of the rest, p_superior = 1/25 (Callao–Lima case)."""
    rng = np.random.default_rng(0)
    y = rng.gamma(2.0, 1.0, 26)
    y[5] = y.max() + 10                            # 'Lima'
    neigh = {i: [5] if i == 7 else [(i + 1) % 26] for i in range(26)}
    neigh[5] = [7]
    cr = conditional_randomization_p(y, neigh)
    assert math.isclose(cr.loc[7, "p_superior"], 1 / 25)
    assert math.isclose(cr.loc[7, "p_bilateral"], 2 / 25)


def test_monte_carlo_aproxima_exacto():
    rng = np.random.default_rng(1)
    y = rng.normal(size=26)
    neigh = {i: [int(v) for v in rng.choice(np.delete(np.arange(26), i), 3, replace=False)]
             for i in range(26)}
    ex = conditional_randomization_p(y, neigh)
    mc = conditional_randomization_p(y, neigh, max_enum=0, draws=99_999)
    assert mc["metodo_p"].str.startswith("monte_carlo").all()
    assert np.max(np.abs(ex["p_plegado"] - mc["p_plegado"])) < 0.01


def test_two_sided_acotado():
    assert np.allclose(two_sided([0.01, 0.4, 0.6]), [0.02, 0.8, 1.0])


def test_labeled_kmeans_conserva_etiquetas():
    rng = np.random.default_rng(2)
    X = np.vstack([rng.normal(0, 1, (150, 2)), rng.normal(5, 1, (150, 2))])
    for seed in range(5):
        lk = LabeledKMeans(2, seed, 10).fit(X, X[:, 0])
        assert (lk.predict(X) == lk.labels_).all()
        assert X[lk.labels_ == 0, 0].mean() < X[lk.labels_ == 1, 0].mean()


def test_jensen_shannon_distancia_y_divergencia():
    from scipy.spatial.distance import jensenshannon
    p, q = np.array([0.5, 0.5]), np.array([0.8, 0.2])
    m = (p + q) / 2
    div = 0.5 * np.sum(p * np.log2(p / m)) + 0.5 * np.sum(q * np.log2(q / m))
    assert math.isclose(jensenshannon(p, q, base=2) ** 2, div, rel_tol=1e-12)


def test_panel_conserva_total_y_no_imputa_huecos():
    rows = [("A", 2019, m, 3) for m in range(1, 13) if m != 5] + \
           [("B", 2019, m, 2) for m in range(1, 13)]
    df = pd.DataFrame(rows, columns=["DPTO_KEY", "ANO", "MES", "CANTIDAD"])
    pop = pd.DataFrame({"DPTO_KEY": ["A", "B"], "ANO": [2019, 2019], "POBLACION": [1000, 2000]})
    gaps = [{"DPTO_KEY": "A", "ANO": 2019, "MES": 5, "FUENTE": "prueba"}]
    p = build_panel(df, pop, [2019], gaps)
    assert len(p) == 24
    assert int(p["REPORTES"].sum()) == int(df["CANTIDAD"].sum())
    hueco = p[(p.DPTO_KEY == "A") & (p.MES == 5)].iloc[0]
    assert math.isnan(hueco["REPORTES"]) and not hueco["TIENE_FILAS_FUENTE"]


def test_json_estricto():
    obj = sanitize({"a": np.nan, "b": np.float64(1.5), "c": [np.inf, 2], "d": np.int64(3)})
    txt = json.dumps(obj, allow_nan=False)
    assert json.loads(txt) == {"a": None, "b": 1.5, "c": [None, 2], "d": 3}


def _panel_sintetico(tasas, anios=(2019, 2020, 2021), seed=0):
    """Panel with Poisson counts; `tasas` = reports per 10,000 person-years by unit."""
    rng = np.random.default_rng(seed)
    filas = []
    for u, tasa in tasas.items():
        for a in anios:
            for m in range(1, 13):
                pm = 1_000_000 / 12
                filas.append({"DPTO_KEY": u, "ANO": a, "MES": m, "PERSONAS_MES": pm,
                              "REPORTES": float(rng.poisson(tasa * pm / 1e4)),
                              "COBERTURA": "OBSERVADO"})
    return pd.DataFrame(filas)


def test_prioridad_detecta_territorio_alto_y_no_inventa():
    """A territory with twice the rate is classified 'superior'; equal territories are not flagged."""
    tasas = {f"U{i:02d}": 6.0 for i in range(12)}
    tasas["ALTO"] = 12.0
    t, _ = priority_table(_panel_sintetico(tasas), [2019, 2020, 2021], B=999, seed=1)
    fila = t.set_index("DPTO_KEY").loc["ALTO"]
    assert fila["CLASE"] == "superior" and 1.7 < fila["RR_VS_RESTO"] < 2.3
    otros = t[t.DPTO_KEY != "ALTO"]
    assert (otros["CLASE"] == "superior").sum() == 0


def test_prioridad_respeta_meses_faltantes():
    """With observed exposure, a missing month enters neither the reports nor the person-years."""
    p = _panel_sintetico({"A": 6.0, "B": 6.0}, anios=(2019,))
    i = p.index[(p.DPTO_KEY == "A") & (p.MES == 3)][0]
    p.loc[i, ["REPORTES", "COBERTURA"]] = [np.nan, "SIN_FILAS_FUENTE"]
    t, _ = priority_table(p, [2019], "observada", B=99, seed=1)
    a = t.set_index("DPTO_KEY").loc["A"]
    esperado = p[(p.DPTO_KEY == "A") & (p.COBERTURA == "OBSERVADO")]
    tasa = esperado.REPORTES.sum() / esperado.PERSONAS_MES.sum() * 1e4
    assert math.isclose(a["TASA_10K"], tasa)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  OK    {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"  FALLA {name}: {e!r}")
    sys.exit(1 if fails else 0)

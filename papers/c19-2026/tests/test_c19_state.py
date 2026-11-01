# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Fast checks for the c19-2026 ETL state (synthetic data only, never data/)."""

import json
import pathlib
import subprocess
import sys

import pandas as pd
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments"
sys.path.insert(0, str(EXP))

import _etl  # noqa: E402
import _sample_data  # noqa: E402
import _schema  # noqa: E402
import census2025_prepare  # noqa: E402


def _build(tmp_path):
    renipress, census = _sample_data.write_sample(tmp_path / "data")
    return _etl.load_or_build(renipress, census, tmp_path / "data" / "processed", 42)


def _read_raw(path):
    return pd.read_csv(path, encoding="utf-8-sig", sep=";", engine="python", dtype=str)


def _write_raw(df, path):
    df.to_csv(path, index=False, encoding="utf-8-sig", sep=";")


def test_state_builds_and_caches(tmp_path, monkeypatch):
    raw, _ = _sample_data.build_sample()
    renipress, census = _sample_data.write_sample(tmp_path / "data")
    cache = tmp_path / "data" / "processed"
    state = _etl.load_or_build(renipress, census, cache, 42)
    assert state["N_FILAS_CRUDAS_RENIPRESS"] == len(raw)
    assert state["N_ACTIVOS"] == int((raw["ESTADO"] == "ACTIVO").sum())
    assert state["N_COORDS_VALIDAS"] > 0
    assert "dist_km_complex_hospital" in state["df_activos"].columns
    assert "spatial_anomaly" in state["df_activos"].columns
    assert (cache / "df_activos.parquet").is_file()

    def boom(*args, **kwargs):
        raise AssertionError("cache miss: the ETL was recomputed")

    monkeypatch.setattr(_etl, "_build_enriched", boom)
    cached = _etl.load_or_build(renipress, census, cache, 42)
    assert cached["df_activos"].shape == state["df_activos"].shape
    assert cached["df_validas"].shape == state["df_validas"].shape


def test_cache_rebuilds_when_input_changes(tmp_path):
    renipress, census = _sample_data.write_sample(tmp_path / "data")
    cache = tmp_path / "data" / "processed"
    _etl.load_or_build(renipress, census, cache, 42)
    stamp = cache / "state.json"
    key_before = json.loads(stamp.read_text(encoding="utf-8"))["key"]

    with open(renipress, "a", encoding="utf-8") as f:
        f.write("\n")

    _etl.load_or_build(renipress, census, cache, 42)
    assert json.loads(stamp.read_text(encoding="utf-8"))["key"] != key_before


def test_sample_never_defaults_to_real_raw():
    with pytest.raises(SystemExit):
        sys.argv = ["_sample_data.py", "--out", str(ROOT / "data" / "raw")]
        _sample_data.main()


def test_frames_use_english_names(tmp_path):
    state = _build(tmp_path)
    assert not any(c.isupper() for c in state["df"].columns), "raw columns must be renamed to English"
    assert {"ubigeo", "category", "lat_raw", "lat", "care_level", "natural_region"} <= set(state["df"].columns)
    assert {"population_total", "pop_60_plus", "pop5_with_disability"} <= set(state["df_activos"].columns)
    assert "poblacion_total" not in state["df_activos"].columns


def test_every_etl_column_is_documented(tmp_path):
    state = _build(tmp_path)
    documented = ({c["name"] for c in _schema.RENIPRESS_COLUMNS} | {c["name"] for c in _schema.CENSUS_COLUMNS}
                  | {c["name"] for c in _schema.DERIVED_COLUMNS})
    for frame in ("df", "df_activos", "df_validas"):
        undocumented = set(state[frame].columns) - documented
        assert not undocumented, f"{frame} has columns missing from the data dictionary: {sorted(undocumented)}"


def test_care_levels_follow_the_schema():
    df = pd.DataFrame({
        "category": ["I-1", "II-E", "II-2", "III-E", "III-2", "0", None, ""],
        "status": ["ACTIVO"] * 8,
        "classification": ["", "", "", "", "", "HOSPITALES O CLINICAS DE ATENCION GENERAL", "PATOLOGIA CLINICA", ""],
    })
    out = _etl.add_care_fields(df)
    assert out["care_level"].tolist() == [1, 5, 6, 7, 8, 0, 0, 0]
    assert out["care_tier"].tolist()[:5] == ["primary", "secondary", "secondary", "tertiary", "tertiary"]
    # III-E is a tertiary hospital; a facility without a category is neither primary care nor a hospital.
    assert out["is_complex_hospital"].tolist() == [False, True, True, True, True, False, False, False]
    assert out["is_hospital_like_uncategorized"].tolist() == [False] * 5 + [True, False, False]


def test_unknown_category_on_active_facility_aborts():
    df = pd.DataFrame({"category": ["I-1", "IV-9"], "status": ["ACTIVO", "ACTIVO"], "classification": ["", ""]})
    with pytest.raises(ValueError, match="IV-9"):
        _etl.add_care_fields(df)
    # An unknown category on a closed facility is ignored: nothing downstream reads it.
    df["status"] = ["ACTIVO", "BAJA DEFINITIVA"]
    assert _etl.add_care_fields(df)["care_level"].tolist() == [1, 0]


def test_renipress_reads_utf8_bom_and_latin1(tmp_path):
    renipress, _ = _sample_data.write_sample(tmp_path / "data")
    bom = _etl._read_renipress_csv(renipress)
    assert bom.columns[0] == "INSTITUCION", "the BOM must not leak into the first column name"

    legacy = tmp_path / "legacy.csv"
    _read_raw(renipress).assign(NOMBRE="Clínica Señora").to_csv(legacy, sep=";", index=False, encoding="latin1")
    assert _etl._read_renipress_csv(legacy)["NOMBRE"].iloc[0] == "Clínica Señora"


def test_missing_renipress_column_fails_loudly(tmp_path):
    renipress, census = _sample_data.write_sample(tmp_path / "data")
    _write_raw(_read_raw(renipress).drop(columns=["CATEGORIA"]), renipress)
    with pytest.raises(ValueError, match="CATEGORIA"):
        _etl._read_sources(renipress, census)


def test_facility_without_census_is_excluded_not_zeroed(tmp_path):
    renipress, census = _sample_data.write_sample(tmp_path / "data")
    r = _read_raw(renipress)
    orphan = r[r["ESTADO"] == "ACTIVO"].head(1).copy()
    orphan["UBIGEO"] = "999999"
    _write_raw(pd.concat([r, orphan]), renipress)

    state = _etl.load_or_build(renipress, census, tmp_path / "data" / "processed", 42)
    activos = state["df_activos"]
    assert "999999" not in set(activos["ubigeo"])
    assert state["N_ACTIVOS_SIN_CENSO"] >= 1
    assert "999999" in state["UBIGEO_SIN_CENSO"]
    assert (activos["population_total"] > 0).all()


def _write_workbook(path, header, national, rows):
    width = max(len(header), len(national) + 5, *(len(r) + 1 for r in rows))

    def pad(r):
        return list(r) + [None] * (width - len(r))

    body = [pad(["Consulta de población"]), pad(["Todos los departamentos"]), pad([]), pad(["Nro", "Ubigeo"]),
            pad(header), pad([None, "Perú", "Total", None, None, *national])]
    body += [pad([i + 1, *r]) for i, r in enumerate(rows)]
    body += [pad(["Nota:"]), pad(["1/ Comprende los 43 distritos de la provincia de Lima."])]
    pd.DataFrame(body).to_excel(path, header=False, index=False)


def test_census_prepare_converts_and_checks_totals(tmp_path):
    age_rows = [["010101", "Amazonas", "Chachapoyas", "Chachapoyas", 100, 30, 60, 10],
                ["150101", "Lima Metropolitana ¹/", "Lima", "Lima", 200, 50, 120, 30],
                ["210303", "Puno", "Carabaya", "Ayapata 3/", 50, 10, 30, 10]]
    dis_rows = [["010101", "Amazonas", "Chachapoyas", "Chachapoyas", 90, 9, 81],
                ["150101", "Lima Metropolitana ¹/", "Lima", "Lima", 190, 19, 171],
                ["210303", "Puno", "Carabaya", "Ayapata 3/", 45, 5, 40]]
    age, dis = tmp_path / "age.xlsx", tmp_path / "dis.xlsx"
    age_header = [None] * 6 + ["De 0 a 14 años", "De 15 a 59 años", "De 60 años y más"]
    dis_header = [None] * 6 + ["Sí tiene discapacidad", "No tiene discapacidad"]
    _write_workbook(age, age_header, [350, 90, 210, 50], age_rows)
    _write_workbook(dis, dis_header, [325, 33, 292], dis_rows)

    out = census2025_prepare.convert(age, dis)
    assert list(out.columns) == _schema.CENSUS_REQUIRED
    assert out["population_total"].sum() == 350 and out["pop5_with_disability"].sum() == 33
    assert out.loc[out["ubigeo"] == "150101", "department"].iloc[0] == "Lima Metropolitana"
    assert out["boundary_undefined"].tolist() == [False, False, True]
    assert out.loc[out["ubigeo"] == "210303", "district"].iloc[0] == "Ayapata"

    # A workbook whose districts do not add up to its national row must not pass as plausible numbers.
    _write_workbook(age, age_header, [999, 90, 210, 50], age_rows)
    with pytest.raises(AssertionError, match="national total"):
        census2025_prepare.convert(age, dis)


def test_data_dictionary_is_in_sync_with_the_schema():
    result = subprocess.run([sys.executable, "_build_dictionary.py", "--check"], cwd=EXP,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr


def test_config_and_colab_name_the_same_raw_files():
    cfg = yaml.safe_load((EXP / "config.yaml").read_text(encoding="utf-8"))
    colab = yaml.safe_load((EXP / "colab.yaml").read_text(encoding="utf-8"))
    assert sorted(colab["state_inputs"]) == sorted(f"data/raw/{v}" for v in cfg["data"].values())
    assert cfg["data"]["renipress"] == _schema.DATASETS["renipress"]["local_file"]
    assert cfg["data"]["census"] == _schema.DATASETS["census2025"]["local_file"]


def test_cache_key_changes_when_paths_py_changes(tmp_path, monkeypatch):
    # REGION_NATURAL_MAP lives in _paths.py and is baked into the cached frames.
    renipress, census = _sample_data.write_sample(tmp_path / "data")
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("A = 1\n", encoding="utf-8")
    b.write_text("A = 2\n", encoding="utf-8")
    monkeypatch.setattr(_etl._paths, "__file__", str(a))
    key_a = _etl._cache_key(renipress, census)
    monkeypatch.setattr(_etl._paths, "__file__", str(b))
    assert _etl._cache_key(renipress, census) != key_a

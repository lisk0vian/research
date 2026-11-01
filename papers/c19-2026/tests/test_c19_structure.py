# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Fast structural checks for c19-2026 experiment scripts (no heavy execution)."""

import py_compile
import pathlib

EXP = pathlib.Path(__file__).resolve().parents[1] / "experiments"
EXPECTED = [
    "_common.py", "_paths.py", "_deps.py", "_etl.py", "_figstyle.py",
    "_sample_data.py", "_schema.py", "_build_dictionary.py", "_download_inputs.py",
    "_probe_ml.py",
    "_access.py", "_simulate.py",
    "02_geo_inputs.py", "02_regions.py", "03_access_travel_time.py",
    "04_access_sensitivity.py", "05_need_priority.py", "06_spatial_stats.py",
    "07_outcome_sinadef.py", "08_validation_models.py", "09_ml_checks.py",
    "census2025_prepare.py", "config.yaml", "colab.yaml", "run_all.py",
    "analysis_plan.yaml",
    "00_verify_datasets.py", "01_clean_renipress.py",
    "_legacy/02_spatial_clusters.py", "_legacy/03_build_invs.py",
    "_legacy/04_define_target.py", "_legacy/05_train_classifier.py",
    "_legacy/06_evaluate_classifier.py", "_legacy/07_explain_shap.py",
    "_legacy/08_test_geographic_transfer.py", "_legacy/09_audit_equity.py",
    "_legacy/10_stress_noise.py", "_legacy/11_conformal_sota.py",
    "_legacy/12_economic_priority.py", "_legacy/13_reproducibility_package.py",
]


def test_expected_files_present():
    for name in EXPECTED:
        assert (EXP / name).is_file(), f"missing {name}"


def test_scripts_compile():
    for name in EXPECTED:
        if name.endswith(".py"):
            py_compile.compile(str(EXP / name), doraise=True)


def test_colab_yaml_has_stages():
    import yaml
    cfg = yaml.safe_load((EXP / "colab.yaml").read_text(encoding="utf-8"))
    assert "stages" in cfg and len(cfg["stages"]) == 11
    assert cfg.get("gpu") == "none"


def test_no_excel_artifacts():
    """No stage may write .xlsx: the pipeline's artefacts of record are CSV."""
    for name in EXPECTED:
        if name.endswith(".py"):
            src = (EXP / name).read_text(encoding="utf-8")
            assert "ExcelWriter" not in src, f"{name} still uses pd.ExcelWriter"
            assert "to_excel" not in src, f"{name} still uses to_excel"


def test_data_files_present():
    """Only the two always-local inputs. The access inputs live on Drive and are
    fetched by Colab's setup, never committed (see data/SOURCES.md)."""
    import yaml
    cfg = yaml.safe_load((EXP / "config.yaml").read_text(encoding="utf-8"))
    raw = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
    for name in (cfg["data"]["renipress"], cfg["data"]["census"]):
        assert (raw / name).is_file(), f"missing data/raw/{name} (see data/SOURCES.md)"

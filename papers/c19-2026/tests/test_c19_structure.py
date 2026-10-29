# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Fast structural checks for c19-2026 experiment scripts (no heavy execution)."""

import py_compile
import pathlib

EXP = pathlib.Path(__file__).resolve().parents[1] / "experiments"
EXPECTED = [
    "_common.py", "_figstyle.py", "config.yaml", "colab.yaml", "run_all.py",
    "00_verify_datasets.py", "01_clean_renipress.py", "02_spatial_clusters.py",
    "03_build_invs.py", "04_define_target.py", "05_train_classifier.py",
    "06_evaluate_classifier.py", "07_explain_shap.py", "08_test_geographic_transfer.py",
    "09_audit_equity.py", "10_stress_noise.py", "11_conformal_sota.py",
    "12_economic_priority.py", "13_reproducibility_package.py",
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
    assert "stages" in cfg and len(cfg["stages"]) == 14
    assert cfg.get("gpu") == "none"


def test_data_files_present():
    raw = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
    assert (raw / "renipress.csv").is_file()
    assert (raw / "censo-2017.csv").is_file()

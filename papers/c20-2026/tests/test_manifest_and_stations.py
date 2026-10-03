# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Jerremi Aron Chancan Labajos
"""Tests for manifest accumulation and the station list contract.

`write_manifest` used `data.update(payload)`, a shallow merge. With one
station that was indistinguishable from correct. With five, the second
station overwrites the first: no exception, no warning, one station's
numbers where there should be five. These tests pin the merge and the
station helpers that Phase 1 introduces on top of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import _common  # noqa: E402


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    """Point _common's OUTPUTS at a tmp tree so the real one is untouched."""
    outs = tmp_path / "outputs"
    outs.mkdir()
    monkeypatch.setattr(_common, "OUTPUTS", outs)
    return outs


def _read(outs: Path) -> dict:
    return json.loads((outs / "manifest_index.json").read_text(encoding="utf-8"))


# --- the merge -------------------------------------------------------------

def test_a_second_unit_does_not_overwrite_the_first(outputs):
    """The whole point. Five stations, one slot, and the run looks fine."""
    _common.write_manifest({"stations": {"040514": {"elev_m": 3329}}})
    _common.write_manifest({"stations": {"040114": {"elev_m": 4475}}})
    stations = _read(outputs)["stations"]
    assert set(stations) == {"040514", "040114"}


def test_units_accumulate_across_many_writes(outputs):
    for i, code in enumerate(["040514", "040114", "040122", "040506", "040513"]):
        _common.write_manifest({"stations": {code: {"elev_m": 2000 + i}}})
    stations = _read(outputs)["stations"]
    assert len(stations) == 5
    assert stations["040513"]["elev_m"] == 2004


def test_nesting_is_deep_not_shallow(outputs):
    """A fold's block must not wipe the fold that was written before it."""
    _common.write_manifest({"stations": {"040514": {"folds": {"D1": {"skill": 0.1}}}}})
    _common.write_manifest({"stations": {"040514": {"folds": {"D2": {"skill": 0.2}}}}})
    folds = _read(outputs)["stations"]["040514"]["folds"]
    assert set(folds) == {"D1", "D2"}


def test_a_leaf_value_still_replaces_rather_than_merging(outputs):
    """Deep merge is for dicts. A scalar has no children to accumulate."""
    _common.write_manifest({"stations": {"040514": {"n_rows": 100}}})
    _common.write_manifest({"stations": {"040514": {"n_rows": 250}}})
    assert _read(outputs)["stations"]["040514"]["n_rows"] == 250


def test_replace_drops_entries_that_config_no_longer_declares(outputs):
    """Deep merge never forgets, which is its own bug: drop a station from
    config and its last entry stays on disk pretending it still ran."""
    _common.write_manifest({"stations": {"040514": {}, "040114": {}}})
    _common.write_manifest({"stations": {"040514": {}}}, replace=("stations",))
    assert set(_read(outputs)["stations"]) == {"040514"}


def test_replace_only_affects_the_named_key(outputs):
    _common.write_manifest({"source": {"a": 1}, "logs": {"run_all": "x"}})
    _common.write_manifest({"logs": {}}, replace=("logs",))
    data = _read(outputs)
    assert data["source"] == {"a": 1}
    assert data["logs"] == {}


def test_deep_merge_does_not_mutate_its_inputs():
    base = {"a": {"b": {"c": 1}}}
    payload = {"a": {"b": {"d": 2}}}
    merged = _common.deep_merge(base, payload)
    assert merged == {"a": {"b": {"c": 1, "d": 2}}}
    assert base == {"a": {"b": {"c": 1}}}
    assert payload == {"a": {"b": {"d": 2}}}


def test_the_declared_contract_survives_every_write(outputs):
    _common.write_manifest({"stations": {"040514": {}}})
    data = _read(outputs)
    assert data["paper"] == "c20-2026"
    assert data["design_version"] == "2.0"
    assert data["status"] == "partial"


def test_a_corrupt_manifest_is_replaced_not_appended_to(outputs):
    path = outputs / "manifest_index.json"
    path.write_text("{not json", encoding="utf-8")
    _common.write_manifest({"stations": {"040514": {"elev_m": 3329}}})
    assert _read(outputs)["stations"] == {"040514": {"elev_m": 3329}}


# --- the station list ------------------------------------------------------

def test_stations_declares_more_than_one_station():
    """A one-element stations list is the single-station design wearing a
    list, and the whole refactor is then untested by the config itself."""
    cfg = _common.load_config()
    stations = cfg.get("stations")
    assert isinstance(stations, list) and len(stations) > 1
    for entry in stations:
        assert entry.get("ubigeo"), entry
        assert len(entry["ubigeo"]) == 6, entry


def test_station_codes_are_unique():
    cfg = _common.load_config()
    codes = [s["ubigeo"] for s in cfg["stations"]]
    assert len(codes) == len(set(codes))


def test_every_station_declares_the_coordinate_triple():
    """lat/lon/elev are what make the 2054 m gradient claim checkable, so a
    station missing them cannot participate in the elevation analysis."""
    cfg = _common.load_config()
    for entry in cfg["stations"]:
        for key in ("name", "lat", "lon", "elev_m"):
            assert entry.get(key) is not None, f"{entry.get('ubigeo')}: {key}"


def test_helper_returns_codes_in_declared_order():
    cfg = _common.load_config()
    assert _common.station_codes(cfg) == [s["ubigeo"] for s in cfg["stations"]]


def test_helper_pads_a_float_style_code():
    """The portal serves UBIGEO as float, so 40514.0 loses its leading zero.
    Normalising at the boundary is the only place it is safe to do."""
    cfg = {"stations": [{"ubigeo": 40514.0}]}
    assert _common.station_codes(cfg) == ["040514"]


def test_helper_is_empty_when_no_station_is_declared():
    """Single-station data predates the list; stages still have to run."""
    assert _common.station_codes({}) == []

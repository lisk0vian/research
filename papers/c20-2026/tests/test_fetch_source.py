"""Tests for fetch_source.py: provenance, not just downloading a file.

The network is monkeypatched everywhere. These tests never contact the portal,
never read the real dataset, and never touch data/. What they pin down is the
part that quietly rots: that a wrong file is rejected, that a truncated download
leaves nothing behind, that UBIGEO padding is recorded rather than assumed, and
that an offline run fails with a message that says what to do instead.

An earlier version of this had no tests, which is how a fetched file could sit
in data/raw with no record of where it came from.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))

import _common  # noqa: E402

fetch = __import__("fetch_source")


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Route DATA_DIR at a tmp tree so nothing lands in the real data/."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(fetch, "DATA_DIR", d)
    monkeypatch.setattr(_common, "DATA_DIR", d)
    return d


SENSOR = (
    "ESTACION,UBIGEO,FECHA_CORTE,TEMP,HR\n"
    "A,40514.0,20200101,12.3,55\n"
    "A,40514.0,20200102,12.9,52\n"
    "B,40114.0,20200101,4.1,70\n"
    "B,40114.0,20200103,3.8,72\n"
)


def _write_csv(path: Path, text: str = SENSOR) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class _FakeResp(io.BytesIO):
    """Minimal stand-in for the object urlopen returns."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _fake_urlopen(payload: bytes = b"", side_effect: Exception | None = None):
    def _open(url, timeout=None):
        if side_effect is not None:
            raise side_effect
        return _FakeResp(payload)
    return _open


# --- column families -------------------------------------------------------

def test_families_are_found_case_insensitively():
    cols = ["ESTACION", "UBIGEO", "FECHA_CORTE", "TEMP"]
    found = fetch.check_families(cols)
    assert found["station"] == "UBIGEO"
    assert found["temperature"] == "TEMP"
    assert found["timestamp"] == "FECHA_CORTE"


def test_a_compound_column_name_still_matches_its_family():
    """SENAMHI's date column is FECHA_CORTE, which is neither `fecha` nor
    `corte` but both at once. Equality-only matching rejected the real file."""
    found = fetch.check_families(["UBIGEO", "FECHA_CORTE", "TEMP"])
    assert found["timestamp"] == "FECHA_CORTE"
    assert found["temperature"] == "TEMP"


def test_a_shorter_column_is_preferred_over_a_longer_one():
    """`TEMP` must not be captured by a derived column such as TEMP_MAX_CUM."""
    found = fetch.check_families(["UBIGEO", "FECHA", "TEMP_MAX_CUMULADO", "TEMP"])
    assert found["temperature"] == "TEMP"


def test_a_file_without_a_temperature_column_is_rejected():
    """The portal serves several series; the wrong one must fail loudly here,
    not three stages later as a KeyError on a column nobody remembered."""
    with pytest.raises(fetch.FetchError) as exc:
        fetch.check_families(["ESTACION", "UBIGEO", "FECHA_CORTE", "PRECIPITACION"])
    assert "temperature" in str(exc.value)


def test_an_empty_file_is_rejected(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(fetch.FetchError, match="empty"):
        fetch.read_header(empty)


# --- UBIGEO padding --------------------------------------------------------

def test_ubigeo_float_loses_its_leading_zero_and_padding_recovers_it(data_dir):
    """The portal serves UBIGEO as float, so 040514 arrives as 40514.0 and
    pandas types the whole column float64. The provenance has to show both."""
    csv = _write_csv(data_dir / "raw" / "s.csv")
    stations = fetch.station_inventory(csv, "UBIGEO", "FECHA_CORTE")
    by_code = {s["ubigeo"]: s for s in stations}
    assert "040514" in by_code
    assert by_code["040514"]["ubigeo_raw"] == "40514.0"
    assert by_code["040514"]["needs_padding"] is True


def test_a_correctly_padded_ubigeo_is_left_alone(data_dir):
    csv = _write_csv(data_dir / "raw" / "s.csv",
                     "UBIGEO,FECHA_CORTE,TEMP\n040514,20200101,12.3\n")
    stations = fetch.station_inventory(csv, "UBIGEO", "FECHA_CORTE")
    assert stations[0]["ubigeo"] == "040514"
    assert stations[0]["needs_padding"] is False


def test_inventory_counts_rows_and_spans_the_recorded_dates(data_dir):
    csv = _write_csv(data_dir / "raw" / "s.csv")
    stations = fetch.station_inventory(csv, "UBIGEO", "FECHA_CORTE")
    by_code = {s["ubigeo"]: s for s in stations}
    assert by_code["040514"]["rows"] == 2
    assert by_code["040514"]["first"] == "2020-01-01"
    assert by_code["040114"]["rows"] == 2


# --- download atomicity ----------------------------------------------------

def test_download_writes_the_file_and_returns_its_hash(data_dir, monkeypatch):
    body = SENSOR.encode("utf-8")
    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        _fake_urlopen(payload=body))
    dest = data_dir / "raw" / "s.csv"
    digest, total = fetch.download("https://example.invalid/s.csv", dest, 10)
    assert dest.read_bytes() == body
    assert total == len(body)
    assert len(digest) == 64


def test_an_interrupted_transfer_leaves_no_file_behind(data_dir, monkeypatch):
    """A truncated CSV that looks present is worse than one that is absent: the
    next run would hash it, match it against itself, and call it good."""
    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        _fake_urlopen(side_effect=urllib.error.URLError("timed out")))
    dest = data_dir / "raw" / "s.csv"
    with pytest.raises(fetch.FetchError):
        fetch.download("https://example.invalid/s.csv", dest, 10)
    assert not dest.exists()
    assert not dest.with_suffix(".csv.part").exists()


def test_a_zero_byte_response_is_not_a_dataset(data_dir, monkeypatch):
    monkeypatch.setattr(fetch.urllib.request, "urlopen", _fake_urlopen(payload=b""))
    dest = data_dir / "raw" / "s.csv"
    with pytest.raises(fetch.FetchError, match="zero bytes"):
        fetch.download("https://example.invalid/s.csv", dest, 10)
    assert not dest.exists()


# --- catalogue resolution --------------------------------------------------

def _pkg(resources):
    return json.dumps({"success": True, "result": {
        "id": "abc", "name": "senamhi", "title": "SENAMHI",
        "license_title": "ODC-By", "license_id": "odc-by",
        "organization": {"title": "SENAMHI"},
        "resources": resources}}).encode("utf-8")


def test_resource_is_selected_by_name_when_configured(monkeypatch):
    monkeypatch.setattr(fetch.urllib.request, "urlopen", _fake_urlopen(
        payload=_pkg([
            {"name": "hourly", "format": "CSV", "url": "https://x/h.csv"},
            {"name": "daily", "format": "CSV", "url": "https://x/d.csv"},
        ])))
    cfg = {"source": {"dataset_id": "abc", "prefer_name": "daily"}}
    assert fetch.resolve_resource(cfg, 10)["resource"]["url"] == "https://x/d.csv"


def test_a_single_csv_is_taken_unambiguously(monkeypatch):
    monkeypatch.setattr(fetch.urllib.request, "urlopen", _fake_urlopen(
        payload=_pkg([{"name": "series", "format": "CSV", "url": "https://x/a.csv"}])))
    cfg = {"source": {"dataset_id": "abc"}}
    assert fetch.resolve_resource(cfg, 10)["resource"]["url"] == "https://x/a.csv"


def test_several_candidates_without_a_preference_is_an_error(monkeypatch):
    """Picking one arbitrarily is how a silent wrong-file download happens."""
    monkeypatch.setattr(fetch.urllib.request, "urlopen", _fake_urlopen(
        payload=_pkg([
            {"name": "a", "format": "CSV", "url": "https://x/a.csv"},
            {"name": "b", "format": "CSV", "url": "https://x/b.csv"},
        ])))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.resolve_resource({"source": {"dataset_id": "abc"}}, 10)
    assert "prefer_name" in str(exc.value)


def test_an_unreachable_catalogue_says_what_to_do_instead(monkeypatch):
    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        _fake_urlopen(side_effect=urllib.error.URLError("no dns")))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.resolve_resource({"source": {"dataset_id": "abc"}}, 10)
    assert "--check" in str(exc.value)


def test_a_missing_dataset_id_is_a_config_error_not_a_network_error():
    with pytest.raises(fetch.FetchError, match="dataset_id"):
        fetch.resolve_resource({"source": {}}, 10)


# --- provenance ------------------------------------------------------------

def test_source_json_carries_the_whole_chain_of_custody(data_dir):
    csv = _write_csv(data_dir / "raw" / "s.csv")
    pkg = {"id": "abc", "title": "SENAMHI", "license_title": "ODC-By"}
    res = {"name": "series", "format": "CSV", "url": "https://x/a.csv"}
    stations = fetch.station_inventory(csv, "UBIGEO", "FECHA_CORTE")
    payload = fetch.build_source_json(
        pkg, res, csv, "a" * 64, 123, ["UBIGEO", "FECHA_CORTE", "TEMP"],
        stations, {"source": {"provider": "SENAMHI"}, "station": {"n_stations": 5}})

    path = fetch.write_source_json(payload)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["catalogue"]["dataset_id"] == "abc"
    assert saved["resource"]["url"] == "https://x/a.csv"
    assert saved["local"]["sha256"] == "a" * 64
    assert saved["local"]["bytes"] == 123
    assert saved["declared"]["declared_stations"] == 5
    assert saved["retrieved_at"]


def test_provenance_declares_what_config_claims_so_they_can_differ(data_dir):
    """A mismatch between the declared station count and the file is a finding.
    Recording both sides is what makes it visible to whoever reads it."""
    csv = _write_csv(data_dir / "raw" / "s.csv")
    stations = fetch.station_inventory(csv, "UBIGEO", "FECHA_CORTE")
    payload = fetch.build_source_json(
        {}, {}, csv, "b" * 64, 1, [], stations,
        {"station": {"n_stations": 5}, "data": {"coverage_declared": [2015, 2024]}})
    assert payload["declared"]["declared_stations"] == 5
    assert len(payload["stations"]) == 2


def test_source_json_survives_a_round_trip_through_disk(data_dir):
    payload = {"schema_version": fetch.SCHEMA_VERSION, "local": {"sha256": "c" * 64}}
    fetch.write_source_json(payload)
    assert fetch.read_source_json()["local"]["sha256"] == "c" * 64


def test_unparseable_provenance_is_reported_not_crashed_on(data_dir):
    (data_dir / "SOURCE.json").write_text("{not json", encoding="utf-8")
    assert fetch.read_source_json() is None


# --- provenance comparison -------------------------------------------------

def test_a_matching_hash_is_recognised_as_a_match():
    assert fetch.compare({"local": {"sha256": "d" * 64}}, "d" * 64) == "match"


def test_a_different_hash_is_reported_as_differ():
    assert fetch.compare({"local": {"sha256": "d" * 64}}, "e" * 64) == "differ"


def test_no_recorded_hash_is_unrecorded_not_a_mismatch():
    assert fetch.compare(None, "d" * 64) == "unrecorded"
    assert fetch.compare({"local": {}}, "d" * 64) == "unrecorded"


# --- the CLI surface -------------------------------------------------------

def test_check_needs_no_network_and_exits_zero_on_a_match(data_dir, monkeypatch):
    csv = _write_csv(data_dir / "raw" / "senamhi.csv")
    fetch.write_source_json({"local": {"sha256": fetch.sha256_of(csv)[0]}})

    def _explode(*a, **k):
        raise AssertionError("--check must not touch the network")
    monkeypatch.setattr(fetch.urllib.request, "urlopen", _explode)

    assert fetch.main(["--check"]) == 0


def test_check_exits_nonzero_when_the_file_was_swapped(data_dir, monkeypatch):
    csv = _write_csv(data_dir / "raw" / "senamhi.csv")
    fetch.write_source_json({"local": {"sha256": "f" * 64}})
    assert fetch.main(["--check"]) == 1


def test_check_without_a_local_file_says_so(data_dir):
    with pytest.raises(fetch.FetchError, match="not there"):
        fetch.main(["--check"])

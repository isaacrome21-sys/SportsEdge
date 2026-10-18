"""NFL stadium registry v2026.2 cleanup: versioning, fingerprints, unknowns.

v2026.1 -> v2026.2 (owner-ruled):
- SoFi Stadium roof_type OPEN_AIR -> FIXED (it has a fixed roof).
- The 28 unverified field_bearing_deg placeholders (0.0) become explicit
  unknowns (JSON null -> None). Only Arrowhead (45.0) and MetLife (15.0)
  carry verified bearings; they are preserved exactly.
- The v2026.1 file is preserved byte-for-byte as stadiums_2026_v2026.1.json
  so fingerprints recorded against it (registry_sha256 in run records)
  still resolve through load_stadium_registry(path=...).
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.context_providers import (
    StadiumRecord,
    build_weather_roof_provider,
    resolve_roof_decision,
    rotate_wind_to_field,
)
from sportsedge.sports.nfl.stadium_registry import (
    load_stadium_registry,
    stadium_registry_manifest,
)

NFL_DIR = Path(__file__).resolve().parents[1] / "sportsedge" / "sports" / "nfl"
ARCHIVE_PATH = NFL_DIR / "stadiums_2026_v2026.1.json"
# sha256 of the v2026.1 registry file bytes: the fingerprint run records
# captured before the v2026.2 cleanup (registry_sha256 / stadium_registry_sha256).
V2026_1_REGISTRY_SHA256 = "725225dac935b51162e71d83079737ced666e697ec1b13caeaec6edf98607ab7"

NOW = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
KICK = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


def test_current_registry_is_v2026_2_with_sofi_fixed():
    registry = load_stadium_registry()
    assert registry["version"] == "2026.2"
    assert len(registry["stadiums"]) == 30
    sofi = registry["stadiums"]["sofi"]
    assert sofi.roof_type == "FIXED"
    # FIXED roof resolves to a CLOSED roof decision with no external feed.
    assert resolve_roof_decision(sofi, None) == "CLOSED"


def test_unverified_bearings_are_unknown_never_zero():
    registry = load_stadium_registry()
    bearings = {sid: row.field_bearing_deg for sid, row in registry["stadiums"].items()}
    assert sum(1 for value in bearings.values() if value is None) == 28
    assert bearings["arrowhead"] == 45.0
    assert bearings["metlife"] == 15.0
    assert all(value != 0.0 for value in bearings.values())


def test_v2026_1_fingerprint_still_resolves():
    raw = ARCHIVE_PATH.read_bytes()
    assert sha256(raw).hexdigest() == V2026_1_REGISTRY_SHA256
    registry = load_stadium_registry(ARCHIVE_PATH)
    assert registry["version"] == "2026.1"
    assert registry["registry_sha256"] == V2026_1_REGISTRY_SHA256
    # The archived version resolves to the data exactly as recorded.
    assert registry["stadiums"]["sofi"].roof_type == "OPEN_AIR"
    assert (
        sum(1 for row in registry["stadiums"].values() if row.field_bearing_deg == 0.0)
        == 28
    )
    assert load_stadium_registry()["registry_sha256"] != V2026_1_REGISTRY_SHA256


def test_manifest_serializes_unknown_bearings():
    manifest = stadium_registry_manifest(load_stadium_registry())
    assert manifest["version"] == "2026.2"
    assert manifest["stadiums"]["sofi"]["roof_type"] == "FIXED"
    assert manifest["stadiums"]["highmark"]["field_bearing_deg"] is None
    json.dumps(manifest)  # must stay JSON-serializable for run records


def _record(bearing):
    return StadiumRecord(
        stadium_id="test",
        name="Test Stadium",
        team_ids=("TST",),
        lat=41.0,
        lon=-87.0,
        field_bearing_deg=bearing,
        roof_type="OPEN_AIR",
        timezone_name="America/Chicago",
        typical_home_kickoff_hour_local=12.0,
        version="2026.2",
    )


def test_record_validate_accepts_unknown_and_rejects_out_of_range():
    assert _record(None).validate().field_bearing_deg is None
    assert _record(0.0).validate().field_bearing_deg == 0.0
    with pytest.raises(NFLContextError, match="bearing"):
        _record(360.0).validate()


def test_rotate_wind_to_field_refuses_unknown_bearing():
    with pytest.raises(NFLContextError, match="bearing unknown"):
        rotate_wind_to_field(wind_speed_mph=10, wind_dir_deg=180, field_bearing_deg=None)


def test_weather_provider_fails_closed_on_unknown_bearing():
    nws = {
        "properties": {
            "periods": [
                {
                    "startTime": KICK.isoformat(),
                    "temperature": 55,
                    "windSpeedMph": 12,
                    "windDirDeg": 270,
                }
            ]
        }
    }
    kwargs = dict(
        game_id="g1",
        kickoff=KICK,
        as_of=NOW,
        nws_payload=nws,
        source_uri="https://api.weather.gov/gridpoints/TEST/1,1/forecast/hourly",
        source_sha256="a" * 64,
    )
    unknown = build_weather_roof_provider(stadium=_record(None), **kwargs)["payload"]
    assert unknown["wind_speed_mph"] == 12.0
    assert unknown["wind_dir_deg"] == 270.0
    # No bearing adjustment is fabricated against a placeholder orientation.
    assert unknown["wind_relative"] is None

    known = build_weather_roof_provider(stadium=_record(45.0), **kwargs)["payload"]
    assert isinstance(known["wind_relative"], dict)
    assert known["wind_relative"]["speed_mph"] == 12.0


def test_null_bearing_stadium_from_registry_produces_no_wind_relative():
    """Required form: a null-bearing stadium loaded from the NEW registry,
    taken through the weather context path, produces NO wind_relative —
    the unknown never becomes a 0-degree rotation."""
    registry = load_stadium_registry()
    highmark = registry["stadiums"]["highmark"]
    assert highmark.field_bearing_deg is None
    nws = {
        "properties": {
            "periods": [
                {
                    "startTime": KICK.isoformat(),
                    "temperature": 63,
                    "windSpeedMph": 8,
                    "windDirDeg": 270,
                }
            ]
        }
    }
    payload = build_weather_roof_provider(
        game_id="g1",
        stadium=highmark,
        kickoff=KICK,
        as_of=NOW,
        nws_payload=nws,
        source_uri="https://api.weather.gov/gridpoints/BUF/1,1/forecast/hourly",
        source_sha256="a" * 64,
    )["payload"]
    assert payload["wind_speed_mph"] == 8.0
    assert payload["wind_dir_deg"] == 270.0
    assert payload["wind_relative"] is None


def test_loader_rejects_non_numeric_bearing(tmp_path):
    row = {
        "stadium_id": "x",
        "name": "X Stadium",
        "team_ids": ["TST"],
        "lat": 41.0,
        "lon": -87.0,
        "roof_type": "OPEN_AIR",
        "timezone": "America/Chicago",
        "typical_home_kickoff_hour_local": 12.0,
    }
    for bad in ("north", True, [45]):
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({"version": "test", "stadiums": [dict(row, field_bearing_deg=bad)]}))
        with pytest.raises(NFLContextError, match="bearing"):
            load_stadium_registry(path)
    good = tmp_path / "registry.json"
    good.write_text(json.dumps({"version": "test", "stadiums": [dict(row, field_bearing_deg=None)]}))
    assert load_stadium_registry(good)["stadiums"]["x"].field_bearing_deg is None

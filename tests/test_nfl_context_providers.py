from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.context_providers import (
    StadiumRecord,
    build_official_injury_provider,
    build_rest_travel_provider,
    build_weather_roof_provider,
    build_workload_leash_provider,
    resolve_roof_decision,
    rotate_wind_to_field,
)

NOW = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
KICK = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


def stadium(roof_type="OPEN_AIR"):
    return StadiumRecord(
        stadium_id="test",
        name="Test Stadium",
        team_ids=("TST",),
        lat=41.0,
        lon=-87.0,
        field_bearing_deg=0.0,
        roof_type=roof_type,
        timezone_name="America/Chicago",
        typical_home_kickoff_hour_local=12.0,
        version="2026.1",
    )


def test_fixed_roof_is_closed_without_authoritative_feed():
    assert resolve_roof_decision(stadium("FIXED"), None) == "CLOSED"


def test_retractable_without_authoritative_feed_is_missing_decision():
    assert resolve_roof_decision(stadium("RETRACTABLE"), None) == "MISSING_ROOF_DECISION"


def test_missing_weather_fields_stay_none_not_zero():
    nws = {"properties": {"periods": [{"startTime": KICK.isoformat(), "temperature": 72}]}}
    row = build_weather_roof_provider(
        game_id="g1",
        stadium=stadium(),
        kickoff=KICK,
        as_of=NOW,
        nws_payload=nws,
        source_uri="https://api.weather.gov/gridpoints/TEST/1,1/forecast/hourly",
        source_sha256="a" * 64,
    )
    payload = row["payload"]
    assert payload["wind_speed_mph"] is None
    assert payload["wind_dir_deg"] is None
    assert payload["precip_prob"] is None
    assert payload["humidity"] is None


def test_wind_rotation_produces_relative_components():
    out = rotate_wind_to_field(wind_speed_mph=10, wind_dir_deg=180, field_bearing_deg=0)
    assert out["speed_mph"] == 10
    assert abs(out["along_field_mph"] - 10) < 1e-9


def test_nonofficial_injury_source_is_rejected():
    with pytest.raises(NFLContextError, match="official"):
        build_official_injury_provider(
            game_id="g1", team_id="TST", player_id="p1", as_of=NOW,
            source_uri="https://example.com/report",
            source_payload={"status": "QUESTIONABLE", "practice_history": {}},
            official_source=False,
        )


def test_future_injury_report_fails_pit():
    with pytest.raises(NFLContextError, match="after PIT"):
        build_official_injury_provider(
            game_id="g1", team_id="TST", player_id="p1", as_of=NOW,
            source_uri="https://www.nfl.com/injuries/",
            source_payload={
                "status": "QUESTIONABLE",
                "practice_history": {"FRI": "LP"},
                "report_ts": datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc).isoformat(),
            },
            official_source=True,
        )


def test_rest_travel_is_schedule_derived_and_missing_stays_missing():
    row = build_rest_travel_provider(
        game_id="g1", team_id="TST", as_of=NOW,
        source_uri="https://example.com/official-schedule.json",
        source_payload={
            "kickoff_ts": KICK.isoformat(),
            "previous_kickoff_ts": datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc).isoformat(),
            "previous_lat": 41.0,
            "previous_lon": -87.0,
            "current_lat": 40.0,
            "current_lon": -74.0,
            "consec_road": 2,
            "tz_shift_hours": 1,
            "neutral_or_intl": False,
        },
    )
    payload = row["payload"]
    assert payload["days_rest"] == 5
    assert payload["short_week"] is True
    assert payload["body_clock_offset"] is None
    assert payload["travel_distance_km"] > 0


def test_workload_leash_is_additive_and_not_zero_filled():
    row = build_workload_leash_provider(
        game_id="g1", player_id="p1", team_id="TST", as_of=NOW,
        source_uri="https://example.com/pit-snaps.json",
        source_payload={
            "snaps": [42, 50, 55, 58, 60],
            "snap_share": [0.61, 0.67, 0.72],
            "targets": [5, 7, 8],
        },
        injury_ramp_state=False,
        short_week=True,
    )
    payload = row["payload"]
    assert payload["snaps_median_5"] == 55
    assert payload["routes_median_3"] is None
    assert payload["projected_snap_band"] is not None
    assert payload["snap_share_trend"] == pytest.approx(0.11)

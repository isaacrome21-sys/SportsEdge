from sportsedge.mlb_context_forward_capture import capture_training_row


def _bundle():
    return {
        "game_pk": 1,
        "as_of_utc": "2026-10-07T17:00:00+00:00",
        "starters": {
            "status": "AVAILABLE",
            "probable_pitchers": {
                "away": {"player_id": 11},
                "home": {"player_id": 22},
            },
        },
        "lineups": {
            "status": "AVAILABLE",
            "complete_by_side": {"away": True, "home": True},
        },
        "injuries_scratches": {"status": "AVAILABLE"},
        "umpire": {"status": "AVAILABLE", "home_plate_games": 30},
        "statcast": {"status": "AVAILABLE"},
        "park_venue": {"status": "AVAILABLE", "roof_type": "Open"},
        "weather_roof": {"status": "AVAILABLE", "temperature_f": 70},
        "bullpen_workload": {"status": "AVAILABLE"},
        "hybrid_dk": {"quotes": [{"american_odds": -110}]},
    }


def test_capture_requires_strict_pregame_time():
    try:
        capture_training_row(
            _bundle(),
            game_date="2026-10-07",
            first_pitch_utc="2026-10-07T18:00:00Z",
            captured_at_utc="2026-10-07T18:00:00Z",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected pregame rejection")


def test_capture_manifest_is_price_blind():
    row = capture_training_row(
        _bundle(),
        game_date="2026-10-07",
        first_pitch_utc="2026-10-07T18:00:00Z",
        captured_at_utc="2026-10-07T17:00:00Z",
    )
    assert row["pit_strict"] is True
    assert row["contains_sportsbook_prices"] is False
    assert "hybrid_dk" not in str(row)
    assert row["capture_sha256"]


def test_capture_accepts_equivalent_timezone_offsets():
    row = capture_training_row(
        _bundle(),
        game_date="2026-10-07",
        first_pitch_utc="2026-10-07T13:00:00-05:00",
        captured_at_utc="2026-10-07T12:00:00-05:00",
    )
    assert row["first_pitch_utc"] == "2026-10-07T18:00:00+00:00"
    assert row["captured_at_utc"] == "2026-10-07T17:00:00+00:00"

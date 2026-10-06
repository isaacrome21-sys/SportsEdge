from datetime import date, datetime, timezone

from sportsedge.mlb_statcast_preview_source import pitcher_context
from sportsedge.statcast_daily_source import aggregate_statcast


NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)


def _pitch(description, zone, *, event="", stand="R", p_throws="R"):
    return {
        "game_date": "2026-10-05",
        "batter": "101",
        "pitcher": "501",
        "events": event,
        "description": description,
        "stand": stand,
        "p_throws": p_throws,
        "zone": zone,
        "release_speed": 94.0,
    }


def test_pitcher_snapshot_adds_whiff_chase_and_hand_without_model_output():
    rows = [
        _pitch("swinging_strike", 12),
        _pitch("foul", 13),
        _pitch("ball", 11),
        _pitch("swinging_strike_blocked", 5),
        _pitch("hit_into_play", 1, event="single"),
    ]
    _batters, pitchers = aggregate_statcast(
        rows,
        start_date=date(2026, 9, 6),
        end_date=date(2026, 10, 6),
        retrieved_at=NOW,
    )
    assert len(pitchers) == 1
    row = pitchers[0]
    assert row["entity_id"] == "501"
    assert row["swings"] == 4
    assert row["whiffs"] == 2
    assert row["whiff_rate"] == 0.5
    assert row["out_of_zone_pitches"] == 3
    assert row["chases"] == 2
    assert row["chase_rate"] == 0.666667
    assert row["pitcher_hand"] == "R"
    assert "model_p" not in row


def test_pitcher_context_surfaces_skill_observations_only():
    context = pitcher_context({
        "entity_id": "501",
        "whiff_rate": 0.31,
        "chase_rate": 0.29,
        "swings": 210,
        "whiffs": 65,
        "out_of_zone_pitches": 180,
        "chases": 52,
        "pitcher_hand": "L",
        "window_start": "2026-09-06",
        "window_end": "2026-10-06",
    })
    assert context["whiff_rate"] == 0.31
    assert context["chase_rate"] == 0.29
    assert context["pitcher_hand"] == "L"
    assert "model_p" not in context


def test_missing_zone_or_swing_data_fails_to_none_rates_not_fake_zero_skill():
    rows = [
        _pitch("called_strike", None),
        _pitch("ball", None),
    ]
    _batters, pitchers = aggregate_statcast(
        rows,
        start_date=date(2026, 9, 6),
        end_date=date(2026, 10, 6),
        retrieved_at=NOW,
    )
    row = pitchers[0]
    assert row["swings"] == 0
    assert row["whiffs"] == 0
    assert row["whiff_rate"] is None
    assert row["out_of_zone_pitches"] == 0
    assert row["chases"] == 0
    assert row["chase_rate"] is None


def test_inconsistent_pitcher_hand_is_not_asserted():
    rows = [
        _pitch("called_strike", 5, p_throws="R"),
        _pitch("called_strike", 5, p_throws="L"),
    ]
    _batters, pitchers = aggregate_statcast(
        rows,
        start_date=date(2026, 9, 6),
        end_date=date(2026, 10, 6),
        retrieved_at=NOW,
    )
    assert pitchers[0]["pitcher_hand"] is None

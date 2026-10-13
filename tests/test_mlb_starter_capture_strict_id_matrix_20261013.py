"""Offline adversarial strict-identity matrix for #2168 composed starter capture.

59 independent parameterized cases; no HTTP, no live capture or evidence
promotion. The only permitted StatsAPI identity is a positive JSON integer
that is not a boolean. A present malformed probable is ID_MISSING, not
NOT_ANNOUNCED. The old append/verify battery is independent and retained.
"""
import json
from datetime import datetime, timezone

import pytest

from sportsedge.sports.mlb.starter_capture import (
    parse_schedule_games, build_plan, capture_snapshot,
)
from tests.test_mlb_starter_capture_20261013 import (
    GAME1_PK, GAME1_PITCH, AWAY_TEAM, HOME_TEAM, AWAY_PROB, HOME_PROB,
    _game, _game1_plan, _payload, _static_fetcher, FakeClock,
)

# Ten disallowed coerced/malformed IDs. Must fail without raising.
BAD_IDS = [0, -3, True, False, "123", 12.5, "abc", None, "", 0.0]


@pytest.mark.parametrize("side", ["away", "home"])
@pytest.mark.parametrize("value", BAD_IDS, ids=[
    "zero", "negative", "true", "false", "numeric-string",
    "fractional", "nonnumeric-string", "null", "empty", "float-zero",
])
def test_present_probable_bad_id_fails_record(side, value):
    _, plan_game = _game1_plan()
    game = _game(GAME1_PK, GAME1_PITCH)
    game["teams"][side]["probablePitcher"] = {"id": value, "fullName": "Ignore Me"}
    raw = json.dumps(_payload(game)).encode()
    record = capture_snapshot(
        plan_game, "T-30M", fetcher=_static_fetcher(raw),
        clock=FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=timezone.utc)),
    )
    assert record["record_status"] == "FAILED"
    assert record["failure_reason"] == "PROBABLE_PITCHER_ID_MISSING:" + side.upper()
    assert record[side + "_probable_id"] is None
    assert record[side + "_probable_status"] == "ID_MISSING"


@pytest.mark.parametrize("side", ["away", "home"])
@pytest.mark.parametrize("value", BAD_IDS)
def test_invalid_team_id_fails_planning(side, value):
    game = _game(GAME1_PK, GAME1_PITCH)
    game["teams"][side]["team"]["id"] = value
    payload = _payload(game)
    row = parse_schedule_games(payload)[0]
    assert row[side + "_team_id"] is None
    plan = build_plan(payload, planned_at=datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert plan["games"] == []
    assert plan["issues"] == [{"game_pk": GAME1_PK, "reason": "TEAM_ID_MISSING"}]


@pytest.mark.parametrize("value", [
    "Anonymous Pitcher", ["Name", 123], 0, 99, True, False,
    {}, {"fullName": "Name Only"},
])
def test_present_malformed_probable_never_becomes_not_announced(value):
    _, plan_game = _game1_plan()
    game = _game(GAME1_PK, GAME1_PITCH)
    game["teams"]["away"]["probablePitcher"] = value
    row = parse_schedule_games(_payload(game))[0]
    assert row["away_probable"] == {"present": True, "id": None}
    record = capture_snapshot(
        plan_game, "T-30M",
        fetcher=_static_fetcher(json.dumps(_payload(game)).encode()),
        clock=FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=timezone.utc)),
    )
    assert record["away_probable_status"] == "ID_MISSING"
    assert record["record_status"] == "FAILED"


@pytest.mark.parametrize("value", BAD_IDS)
def test_invalid_game_pk_cannot_be_bound_or_planned(value):
    game = _game(GAME1_PK, GAME1_PITCH)
    game["gamePk"] = value
    assert parse_schedule_games(_payload(game)) == []
    plan = build_plan(_payload(game), planned_at=datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert plan["games"] == []


def test_valid_positive_integer_identity_unmodified():
    game = _game(GAME1_PK, GAME1_PITCH)
    rows = parse_schedule_games(_payload(game))
    assert len(rows) == 1
    row = rows[0]
    assert row["game_pk"] == GAME1_PK
    assert row["away_team_id"] == AWAY_TEAM
    assert row["home_team_id"] == HOME_TEAM
    assert row["away_probable"] == {"present": True, "id": AWAY_PROB}
    assert row["home_probable"] == {"present": True, "id": HOME_PROB}


# Separate fixture/status fail-closed regressions, composed after the strict-ID
# matrix. None weakens or modifies the 59 existing identity cases.
def _fixture_capture(game):
    _, plan_game = _game1_plan()
    return capture_snapshot(
        plan_game, "T-30M",
        fetcher=_static_fetcher(json.dumps(_payload(game)).encode()),
        clock=FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=timezone.utc)),
    )


def test_duplicate_gamepk_rejected_in_plan_and_capture():
    game = _game(GAME1_PK, GAME1_PITCH)
    payload = _payload(game, game)
    plan = build_plan(payload, planned_at=datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert plan["games"] == []
    assert plan["issues"] == [{"game_pk": GAME1_PK, "reason": "DUPLICATE_GAME_PK"}]
    _, plan_game = _game1_plan()
    record = capture_snapshot(
        plan_game, "T-30M",
        fetcher=_static_fetcher(json.dumps(payload).encode()),
        clock=FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=timezone.utc)),
    )
    assert record["record_status"] == "FAILED"
    assert record["failure_reason"] == "DUPLICATE_GAME_PK_IN_RESPONSE"


def test_unrecognized_game_type_cannot_be_planned_or_bound():
    game = _game(GAME1_PK, GAME1_PITCH)
    game["gameType"] = "X"
    plan = build_plan(_payload(game), planned_at=datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert plan["games"] == []
    assert plan["issues"] == [{"game_pk": GAME1_PK, "reason": "GAME_TYPE_UNRECOGNIZED"}]
    record = _fixture_capture(game)
    assert record["record_status"] == "FAILED"
    assert record["failure_reason"] == "GAME_TYPE_UNRECOGNIZED"


@pytest.mark.parametrize("kind,reason", [
    ("away", "FIXTURE_TEAM_ID_MISMATCH"),
    ("home", "FIXTURE_TEAM_ID_MISMATCH"),
    ("first_pitch", "FIXTURE_FIRST_PITCH_MISMATCH"),
    ("official_date", "FIXTURE_OFFICIAL_DATE_MISMATCH"),
    ("game_type", "FIXTURE_GAME_TYPE_MISMATCH"),
    ("doubleheader", "FIXTURE_DOUBLEHEADER_MISMATCH"),
    ("game_number", "FIXTURE_GAME_NUMBER_MISMATCH"),
])
def test_same_gamepk_hostile_fixture_drift_fails_closed(kind, reason):
    from datetime import timedelta
    game = _game(GAME1_PK, GAME1_PITCH)
    if kind in ("away", "home"):
        game["teams"][kind]["team"]["id"] = 999999
    elif kind == "first_pitch":
        game["gameDate"] = (GAME1_PITCH + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif kind == "official_date":
        game["officialDate"] = "2026-10-14"
    elif kind == "game_type":
        game["gameType"] = "W"  # allowed type, but not the planned R
    elif kind == "doubleheader":
        game["doubleHeader"] = "Y"
    elif kind == "game_number":
        game["gameNumber"] = 2
    record = _fixture_capture(game)
    assert record["record_status"] == "FAILED"
    assert record["failure_reason"] == reason


@pytest.mark.parametrize("status", [
    {"codedGameState": "I", "detailedState": "In Progress", "abstractGameState": "Live"},
    {"codedGameState": "F", "detailedState": "Final", "abstractGameState": "Final"},
    {"codedGameState": "D", "detailedState": "Postponed", "abstractGameState": "Preview"},
    {"codedGameState": "S", "detailedState": "In Progress", "abstractGameState": "Preview"},
    {"codedGameState": "S", "detailedState": "Suspended", "abstractGameState": "Preview"},
    {},
])
def test_live_final_postponed_or_missing_status_is_not_pregame(status):
    game = _game(GAME1_PK, GAME1_PITCH)
    game["status"] = status
    record = _fixture_capture(game)
    # A future *scheduled* gameDate is not proof the game is pregame.
    assert record["minutes_to_first_pitch"] == 30.0
    assert record["record_status"] == "FAILED"
    assert record["failure_reason"] == "GAME_STATUS_NOT_PREGAME"

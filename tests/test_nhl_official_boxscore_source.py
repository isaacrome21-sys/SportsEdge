from __future__ import annotations

import pytest

from sportsedge.sports.nhl.official_boxscore_source import (
    BOXSCORE_ENDPOINT,
    build_official_completed_game,
    completed_game_from_json_dict,
    dataset_sha256,
    raw_sha256,
)


def _payload() -> dict:
    return {
        "id": 2026020001,
        "season": 20262027,
        "gameType": 2,
        "gameDate": "2026-10-08",
        "startTimeUTC": "2026-10-08T23:00:00Z",
        "gameState": "OFF",
        "awayTeam": {
            "id": 1, "abbrev": "AAA", "score": 3, "sog": 29,
            "powerPlayConversion": "1/4",
        },
        "homeTeam": {
            "id": 2, "abbrev": "BBB", "score": 4, "sog": 34,
            "powerPlayConversion": "2/5",
        },
        "boxscore": {
            "linescore": {
                "byPeriod": [
                    {"period": 1, "periodDescriptor": {"number": 1, "periodType": "REG"}, "away": 1, "home": 1},
                    {"period": 2, "periodDescriptor": {"number": 2, "periodType": "REG"}, "away": 1, "home": 0},
                    {"period": 3, "periodDescriptor": {"number": 3, "periodType": "REG"}, "away": 1, "home": 2},
                    {"period": 4, "periodDescriptor": {"number": 4, "periodType": "OT"}, "away": 0, "home": 1},
                ]
            },
            "playerByGameStats": {
                "awayTeam": {
                    "goalies": [
                        {"playerId": 101, "goalsAgainst": 4, "saveShotsAgainst": "30/34", "toi": "61:12"}
                    ]
                },
                "homeTeam": {
                    "goalies": [
                        {"playerId": 202, "goalsAgainst": 3, "saveShotsAgainst": "26/29", "toi": "61:12"}
                    ]
                },
            },
        },
    }


def _receipt():
    return build_official_completed_game(
        payload=_payload(),
        captured_at="2026-10-09T02:00:00Z",
        raw_sha256="a" * 64,
        source_uri=BOXSCORE_ENDPOINT.format(game_id="2026020001"),
        source_version="fixture-v1",
    )


def test_completed_game_separates_regulation_from_final_and_binds_raw_source():
    game = _receipt()
    assert game.away_regulation_goals == 3
    assert game.home_regulation_goals == 3
    assert game.away_final_goals == 3
    assert game.home_final_goals == 4
    assert game.away_pp_goals == 1 and game.away_pp_opportunities == 4
    assert game.home_pp_goals == 2 and game.home_pp_opportunities == 5
    assert game.away_goalies[0].shots_against == 34
    assert game.away_goalies[0].saves == 30
    assert game.source_raw_sha256 == "a" * 64


def test_completed_game_round_trip_and_dataset_hash_are_deterministic():
    game = _receipt()
    restored = completed_game_from_json_dict(game.as_json_dict())
    assert restored == game
    assert dataset_sha256([game]) == dataset_sha256([restored])
    assert raw_sha256(b"official raw bytes") == raw_sha256(b"official raw bytes")


def test_nonfinal_boxscore_fails_closed():
    payload = _payload()
    payload["gameState"] = "LIVE"
    with pytest.raises(ValueError, match="not final"):
        build_official_completed_game(
            payload=payload,
            captured_at="2026-10-09T02:00:00Z",
            raw_sha256="b" * 64,
        )


def test_incomplete_regulation_linescore_fails_closed():
    payload = _payload()
    payload["boxscore"]["linescore"]["byPeriod"] = payload["boxscore"]["linescore"]["byPeriod"][:2]
    with pytest.raises(ValueError, match="periods 1-3"):
        build_official_completed_game(
            payload=payload,
            captured_at="2026-10-09T02:00:00Z",
            raw_sha256="c" * 64,
        )


def test_wrong_source_uri_or_bad_hash_fails_closed():
    with pytest.raises(ValueError, match="Gamecenter boxscore URI"):
        build_official_completed_game(
            payload=_payload(), captured_at="2026-10-09T02:00:00Z",
            raw_sha256="d" * 64, source_uri="https://example.com/boxscore",
        )
    with pytest.raises(ValueError, match="SHA-256"):
        build_official_completed_game(
            payload=_payload(), captured_at="2026-10-09T02:00:00Z",
            raw_sha256="not-a-hash",
        )


# --- Live Gamecenter shape (recorded 2026-10-26, game 2026020168 ANA @ PHI) ---
# The live boxscore payload has NO nested "boxscore" object and no
# powerPlayConversion; period scoring lives only in the landing payload.
# Fixtures are the verbatim API responses, not synthetic reconstructions.

import json
from pathlib import Path

_FIXTURES = Path(__file__).parent / "fixtures"


def _live_payloads():
    boxscore = json.loads((_FIXTURES / "nhl_gamecenter_2026020168_boxscore.json").read_text())
    landing = json.loads((_FIXTURES / "nhl_gamecenter_2026020168_landing.json").read_text())
    return boxscore, landing


def test_live_shape_parses_with_landing_payload():
    boxscore, landing = _live_payloads()
    assert "boxscore" not in boxscore  # the shape that broke the old parser
    game = build_official_completed_game(
        payload=boxscore,
        captured_at="2026-10-26T15:00:00Z",
        raw_sha256="e" * 64,
        source_version="nhl-web-api-v1-live2",
        landing_payload=landing,
    )
    assert game.game_id == "2026020168"
    assert (game.away_abbrev, game.home_abbrev) == ("ANA", "PHI")
    assert (game.away_final_goals, game.home_final_goals) == (5, 4)
    assert (game.away_regulation_goals, game.home_regulation_goals) == (5, 4)
    assert (game.away_sog, game.home_sog) == (26, 32)
    # Exact PP goals from per-goal strength; opportunities exist in no live
    # payload, so they stay None (receipt invariant allows goals-only).
    assert game.away_pp_goals == 1 and game.away_pp_opportunities is None
    assert game.home_pp_goals == 2 and game.home_pp_opportunities is None
    assert any(g.player_id == "8480843" and g.goals_against == 4 for g in game.away_goalies)


def test_live_shape_without_landing_fails_closed():
    boxscore, _ = _live_payloads()
    with pytest.raises(ValueError, match="official boxscore object required"):
        build_official_completed_game(
            payload=boxscore,
            captured_at="2026-10-26T15:00:00Z",
            raw_sha256="f" * 64,
        )


def test_live_shape_scoring_mismatch_fails_closed():
    boxscore, landing = _live_payloads()
    landing["summary"]["scoring"][0]["goals"] = []
    with pytest.raises(ValueError, match="does not reconcile"):
        build_official_completed_game(
            payload=boxscore,
            captured_at="2026-10-26T15:00:00Z",
            raw_sha256="a" * 64,
            landing_payload=landing,
        )

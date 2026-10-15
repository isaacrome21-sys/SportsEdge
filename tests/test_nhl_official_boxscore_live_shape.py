"""RED tests: live NHL Gamecenter feed splits boxscore / right-rail.

Live /boxscore has top-level ``playerByGameStats`` and no ``boxscore`` key;
the regulation linescore lives in /right-rail.  The parser must accept that
split shape with separately hashed provenance, and still fail closed.
"""
from __future__ import annotations

import copy

import pytest

from sportsedge.sports.nhl.official_boxscore_source import (
    BOXSCORE_ENDPOINT,
    RIGHT_RAIL_ENDPOINT,
    build_official_completed_game,
    completed_game_from_json_dict,
    dataset_sha256,
)

from tests.test_nhl_official_boxscore_source import _payload, _receipt


def _live():
    legacy = _payload()
    box = legacy.pop("boxscore")
    legacy["playerByGameStats"] = box["playerByGameStats"]
    rail = {"linescore": box["linescore"]}
    return legacy, rail


def _build(payload, rail, **kw):
    args = dict(
        payload=payload,
        captured_at="2026-10-09T02:00:00Z",
        raw_sha256="a" * 64,
        source_uri=BOXSCORE_ENDPOINT.format(game_id="2026020001"),
        source_version="fixture-v1",
        right_rail_payload=rail,
        right_rail_raw_sha256="b" * 64,
    )
    args.update(kw)
    return build_official_completed_game(**args)


def test_live_split_shape_matches_legacy_values():
    payload, rail = _live()
    live = _build(payload, rail)
    legacy = _receipt()
    assert live.away_regulation_goals == legacy.away_regulation_goals == 3
    assert live.home_regulation_goals == legacy.home_regulation_goals == 3
    assert live.away_goalies == legacy.away_goalies
    assert live.home_goalies == legacy.home_goalies
    assert live.right_rail_uri == RIGHT_RAIL_ENDPOINT.format(game_id="2026020001")
    assert live.right_rail_raw_sha256 == "b" * 64


def test_live_shape_without_right_rail_fails_closed():
    payload, _ = _live()
    with pytest.raises(ValueError):
        build_official_completed_game(
            payload=payload, captured_at="2026-10-09T02:00:00Z", raw_sha256="a" * 64,
        )


def test_right_rail_requires_valid_hash():
    payload, rail = _live()
    with pytest.raises(ValueError):
        _build(payload, rail, right_rail_raw_sha256="nothex")


def test_right_rail_for_wrong_game_fails_closed():
    payload, rail = _live()
    rail = copy.deepcopy(rail)
    rail["gameInfo"] = {"id": 2026020999}
    with pytest.raises(ValueError):
        _build(payload, rail)


def test_live_receipt_round_trips_and_legacy_hash_unchanged():
    payload, rail = _live()
    live = _build(payload, rail)
    assert completed_game_from_json_dict(live.as_json_dict()) == live
    legacy = _receipt()
    d = legacy.as_json_dict()
    assert "right_rail_uri" not in d and "right_rail_raw_sha256" not in d
    assert dataset_sha256([legacy]) == dataset_sha256([completed_game_from_json_dict(d)])

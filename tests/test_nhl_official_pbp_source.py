from __future__ import annotations

import pytest

from sportsedge.sports.nhl.official_pbp_source import (
    canonical_payload_sha256,
    decode_situation_code,
    materialize_staged_shots,
    stage_official_nhl_pbp,
)


def _play(event_id, sort_order, time, kind, team=None, x=None, y=None, *,
          shooter=None, scorer=None, goalie=99, shot_type="wrist", situation="1551",
          defending="left", period=1):
    details = {}
    if team is not None:
        details["eventOwnerTeamId"] = team
    if x is not None:
        details["xCoord"] = x
    if y is not None:
        details["yCoord"] = y
    if shooter is not None:
        details["shootingPlayerId"] = shooter
    if scorer is not None:
        details["scoringPlayerId"] = scorer
    if goalie is not None:
        details["goalieInNetId"] = goalie
    if kind in {"shot-on-goal", "goal", "missed-shot"}:
        details["shotType"] = shot_type
    return {
        "eventId": event_id,
        "sortOrder": sort_order,
        "periodDescriptor": {"number": period},
        "timeInPeriod": time,
        "typeDescKey": kind,
        "situationCode": situation,
        "homeTeamDefendingSide": defending,
        "details": details,
    }


def _payload():
    return {
        "id": 2026020001,
        "homeTeam": {"id": 1},
        "awayTeam": {"id": 2},
        "plays": [
            _play(1, 1, "01:00", "takeaway", team=1, x=0, y=0),
            _play(2, 2, "01:03", "shot-on-goal", team=1, x=70, y=4, shooter=10),
            _play(3, 3, "01:05", "goal", team=1, x=76, y=2, scorer=11),
            _play(4, 4, "01:06", "faceoff", team=1, x=0, y=0),
            _play(5, 5, "01:07", "shot-on-goal", team=1, x=72, y=-3, shooter=12),
        ],
    }


def _stage(payload=None):
    payload = _payload() if payload is None else payload
    return stage_official_nhl_pbp(
        payload,
        source_uri="https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play",
        raw_sha256="a" * 64,
        source_version="nhl-api-v1",
    )


def test_decodes_official_situation_code():
    assert decode_situation_code("1551", shooter_is_home=True) == "EV"
    assert decode_situation_code("1451", shooter_is_home=True) == "PP"
    assert decode_situation_code("1651", shooter_is_home=True) == "SH"
    assert decode_situation_code("0551", shooter_is_home=True) == "EN"
    with pytest.raises(ValueError, match="malformed"):
        decode_situation_code("55", shooter_is_home=True)


def test_stages_shots_with_frozen_rebound_and_rush_context():
    shots = _stage()
    assert [s.event_id for s in shots] == ["2", "3", "5"]
    first, second, third = shots
    assert first.is_rush is True
    assert first.is_rebound is False
    assert second.is_rebound is True
    assert second.is_rush is False
    assert third.is_rebound is False
    assert third.is_rush is True
    assert second.is_goal is True
    assert first.strength_state == "EV"
    assert first.source_raw_sha256 == "a" * 64


def test_period_boundary_resets_context():
    payload = _payload()
    payload["plays"] = [
        _play(1, 1, "19:59", "shot-on-goal", team=1, x=70, y=0, shooter=10, period=1),
        _play(2, 2, "00:01", "goal", team=1, x=75, y=0, scorer=11, period=2, defending="right"),
    ]
    shots = _stage(payload)
    assert shots[1].is_rebound is False
    assert shots[1].is_rush is False


def test_materialization_blocks_without_absolute_event_utc():
    shots = _stage()
    with pytest.raises(ValueError, match="absolute event UTC missing"):
        materialize_staged_shots(shots, event_time_utc_by_event_id={"2": "2026-10-01T00:01:03Z"})


def test_materializes_only_when_every_absolute_utc_is_supplied():
    shots = _stage()
    out = materialize_staged_shots(
        shots,
        event_time_utc_by_event_id={
            "2": "2026-10-01T00:01:03Z",
            "3": "2026-10-01T00:01:05Z",
            "5": "2026-10-01T00:01:07Z",
        },
    )
    assert [e.event_id for e in out] == ["2", "3", "5"]
    assert out[1].is_goal is True
    assert out[0].source.startswith("https://api-web.nhle.com/")
    assert "raw=" in out[0].source_version


def test_rejects_wrong_source_uri_and_bad_raw_hash():
    payload = _payload()
    with pytest.raises(ValueError, match="official NHL gamecenter"):
        stage_official_nhl_pbp(payload, source_uri="https://example.com/pbp", raw_sha256="a" * 64, source_version="v")
    with pytest.raises(ValueError, match="SHA-256"):
        stage_official_nhl_pbp(
            payload,
            source_uri="https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play",
            raw_sha256="bad",
            source_version="v",
        )


def test_canonical_payload_hash_is_deterministic():
    assert canonical_payload_sha256(_payload()) == canonical_payload_sha256(_payload())
    assert len(canonical_payload_sha256(_payload())) == 64

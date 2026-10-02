from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from sportsedge.canonical_manual_mlb import (
    CanonicalManualMLBError,
    _norm_person,
    _resolve_subject,
)
from sportsedge.manual_quote import ManualQuote
from sportsedge.mlb_source import GameSnapshot


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


def _opener(payload):
    def open_url(_url, timeout=15):
        assert timeout == 15
        return _Response(payload)

    return open_url


def _game() -> GameSnapshot:
    return GameSnapshot(
        game_pk=849848,
        game_date="2026-09-30T23:05:00Z",
        status="Preview",
        away_id=111,
        away_name="Boston Red Sox",
        home_id=147,
        home_name="New York Yankees",
        away_probable_pitcher_id=543243,
        away_probable_pitcher_name="Sonny Gray",
        home_probable_pitcher_id=608331,
        home_probable_pitcher_name="Max Fried",
        retrieved_at="2026-09-30T21:51:00Z",
        official_date="2026-09-30",
    )


def _quote(name: str) -> ManualQuote:
    return ManualQuote(
        game_id="849848",
        market_type="HITS",
        side="OVER",
        line=0.5,
        price=-120,
        paired_side="UNDER",
        paired_price=100,
        book="draftkings",
        observed_at=datetime(2026, 9, 30, 21, 51, tzinfo=timezone.utc),
        first_pitch_at=datetime(2026, 9, 30, 23, 5, tzinfo=timezone.utc),
        source="MANUAL",
        subject_name=name,
    )


def test_person_name_normalization_ignores_accents_and_suffixes():
    assert _norm_person("Luis García Jr.") == _norm_person("Luis Garcia")
    assert _norm_person("Jazz Chisholm Jr.") == _norm_person("Jazz Chisholm")
    assert _norm_person("George Lombard Jr.") == _norm_person("George Lombard")


@pytest.mark.parametrize(
    ("typed_name", "api_name", "person_id"),
    [
        ("Jazz Chisholm", "Jazz Chisholm Jr.", 665862),
        ("George Lombard", "George Lombard Jr.", 807122),
    ],
)
def test_short_sportsbook_name_resolves_canonical_jr_name(typed_name, api_name, person_id):
    payload = {"people": [{"id": person_id, "fullName": api_name, "currentTeam": {"id": 147}}]}
    resolved_id, team_id = _resolve_subject(_quote(typed_name), opener=_opener(payload), game=_game())
    assert resolved_id == str(person_id)
    assert team_id == 147


def test_ambiguous_luis_garcia_is_disambiguated_by_game_team():
    payload = {
        "people": [
            {"id": 999001, "fullName": "Luis Garcia", "currentTeam": {"id": 136}},
            {"id": 999147, "fullName": "Luis García Jr.", "currentTeam": {"id": 147}},
        ]
    }
    resolved_id, team_id = _resolve_subject(_quote("Luis Garcia"), opener=_opener(payload), game=_game())
    assert resolved_id == "999147"
    assert team_id == 147


def test_two_same_name_players_on_game_teams_still_fail_closed():
    payload = {
        "people": [
            {"id": 1, "fullName": "Luis Garcia", "currentTeam": {"id": 111}},
            {"id": 2, "fullName": "Luis García Jr.", "currentTeam": {"id": 147}},
        ]
    }
    with pytest.raises(CanonicalManualMLBError, match="MANUAL_SUBJECT_RESOLUTION_FAILED"):
        _resolve_subject(_quote("Luis Garcia"), opener=_opener(payload), game=_game())

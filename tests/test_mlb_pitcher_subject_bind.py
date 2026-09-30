from datetime import datetime, timezone

import pytest

from sportsedge.canonical_manual_mlb import CanonicalManualMLBError, _resolve_subject
from sportsedge.mlb_lines_intake import parse_lines
from sportsedge.mlb_resolve import build_bound_input
from sportsedge.mlb_source import GameSnapshot
from sportsedge.manual_quote import validate_manual_quote


def _game() -> GameSnapshot:
    return GameSnapshot(
        game_pk=849841,
        game_date="2026-09-30T18:00:00+00:00",
        status="Scheduled",
        away_id=143,
        away_name="Philadelphia Phillies",
        home_id=144,
        home_name="Atlanta Braves",
        away_probable_pitcher_id=661563,
        away_probable_pitcher_name="Cristopher Sánchez",
        home_probable_pitcher_id=641835,
        home_probable_pitcher_name="Tyler Mahle",
        retrieved_at="2026-09-30T10:47:51+00:00",
    )


def test_outs_and_k_names_survive_bind() -> None:
    text = """Phillies @ Braves
Cristopher Sanchez outs 17.5 -174 +130
Tyler Mahle k 5.5 -110 -110
"""
    bound = build_bound_input(
        text,
        observed_at="2026-09-30T10:47:51+00:00",
        schedule=[_game()],
    )
    outs = next(r for r in bound["rows"] if r["market_type"] == "PITCHER_OUTS")
    ks = next(r for r in bound["rows"] if r["market_type"] == "PITCHER_STRIKEOUTS")
    assert outs["subject_name"] == "Cristopher Sanchez"
    assert ks["subject_name"] == "Tyler Mahle"
    assert outs["paired_side"] == "UNDER" and ks["paired_side"] == "UNDER"
    parsed = parse_lines(text)
    assert {r.market_type for r in parsed} == {"PITCHER_OUTS", "PITCHER_STRIKEOUTS"}


def test_probable_starter_resolves_to_id() -> None:
    row = validate_manual_quote({
        "game_id": "Philadelphia Phillies@Atlanta Braves",
        "market_type": "PITCHER_OUTS",
        "side": "OVER",
        "line": 17.5,
        "price": -174,
        "paired_side": "UNDER",
        "paired_price": 130,
        "book": "draftkings",
        "observed_at": "2026-09-30T10:47:51+00:00",
        "first_pitch_at": "2026-09-30T18:00:00+00:00",
        "source": "MANUAL",
        "subject_name": "Cristopher Sanchez",
    })
    person_id, team_id = _resolve_subject(row, game=_game())
    assert person_id == "661563"
    assert team_id == 143


def test_non_starter_is_subject_unresolved() -> None:
    row = validate_manual_quote({
        "game_id": "Philadelphia Phillies@Atlanta Braves",
        "market_type": "PITCHER_K",
        "side": "OVER",
        "line": 5.5,
        "price": -110,
        "paired_side": "UNDER",
        "paired_price": -110,
        "book": "draftkings",
        "observed_at": "2026-09-30T10:47:51+00:00",
        "first_pitch_at": "2026-09-30T18:00:00+00:00",
        "source": "MANUAL",
        "subject_name": "Zack Wheeler",
    })
    with pytest.raises(CanonicalManualMLBError, match="SUBJECT_UNRESOLVED"):
        _resolve_subject(row, game=_game())

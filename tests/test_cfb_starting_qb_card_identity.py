"""Tests for research-only starting-QB card identity attachment."""
from datetime import datetime, timezone, timedelta

from sportsedge.cfb_starting_qb_card_identity import attach_starting_qb_identity


def _now():
    return datetime.now(timezone.utc)


def _kwargs(**overrides):
    base = dict(
        line=-3.5,
        opposite_line=3.5,
        price_american=-110,
        opposite_price_american=-110,
        side_quoted_at=_now(),
        opposite_quoted_at=_now(),
        as_of=_now(),
        event_start=_now() + timedelta(hours=3),
        sportsbook="DraftKings",
        source_ref="dk:card",
        cover_probability=0.53,
        push_probability=0.04,
        loss_probability=0.43,
        model_verified=True,
        model_market_blind=True,
        model_id="CFB_JOINT_MODEL_V1",
        illinois_college_team=False,
    )
    base.update(overrides)
    return base


def test_attach_identity_to_card():
    card = {"home_team": "Alabama", "away_team": "Georgia", "game_id": "401", "week": 8}
    rows = [
        {
            "team": "Alabama",
            "source": "OFFICIAL_TEAM_OR_CONFERENCE",
            "starter_name": "Jalen Milroe",
            "source_url": "https://rolltide.com",
            "game_id": "401",
            "week": 8,
        },
        {
            "team": "Georgia",
            "source": "PRESS_BOX_OR_247_DEPTH_CHART",
            "starter_name": "Carson Beck",
            "source_url": "https://247sports.com",
            "game_id": "401",
            "week": 8,
        },
    ]
    out = attach_starting_qb_identity(card, rows, assess_kwargs=_kwargs())
    ident = out["starting_qb_identity"]
    assert ident["home_qb"]["name"] == "Jalen Milroe"
    assert ident["away_qb"]["name"] == "Carson Beck"
    assert ident["play_authority"] is False
    assert ident["matchup_identity_label"] in ("HIGH", "CONFIRMED")


def test_attach_handles_missing_and_contradictory():
    card = {"home": "Ohio State", "away": "Penn State", "id": "402", "week": 8}
    rows = [
        {
            "team": "Ohio State",
            "source": "OFFICIAL_TEAM_OR_CONFERENCE",
            "starter_name": "Will Howard",
            "source_url": "https://example.com/a",
            "game_id": "402",
            "week": 8,
        },
        {
            "team": "Ohio State",
            "source": "PRESS_BOX_OR_247_DEPTH_CHART",
            "starter_name": "Someone Else",
            "source_url": "https://example.com/b",
            "game_id": "402",
            "week": 8,
        },
    ]
    out = attach_starting_qb_identity(card, rows, assess_kwargs=_kwargs())
    ident = out["starting_qb_identity"]
    assert ident["home_qb"]["label"] == "LOW"
    assert "contradictory" in ident["binding_notes"]
    assert ident["play_authority"] is False

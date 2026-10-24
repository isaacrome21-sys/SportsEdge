"""Tests for research-only CFB starting-QB binding to spread assessments."""
from datetime import datetime, timezone, timedelta

from sportsedge.cfb_starting_qb_spread_binding import bind_starting_qbs_to_spread


def _now():
    return datetime.now(timezone.utc)


def _kwargs(**overrides):
    base = dict(
        line=-7.5,
        opposite_line=7.5,
        price_american=-110,
        opposite_price_american=-110,
        side_quoted_at=_now(),
        opposite_quoted_at=_now(),
        as_of=_now(),
        event_start=_now() + timedelta(hours=2),
        sportsbook="DraftKings",
        source_ref="dk:123",
        cover_probability=0.55,
        push_probability=0.05,
        loss_probability=0.40,
        model_verified=True,
        model_market_blind=True,
        model_id="CFB_JOINT_MODEL_V1",
        illinois_college_team=False,
    )
    base.update(overrides)
    return base


def test_binding_requires_url_for_high_and_scopes_by_team():
    rows = [
        {
            "team": "Alabama",
            "source": "OFFICIAL_TEAM_OR_CONFERENCE",
            "starter_name": "Jalen Milroe",
            "source_url": "https://rolltide.com/depth",
            "game_id": "401",
            "week": 8,
        },
        {
            "team": "Alabama",
            "source": "PROJECTED_OR_OR_LISTED",
            "starter_name": "Backup",
            "game_id": "401",
            "week": 8,
        },
        {
            "team": "Georgia",
            "source": "CFBDEPTH_OR_OURLADS",
            "starter_name": "Carson Beck",
            "game_id": "401",
            "week": 8,
        },
    ]
    bound = bind_starting_qbs_to_spread(
        source_rows=rows,
        home_team="Alabama",
        away_team="Georgia",
        game_id="401",
        week=8,
        assess_kwargs=_kwargs(),
    )
    assert bound.home_qb is not None
    assert bound.home_qb.starter_name == "Jalen Milroe"
    assert bound.home_qb.confidence >= 0.90
    assert bound.away_qb is not None
    assert bound.away_qb.confidence_label == "MODERATE"
    assert bound.play_authority is False
    assert bound.assessment.status in ("WATCH", "PASS")


def test_contradictory_high_confidence_forces_low():
    rows = [
        {
            "team": "Ohio State",
            "source": "OFFICIAL_TEAM_OR_CONFERENCE",
            "starter_name": "Will Howard",
            "source_url": "https://ohiostatebuckeyes.com/depth",
            "game_id": "402",
            "week": 8,
        },
        {
            "team": "Ohio State",
            "source": "PRESS_BOX_OR_247_DEPTH_CHART",
            "starter_name": "Deuce Hogan",
            "source_url": "https://247sports.com/depth",
            "game_id": "402",
            "week": 8,
        },
    ]
    bound = bind_starting_qbs_to_spread(
        source_rows=rows,
        home_team="Ohio State",
        away_team="Penn State",
        game_id="402",
        week=8,
        assess_kwargs=_kwargs(),
    )
    assert bound.home_qb is not None
    assert bound.home_qb.confidence_label == "LOW"
    assert "CONTRADICTORY" in (bound.home_qb.notes or "")
    assert "contradictory_high_confidence_detected" in bound.binding_notes
    assert bound.matchup_identity_label == "LOW"


def test_illinois_still_excluded():
    bound = bind_starting_qbs_to_spread(
        source_rows=[],
        home_team="Illinois",
        away_team="Purdue",
        assess_kwargs=_kwargs(illinois_college_team=True),
    )
    assert bound.assessment.reason == "ILLINOIS_COLLEGE_EXCLUDED"
    assert bound.play_authority is False


def test_empty_rows_and_missing_qb():
    bound = bind_starting_qbs_to_spread(
        source_rows=[],
        home_team="Alabama",
        away_team="Georgia",
        assess_kwargs=_kwargs(),
    )
    assert bound.home_qb is None
    assert bound.away_qb is None
    assert bound.matchup_identity_label == "UNKNOWN"
    assert "home_qb_missing" in bound.binding_notes
    assert "away_qb_missing" in bound.binding_notes


def test_wrong_game_id_excluded():
    rows = [
        {
            "team": "Alabama",
            "source": "OFFICIAL_TEAM_OR_CONFERENCE",
            "starter_name": "Jalen Milroe",
            "source_url": "https://rolltide.com/depth",
            "game_id": "999",
            "week": 8,
        }
    ]
    bound = bind_starting_qbs_to_spread(
        source_rows=rows,
        home_team="Alabama",
        away_team="Georgia",
        game_id="401",
        week=8,
        assess_kwargs=_kwargs(),
    )
    assert bound.home_qb is None


def test_empty_team_names_rejected():
    bound = bind_starting_qbs_to_spread(
        source_rows=[],
        home_team="",
        away_team="Georgia",
        assess_kwargs=_kwargs(),
    )
    assert bound.home_qb is None
    assert bound.away_qb is None
    assert bound.binding_notes == "empty_team_name"
    assert bound.play_authority is False


def test_returned_qbs_always_zero_authority():
    rows = [
        {
            "team": "Alabama",
            "source": "OFFICIAL_TEAM_OR_CONFERENCE",
            "starter_name": "Jalen Milroe",
            "source_url": "https://rolltide.com",
            "game_id": "401",
            "week": 8,
        }
    ]
    bound = bind_starting_qbs_to_spread(
        source_rows=rows,
        home_team="Alabama",
        away_team="Georgia",
        game_id="401",
        week=8,
        assess_kwargs=_kwargs(),
    )
    assert bound.home_qb is not None
    assert bound.home_qb.play_authority is False
    assert bound.home_qb.promotion_authority is False

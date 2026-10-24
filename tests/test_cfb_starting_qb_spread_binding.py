"""Tests for research-only CFB starting-QB binding to spread assessments."""
from datetime import datetime, timezone

from sportsedge.cfb_starting_qb_spread_binding import bind_starting_qbs_to_spread


def _now():
    return datetime.now(timezone.utc)


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
            # no URL — should downgrade
            "game_id": "401",
            "week": 8,
        },
    ]
    kwargs = dict(
        line=-7.5,
        opposite_line=7.5,
        price_american=-110,
        opposite_price_american=-110,
        side_quoted_at=_now(),
        opposite_quoted_at=_now(),
        as_of=_now(),
        event_start=_now().replace(hour=_now().hour + 2),
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
    bound = bind_starting_qbs_to_spread(
        source_rows=rows,
        home_team="Alabama",
        away_team="Georgia",
        game_id="401",
        week=8,
        assess_kwargs=kwargs,
    )
    assert bound.home_qb is not None
    assert bound.home_qb.starter_name == "Jalen Milroe"
    assert bound.home_qb.confidence >= 0.90
    assert bound.away_qb is not None
    assert bound.away_qb.confidence_label == "MODERATE"  # downgraded for missing URL
    assert bound.matchup_identity_label in ("MODERATE", "LOW")
    assert bound.play_authority is False
    assert bound.assessment.status in ("WATCH", "PASS")


def test_illinois_still_excluded():
    kwargs = dict(
        line=-3.5,
        opposite_line=3.5,
        price_american=-110,
        opposite_price_american=-110,
        side_quoted_at=_now(),
        opposite_quoted_at=_now(),
        as_of=_now(),
        event_start=_now().replace(hour=_now().hour + 2),
        sportsbook="DraftKings",
        source_ref="dk:456",
        cover_probability=0.52,
        push_probability=0.04,
        loss_probability=0.44,
        model_verified=True,
        model_market_blind=True,
        model_id="CFB_JOINT_MODEL_V1",
        illinois_college_team=True,
    )
    bound = bind_starting_qbs_to_spread(
        source_rows=[],
        home_team="Illinois",
        away_team="Purdue",
        assess_kwargs=kwargs,
    )
    assert bound.assessment.reason == "ILLINOIS_COLLEGE_EXCLUDED"
    assert bound.play_authority is False

from datetime import datetime, timedelta, timezone
import pytest
from sportsedge.sports.nhl.features import GoalieState, TeamSnapshot, NHLFeatureSnapshot
from sportsedge.sports.nhl.rate_model import NHLRateParameters, game_state_from_snapshot


def snapshot():
    puck = datetime(2026, 10, 10, tzinfo=timezone.utc)
    h = TeamSnapshot("H", 3.1, 2.7, 32, 28, 7, 5.8, 2, 0, .2)
    a = TeamSnapshot("A", 2.8, 3.0, 29, 31, 6, 6.4, 1, 500, -.1)
    g1 = GoalieState("g1", "CONFIRMED", .915, .2, 700)
    g2 = GoalieState("g2", "PROJECTED", .905, -.1, 400)
    return NHLFeatureSnapshot("game", puck, puck-timedelta(hours=2), h, a, g1, g2, "fixture", "v1")


def params():
    return NHLRateParameters("fixture-v1", -2.0, .2, .2, .3, .02, .1, .02, -.0001, .1, .08)


def test_rate_assembly_is_positive_and_deterministic():
    a = game_state_from_snapshot(snapshot(), params())
    b = game_state_from_snapshot(snapshot(), params())
    assert a == b
    assert a.home_regulation_goals > 0
    assert a.away_regulation_goals > 0


def test_requires_versioned_parameters():
    p = params()
    bad = NHLRateParameters("", p.intercept, p.offense_xg, p.opponent_xga, p.shot_share, p.special_teams, p.goalie_gsax, p.rest, p.travel, p.lineup, p.home_ice)
    with pytest.raises(ValueError, match="version"):
        game_state_from_snapshot(snapshot(), bad)

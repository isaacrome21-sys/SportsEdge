from datetime import datetime, timedelta, timezone
import pytest

from sportsedge.sports.nba.binding import NBAQuote, bind_quote
from sportsedge.sports.nba.pricing import path_outcome


def quote(now, odds=2.0):
    return NBAQuote("g1","PLAYER_POINTS","OVER",24.5,odds,"DK",now-timedelta(seconds=30))


def test_bound_score_is_not_probability_and_uses_ev():
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    fair=path_outcome((25,26,27,20),24.5,over=True)
    out=bind_quote(quote(now),fair,as_of=now,model_quality=.8,context_quality=.9)
    assert out.ev > 0
    assert 50 < out.score <= 100
    assert out.score_version == "NBA_RUN_IT_SCORE_V1"


def test_quality_tempers_same_edge():
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    fair=path_outcome((25,26,27,20),24.5,over=True)
    high=bind_quote(quote(now),fair,as_of=now,model_quality=1,context_quality=1)
    low=bind_quote(quote(now),fair,as_of=now,model_quality=.25,context_quality=.25)
    assert high.score > low.score > 50


def test_stale_future_and_bad_quality_fail_closed():
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    fair=path_outcome((1,2,3),1.5)
    with pytest.raises(ValueError): bind_quote(quote(now),fair,as_of=now+timedelta(minutes=10),max_age_seconds=300,model_quality=.8,context_quality=.8)
    future=NBAQuote("g","TOTAL","OVER",220.5,1.91,"DK",now+timedelta(seconds=1))
    with pytest.raises(ValueError): bind_quote(future,fair,as_of=now,model_quality=.8,context_quality=.8)
    with pytest.raises(ValueError): bind_quote(quote(now),fair,as_of=now,model_quality=1.1,context_quality=.8)


def test_quote_requires_timezone_and_valid_odds():
    q=NBAQuote("g","TOTAL","OVER",220.5,1.0,"DK",datetime(2026,1,1))
    with pytest.raises(ValueError): q.validate()

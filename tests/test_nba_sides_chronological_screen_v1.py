from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.research.nba_sides_chronological_screen_v1 import chronological_side_screen


def rows(n=28, quotes=True):
    t=datetime(2025,1,1,tzinfo=timezone.utc)
    out=[]
    for i in range(n):
        dt=t+timedelta(days=i)
        g={"event_id":str(i),"tipoff":dt.isoformat(),
           "observed_at":(dt+timedelta(hours=4)).isoformat(),
           "source_ref":"final-receipt","season":"2025",
           "home":"A","away":"B",
           "home_score":120,"away_score":105}
        if quotes:
            g.update(home_close_spread=-7.5,home_ml=-200,away_ml=+170,
                     close_captured_at=(dt-timedelta(minutes=10)).isoformat(),
                     close_source_ref="market-archive")
        out.append(g)
    return out


def test_walking_side_screen_compares_prices_without_claiming_admission():
    r=chronological_side_screen(rows())
    assert r["games_scored"]>0
    assert r["spread_reference_games"]==r["ml_reference_games"]==r["games_scored"]
    assert r["candidate_margin_rmse"] is not None
    assert r["candidate_ml_brier"] is not None
    assert r["market_admission"]=="NOT_VERIFIED"
    assert r["validation_authority"]=="NONE"


def test_no_quotes_reports_no_market_comparison():
    r=chronological_side_screen(rows(quotes=False))
    assert r["indicative_market_spread_rmse"] is None
    assert r["indicative_market_ml_brier"] is None
    assert r["ml_reference_games"]==0


def test_refuse_one_sided_moneyline():
    g=rows()
    del g[1]["away_ml"]
    with pytest.raises(ValueError,match="ML_PAIR_REQUIRED"):
        chronological_side_screen(g)


def test_refuse_quotes_after_tip():
    g=rows()
    g[0]["close_captured_at"]=g[0]["observed_at"]
    with pytest.raises(ValueError,match="CLOSE_NOT_PRETIP"):
        chronological_side_screen(g)


def test_no_future_outcome_contaminates_older_ratings():
    data=rows()
    # Delaying game 0's result until after the entire slate correctly
    # changes the warmup count. Comparing to the original score count is
    # WRONG: a previously available prior became unavailable by design.
    delayed_result_at=data[-1]["observed_at"]
    without_first=chronological_side_screen(data[1:])
    data[0]["observed_at"]=delayed_result_at
    altered=chronological_side_screen(data)
    # For every target whose features precede the deferred result,
    # the projection must match completely excluding the unobserved game.
    assert altered["games_scored"]==without_first["games_scored"]
    assert altered["candidate_margin_rmse"]==without_first["candidate_margin_rmse"]
    assert altered["candidate_ml_brier"]==without_first["candidate_ml_brier"]
    assert altered["market_admission"]=="NOT_VERIFIED"

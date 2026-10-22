from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.research.nba_totals_chronological_screen_v1 import chronological_total_screen


def rows(n=55, quoted=True):
    base=datetime(2025,1,1,tzinfo=timezone.utc)
    out=[]
    for i in range(n):
        t=base+timedelta(days=i)
        x={"event_id":str(i),"source_ref":"recorded-final",
           "tipoff":t.isoformat(),
           "observed_at":(t+timedelta(hours=5)).isoformat(),
           "home":"A" if i%2 else "B","away":"B" if i%2 else "A",
           "home_pts":120,"away_pts":112}
        if quoted:
            x.update(closing_total=235.5,
                     close_captured_at=(t-timedelta(minutes=30)).isoformat(),
                     close_source_ref="archive-quote-ref")
        out.append(x)
    return out


def test_comparison_is_chronological_and_never_admitted():
    result=chronological_total_screen(rows())
    assert result["counts"]["model_priced"]>0
    assert result["paired_games"]==result["counts"]["model_priced"]
    assert result["market_admission"]=="NOT_VERIFIED"
    assert result["validation_authority"]=="NONE"
    assert result["candidate_rmse"] is not None


def test_missing_prices_returns_no_market_comparison():
    result=chronological_total_screen(rows(quoted=False))
    assert result["paired_games"]==0
    assert result["indicative_market_reference_rmse"] is None


def test_late_close_never_treated_as_pre_event_reference():
    data=rows()
    data[3]["close_captured_at"]=data[3]["observed_at"]
    with pytest.raises(ValueError, match="CLOSE_NOT_PRETIP"):
        chronological_total_screen(data)


def test_future_result_availability_not_visible_to_earlier_tip():
    data=rows()
    data[0]["observed_at"]=data[-1]["observed_at"]
    x=chronological_total_screen(data)
    assert x["counts"]["model_priced"]>0
    assert x["market_admission"]=="NOT_VERIFIED"


def test_duplicate_and_unidentified_event_fail_closed():
    data=rows()
    data[1]["event_id"]=data[0]["event_id"]
    with pytest.raises(ValueError,match="DUPLICATE_OR_MISSING"):
        chronological_total_screen(data)

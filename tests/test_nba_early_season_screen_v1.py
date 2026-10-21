from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.research.nba_early_season_screen_v1 import screen_early_prop_mae


def rows():
    history=[]
    for year,base,n,pts in [(2025,datetime(2025,1,1,tzinfo=timezone.utc),15,20),
                            (2026,datetime(2026,10,1,tzinfo=timezone.utc),4,30)]:
        for i in range(n):
            t=base+timedelta(days=i)
            history.append({"player_id":"p1","game_id":f"{year}-{i}",
                            "season":year,"game_date":t.date().isoformat(),
                            "observed_at":(t+timedelta(hours=6)).isoformat(),
                            "source_ref":"scorelog","team_id":"A","position":"G",
                            "minutes":30,"points":pts,"rebounds":5,"assists":5})
    targets=[]
    for i in range(4):
        dt=datetime(2026,10,1,tzinfo=timezone.utc)+timedelta(days=i)
        targets.append({"player_id":"p1","game_id":f"2026-{i}",
                        "team_id":"A","season":2026,
                        "game_date":dt.date().isoformat(),
                        "tipoff":dt.isoformat(),
                        "decision_as_of":(dt-timedelta(minutes=5)).isoformat(),
                        "observed_at":(dt+timedelta(hours=6)).isoformat(),
                        "source_ref":"scorelog","minutes":30,
                        "points":30,"rebounds":5,"assists":5})
    return history,targets


def test_historical_early_prop_screen_is_not_market_validation():
    h,t=rows()
    x=screen_early_prop_mae(h,t,stat="points")
    assert x["scored"]==4
    assert x["market_vintage"]=="NONE_NO_PROP_QUOTES"
    assert x["validation_authority"]=="NONE"
    assert x["model_mae"]<x["prior_season_mae"]


def test_ineligible_or_postdecision_future_rows_do_not_qualify():
    h,t=rows()
    t[0]["decision_as_of"]=t[0]["observed_at"]
    with pytest.raises(ValueError,match="TEMPORAL_ORDER"):
        screen_early_prop_mae(h,t,stat="points")


def test_pra_is_own_game_sum():
    h,t=rows()
    x=screen_early_prop_mae(h,t,stat="pra")
    assert x["scored"]==4
    assert x["rows"][0]["actual"]==40


def test_transfer_is_blocked_not_faked_eligibility():
    h,t=rows()
    for row in h:
        if row["season"]==2025:
            row["team_id"]="B"
    x=screen_early_prop_mae(h,t,stat="points")
    assert x["scored"]==0
    assert x["blocked"]["WATCH_TRANSFER_NOT_MODELED"]==4

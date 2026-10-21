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
                            "tipoff":(t+timedelta(hours=20)).isoformat(),
                            "observed_at":(t+timedelta(hours=23)).isoformat(),
                            "finalized_at":(t+timedelta(hours=22)).isoformat(),
                            "role_observed_at":(t+timedelta(hours=19)).isoformat(),
                            "event_state":"FINAL","result_state":"FINAL",
                            "source_ref":"scorelog","team_id":"A","position":"G",
                            "minutes":30,"points":pts,"rebounds":5,"assists":5})
    targets=[]
    for i in range(4):
        dt=datetime(2026,10,1,tzinfo=timezone.utc)+timedelta(days=i)
        targets.append({"player_id":"p1","game_id":f"2026-{i}",
                        "team_id":"A","season":2026,
                        "game_date":dt.date().isoformat(),
                        "tipoff":(dt+timedelta(hours=20)).isoformat(),
                        "decision_as_of":(dt+timedelta(hours=19,minutes=55)).isoformat(),
                        "observed_at":(dt+timedelta(hours=23)).isoformat(),
                        "finalized_at":(dt+timedelta(hours=22)).isoformat(),
                        "event_state":"FINAL","result_state":"FINAL",
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


def test_target_slated_on_wrong_chicago_date_refuses():
    h,t=rows()
    # The supplied tip remains Oct 1 at 15:00 Central, but the declared
    # target day is Oct 2. Do not allow this to shift prior exclusions.
    t[0]["game_date"]="2026-10-02"
    with pytest.raises(ValueError,match="TARGET_LOCAL_DATE_MISMATCH"):
        screen_early_prop_mae(h,t,stat="points")


def test_utc_next_day_still_chicago_local_previous_day():
    h,t=rows()
    # 00:30Z Oct 2 is 19:30 CT Oct 1. An actual local Oct 1 target is
    # admissible, provided its decision and receipt bracket the tip.
    t[0]["tipoff"]="2026-10-02T00:30:00Z"
    t[0]["decision_as_of"]="2026-10-02T00:20:00Z"
    t[0]["observed_at"]="2026-10-02T03:00:00Z"
    t[0]["finalized_at"]="2026-10-02T02:30:00Z"
    x=screen_early_prop_mae(h,t,stat="points")
    assert x["scored"]==4


def test_screen_refuses_target_without_final_state():
    h,t=rows()
    t[0].pop("event_state")
    with pytest.raises(ValueError,match="FINAL_WITNESS_REQUIRED"):
        screen_early_prop_mae(h,t,stat="points")


def test_screen_refuses_target_final_receipt_before_finalization():
    h,t=rows()
    t[0]["finalized_at"]="2026-10-02T06:00:00Z"
    with pytest.raises(ValueError,match="FINAL_CHRONOLOGY_INVALID"):
        screen_early_prop_mae(h,t,stat="points")

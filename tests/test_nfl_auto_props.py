"""NFL AUTO prop intake must be paired, provider-grounded, and credit-bounded."""
import importlib.util,json
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location("auto_nfl_props",ROOT/"scripts"/"collect_nfl_auto_props.py")
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
NOW=datetime(2026,10,11,15,0,tzinfo=timezone.utc)


def event(stamp=None):
    stamp=stamp or NOW.isoformat()
    return {"id":"provider-e1","sport_key":"americanfootball_nfl",
            "away_team":"Cincinnati Bengals","home_team":"Miami Dolphins",
            "commence_time":"2026-10-11T17:00:00Z",
            "bookmakers":[{"key":"draftkings","markets":[
                {"key":"player_pass_yds","last_update":stamp,"outcomes":[
                    {"name":"Over","description":"Joe Burrow","point":251.5,"price":-110},
                    {"name":"Under","description":"Joe Burrow","point":251.5,"price":-120},
                    {"name":"Over","description":"Another QB","point":230.5,"price":-105}
                ]},
                {"key":"player_receptions","last_update":stamp,"outcomes":[
                    {"name":"Over","description":"Player WR","point":5.5,"price":+110},
                    {"name":"Under","description":"Player WR","point":5.5,"price":-130}
                ]},
            ]}]}


def base():
    return {"sport":"NFL","status":"READY","games":[
        {"provider_event_id":"provider-e1",
         "away":"Cincinnati Bengals","home":"Miami Dolphins",
         "commence_time":"2026-10-11T17:00:00Z",
         "slate_ct":"2026-10-11",
         "markets":{"h2h":{"line":None,"away":130,"home":-150,
                            "observed_at":NOW.isoformat()},
                    "spreads":{"line":3.0,"away":-115,"home":-105,
                               "observed_at":NOW.isoformat()},
                    "totals":{"line":43.5,"over":-110,"under":-110,
                              "observed_at":NOW.isoformat()}}}]}


def ready(slots,minimum_remaining):
    assert minimum_remaining==80
    return {"state":"READY","ready_key_slots":["SPORTSEDGE_ODDS_API_KEY"]}


def test_exact_pair_and_one_sided_rejection_and_no_model():
    good,bad=m.parse_pairs(event(),NOW)
    assert len(good)==2
    assert {r["market"] for r in good}=={"passing_yards","receptions"}
    assert "UNPAIRED_OR_DUPLICATE" in " ".join(bad)
    assert good[0]["away_or_over_price"]==-110
    assert good[0]["home_or_under_price"]==-120
    assert all("estimate_p" not in r for r in good)


def test_mismatched_threshold_and_stale_market_cannot_pair():
    e=event()
    e["bookmakers"][0]["markets"][0]["outcomes"][1]["point"]=252.5
    good,bad=m.parse_pairs(e,NOW)
    assert len(good)==1
    e=event((NOW-timedelta(minutes=11)).isoformat())
    good,bad=m.parse_pairs(e,NOW)
    assert good==[] and "QUOTE_TIMESTAMP_INVALID" in " ".join(bad)


def test_event_mismatch_rejected_without_fabricated_player():
    wrong=event();wrong["home_team"]="New York Jets"
    report=m.collect(base(),NOW,key_slots=[("SPORTSEDGE_ODDS_API_KEY","mock")],
                     preflight=ready,fetch=lambda event_id,key:wrong)
    assert report["events"][0]["reason"]=="WRONG_EVENT_TEAM_OR_KICKOFF"
    assert report["status"]=="NO_PRICED_PROP_MARKETS"


def test_no_credits_no_paid_call():
    def block(slots,minimum_remaining):
        return {"state":"BLOCKED","reason":"INSUFFICIENT_REMAINING_CREDITS"}
    def forbidden(*args):
        raise AssertionError("Cannot fetch prop odds below reserve")
    result=m.collect(base(),NOW,key_slots=[("SPORTSEDGE_ODDS_API_KEY","mock")],
                     preflight=block,fetch=forbidden)
    assert result["events"][0]["reason"]=="QUOTA_INSUFFICIENT_REMAINING_CREDITS"


def test_quote_ready_injects_only_verified_same_event_ticket():
    report=m.collect(base(),NOW,key_slots=[("SPORTSEDGE_ODDS_API_KEY","mock")],
                     preflight=ready,fetch=lambda event_id,key:event())
    assert report["status"]=="QUOTE_PAIRS_READY"
    tickets=m.ticket_with_props(base(),report,NOW)
    row=tickets["2026-10-11"]["games"][0]
    assert row["away"]=="CIN" and row["home"]=="MIA"
    assert len(row["markets"])==5
    assert [x["market"] for x in row["markets"][-2:]]==["passing_yards","receptions"]
    assert row["markets"][-1]["player"]=="Player WR"
    assert row["markets"][-1]["quote_retrieved_at"]==NOW.isoformat()


def test_same_kickoff_wrong_team_never_injects_prop():
    report=m.collect(base(),NOW,key_slots=[("SPORTSEDGE_ODDS_API_KEY","mock")],
                     preflight=ready,fetch=lambda event_id,key:event())
    broken=base()
    broken["games"][0]["home"]="New York Jets"
    tickets=m.ticket_with_props(broken,report,NOW)
    assert len(tickets["2026-10-11"]["games"][0]["markets"])==3
    assert all(not r.get("player") for r in tickets["2026-10-11"]["games"][0]["markets"])

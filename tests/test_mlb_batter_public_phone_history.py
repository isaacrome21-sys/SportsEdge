"""Offline exact-source tests for free MLB batter history into phone RUN IT.

These tests use mocked public StatsAPI data, never odds-derived player p.
"""
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from artifacts.run_it_full import run_full
from scripts.free_models_phone_issue import render_card

NOW = datetime(2026, 10, 11, 20, 55, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T00:00:00Z"
CAPTURE = "2026-10-11T20:54:00Z"
ID = "605141"


def mock_public(*, lineup=True, past_games=10, pa=4, total_bases=True,
                player_name="Mookie Betts", include_game=True):
    def get(url):
        parsed = urlparse(url)
        assert parsed.hostname == "statsapi.mlb.com", url
        path = parsed.path
        if path.endswith("/schedule"):
            return {"dates":[{"games":[{
                "gamePk": 810001, "gameDate": KICKOFF,
                "teams":{
                    "away":{"team":{"name":"Los Angeles Dodgers","id":119}},
                    "home":{"team":{"name":"Milwaukee Brewers","id":158}},
                }
            }]}]}
        if path.endswith("/people/search"):
            assert parse_qs(parsed.query)["sportIds"] == ["1"]
            return {"people":[{"id":int(ID),"fullName":player_name}]}
        if path.endswith("/boxscore"):
            return {"teams":{"away":{"players":{
                ("ID"+ID if include_game else "ID999999"): {
                    "person":{"id":int(ID) if include_game else 999999,
                              "fullName":player_name if include_game else "Someone Else"},
                    **({"battingOrder":"100"} if lineup else {})
                }
            }},"home":{"players":{}}}}
        if "/people/" in path and path.endswith("/stats"):
            splits=[]
            for i in range(past_games):
                hits = 1 if i<7 else 0
                data = {"plateAppearances":pa, "hits":hits,
                        "totalBases":hits if total_bases else None,
                        "rbi":0, "runs":i%2, "homeRuns":0, "stolenBases":0}
                if not total_bases:
                    data.pop("totalBases")
                splits.append({
                    "date":f"2026-09-{i+1:02d}",
                    "game":{"gamePk":700100+i}, "stat":data
                })
            return {"stats":[{"splits":splits}]}
        raise AssertionError("unexpected StatsAPI URL "+url)
    return get


def quote(side, odds, **extra):
    row = {
        "sport":"MLB", "away":"Los Angeles Dodgers",
        "home":"Milwaukee Brewers", "kickoff":KICKOFF,
        "market":"BATTER_HITS", "player_name":"Mookie Betts",
        "side":side, "line":0.5, "odds":odds, "book":"draftkings",
        "quote_captured_at":CAPTURE,
    }
    row.update(extra)
    return row


def run(getter=None, rows=None, now=NOW):
    return run_full({"sport":"MLB","lines":rows if rows is not None else [
        quote("OVER",-110),quote("UNDER",-110)]},
        now=now,getter=getter or mock_public())


def test_verified_starting_batter_uses_real_public_history_and_dual_dk():
    c=run()
    assert c["summary"]["rows"] == 2
    assert len(c["evaluated_rows"]) == 2
    assert len(c["prop_candidates"]) == 1
    assert len(c["prop_watchlist"]) == 1
    over=c["prop_candidates"][0]
    assert over["player_name"] == "Mookie Betts"
    assert over["source"] == "FREE_MLB_STATSAPI_BATTER_GAMELOG"
    assert over["model_probability"] == 0.7
    assert over["dk_no_vig_p"] == .5
    assert over["line"] == .5
    assert over["prior_game_count"] == 10
    assert over["prior_plate_appearances"] == 40
    assert over["lineup_status"] == "PUBLIC_BOXSCORE_STARTER_VERIFIED"
    assert over["research_only"] is True
    assert over["official_authority"] is False
    assert c["factor_coverage"]["advanced_metrics"]["statcast"] == "NOT_WIRED"
    md=render_card(c)
    assert "MLB pitcher + batter history research" in md
    assert "Mookie Betts" in md
    assert "1 verified public MLB batter-log inputs" in md
    assert "40 plate appearances" in md


def test_lineup_not_confirmed_has_probability_but_no_candidate():
    c=run(getter=mock_public(lineup=False))
    assert not c["prop_candidates"]
    assert len(c["prop_watchlist"])==2
    status={r["selection"]:r["status"] for r in c["evaluated_rows"]}
    assert status["OVER"]=="WATCH_LINEUP_NOT_CONFIRMED"
    assert "LINEUP_UNCONFIRMED" in render_card(c)


def test_missing_boxscore_player_also_watch_only():
    c=run(getter=mock_public(include_game=False))
    assert not c["prop_candidates"]
    assert c["evaluated_rows"][0]["lineup_status"]=="PUBLIC_BOXSCORE_LINEUP_NOT_VERIFIED"


def test_min_twenty_pas_and_ten_games_must_both_hold():
    c=run(getter=mock_public(pa=1))
    assert not c["prop_candidates"] and len(c["prop_unpriced"])==2
    assert "FEWER_THAN_TWENTY" in c["prop_unpriced"][0]["reason"]
    c=run(getter=mock_public(past_games=8))
    assert len(c["prop_unpriced"])==2
    assert "FEWER_THAN_TEN" in c["prop_unpriced"][0]["reason"]


def test_missing_stat_field_blocks_its_market_not_unrelated_hits():
    # All 10 StatsAPI games have independent PA, hits and identity evidence.
    # Missing totalBases is NOT a zero and must block TOTAL_BASES only.
    getter=mock_public(total_bases=False)
    hit_card=run(getter=getter)
    assert hit_card["evaluated_rows"][0]["model_probability"] == 0.7
    assert hit_card["prop_candidates"]
    tb_rows=[quote("OVER",-110,market="BATTER_TOTAL_BASES"),
             quote("UNDER",-110,market="BATTER_TOTAL_BASES")]
    total_bases_card=run(getter=getter,rows=tb_rows)
    assert len(total_bases_card["prop_unpriced"])==2
    assert all("total_bases_INVALID" in r["reason"]
               for r in total_bases_card["prop_unpriced"])


def test_one_missing_total_bases_field_does_not_cherry_pick_history():
    upstream=mock_public(total_bases=True)
    def getter(url):
        result=upstream(url)
        if "/people/" in url and url.endswith("/stats"):
            result["stats"][0]["splits"][0]["stat"].pop("totalBases")
        return result
    hits=run(getter=getter)
    assert hits["evaluated_rows"][0]["model_probability"] == 0.7
    tb=run(getter=getter,rows=[
        quote("OVER",-110,market="BATTER_TOTAL_BASES"),
        quote("UNDER",-110,market="BATTER_TOTAL_BASES")])
    assert len(tb["prop_unpriced"]) == 2
    assert all("total_bases_INVALID" in row["reason"]
               for row in tb["prop_unpriced"])


def test_missing_walk_stat_blocks_walk_market_not_hits():
    hits=run(getter=mock_public())
    assert hits["prop_candidates"]
    walks=run(getter=mock_public(),rows=[
        quote("OVER",-110,market="BATTER_BB"),
        quote("UNDER",-110,market="BATTER_BB")])
    assert len(walks["prop_unpriced"]) == 2
    assert all("walks_INVALID" in row["reason"] for row in walks["prop_unpriced"])


def test_wrong_name_is_not_fuzzy_matched():
    c=run(getter=mock_public(player_name="Different Baseball Player"))
    assert len(c["prop_unpriced"])==2
    assert "PLAYER_NOT_UNIQUELY_RESOLVED" in c["prop_unpriced"][0]["reason"]


def test_untrusted_user_probability_and_lineup_override_ignored():
    c=run(rows=[quote("OVER",-110,estimate_p=.999,lineup_verified=True,
                      features={"pa_history":[{"hits":99}]*100}),
                quote("UNDER",-110)])
    assert len(c["prop_candidates"])==1
    assert c["prop_candidates"][0]["model_probability"] == 0.7
    c2=run(getter=mock_public(lineup=False),
           rows=[quote("OVER",-110,lineup_verified=True),quote("UNDER",-110)])
    assert not c2["prop_candidates"]


def test_missing_paired_quote_and_stale_quote_not_actionable():
    no_pair=run(rows=[quote("OVER",-110)])
    assert len(no_pair["prop_unpriced"])==1
    stale=run(rows=[quote("OVER",-110,quote_captured_at="2026-10-11T18:00:00Z"),
                    quote("UNDER",-110,quote_captured_at="2026-10-11T18:00:00Z")])
    assert len(stale["prop_candidates"])==0
    assert len(stale["prop_watchlist"])==2
    assert all(r["status"]=="WATCH_QUOTE_NOT_CURRENT" for r in stale["prop_watchlist"])


def test_game_in_progress_never_reuses_prior_history_model():
    late=datetime(2026,10,12,0,5,tzinfo=timezone.utc)
    c=run(now=late)
    assert len(c["prop_unpriced"])==2
    assert "STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE" in c["prop_unpriced"][0]["reason"]


def test_mixed_batter_unavailable_market_and_pitcher_stay_indexed():
    c=run(rows=[quote("OVER",-110),
                quote("OVER",-110,market="FIRST_INNING_RUNS",player_name=""),
                quote("UNDER",-110)])
    assert [r["input_index"] for r in c["evaluated_rows"]] == [0,1,2]
    assert c["evaluated_rows"][1]["status"]=="NO_MODEL_OR_MARKET"
    assert c["summary"]["rows"]==3

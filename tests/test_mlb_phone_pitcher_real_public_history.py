"""Offline public MLB game-log and real pitcher-model phone integration tests."""
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from artifacts.run_it_full import run_full
from scripts.free_models_phone_issue import render_card
from sportsedge.mlb_public_pitcher_history import MLBPitcherPublicSource, MissingMLBHistory

AS_OF = datetime(2026,10,11,21,13,tzinfo=timezone.utc)
KICKOFF="2026-10-12T00:00:00Z"
CAPTURE="2026-10-11T21:12:10Z"


def schedule():
    return {"dates":[{"date":"2026-10-11","games":[{
        "gamePk":831111,"gameDate":KICKOFF,
        "teams":{
            "home":{"team":{"name":"Milwaukee Brewers","id":158},
                    "probablePitcher":{"id":800222,"fullName":"Jacob Misiorowski"}},
            "away":{"team":{"name":"Los Angeles Dodgers","id":119},
                    "probablePitcher":{"id":800111,"fullName":"Tarik Skubal"}},
        }}]}]}


def logs(starts=7):
    splits=[]
    for i in range(starts):
        splits.append({
            "date":f"2026-09-{i+1:02d}",
            "game":{"gamePk":900100+i},
            "stat":{"gamesStarted":1,"strikeOuts":5+i%4,"inningsPitched":"5.2",
                    "earnedRuns":i%3,"hits":3+i%4,"baseOnBalls":i%3}})
    return {"stats":[{"type":{"displayName":"gameLog"},
                      "group":{"displayName":"pitching"},"splits":splits}]}


def getter(url, *, starts=7, schedule_response=None):
    host=urlparse(url).hostname
    assert host=="statsapi.mlb.com",url
    if urlparse(url).path.endswith("/schedule"):
        assert "probablePitcher" in parse_qs(urlparse(url).query)["hydrate"][0]
        return schedule() if schedule_response is None else schedule_response
    if "/people/" in url and "/stats" in url:
        q=parse_qs(urlparse(url).query)
        assert q["stats"]==["gameLog"] and q["group"]==["pitching"]
        return logs(starts=starts)
    raise AssertionError(url)


def prop(side="OVER",market="PITCHER_K",line=7.5,odds=-111,
         captured=CAPTURE,player="Jacob Misiorowski",**extra):
    row={"sport":"MLB","away":"Los Angeles Dodgers","home":"Milwaukee Brewers",
         "kickoff":KICKOFF, "market":market,"side":side,"line":line,
         "odds":odds,"book":"draftkings",
         "player_name":player, "quote_captured_at":captured}
    row.update(extra)
    return row


def full(lines, **kw):
    return run_full({"sport":"MLB","lines":lines},
                    now=AS_OF,getter=kw.get("getter",getter),
                    auto_context=kw.get("auto_context",True))


def test_public_source_verifies_probable_pitcher_and_actual_prior_starts():
    src=MLBPitcherPublicSource(getter=getter)
    record=src.prior_starts(away="Los Angeles Dodgers",
            home="Milwaukee Brewers",player_name="Jacob Misiorowski",
            owner_kickoff=KICKOFF,as_of=AS_OF.isoformat())
    assert record["game_id"]=="831111"
    assert record["pitcher_id"]=="800222"
    assert record["prior_start_count"]==7
    assert record["features"]["history_pool"][0]["outs"]==17
    assert len(record["prior_start_times_utc"])==7
    assert record["starter_status"].endswith("NOT_CONFIRMED_START")


def test_priced_paired_pitcher_rows_reach_true_shared_research_bridge():
    card=full([prop(),prop(side="UNDER",odds=-114)])
    assert card["schema"]=="SPORTSEDGE_FREE_RESEARCH_CARD_V1"
    assert len(card["evaluated_rows"])==2
    assert len(card["prop_candidates"])+len(card["prop_watchlist"])==2
    assert not card["prop_unpriced"]
    assert len(card["source_receipts"])==1
    for r in card["evaluated_rows"]:
        assert r["source"]=="FREE_MLB_STATSAPI_GAMELOG"
        assert r["model_source"].startswith("mlb_pitcher_joint:")
        assert r["prior_start_count"]==7
        assert r["line"]==7.5
        assert r["quote_status"]=="RECENT_CAPTURED_QUOTE"
        assert 0<r["dk_no_vig_p"]<1
        assert 0<r["model_probability"]<1
        assert r["official_authority"] is False
    assert "REAL_PUBLIC_HISTORY_MODEL_UNVALIDATED" in str(card["factor_coverage"])
    text=render_card(card)
    assert "MLB pitcher + batter history research" in text
    assert "Jacob Misiorowski" in text
    assert "OVER 7.5" in text
    assert "1 verified public MLB pitcher-log inputs" in text
    assert "probable" in text.lower()
    assert "DK no-vig p" in text


def test_raw_user_submitted_probabilities_and_verification_flags_ignored():
    a=prop(estimate_p=.99,market_blind=True,
           starting_pitcher_verified=True,
           features={"history_pool":[{"strikeouts":50}]*10},
           prior_start_times_utc=["2099-01-01T00:00:00Z"]*10)
    c=full([a,prop(side="UNDER",odds=-114)])
    assert not c["prop_unpriced"]
    assert c["evaluated_rows"][0]["model_probability"]<.99
    assert c["evaluated_rows"][0]["prior_start_count"]==7


def test_stale_screenshot_watches_not_bet():
    c=full([prop(captured="2026-10-11T19:00:00Z"),
            prop(side="UNDER",odds=-114,captured="2026-10-11T19:00:00Z")])
    assert len(c["prop_candidates"])==0
    assert len(c["prop_watchlist"])==0
    assert len(c["prop_unpriced"])==2
    assert all(r["reason"]=="QUOTE_OVER_300S_REFUSED" for r in c["prop_unpriced"])
    assert all("ev_per_dollar" not in r for r in c["prop_unpriced"])


def test_no_probable_or_wrong_name_no_probability():
    c=full([prop(player="Wrong Person"),prop(side="UNDER",odds=-114,player="Wrong Person")])
    assert len(c["prop_unpriced"])==2
    assert all(r["reason"]=="PLAYER_NOT_VERIFIED_AS_SCHEDULED_PROBABLE_PITCHER" for r in c["prop_unpriced"])


def test_history_missing_and_no_fetch_fail_closed():
    bad=lambda url:getter(url,starts=3)
    c=full([prop(),prop(side="UNDER",odds=-114)],getter=bad)
    assert len(c["prop_unpriced"])==2
    assert "FEWER_THAN_FIVE" in c["prop_unpriced"][0]["reason"]
    nf=full([prop(),prop(side="UNDER",odds=-114)],auto_context=False)
    assert len(nf["prop_unpriced"])==2
    assert not nf["prop_candidates"]


def test_live_game_needs_live_specific_model_not_prior_starts():
    now=datetime(2026,10,12,0,5,tzinfo=timezone.utc)
    c=run_full({"sport":"MLB","lines":[prop(),prop(side="UNDER",odds=-114)]},
               now=now,getter=getter)
    assert len(c["prop_unpriced"])==2
    assert all("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE" in r["reason"] for r in c["prop_unpriced"])


def test_unmodeled_batter_and_first_inning_markets_remain_visible():
    c=full([prop(market="BATTER_HITS",player="Mookie Betts"),
            prop(market="FIRST_INNING_RUNS",player=None)])
    assert len(c["prop_unpriced"])==2
    assert not c["prop_candidates"]
    assert c["summary"]["status_counts"]["NO_MODEL_OR_MARKET"]==2
    assert "2" in render_card(c)


def test_paired_quotes_must_be_exact_same_market_and_line():
    # Mismatched lines never pair and never price. The phone pricer binds
    # quotes per quoted line, so each bridge call is one-sided; with no
    # VALIDATED family in the canonical coverage authority the terminal
    # refusal is the single-side validation gate naming the state.
    c=full([prop(),prop(side="UNDER",line=6.5,odds=-114)])
    assert len(c["prop_unpriced"])==2
    assert all("MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:NOT_RUN" in r["reason"] for r in c["prop_unpriced"])


def test_mixed_game_and_prop_rows_keep_input_positions_without_missing_models():
    lines=[prop(),prop(market="BATTER_HITS",player="Mookie Betts"),
           prop(side="UNDER",odds=-114)]
    # Do not claim game-pipeline mocked ESPN, just ensure mixed props preserve order.
    c=full(lines)
    assert len(c["evaluated_rows"])==3
    assert [r["input_index"] for r in c["evaluated_rows"]]==[0,1,2]
    assert c["summary"]["rows"]==3
    assert c["factor_coverage"]["by_input_index"][1]["factors"]["player_props"]["status"]=="NO_MODEL_OR_MARKET"


def test_invalid_game_public_source_blocks_all_pitcher_quotes():
    c=full([prop(),prop(side="UNDER",odds=-114)],
           getter=lambda url:getter(url,schedule_response={"dates":[]}))
    assert len(c["prop_unpriced"])==2
    assert not c["prop_watchlist"]

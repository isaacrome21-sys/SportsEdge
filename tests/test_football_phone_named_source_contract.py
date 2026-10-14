"""NFL/CFB user-odds input -> free ESPN named history -> research watch-only."""
import pytest
from datetime import datetime, timezone
from urllib.parse import urlparse

from sportsedge.football_gamelog_decode import (
    decode_football_event, FootballGamelogSchemaError,
)
from artifacts.run_it_full import run_full

NOW=datetime(2026,10,11,20,30,tzinfo=timezone.utc)
KICKOFF="2026-10-12T00:00:00Z"
CAPTURE="2026-10-11T20:29:30Z"


def public_response(url, *, names=True, matching_team=True, games=5,
                    home="Los Angeles Rams", away="Buffalo Bills"):
    path=urlparse(url).path
    if path.endswith("/scoreboard"):
        return {"events":[{"id":"401999001","date":KICKOFF,
            "competitions":[{"competitors":[
                {"homeAway":"home","team":{"id":"14","displayName":home}},
                {"homeAway":"away","team":{"id":"02","displayName":away}},
            ]}]}]}
    if path.endswith("/roster"):
        return None  # Legacy fake source has no team-roster feed; try old team-bound search.
    if path.endswith("/search/v2"):
        return {"results":[{"contents":[{"player":{
            "id":"777","displayName":"Example Receiver",
            "team":{"id":"02" if matching_team else "999"}
        }}]}]}
    if path.endswith("/gamelog"):
        return {**({"names":["receivingYards","receptions","rushingYards"]} if names else {}),
            "events":[{"id":str(401999100+i),
                "date":f"2026-09-{i+1:02d}T12:00:00Z",
                "stats":[str(70 if i < 3 else 20),"6","0"]}
            for i in range(games)]}
    raise AssertionError("Unexpected public URL "+url)


def quote(sport,side,**extra):
    return {
        "sport":sport,"away":"Buffalo Bills","home":"Los Angeles Rams",
        "kickoff":KICKOFF,"market":"RECEIVING_YARDS",
        "player_name":"Example Receiver","side":side,"line":55.5,
        "odds":-110,"book":"draftkings","quote_captured_at":CAPTURE,
        **extra,
    }


def run(sport, getter=None, game_rows=None):
    return run_full({"sport":sport,"lines":game_rows or [
        quote(sport,"OVER"),quote(sport,"UNDER")]},
        now=NOW,getter=getter or public_response)


@pytest.mark.registry_lane_internals
def test_named_espn_stats_decode_unambiguous_paired_research_watch():
    for sport in ("NFL","CFB"):
        c=run(sport)
        assert len(c["evaluated_rows"])==2
        assert len(c["prop_candidates"])==0
        assert len(c["prop_watchlist"])==2
        assert len(c["prop_unpriced"])==0
        assert len([r for r in c["source_receipts"]
                    if r.get("status")=="PUBLIC_"+sport+"_PRIOR_GAMES_VERIFIED"])==1
        over=next(x for x in c["evaluated_rows"] if x["selection"]=="OVER")
        assert over["market"]=="PLAYER_RECEIVING_YARDS"
        assert over["model_probability"]==.6
        assert over["dk_no_vig_p"]==.5
        assert over["status"]=="WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
        assert over["stats_schema"]=="ESPN_EXPLICIT_NAMES_ONLY"
        assert over["prior_game_count"]==5
        assert over["official_authority"] is False
        assert c["summary"]["rows"]==2


@pytest.mark.registry_lane_internals
def test_unlabelled_stat_arrays_are_never_guessed():
    for sport in ("NFL","CFB"):
        c=run(sport, getter=lambda url:public_response(url,names=False))
        assert len(c["prop_unpriced"])==2
        assert "FEWER_THAN_FIVE_VERIFIED_NAMED_PRIOR_GAMES" in c["prop_unpriced"][0]["reason"]


@pytest.mark.registry_lane_internals
def test_player_not_on_verified_matchup_team_is_not_priced():
    c=run("NFL",getter=lambda url:public_response(url,matching_team=False))
    assert len(c["prop_unpriced"])==2
    assert "PLAYER_NOT_UNIQUELY_RESOLVED_FROM_ESPN_SEARCH" in c["prop_unpriced"][0]["reason"]


@pytest.mark.registry_lane_internals
def test_fewer_than_five_games_blocks_cfb_and_nfl():
    for sport in ("NFL","CFB"):
        c=run(sport,getter=lambda url:public_response(url,games=4))
        assert len(c["prop_unpriced"])==2
        assert "FEWER_THAN_FIVE" in c["prop_unpriced"][0]["reason"]


def test_il_colleges_are_blocked_in_cfb_research_quote_bridge():
    home="Illinois Fighting Illini"
    original=[quote("CFB","OVER",home=home),quote("CFB","UNDER",home=home)]
    c=run("CFB",game_rows=original,
          getter=lambda url:public_response(url,home=home))
    assert len(c["prop_unpriced"])==2
    assert "ILLINOIS_COLLEGE_EXCLUDED" in c["prop_unpriced"][0]["reason"]


def test_derived_combinations_never_use_missing_component_as_zero():
    from sportsedge.nfl_player_empirical import price_nfl_player_market, NFLEmpiricalError
    rows=[{"rushing_yards":10}]*5
    try:
        price_nfl_player_market(market="PLAYER_RUSH_PLUS_REC_YARDS",side="OVER",
                                line=20.5,game_history=rows)
    except NFLEmpiricalError as exc:
        assert "COMBO_COMPONENT_MISSING" in str(exc)
    else:
        raise AssertionError("missing receiving yards cannot mean zero")


def test_bad_or_duplicate_stat_labels_fail_closed():
    for names,stats in [
        (["YDS","ATT"],["70","6"]),
        (["receivingYards","receivingYards"],["70","6"]),
        (["receivingYards"],["70","6"]),
    ]:
        try:
            decode_football_event({"names":names},{"stats":stats})
        except FootballGamelogSchemaError:
            pass
        else:
            raise AssertionError("unverified stat labels cannot create probability")


@pytest.mark.registry_lane_internals
def test_prior_gamelogs_ignore_untrusted_user_model_flags():
    rows=[quote("NFL","OVER",estimate_p=.99,verified=True,
                game_history=[{"receiving_yards":800}]*12),
          quote("NFL","UNDER",estimate_p=.01)]
    c=run("NFL",game_rows=rows)
    assert c["evaluated_rows"][0]["model_probability"]==.6
    assert not c["prop_candidates"]


@pytest.mark.registry_lane_internals
def test_kickoff_started_does_not_reuse_pregame_player_history():
    c=run_full({"sport":"NFL","lines":[quote("NFL","OVER"),quote("NFL","UNDER")]},
        now=datetime(2026,10,12,0,1,tzinfo=timezone.utc),
        getter=public_response)
    assert len(c["prop_unpriced"])==2
    assert all("STARTED_GAME" in x["reason"] for x in c["prop_unpriced"])


@pytest.mark.registry_lane_internals
def test_football_roster_resolves_exact_player_without_global_search_team_id():
    for sport in ("NFL", "CFB"):
        called = []
        def roster_getter(url):
            called.append(url)
            path = urlparse(url).path
            if path.endswith("/teams/02/roster"):
                return {"team": {"id": "02"},
                        "athletes": [{"position": "Wide Receiver", "items": [
                            {"id": "777", "displayName": "Example Receiver"},
                            {"id": "888", "displayName": "Other Receiver"},
                        ]}]}
            if path.endswith("/teams/14/roster"):
                return {"team": {"id": "14"}, "athletes": []}
            if path.endswith("/search/v2"):
                raise AssertionError("Roster identity should not rely on search")
            return public_response(url)
        c = run(sport, getter=roster_getter)
        assert len(c["prop_watchlist"]) == 2
        assert not c["prop_unpriced"]
        assert any("/roster" in url for url in called)
        assert all("/search/v2" not in url for url in called)


@pytest.mark.registry_lane_internals
def test_same_name_on_both_matchup_rosters_is_ambiguous_not_priced():
    def duplicated(url):
        path = urlparse(url).path
        if path.endswith("/teams/02/roster") or path.endswith("/teams/14/roster"):
            return {"athletes": [{"items": [{
                "id": "777" if "/02/" in path else "999",
                "displayName": "Example Receiver"}]}]}
        return public_response(url)
    for sport in ("NFL", "CFB"):
        c = run(sport, getter=duplicated)
        assert len(c["prop_unpriced"]) == 2
        assert "PLAYER_DUPLICATE_MATCHUP_ROSTERS" in c["prop_unpriced"][0]["reason"]


@pytest.mark.registry_lane_internals
def test_roster_claiming_wrong_team_does_not_override_fixture():
    def wrong_team(url):
        path = urlparse(url).path
        if path.endswith("/teams/02/roster"):
            return {"team": {"id": "02"}, "athletes": [{"items": [{
                "id": "777", "displayName": "Example Receiver",
                "team": {"id": "999"}}]}]}
        if path.endswith("/teams/14/roster"):
            return {"athletes": []}
        return public_response(url, matching_team=False)
    c = run("NFL", getter=wrong_team)
    assert len(c["prop_unpriced"]) == 2
    assert "PLAYER_NOT_UNIQUELY_RESOLVED" in c["prop_unpriced"][0]["reason"]

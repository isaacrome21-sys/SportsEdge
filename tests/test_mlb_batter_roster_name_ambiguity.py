"""Duplicate MLB names and accented display names are resolved by game roster."""
from sportsedge.mlb_public_batter_history import (
    MLBBatterPublicSource, MissingMLBBatterHistory,
)
from urllib.parse import urlparse

GAME="2026-10-12T00:00:00Z"
NOW="2026-10-11T21:15:00Z"


def source(display, official, ident, *, duplicate=False, roster=True):
    calls=[]
    def getter(url):
        calls.append(url)
        p=urlparse(url).path
        if p.endswith("/schedule"):
            return {"dates":[{"games":[{"gamePk":881111,"gameDate":GAME,
                "teams":{"away":{"team":{"name":"Los Angeles Dodgers"}},
                         "home":{"team":{"name":"Milwaukee Brewers"}}}}]}]}
        if p.endswith("/boxscore"):
            selected = {"ID"+str(ident):{
                "person":{"id":ident,"fullName":official}, "battingOrder":"400"}} if roster else {}
            home = {"ID987654":{"person":{"id":987654,"fullName":official},
                                "battingOrder":"400"}} if duplicate else {}
            return {"teams":{"away":{"players":selected},"home":{"players":home}}}
        if p.endswith("/people/search"):
            # Simulate the duplicate MLB-name global search. It must NOT
            # decide between player IDs when official game roster is known.
            return {"people":[{"id":ident,"fullName":official},
                              {"id":987654,"fullName":official}]}
        if p.endswith("/stats"):
            assert "/people/"+str(ident)+"/" in p
            return {"stats":[{"splits":[{
                "date":f"2026-09-{i+1:02d}",
                "game":{"gamePk":730100+i},
                "stat":{"plateAppearances":4,"hits":i%2,"totalBases":i%2,
                        "rbi":0,"runs":0,"homeRuns":0,"stolenBases":0},
            } for i in range(10)]}]}
        raise AssertionError("unknown "+url)
    return MLBBatterPublicSource(getter=getter),calls


def test_global_name_collisions_resolved_only_from_this_games_lineup():
    for supplied, official, pid in (
        ("Will Smith", "Will Smith", 669257),
        ("Max Muncy", "Max Muncy", 571970),
        ("Teoscar Hernandez", "Teoscar Hernández", 606192),
    ):
        src,calls=source(supplied,official,pid)
        record=src.prior_games(
            away="Los Angeles Dodgers",home="Milwaukee Brewers",
            player_name=supplied,owner_kickoff=GAME,as_of=NOW)
        assert record["batter_id"]==str(pid)
        assert record["lineup_verified"] is True
        assert record["prior_game_count"]==10
        assert record["prior_plate_appearances"]==40
        assert not any("/people/search" in x for x in calls)


def test_duplicate_same_name_across_game_is_rejected_not_arbitrarily_selected():
    src,calls=source("Will Smith","Will Smith",669257,duplicate=True)
    try:
        src.prior_games(away="Los Angeles Dodgers",home="Milwaukee Brewers",
                        player_name="Will Smith",owner_kickoff=GAME,as_of=NOW)
    except MissingMLBBatterHistory as e:
        assert "AMBIGUOUS" in str(e)
    else:
        raise AssertionError("should not choose between duplicate in-game names")


def test_duplicate_search_without_published_lineup_blocks():
    src,calls=source("Will Smith","Will Smith",669257,roster=False)
    try:
        src.prior_games(away="Los Angeles Dodgers",home="Milwaukee Brewers",
                        player_name="Will Smith",owner_kickoff=GAME,as_of=NOW)
    except MissingMLBBatterHistory as e:
        assert "PLAYER_NOT_UNIQUELY_RESOLVED" in str(e)
    else:
        raise AssertionError("unconfirmed global-name collision must block")

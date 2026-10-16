"""t206: DK 'Will Smith (LAD)' resolves via team + MLBAM id on the game roster; else fail closed."""
from urllib.parse import urlparse

import pytest

from sportsedge.mlb_public_batter_history import MLBBatterPublicSource, MissingMLBBatterHistory

GAME = "2026-10-16T00:00:00Z"
NOW = "2026-10-15T22:39:00Z"
LAD_ID, OTHER_ID = 669257, 519293


def source(*, away_players, home_players, abbrevs=("MIL", "LAD"), search=None):
    calls = []

    def team(name, ab):
        t = {"name": name}
        if ab is not None:
            t["abbreviation"] = ab
        return t

    def getter(url):
        calls.append(url)
        p = urlparse(url).path
        if p.endswith("/schedule"):
            return {"dates": [{"games": [{"gamePk": 849810, "gameDate": GAME, "teams": {
                "away": {"team": {"name": "Milwaukee Brewers"}},
                "home": {"team": {"name": "Los Angeles Dodgers"}}}}]}]}
        if p.endswith("/boxscore"):
            def players(ids):
                return {"ID" + str(i): {"person": {"id": i, "fullName": "Will Smith"}} for i in ids}
            return {"teams": {
                "away": {"team": team("Milwaukee Brewers", abbrevs[0]), "players": players(away_players)},
                "home": {"team": team("Los Angeles Dodgers", abbrevs[1]), "players": players(home_players)}}}
        if p.endswith("/people/search"):
            return search if search is not None else {"people": [{"id": LAD_ID, "fullName": "Will Smith"}]}
        if p.endswith("/stats"):
            assert "/people/%d/" % LAD_ID in p
            return {"stats": [{"splits": [{
                "date": f"2026-09-{i+1:02d}", "game": {"gamePk": 730100 + i},
                "stat": {"plateAppearances": 4, "hits": i % 2, "totalBases": i % 2, "rbi": 0,
                         "runs": 0, "homeRuns": 0, "stolenBases": 0}} for i in range(12)]}]}
        raise AssertionError(url)
    return MLBBatterPublicSource(getter=getter), calls


def run(src, name="Will Smith (LAD)"):
    return src.prior_games(away="Milwaukee Brewers", home="Los Angeles Dodgers",
                           player_name=name, owner_kickoff=GAME, as_of=NOW)


def test_team_qualified_name_resolves_from_roster_by_mlbam_id():
    src, calls = source(away_players=[], home_players=[LAD_ID])
    rec = run(src)
    assert rec["batter_id"] == str(LAD_ID)
    assert not any("/people/search" in c for c in calls)


def test_team_qualifier_disambiguates_same_name_on_other_team():
    src, _ = source(away_players=[OTHER_ID], home_players=[LAD_ID])
    assert run(src)["batter_id"] == str(LAD_ID)


def test_same_name_twice_on_qualified_team_fails_closed():
    src, _ = source(away_players=[], home_players=[LAD_ID, OTHER_ID])
    with pytest.raises(MissingMLBBatterHistory, match="AMBIGUOUS"):
        run(src)


def test_qualifier_matching_neither_team_fails_closed():
    src, _ = source(away_players=[], home_players=[LAD_ID])
    with pytest.raises(MissingMLBBatterHistory, match="PLAYER_TEAM_QUALIFIER_UNVERIFIED"):
        run(src, "Will Smith (NYY)")


def test_unverifiable_team_abbreviation_fails_closed():
    src, _ = source(away_players=[], home_players=[LAD_ID], abbrevs=(None, None))
    with pytest.raises(MissingMLBBatterHistory, match="PLAYER_TEAM_QUALIFIER_UNVERIFIED"):
        run(src)


def test_qualified_name_not_on_roster_never_falls_back_to_global_search():
    src, calls = source(away_players=[], home_players=[])
    with pytest.raises(MissingMLBBatterHistory, match="PLAYER_TEAM_QUALIFIED_NOT_ON_VERIFIED_ROSTER"):
        run(src)
    assert not any("/people/search" in c for c in calls)


def test_unqualified_duplicate_across_teams_still_ambiguous():
    src, _ = source(away_players=[OTHER_ID], home_players=[LAD_ID])
    with pytest.raises(MissingMLBBatterHistory, match="AMBIGUOUS"):
        run(src, "Will Smith")

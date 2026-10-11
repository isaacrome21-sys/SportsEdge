"""Offline tests for the hardened ESPN gamelog field parser.

The ESPN gamelog endpoints return per-event stat *arrays* aligned with a
top-level `names` list; per-event metadata lives in a dict keyed by eventId.
These tests pin the normalized extraction (passing_yards, rushing_yards, ...)
so the empirical pricer receives real player-level fields instead of raw
arrays. No network calls; fixtures are ESPN-shaped canned payloads.
Research-only semantics are asserted alongside normalization.
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsedge import nfl_public_player_history as nfl_hist
from sportsedge import cfb_public_player_history as cfb_hist
from sportsedge import nfl_player_empirical as emp

NOW = "2026-10-11T18:00:00Z"
KICKOFF = "2026-10-18T20:25:00Z"


def _gamelog(athlete_id="3139477"):
    names = ["completions", "passingAttempts", "passingYards", "passingTouchdowns",
             "interceptions", "rushingAttempts", "rushingYards", "receptions", "receivingYards"]
    events = {}
    season_events = []
    for i in range(6):
        eid = f"4018729{30 + i}"
        stats = [str(15 + i), str(28 + i), str(220 + 10 * i), str(2),
                 str(i % 2), str(3 + i), str(5 + 2 * i), "0", "0"]
        events[eid] = {
            "id": eid,
            "gameDate": f"2026-09-{1 + 4 * i:02d}T20:00:00.000+00:00",
            "gameResult": "W" if i % 2 == 0 else "L",
            "opponent": {"abbreviation": "LV", "displayName": "Las Vegas Raiders"},
        }
        season_events.append({"eventId": eid, "stats": stats})
    return {
        "names": names,
        "events": events,
        "seasonTypes": [{"displayName": "2026 Regular Season",
                         "categories": [{"displayName": "Regular Season Stats",
                                         "events": season_events}]}],
    }


def _getter_factory(search_name, gamelog, away, home, kickoff):
    search_payload = {"results": [{"type": "player", "contents": [{
        "id": "some-guid",
        "uid": "s:20~l:28~a:3139477",
        "type": "player",
        "displayName": search_name,
        "defaultLeagueSlug": "nfl",
        "sport": "football",
    }]}]}
    scoreboard_payload = {"events": [{
        "id": "401880001",
        "date": kickoff,
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": home}},
            {"homeAway": "away", "team": {"displayName": away}},
        ]}],
    }]}

    def getter(url):
        if "search/v2" in url:
            return search_payload
        if "scoreboard" in url:
            return scoreboard_payload
        if "gamelog" in url:
            return gamelog
        return None

    return getter


def _prior_games(module, cls, exc, search_name, gamelog):
    src = cls(getter=_getter_factory(search_name, gamelog,
                                     "Las Vegas Raiders", "Kansas City Chiefs", KICKOFF))
    return src.prior_games(away="Las Vegas Raiders", home="Kansas City Chiefs",
                           player_name=search_name,
                           owner_kickoff=KICKOFF, as_of=NOW)


def test_nfl_gamelog_normalizes_fields_instead_of_raw_arrays():
    out = _prior_games(nfl_hist, nfl_hist.NFLPlayerPublicSource,
                       nfl_hist.MissingNFLHistory, "Patrick Mahomes", _gamelog())
    assert out["player_id"] == "3139477"
    assert out["prior_game_count"] == 6
    hist = out["features"]["game_history"]
    assert len(hist) == 6
    first = hist[0]
    assert "raw_stats" not in first
    assert first["passing_yards"] == 270.0
    assert first["pass_attempts"] == 33.0
    assert first["completions"] == 20.0
    assert first["passing_tds"] == 2.0
    assert first["rushing_yards"] == 15.0
    assert first["rush_attempts"] == 8.0
    assert first["opponent"] == "LV"
    assert first["result"] == "L"


def test_cfb_gamelog_normalizes_fields_instead_of_raw_arrays():
    out = _prior_games(cfb_hist, cfb_hist.CFBPlayerPublicSource,
                       cfb_hist.MissingCFBHistory, "Patrick Mahomes", _gamelog())
    assert out["prior_game_count"] == 6
    hist = out["features"]["game_history"]
    assert all("raw_stats" not in g for g in hist)
    assert hist[0]["passing_yards"] == 270.0
    assert hist[0]["interceptions"] == 1.0


def test_misaligned_stat_array_skips_game_without_inventing():
    gamelog = _gamelog()
    # Corrupt one event's array length: names no longer align.
    first_season = gamelog["seasonTypes"][0]["categories"][0]["events"]
    first_season[0]["stats"] = first_season[0]["stats"][:4]
    out = _prior_games(nfl_hist, nfl_hist.NFLPlayerPublicSource,
                       nfl_hist.MissingNFLHistory, "Patrick Mahomes", gamelog)
    assert out["prior_game_count"] == 5  # corrupted game skipped, not invented


def test_nfl_requires_five_prior_games_fail_closed():
    gamelog = _gamelog()
    for key in list(gamelog["events"].keys())[4:]:
        del gamelog["events"][key]
    gamelog["seasonTypes"][0]["categories"][0]["events"] = [
        e for e in gamelog["seasonTypes"][0]["categories"][0]["events"]
        if e["eventId"] in gamelog["events"]]
    try:
        _prior_games(nfl_hist, nfl_hist.NFLPlayerPublicSource,
                     nfl_hist.MissingNFLHistory, "Patrick Mahomes", gamelog)
    except nfl_hist.MissingNFLHistory as exc:
        assert "FEWER_THAN_FIVE_VERIFIED_PRIOR_GAMES" in str(exc)
    else:
        raise AssertionError("expected fail-closed on <5 games")


def test_cfb_requires_four_prior_games_fail_closed():
    gamelog = _gamelog()
    for key in list(gamelog["events"].keys())[3:]:
        del gamelog["events"][key]
    gamelog["seasonTypes"][0]["categories"][0]["events"] = [
        e for e in gamelog["seasonTypes"][0]["categories"][0]["events"]
        if e["eventId"] in gamelog["events"]]
    try:
        _prior_games(cfb_hist, cfb_hist.CFBPlayerPublicSource,
                     cfb_hist.MissingCFBHistory, "Patrick Mahomes", gamelog)
    except cfb_hist.MissingCFBHistory as exc:
        assert "FEWER_THAN_FOUR_VERIFIED_PRIOR_GAMES" in str(exc)
    else:
        raise AssertionError("expected fail-closed on <4 games")


def test_negative_yardage_accepted_negative_counts_rejected():
    hist = [{"passing_yards": 250.0, "passing_tds": 2.0, "pass_attempts": 30.0,
             "completions": 20.0, "interceptions": 0.0,
             "rushing_yards": -6.0, "rush_attempts": 2.0,
             "receiving_yards": 0.0, "receptions": 0.0}] * 6
    out = emp.price_nfl_player_market(market="PLAYER_RUSHING_YARDS", side="OVER",
                                      line=-10.0, game_history=hist)
    assert out["model_p"] == 1.0
    assert out["engine"] == "nfl_player_empirical_gamelog_v1"
    bad = [dict(h, pass_attempts=-1.0) for h in hist]
    try:
        emp.price_nfl_player_market(market="PLAYER_PASS_ATTEMPTS", side="OVER",
                                    line=30.5, game_history=bad)
    except emp.NFLEmpiricalError as exc:
        assert "NEGATIVE" in str(exc)
    else:
        raise AssertionError("negative count must stay fail-closed")
    try:
        emp.price_nfl_player_market(market="PLAYER_PASSING_YARDS", side="OVER",
                                    line=250.5, game_history=[{"opponent": "LV"}] * 6)
    except emp.NFLEmpiricalError as exc:
        assert "MISSING" in str(exc)
    else:
        raise AssertionError("missing field must stay fail-closed")


def test_priced_history_matches_espn_verified_values():
    out = _prior_games(nfl_hist, nfl_hist.NFLPlayerPublicSource,
                       nfl_hist.MissingNFLHistory, "Patrick Mahomes", _gamelog())
    res = emp.price_nfl_player_market(market="PLAYER_PASSING_YARDS", side="OVER",
                                      line=245.5,
                                      game_history=out["features"]["game_history"])
    # values 270,260,250,240,230,220 -> 3 over 245.5 of 6
    assert res["model_p"] == 0.5
    assert res["push_p"] == 0.0
    assert res["effective_history_games"] == 6


def test_athlete_id_extracted_from_uid_not_guid():
    out = _prior_games(nfl_hist, nfl_hist.NFLPlayerPublicSource,
                       nfl_hist.MissingNFLHistory, "Patrick Mahomes", _gamelog())
    assert out["player_id"] == "3139477"
    assert out["player_id"].isdigit()

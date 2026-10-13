"""Doubleheader prior games must not trip the duplicate/leak gate, while the
gate itself stays fail-closed. Offline mocked public StatsAPI only."""
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

import pytest

from sportsedge.mlb_public_batter_history import (
    MLBBatterPublicSource, MissingMLBBatterHistory)
from sportsedge.research_model_adapters import mlb_batter_to_bridge_rows

NOW = "2026-10-11T20:55:00Z"
KICKOFF = "2026-10-12T00:00:00Z"
ID = "605141"
DH_DAY = "2026-09-05"


def getter(*, dh_schedule="ok"):
    def get(url):
        p = urlparse(url)
        q = parse_qs(p.query)
        if p.path.endswith("/schedule"):
            day = q.get("date", [""])[0]
            if day == DH_DAY:
                if dh_schedule == "missing":
                    return None
                t2 = "2026-09-05T17:10:00Z" if dh_schedule == "same" else "2026-09-05T23:05:00Z"
                return {"dates": [{"games": [
                    {"gamePk": 700104, "gameDate": "2026-09-05T17:10:00Z"},
                    {"gamePk": 700199, "gameDate": t2}]}]}
            return {"dates": [{"games": [{
                "gamePk": 810001, "gameDate": KICKOFF,
                "teams": {"away": {"team": {"name": "Los Angeles Dodgers"}},
                          "home": {"team": {"name": "Milwaukee Brewers"}}}}]}]}
        if p.path.endswith("/boxscore"):
            return {"teams": {"away": {"players": {"ID" + ID: {
                "person": {"id": int(ID), "fullName": "Mookie Betts"},
                "battingOrder": "100"}}}, "home": {"players": {}}}}
        if p.path.endswith("/stats"):
            splits = []
            for i in range(12):
                splits.append({"date": f"2026-09-{i+1:02d}", "game": {"gamePk": 700100 + i},
                               "stat": {"plateAppearances": 4, "hits": 1, "totalBases": 1,
                                        "rbi": 0, "runs": 0, "homeRuns": 0, "stolenBases": 0}})
            splits.append({"date": DH_DAY, "game": {"gamePk": 700199},
                           "stat": {"plateAppearances": 4, "hits": 0, "totalBases": 0,
                                    "rbi": 0, "runs": 0, "homeRuns": 0, "stolenBases": 0}})
            return {"stats": [{"splits": splits}]}
        raise AssertionError(url)
    return get


def _prior(**kw):
    return MLBBatterPublicSource(getter=getter(**kw)).prior_games(
        away="Los Angeles Dodgers", home="Milwaukee Brewers",
        player_name="Mookie Betts", owner_kickoff=KICKOFF, as_of=NOW)


def _bridge(v):
    return mlb_batter_to_bridge_rows(
        game_id=v["game_id"], player_id=v["batter_id"], market="BATTER_HITS",
        side="OVER", line=0.5, features=v["features"],
        prior_game_times_utc=v["prior_game_times_utc"],
        source_as_of_utc=v["source_as_of_utc"], as_of_utc=NOW,
        kickoff_utc=v["kickoff_utc"], home_team="Milwaukee Brewers",
        away_team="Los Angeles Dodgers")[0]


def test_verified_doubleheader_keeps_both_games_and_prices():
    v = _prior()
    assert v["prior_game_count"] == 13
    times = v["prior_game_times_utc"]
    assert len(set(times)) == len(times)
    assert "2026-09-05T17:10:00+00:00" in times and "2026-09-05T23:05:00+00:00" in times
    row = _bridge(v)
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" not in str(row)
    assert row.get("status") != "NO_MODEL_OR_MARKET"


@pytest.mark.parametrize("mode", ["missing", "same"])
def test_unverifiable_doubleheader_drops_both_games_never_invents(mode):
    v = _prior(dh_schedule=mode)
    assert v["prior_game_count"] == 11
    pks_day = [t for t in v["prior_game_times_utc"] if t.startswith(DH_DAY)]
    assert pks_day == []


def test_leak_gate_still_rejects_true_duplicate_and_future():
    v = _prior()
    dup = dict(v, prior_game_times_utc=[v["prior_game_times_utc"][0]] * v["prior_game_count"])
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(_bridge(dup))
    fut = list(v["prior_game_times_utc"]); fut[0] = "2026-10-11T21:00:00+00:00"
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(_bridge(dict(v, prior_game_times_utc=fut)))


def test_pre_fix_behavior_would_have_overfired():
    # Date-midnight stamps for a doubleheader collide: exactly the old bug.
    v = _prior()
    old = [t[:10] + "T00:00:00+00:00" for t in v["prior_game_times_utc"]]
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(_bridge(dict(v, prior_game_times_utc=old)))

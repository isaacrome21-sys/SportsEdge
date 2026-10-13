"""Integration test: MLB batter game-log history -> every batter market.

One offline pipeline (mocked public StatsAPI from local fixtures only):
schedule + boxscore + hitting gameLog -> MLBBatterPublicSource.prior_games
-> price_batter_market / mlb_batter_to_bridge_rows. Proves each batter
market reads the correct per-game statistic, including a doubleheader
(both games kept, distinct start times, no false duplicate). Grok 2026-10-13.
"""
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import pytest

from sportsedge.mlb_batter_empirical import (
    BATTER_MARKETS, BatterEmpiricalError, price_batter_market)
from sportsedge.mlb_public_batter_history import MLBBatterPublicSource
from sportsedge.research_model_adapters import mlb_batter_to_bridge_rows

NOW = "2026-10-11T20:55:00Z"
KICKOFF = "2026-10-12T00:00:00Z"
ID = "605141"
DH_DAY = "2026-09-05"
DH_G1, DH_G2 = 700104, 700199
DH_T1, DH_T2 = "2026-09-05T17:10:00Z", "2026-09-05T23:05:00Z"


def _line(i):
    """Distinct, internally consistent per-game box line for game i."""
    hits = i % 4
    doubles = 1 if hits >= 2 else 0
    triples = 1 if hits == 3 else 0
    hrs = 1 if hits >= 1 and i % 3 == 0 and hits - doubles - triples >= 1 else 0
    singles = hits - doubles - triples - hrs
    return {"plateAppearances": 4 + i % 2, "hits": hits, "doubles": doubles,
            "triples": triples, "homeRuns": hrs,
            "totalBases": singles + 2 * doubles + 3 * triples + 4 * hrs,
            "runs": i % 3, "rbi": (2 * i) % 5, "baseOnBalls": i % 2,
            "strikeOuts": (i + 1) % 3, "stolenBases": 0}


# 12 single games on Sept 1..12 (Sept 5 game 1 is pk 700104), plus Sept 5
# doubleheader game 2 (pk 700199) with a distinctive line.
GAMES = [(f"2026-09-{i+1:02d}", 700100 + i, _line(i)) for i in range(12)]
GAMES.append((DH_DAY, DH_G2, {"plateAppearances": 5, "hits": 4, "doubles": 1,
                               "triples": 1, "homeRuns": 1, "totalBases": 10,
                               "runs": 3, "rbi": 4, "baseOnBalls": 1,
                               "strikeOuts": 0, "stolenBases": 1}))

FIELD_OF = {"hits": "hits", "total_bases": "totalBases", "home_runs": "homeRuns",
            "runs": "runs", "rbi": "rbi", "walks": "baseOnBalls",
            "doubles": "doubles", "triples": "triples"}
MARKETS = {  # requested market -> model field
    "BATTER_HITS": "hits", "BATTER_TOTAL_BASES": "total_bases",
    "BATTER_HRS": "home_runs", "BATTER_RUNS": "runs", "BATTER_RBIS": "rbi",
    "BATTER_WALKS": "walks", "BATTER_SINGLES": "singles",
    "BATTER_DOUBLES": "doubles",
}


def getter(url):
    p = urlparse(url)
    q = parse_qs(p.query)
    if p.path.endswith("/schedule"):
        if q.get("date", [""])[0] == DH_DAY:
            return {"dates": [{"games": [
                {"gamePk": DH_G1, "gameDate": DH_T1, "officialDate": DH_DAY},
                {"gamePk": DH_G2, "gameDate": DH_T2, "officialDate": DH_DAY}]}]}
        return {"dates": [{"games": [{
            "gamePk": 810001, "gameDate": KICKOFF,
            "teams": {"away": {"team": {"name": "Los Angeles Dodgers"}},
                      "home": {"team": {"name": "Milwaukee Brewers"}}}}]}]}
    if p.path.endswith("/boxscore"):
        return {"teams": {"away": {"players": {"ID" + ID: {
            "person": {"id": int(ID), "fullName": "Mookie Betts"},
            "battingOrder": "100"}}}, "home": {"players": {}}}}
    if p.path.endswith("/stats"):
        assert q["stats"] == ["gameLog"] and q["group"] == ["hitting"]
        return {"stats": [{"splits": [{"date": d, "game": {"gamePk": pk}, "stat": dict(s)}
                                      for d, pk, s in GAMES]}]}
    raise AssertionError("unexpected network call: " + url)


def expected_rows():
    """Fixture rows in the source's order (newest date, then gamePk, desc)."""
    rows = sorted(GAMES, key=lambda g: (g[0], g[1]), reverse=True)
    out = []
    for _d, _pk, s in rows:
        r = {k: s[v] for k, v in FIELD_OF.items()}
        r["singles"] = s["hits"] - s["doubles"] - s["triples"] - s["homeRuns"]
        out.append(r)
    return out


@pytest.fixture(scope="module")
def prior():
    return MLBBatterPublicSource(getter=getter).prior_games(
        away="Los Angeles Dodgers", home="Milwaukee Brewers",
        player_name="Mookie Betts", owner_kickoff=KICKOFF, as_of=NOW)


def test_every_batter_market_reads_correct_per_game_stats_including_doubleheader(prior):
    # Doubleheader: both games retained, distinct verified start times.
    assert prior["prior_game_count"] == len(GAMES) == 13
    times = prior["prior_game_times_utc"]
    assert len(set(times)) == len(times)
    assert "2026-09-05T17:10:00+00:00" in times and "2026-09-05T23:05:00+00:00" in times

    history = prior["features"]["pa_history"]
    exp = expected_rows()
    assert len(history) == len(exp)
    # Per-game, per-field identity with the fixture (incl. derived singles
    # and the triples field, which has no priced market -- see below).
    for got, want in zip(history, exp):
        for field, value in want.items():
            assert got[field] == value, (field, got, want)
    # Both doubleheader lines are present and distinct (not merged/deduped).
    dh2 = {k: v for k, v in history[exp.index(next(r for r in exp if r["total_bases"] == 10))].items()}
    assert dh2["hits"] == 4 and dh2["triples"] == 1 and dh2["home_runs"] == 1

    for market, field in MARKETS.items():
        values = [r[field] for r in exp]
        for line in (0.5, 1.5, 2.0):
            out = price_batter_market(market=market, side="OVER", line=line, pa_history=history)
            want_over = sum(v > line for v in values) / len(values)
            want_push = (sum(v == line for v in values) / len(values)) if line.is_integer() else 0.0
            assert out["model_p"] == pytest.approx(want_over), (market, line)
            assert out["push_p"] == pytest.approx(want_push), (market, line)
            assert out["effective_history_games"] == 13
        # Bridge layer: full pipeline, no false duplicate on the doubleheader.
        row = mlb_batter_to_bridge_rows(
            game_id=prior["game_id"], player_id=prior["batter_id"], market=market,
            side="OVER", line=0.5, features=prior["features"],
            prior_game_times_utc=times, source_as_of_utc=prior["source_as_of_utc"],
            as_of_utc=NOW, kickoff_utc=prior["kickoff_utc"],
            home_team="Milwaukee Brewers", away_team="Los Angeles Dodgers")[0]
        assert "HISTORY_LEAK_OR_DUPLICATE_GAME" not in str(row), market
        assert row.get("status") != "NO_MODEL_OR_MARKET", market

    # Triples: per-game field is read correctly above, but there is no
    # BATTER_TRIPLES market in the engine. Pin that gap so it can't be
    # silently priced from a different field.
    assert not any("TRIPLE" in m for m in BATTER_MARKETS)
    with pytest.raises(BatterEmpiricalError, match="UNSUPPORTED_BATTER_MARKET"):
        price_batter_market(market="BATTER_TRIPLES", side="OVER", line=0.5, pa_history=history)

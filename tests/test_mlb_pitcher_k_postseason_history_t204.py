"""t204: pitcher-K card defect audit (Glasnow and Drohan both 0.807692).

Root cause findings pinned here:
1. The identical 0.807692 is NOT a shared/constant engine output. It is the
   Jeffreys posterior (10 + 0.5) / (12 + 1) = 21/26: on the real 2026 game
   logs both pitchers cleared their own line in 10 of their last 12 starts.
2. Real defect: the public history source fetched only the default
   (regular-season) gameLog, so a postseason game silently ignored the
   pitcher's own earlier postseason starts (Glasnow 2026-10-07, 5 K).
   Postseason games must include gameType=P starts or fail closed.
Offline only; no network. Research-only; no probability is supplied.
"""
from urllib.parse import urlparse, parse_qs
import pytest
from sportsedge.mlb_public_pitcher_history import MLBPitcherPublicSource, MissingMLBHistory
from sportsedge.pitcher_joint_engine import price_pitcher_market

AS_OF = "2026-10-15T22:50:00+00:00"
KICKOFF = "2026-10-16T00:08:00Z"
GLASNOW_K = [11, 10, 7, 8, 6, 7, 2, 9, 9, 7, 7, 9]  # newest first, 2026 regular season
DROHAN_K = [2, 4, 5, 6, 5, 5, 4, 7, 6, 9, 6, 2]


def _pool(ks):
    return [{"strikeouts": k, "outs": 15, "earned_runs": 2, "hits_allowed": 4, "walks_allowed": 1} for k in ks]


def _price(ks, line):
    return price_pitcher_market({"game_id": "1", "entity_id": "2", "market": "PITCHER_K",
                                 "side": "OVER", "line": line, "features": {"history_pool": _pool(ks)}})["model_p"]


def test_identical_card_value_is_the_jeffreys_posterior_of_equal_hit_counts():
    g, d = _price(GLASNOW_K, 6.5), _price(DROHAN_K, 2.5)
    assert g == pytest.approx(21 / 26) and d == pytest.approx(21 / 26)
    # The engine is line- and pitcher-sensitive; equality was a coincidence.
    assert _price(GLASNOW_K, 2.5) != g and _price(DROHAN_K, 6.5) != d


def _schedule(game_type):
    return {"dates": [{"date": "2026-10-15", "games": [{
        "gamePk": 778899, "gameDate": KICKOFF, "gameType": game_type,
        "teams": {"away": {"team": {"name": "Milwaukee Brewers"},
                           "probablePitcher": {"id": 675660, "fullName": "Shane Drohan"}},
                  "home": {"team": {"name": "Los Angeles Dodgers"},
                           "probablePitcher": {"id": 607192, "fullName": "Tyler Glasnow"}}}}]}]}


def _split(date, pk, k):
    return {"date": date, "game": {"gamePk": pk},
            "stat": {"gamesStarted": 1, "strikeOuts": k, "inningsPitched": "6.0",
                     "earnedRuns": 1, "hits": 4, "baseOnBalls": 1}}


def _regular():
    days = ["09-24", "09-18", "09-12", "09-06", "08-31", "08-25", "08-19", "08-13", "08-07", "08-01", "07-26", "07-20"]
    return {"stats": [{"splits": [_split(f"2026-{d}", 700000 + i, k) for i, (d, k) in enumerate(zip(days, GLASNOW_K))]}]}


def _getter(game_type, *, post="ok", calls=None):
    def get(url):
        q = parse_qs(urlparse(url).query)
        if calls is not None:
            calls.append(q)
        if urlparse(url).path.endswith("/schedule"):
            return _schedule(game_type)
        if q.get("gameType") == ["P"]:
            if post == "down":
                raise OSError("unavailable")
            return {"stats": [{"splits": [_split("2026-10-07", 800001, 5)]}]}
        return _regular()
    return get


def _starts(getter):
    return MLBPitcherPublicSource(getter=getter).prior_starts(
        away="Milwaukee Brewers", home="Los Angeles Dodgers", player_name="Tyler Glasnow",
        owner_kickoff=KICKOFF, as_of=AS_OF)


def test_postseason_game_includes_own_prior_postseason_starts():
    rec = _starts(_getter("L"))
    ks = [s["strikeouts"] for s in rec["features"]["history_pool"]]
    assert ks[0] == 5 and len(ks) == 12          # newest start is the 10-07 postseason start
    assert ks == [5] + GLASNOW_K[:11]
    assert rec["prior_start_times_utc"][0].startswith("2026-10-07")


def test_postseason_gamelog_unavailable_fails_closed():
    with pytest.raises(MissingMLBHistory, match="POSTSEASON_GAMELOG_UNAVAILABLE"):
        _starts(_getter("D", post="down"))


def test_regular_season_game_is_unchanged_and_never_requests_postseason_log():
    calls = []
    rec = _starts(_getter("R", calls=calls))
    assert [s["strikeouts"] for s in rec["features"]["history_pool"]] == GLASNOW_K
    assert not any(q.get("gameType") == ["P"] for q in calls)

"""Duplicate detection in the batter history gate keys on game identity.

Regression for the Oct 19 ALCS G6 pricing run (99 rows blocked
HISTORY_LEAK_OR_DUPLICATE_GAME). Two distinct failure shapes:

1. The run executed a stale clone whose producer stamped every prior game
   at date-midnight, so any doubleheader in the window produced duplicate
   stamps. Already repaired on main by per-gamePk verified starts
   (test_mlb_batter_doubleheader_prior_start.py).
2. Residual on main: a doubleheader game 2 whose verified start is exactly
   midnight UTC (a 19:00 CDT / 20:00 EDT first pitch) equals the next
   date's singleton date-midnight stamp, so timestamp-distinctness still
   fired on a legitimate, non-leaking history. Timestamps are neither a
   necessary nor a sufficient identity key: one game counted twice must
   also block even when it carries two different stamps.

The bridge now takes prior_game_ids (gamePks from the collector) and keys
duplicates on identity; the leak arm (every start before the as-of) and
the legacy no-ids timestamp check are unchanged. Offline mocked StatsAPI.
"""
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from sportsedge.mlb_public_batter_history import MLBBatterPublicSource
from sportsedge.research_model_adapters import mlb_batter_to_bridge_rows
from sportsedge.mlb_phone_batter_pricing import phone_batter_rows

NOW = "2026-10-11T20:55:00Z"
KICKOFF = "2026-10-12T00:00:00Z"
ID = "605141"
DH_DAY = "2026-09-05"


def getter(*, extra_splits=()):
    def get(url):
        p = urlparse(url)
        q = parse_qs(p.query)
        if p.path.endswith("/schedule"):
            day = q.get("date", [""])[0]
            if day == DH_DAY:
                return {"dates": [{"games": [
                    {"gamePk": 700104, "gameDate": "2026-09-05T17:10:00Z",
                     "officialDate": DH_DAY},
                    # Game 2 first pitch 19:00 CDT == exactly midnight UTC,
                    # identical to the 2026-09-06 singleton's midnight stamp.
                    {"gamePk": 700199, "gameDate": "2026-09-06T00:00:00Z",
                     "officialDate": DH_DAY}]}]}
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
            splits.extend(extra_splits)
            return {"stats": [{"splits": splits}]}
        raise AssertionError(url)
    return get


def _prior(**kw):
    return MLBBatterPublicSource(getter=getter(**kw)).prior_games(
        away="Los Angeles Dodgers", home="Milwaukee Brewers",
        player_name="Mookie Betts", owner_kickoff=KICKOFF, as_of=NOW)


def _bridge(v, **overrides):
    kw = dict(
        game_id=v["game_id"], player_id=v["batter_id"], market="BATTER_HITS",
        side="OVER", line=0.5, features=v["features"],
        prior_game_times_utc=v["prior_game_times_utc"],
        prior_game_ids=v["prior_game_ids"],
        source_as_of_utc=v["source_as_of_utc"], as_of_utc=NOW,
        kickoff_utc=v["kickoff_utc"], home_team="Milwaukee Brewers",
        away_team="Los Angeles Dodgers")
    kw.update(overrides)
    return mlb_batter_to_bridge_rows(**kw)[0]


def test_midnight_collision_doubleheader_prices_via_identity():
    v = _prior()
    assert v["prior_game_count"] == 13
    times = v["prior_game_times_utc"]
    # The stamp collision is still present in the data; identity, not the
    # stamp, is what now distinguishes the two games.
    assert len(set(times)) == len(times) - 1
    ids = v["prior_game_ids"]
    assert len(ids) == 13 and len(set(ids)) == 13
    assert "700199" in ids and "700105" in ids  # DH game 2 + Sep 6 singleton
    row = _bridge(v)
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" not in str(row)
    assert row.get("status") == "PRICED_RESEARCH"


def test_phone_path_threads_ids_and_prices():
    rows, sources = phone_batter_rows(
        [{"player_name": "Mookie Betts", "market": "BATTER_HITS", "line": 0.5,
          "side": "OVER", "odds": -135, "book": "draftkings",
          "away": "Los Angeles Dodgers", "home": "Milwaukee Brewers",
          "kickoff": KICKOFF, "quote_captured_at": "2026-10-11T20:54:00Z"}],
        now=datetime(2026, 10, 11, 20, 55, tzinfo=timezone.utc),
        getter=getter())
    assert sources and sources[0]["status"] == "PUBLIC_MLB_PRIOR_BATTER_GAMES_VERIFIED"
    # prior_game_count is attached only after the bridge prices the row;
    # a gate block returns early without it. (The judged status itself is
    # the milestone gate's business — this row is single-sided by design.)
    assert rows[0].get("prior_game_count") == 13
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" not in str(rows[0])


def test_same_game_twice_blocks_even_with_distinct_stamps():
    v = _prior()
    # Fully distinct stamps: under the old timestamp-only check this
    # history would have priced despite containing one game twice.
    times = [f"2026-09-{i + 1:02d}T12:00:00+00:00" for i in range(13)]
    assert len(set(times)) == len(times)
    ids = list(v["prior_game_ids"])
    ids[3] = ids[4]  # the same game counted twice under two stamps
    row = _bridge(v, prior_game_times_utc=times, prior_game_ids=ids)
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(row)


def test_leak_still_blocks_with_unique_ids():
    v = _prior()
    times = list(v["prior_game_times_utc"])
    times[0] = "2026-10-11T21:00:00+00:00"  # after the source as-of
    row = _bridge(v, prior_game_times_utc=times)
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(row)


def test_ids_length_mismatch_blocks():
    v = _prior()
    row = _bridge(v, prior_game_ids=v["prior_game_ids"][:-1])
    assert row.get("status") == "NO_MODEL_OR_MARKET"
    assert "GAME_ID_EACH_PRIOR_GAME_REQUIRED" in str(row)


def test_legacy_no_ids_path_still_blocks_duplicate_stamps():
    v = _prior()
    row = _bridge(v, prior_game_ids=None)
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(row)


def test_target_date_games_still_excluded():
    extra = [
        {"date": "2026-10-11", "game": {"gamePk": 700200},
         "stat": {"plateAppearances": 4, "hits": 1, "totalBases": 1,
                  "rbi": 0, "runs": 0, "homeRuns": 0, "stolenBases": 0}},
        {"date": "2026-10-12", "game": {"gamePk": 700201},
         "stat": {"plateAppearances": 4, "hits": 1, "totalBases": 1,
                  "rbi": 0, "runs": 0, "homeRuns": 0, "stolenBases": 0}},
    ]
    v = _prior(extra_splits=extra)
    assert v["prior_game_count"] == 13
    assert "700200" not in v["prior_game_ids"]
    assert "700201" not in v["prior_game_ids"]

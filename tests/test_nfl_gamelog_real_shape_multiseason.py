"""Real ESPN gamelog shape: events dict + names + seasonTypes, multi-season.

Verified live 2026-10-11: the gamelog endpoint returns `events` as a dict
keyed by eventId (not a list), top-level `names` aligned with stat arrays,
and stats under seasonTypes -> categories -> events. A single in-progress
season rarely holds 5+ games, so the collector must span seasons.
"""
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from sportsedge.nfl_public_player_history import (
    NFLPlayerPublicSource, MissingNFLHistory,
)

NOW = datetime(2026, 10, 11, 20, 30, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T00:00:00Z"
CAPTURE = "2026-10-11T20:29:30Z"

NAMES = ["passingYards", "passingTouchdowns", "interceptions"]


def _season_payload(year, game_ids, yards):
    events = {}
    cat_events = []
    for eid, yds in zip(game_ids, yards):
        events[eid] = {"id": eid, "gameDate": f"{year}-09-15T12:00:00Z"}
        cat_events.append({"eventId": eid, "stats": [str(yds), "2", "1"]})
    return {"names": NAMES, "events": events,
            "seasonTypes": [{"categories": [{"events": cat_events}]}]}


def _getter(seasons):
    def get(url):
        path = urlparse(url).path
        qs = parse_qs(urlparse(url).query)
        if path.endswith("/scoreboard"):
            return {"events": [{"id": "401999001", "date": KICKOFF,
                                "competitions": [{"competitors": [
                                    {"homeAway": "home",
                                     "team": {"id": "14", "displayName": "Los Angeles Rams"}},
                                    {"homeAway": "away",
                                     "team": {"id": "02", "displayName": "Buffalo Bills"}},
                                ]}]}]}
        if path.endswith("/roster"):
            return None
        if path.endswith("/search/v2"):
            return {"results": [{"contents": [{"player": {
                "id": "777", "displayName": "Example Quarterback",
                "team": {"id": "02"}}}]}]}
        if path.endswith("/gamelog"):
            season = int(qs.get("season", ["2026"])[0])
            return seasons.get(season)
        raise AssertionError("Unexpected URL " + url)
    return get


def _row(**extra):
    return {"sport": "NFL", "away": "Buffalo Bills", "home": "Los Angeles Rams",
            "kickoff": KICKOFF, "market": "PASSING_YARDS",
            "player_name": "Example Quarterback", "side": "OVER",
            "line": 200.5, "odds": -110, "book": "draftkings",
            "quote_captured_at": CAPTURE, **extra}


def test_events_dict_shape_parses_and_spans_seasons():
    # 2 games in 2026 + 4 games in 2025 = 6 >= 5 required.
    seasons = {
        2026: _season_payload(2026, ["e1", "e2"], [250, 180]),
        2025: _season_payload(2025, ["e3", "e4", "e5", "e6"],
                              [300, 150, 220, 190]),
    }
    src = NFLPlayerPublicSource(getter=_getter(seasons))
    out = src.prior_games(away="Buffalo Bills", home="Los Angeles Rams",
                          player_name="Example Quarterback",
                          owner_kickoff=KICKOFF, as_of=NOW.isoformat())
    assert out["prior_game_count"] == 6
    hist = out["features"]["game_history"]
    assert len(hist) == 6
    assert all("passing_yards" in g for g in hist)
    # Newest first across seasons.
    assert hist[0]["passing_yards"] == 250.0


def test_fewer_than_five_across_all_seasons_still_blocks():
    seasons = {2026: _season_payload(2026, ["e1", "e2"], [250, 180])}
    src = NFLPlayerPublicSource(getter=_getter(seasons))
    try:
        src.prior_games(away="Buffalo Bills", home="Los Angeles Rams",
                        player_name="Example Quarterback",
                        owner_kickoff=KICKOFF, as_of=NOW.isoformat())
    except MissingNFLHistory as exc:
        assert "FEWER_THAN_FIVE" in str(exc)
    else:
        raise AssertionError("expected fail-closed on <5 games")


def test_malformed_shape_fails_closed_not_guessed():
    src = NFLPlayerPublicSource(
        getter=_getter({2026: {"events": [{"id": "x"}]}}))
    try:
        src.prior_games(away="Buffalo Bills", home="Los Angeles Rams",
                        player_name="Example Quarterback",
                        owner_kickoff=KICKOFF, as_of=NOW.isoformat())
    except MissingNFLHistory as exc:
        assert "EVENTS_MALFORMED" in str(exc) or "UNAVAILABLE" in str(exc) \
            or "FEWER_THAN_FIVE" in str(exc)
    else:
        raise AssertionError("expected fail-closed on malformed shape")

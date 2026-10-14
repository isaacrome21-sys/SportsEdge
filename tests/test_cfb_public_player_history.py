"""D1 regression: CFBPlayerPublicSource against the live ESPN gamelog shape.

The live common-v3 gamelog keeps event metadata in a top-level ``events``
dict and the stat arrays under ``seasonTypes[].categories[].events[]``
(aligned to the top-level ``names``). The pre-fix source required
``events`` to be a list of self-contained event objects and raised
ESPN_GAMELOG_EVENTS_NOT_LIST on every real payload. These fixtures pin:

- the live shape decodes (metadata map + seasonTypes stats);
- the legacy list shape is still handled (documented contract decision:
  both shapes are accepted; any other ``events`` type fails closed with
  the existing named error);
- prior-season fill (?season=YYYY) reaches a transfer's prior-school
  games, with per-game season / opponent / team attribution;
- malformed payloads fail closed with the existing named errors and
  per-event schema rejections are counted, never zero-filled.
"""
import copy
from urllib.parse import urlparse, parse_qs

import pytest

from sportsedge.cfb_public_player_history import (
    CFBPlayerPublicSource, MissingCFBHistory)

HOME, AWAY = "Alpha State", "Gamma College"
HOME_ID, AWAY_ID = "101", "303"
PLAYER = "Casey Sample"
ATHLETE_ID = "900001"
KICKOFF = "2026-10-17T23:30:00+00:00"
AS_OF = "2026-10-14T21:00:00+00:00"

NAMES = ["completions", "passingAttempts", "passingYards", "passingTouchdowns",
         "interceptions", "rushingAttempts", "rushingYards"]

FIXTURE_EVENT = {"id": "401999001", "date": KICKOFF,
                 "competitions": [{"competitors": [
                     {"homeAway": "home",
                      "team": {"id": HOME_ID, "displayName": HOME}},
                     {"homeAway": "away",
                      "team": {"id": AWAY_ID, "displayName": AWAY}}]}]}

ROSTERS = {
    HOME_ID: {"team": {"id": HOME_ID}, "athletes": [{"items": [
        {"id": ATHLETE_ID, "displayName": PLAYER}]}]},
    AWAY_ID: {"team": {"id": AWAY_ID}, "athletes": [{"items": [
        {"id": "900777", "displayName": "Other Player"}]}]},
}


def stats_for(yards, comp="20", att="30"):
    return [comp, att, str(yards), "2", "0", "3", "12"]


def live_gamelog(games, season_label):
    """Current ESPN shape: events metadata dict + seasonTypes stat entries."""
    events, cat_events = {}, []
    for g in games:
        meta = {"id": g["id"], "gameDate": g["date"], "gameResult": "W"}
        if "opponent" in g:
            meta["opponent"] = g["opponent"]
        if "home_id" in g:
            meta["homeTeamId"] = g["home_id"]
        if "away_id" in g:
            meta["awayTeamId"] = g["away_id"]
        events[g["id"]] = meta
        if "stats" in g:
            cat_events.append({"eventId": g["id"], "stats": g["stats"]})
    return {"names": list(NAMES), "events": events,
            "seasonTypes": [{"displayName": season_label,
                             "categories": [{"displayName": "Regular Season Stats",
                                             "events": cat_events}]}]}


def game(event_id, date, yards, *, team_id=None, opp=None):
    g = {"id": event_id, "date": date, "stats": stats_for(yards)}
    if opp is not None:
        opp_id, opp_name = opp
        g["opponent"] = {"id": opp_id, "displayName": opp_name,
                         "abbreviation": opp_name[:4].upper()}
        if team_id is not None:
            # Half the games at home, half away; elimination must agree.
            if int(event_id) % 2 == 0:
                g["home_id"], g["away_id"] = team_id, opp_id
            else:
                g["home_id"], g["away_id"] = opp_id, team_id
    return g


def make_getter(gamelogs, calls=None):
    """gamelogs: {None: current payload, 2025: payload-or-None, ...}."""
    def getter(url):
        if calls is not None:
            calls.append(url)
        parsed = urlparse(url)
        path, qs = parsed.path, parse_qs(parsed.query)
        if path.endswith("/scoreboard"):
            return {"events": [copy.deepcopy(FIXTURE_EVENT)]}
        if "/teams/" in path and path.endswith("/roster"):
            tid = path.split("/teams/")[1].split("/")[0]
            return copy.deepcopy(ROSTERS.get(
                tid, {"team": {"id": tid}, "athletes": []}))
        if path.endswith("/gamelog"):
            season = qs.get("season", [None])[0]
            key = int(season) if season else None
            if key is None:
                return copy.deepcopy(gamelogs.get(None))
            return copy.deepcopy(gamelogs.get(key))
        if path.endswith("/search/v2"):
            return {"results": []}
        raise AssertionError("Unexpected URL: " + url)
    return getter


def prior(gamelogs, calls=None, **kwargs):
    opts = dict(away=AWAY, home=HOME, player_name=PLAYER,
                owner_kickoff=KICKOFF, as_of=AS_OF)
    opts.update(kwargs)
    return CFBPlayerPublicSource(
        getter=make_getter(gamelogs, calls)).prior_games(**opts)


def six_current_games():
    return [
        game("401900102", "2026-09-05T17:00:00Z", 210,
             team_id=HOME_ID, opp=("403", "Zeta University")),
        game("401900103", "2026-09-12T17:00:00Z", 188,
             team_id=HOME_ID, opp=("404", "Lambda College")),
        game("401900104", "2026-09-19T17:00:00Z", 260,
             team_id=HOME_ID, opp=("402", "Epsilon College")),
        game("401900105", "2026-09-26T17:00:00Z", 231,
             team_id=HOME_ID, opp=("405", "Mu State")),
        game("401900106", "2026-10-03T17:00:00Z", 305,
             team_id=HOME_ID, opp=("401", "Delta State")),
        game("401900107", "2026-10-10T17:00:00Z", 274,
             team_id=HOME_ID, opp=("406", "Nu University")),
    ]


def test_live_shape_current_season_decodes_without_prior_season_fetch():
    calls = []
    out = prior({None: live_gamelog(six_current_games(), "2026 Regular Season")},
                calls=calls)
    assert out["player_id"] == ATHLETE_ID
    assert out["prior_game_count"] == 6
    assert out["schema_rejected_prior_events"] == 0
    yards = [g["passing_yards"] for g in out["features"]["game_history"]]
    assert yards == [274.0, 305.0, 231.0, 260.0, 188.0, 210.0]  # newest first
    assert out["prior_game_seasons"] == ["2026-regular"] * 6
    assert out["prior_game_team_ids"] == [HOME_ID] * 6
    assert out["prior_game_opponents"][0] == "Nu University"
    assert out["prior_season_history_years"] == []
    assert not any("season=" in c for c in calls)


def test_two_season_two_team_transfer_history_is_attributed_per_game():
    current = [
        game("401900202", "2026-09-05T17:00:00Z", 210,
             team_id="101", opp=("403", "Zeta University")),
        game("401900204", "2026-09-19T17:00:00Z", 260,
             team_id="101", opp=("402", "Epsilon College")),
        game("401900206", "2026-10-03T17:00:00Z", 305,
             team_id="101", opp=("401", "Delta State")),
    ]
    previous = [  # the same athlete's 2025 games at Beta University (id 202)
        game("401800301", "2025-09-06T17:00:00Z", 180,
             team_id="202", opp=("504", "Kappa College")),
        game("401800302", "2025-09-27T17:00:00Z", 240,
             team_id="202", opp=("503", "Iota University")),
        game("401800303", "2025-10-18T17:00:00Z", 275,
             team_id="202", opp=("502", "Theta State")),
        game("401800304", "2025-11-08T17:00:00Z", 199,
             team_id="202", opp=("501", "Eta College")),
    ]
    calls = []
    out = prior({None: live_gamelog(current, "2026 Regular Season"),
                 2025: live_gamelog(previous, "2025 Regular Season")},
                calls=calls)
    assert out["prior_game_count"] == 7
    yards = [g["passing_yards"] for g in out["features"]["game_history"]]
    assert yards == [305.0, 260.0, 210.0, 199.0, 275.0, 240.0, 180.0]
    assert out["prior_game_seasons"] == ["2026-regular"] * 3 + ["2025-regular"] * 4
    # The two schools stay attributed per game; nothing is silently pooled.
    assert out["prior_game_team_ids"] == ["101"] * 3 + ["202"] * 4
    assert out["prior_game_opponents"] == [
        "Delta State", "Epsilon College", "Zeta University",
        "Eta College", "Theta State", "Iota University", "Kappa College"]
    assert out["prior_season_history_years"] == [2025]
    assert any("season=2025" in c for c in calls)
    assert not any("season=2024" in c for c in calls)  # stops once >= 5


def test_legacy_event_list_shape_still_decodes():
    legacy = {"names": list(NAMES),
              "events": [{"id": str(401700100 + i),
                          "date": f"2026-09-{5 + i:02d}T17:00:00Z",
                          "stats": stats_for(200 + 10 * i)}
                         for i in range(6)]}
    out = prior({None: legacy})
    assert out["prior_game_count"] == 6
    yards = [g["passing_yards"] for g in out["features"]["game_history"]]
    assert yards == [250.0, 240.0, 230.0, 220.0, 210.0, 200.0]
    # Legacy payloads carry no seasonTypes and no team metadata: the season
    # falls back to the kickoff's nominal year and attribution stays empty.
    assert out["prior_game_seasons"] == ["2026-unknown"] * 6
    assert out["prior_game_team_ids"] == [None] * 6
    assert out["prior_game_opponents"] == [None] * 6


@pytest.mark.parametrize("bad_events", ["bogus", 42, 3.5])
def test_events_wrong_type_fails_closed_with_existing_named_error(bad_events):
    payload = live_gamelog(six_current_games(), "2026 Regular Season")
    payload["events"] = bad_events
    with pytest.raises(MissingCFBHistory, match="ESPN_GAMELOG_EVENTS_NOT_LIST"):
        prior({None: payload})


def test_gamelog_unavailable_fails_closed():
    with pytest.raises(MissingCFBHistory, match="CFB_GAMELOG_UNAVAILABLE"):
        prior({None: None})


def test_conflicting_duplicate_stats_fail_closed():
    payload = live_gamelog(six_current_games(), "2026 Regular Season")
    cats = payload["seasonTypes"][0]["categories"]
    dup = {"eventId": "401900106", "stats": stats_for(999)}
    cats.append({"displayName": "Duplicate Category", "events": [dup]})
    with pytest.raises(MissingCFBHistory, match="ESPN_GAMELOG_STATS_CONFLICT"):
        prior({None: payload})


def test_misaligned_stats_are_counted_and_skipped_never_zero_filled():
    games = six_current_games()
    games[2]["stats"] = games[2]["stats"][:5]  # names/stats length mismatch
    out = prior({None: live_gamelog(games, "2026 Regular Season")})
    assert out["prior_game_count"] == 5
    assert out["schema_rejected_prior_events"] == 1
    assert out["schema_rejected_prior_reasons"].get(
        "ESPN_GAMELOG_NAMES_STATS_UNALIGNED") == 1
    yards = [g["passing_yards"] for g in out["features"]["game_history"]]
    assert 260.0 not in yards


def test_metadata_key_id_conflict_is_rejected_not_repaired():
    games = six_current_games()
    payload = live_gamelog(games, "2026 Regular Season")
    payload["events"]["401999999"] = {
        "id": "401900102", "gameDate": "2026-08-29T17:00:00Z"}
    out = prior({None: payload})
    assert out["prior_game_count"] == 6
    assert out["schema_rejected_prior_reasons"].get(
        "GAMEDAY_EVENT_METADATA_INVALID") == 1


def test_event_without_stats_is_rejected_not_zero_filled():
    games = six_current_games()
    ghost = {"id": "401900150", "date": "2026-08-29T17:00:00Z"}
    payload = live_gamelog(games, "2026 Regular Season")
    payload["events"]["401900150"] = {
        "id": "401900150", "gameDate": ghost["date"], "gameResult": "W"}
    out = prior({None: payload})
    assert out["prior_game_count"] == 6
    assert out["schema_rejected_prior_events"] == 1
    assert "2026-08-29" not in " ".join(out["prior_game_times_utc"])


def test_post_as_of_game_is_excluded_by_pit_filter():
    games = six_current_games() + [
        game("401900120", "2026-10-15T17:00:00Z", 400,
             team_id=HOME_ID, opp=("407", "Xi College"))]
    out = prior({None: live_gamelog(games, "2026 Regular Season")})
    assert out["prior_game_count"] == 6
    assert out["schema_rejected_prior_events"] == 0
    yards = [g["passing_yards"] for g in out["features"]["game_history"]]
    assert 400.0 not in yards


def test_unavailable_prior_season_is_counted_and_fill_continues():
    current = six_current_games()[:3]
    older = [
        game("401600301", "2024-09-07T17:00:00Z", 190,
             team_id="202", opp=("504", "Kappa College")),
        game("401600302", "2024-09-28T17:00:00Z", 230,
             team_id="202", opp=("503", "Iota University")),
        game("401600303", "2024-10-19T17:00:00Z", 265,
             team_id="202", opp=("502", "Theta State")),
    ]
    out = prior({None: live_gamelog(current, "2026 Regular Season"),
                 2025: None,
                 2024: live_gamelog(older, "2024 Regular Season")})
    assert out["prior_game_count"] == 6
    assert out["prior_season_history_years"] == [2025, 2024]
    assert out["schema_rejected_prior_reasons"].get(
        "PRIOR_SEASON_UNAVAILABLE") == 1
    assert out["prior_game_team_ids"] == ["101"] * 3 + ["202"] * 3


def test_identical_cross_season_duplicate_dedupes_conflict_fails():
    shared = game("401900206", "2026-10-03T17:00:00Z", 305,
                  team_id="101", opp=("401", "Delta State"))
    current = [
        game("401900202", "2026-09-05T17:00:00Z", 210,
             team_id="101", opp=("403", "Zeta University")),
        game("401900204", "2026-09-19T17:00:00Z", 260,
             team_id="101", opp=("402", "Epsilon College")),
        shared]
    previous = [shared,
                game("401800301", "2025-09-06T17:00:00Z", 180,
                     team_id="202", opp=("504", "Kappa College")),
                game("401800302", "2025-09-27T17:00:00Z", 240,
                     team_id="202", opp=("503", "Iota University"))]
    out = prior({None: live_gamelog(current, "2026 Regular Season"),
                 2025: live_gamelog(previous, "2025 Regular Season")})
    assert out["prior_game_count"] == 5  # shared game counted once
    conflict = copy.deepcopy(previous)
    conflict[0] = game("401900206", "2026-10-03T17:00:00Z", 306,
                       team_id="101", opp=("401", "Delta State"))
    with pytest.raises(MissingCFBHistory, match="ESPN_GAMELOG_STATS_CONFLICT"):
        prior({None: live_gamelog(current, "2026 Regular Season"),
               2025: live_gamelog(conflict, "2025 Regular Season")})


def test_fewer_than_five_after_all_seasons_fails_closed():
    current = six_current_games()[:3]
    with pytest.raises(MissingCFBHistory,
                       match="FEWER_THAN_FIVE_VERIFIED_NAMED_PRIOR_GAMES"):
        prior({None: live_gamelog(current, "2026 Regular Season"),
               2025: None, 2024: None})

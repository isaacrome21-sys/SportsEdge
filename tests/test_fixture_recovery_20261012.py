"""Fixture recovery regression tests for 2026-10-12 evening games.

All requests are deterministic recorded JSON fixtures. No network, odds, or
unverified intake IDs are used to establish game identity.
"""
from datetime import datetime, timezone
from urllib.parse import urlencode

from artifacts.free_models import PublicContext, dt
from sportsedge.prepricing.factor_ingestion import (
    mlb_pitcher_adjustments, match_scheduled_game,
)

CLOCK = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
MLB_KICKOFF = dt("2026-10-13T00:00:00Z")
NFL_KICKOFF = dt("2026-10-13T00:15:00Z")
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
STATS = "https://statsapi.mlb.com/api/v1"


class Getter:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.mapping:
            raise OSError("UNMAPPED_URL:" + url)
        return self.mapping[url]


def mlb_schedule_url(day):
    return STATS + "/schedule?" + urlencode({
        "sportId": 1, "date": day, "hydrate": "team,probablePitcher",
    })


def stats_game(*, game_pk=900012, kickoff="2026-10-13T00:00:00Z"):
    return {
        "gamePk": game_pk, "gameDate": kickoff,
        "status": {"detailedState": "Scheduled"},
        "teams": {
            "home": {
                "team": {"id": 139, "name": "Tampa Bay Rays",
                         "teamName": "Rays", "abbreviation": "TB"},
                "probablePitcher": {"id": 50001, "fullName": "Test Rays Pitcher"},
            },
            "away": {
                "team": {"id": 114, "name": "Cleveland Guardians",
                         "teamName": "Guardians", "abbreviation": "CLE"},
                "probablePitcher": {"id": 50002, "fullName": "Test Guardians Pitcher"},
            },
        },
    }


def mlb_mapping(games=None):
    return {
        mlb_schedule_url("2026-10-12"): {
            "dates": [{"games": [stats_game()] if games is None else games}]},
    }


def nfl_teams():
    return {"sports": [{"leagues": [{"teams": [
        {"team": {"id": "2", "displayName": "Buffalo Bills",
                  "name": "Bills", "abbreviation": "BUF"}},
        {"team": {"id": "14", "displayName": "Los Angeles Rams",
                  "name": "Rams", "abbreviation": "LAR"}},
    ]}]}]}


def nfl_schedule_event(*, away_id="2", kickoff="2026-10-13T00:15:00Z",
                       event_id="401999000"):
    return {
        "id": event_id, "date": kickoff,
        "status": {"type": {"state": "pre", "completed": False}},
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "team": {"id": "14"}},
                {"homeAway": "away", "team": {"id": away_id}},
            ],
            "venue": {"fullName": "SoFi Stadium", "indoor": True},
        }],
    }


def nfl_mapping(events):
    return {
        f"{ESPN}/football/nfl/teams?limit=500": nfl_teams(),
        f"{ESPN}/football/nfl/teams/14/schedule?season=2026":
            {"events": events},
    }


def test_mlb_fallback_binds_nickname_on_previous_local_date():
    source = Getter(mlb_mapping())
    provider = PublicContext(CLOCK, getter=source)
    fixture = provider.fixture("MLB", "Guardians", "Rays", MLB_KICKOFF)
    assert fixture is not None
    start, comp = fixture
    assert start == MLB_KICKOFF
    assert comp["game_pk"] == 900012
    assert comp["source"] == "MLB_STATSAPI_SCHEDULE_VERIFIED"
    assert mlb_schedule_url("2026-10-12") in source.calls


def test_mlb_fallback_rejects_two_plausible_game_pks():
    source = Getter(mlb_mapping([
        stats_game(game_pk=900012),
        stats_game(game_pk=900013, kickoff="2026-10-13T00:05:00Z"),
    ]))
    assert PublicContext(CLOCK, getter=source).fixture(
        "MLB", "Guardians", "Rays", MLB_KICKOFF) is None


def test_mlb_pitcher_lookup_crosses_utc_date_without_guessing():
    source = Getter(mlb_mapping())
    changes, records, blocked, reason = mlb_pitcher_adjustments(
        source, game_date=MLB_KICKOFF.date(),
        home={"abbr": "TB", "name": "Tampa Bay Rays"},
        away={"abbr": "CLE", "name": "Cleveland Guardians"},
        season=2026, kickoff=MLB_KICKOFF,
        stats_fetch=lambda fetch, pitcher_id, season: (3.1, 130.0, 25),
    )
    assert not blocked, reason
    assert set(changes) == {"home_pitcher_adj", "away_pitcher_adj"}
    assert sum(r["status"] == "USED" for r in records) == 2
    assert mlb_schedule_url("2026-10-12") in source.calls


def test_mlb_exact_time_prevents_ambiguous_adjacent_starts():
    two = [stats_game(game_pk=900012),
           stats_game(game_pk=900013, kickoff="2026-10-13T04:00:00Z")]
    selected = match_scheduled_game(
        two, {"abbr": "TB", "name": "Tampa Bay Rays"},
        {"abbr": "CLE", "name": "Cleveland Guardians"},
        kickoff=MLB_KICKOFF)
    assert selected["gamePk"] == 900012
    assert match_scheduled_game(
        [stats_game(game_pk=900012), stats_game(game_pk=900013)],
        {"abbr": "TB", "name": "Tampa Bay Rays"},
        {"abbr": "CLE", "name": "Cleveland Guardians"},
        kickoff=MLB_KICKOFF) is None


def test_nfl_missing_scoreboard_uses_unique_id_bound_team_schedule():
    getter = Getter(nfl_mapping([nfl_schedule_event()]))
    provider = PublicContext(CLOCK, getter=getter)
    result = provider.fixture("NFL", "Buffalo Bills", "Los Angeles Rams", NFL_KICKOFF)
    assert result is not None
    start, competition = result
    assert start == NFL_KICKOFF
    assert competition["venue"]["fullName"] == "SoFi Stadium"
    assert f"{ESPN}/football/nfl/teams/14/schedule?season=2026" in getter.calls


def test_nfl_fallback_rejects_wrong_opponent_or_ambiguous_event():
    wrong = Getter(nfl_mapping([nfl_schedule_event(away_id="4")]))
    assert PublicContext(CLOCK, getter=wrong).fixture(
        "NFL", "Buffalo Bills", "Los Angeles Rams", NFL_KICKOFF) is None
    duplicate = Getter(nfl_mapping([
        nfl_schedule_event(event_id="A"), nfl_schedule_event(event_id="B"),
    ]))
    assert PublicContext(CLOCK, getter=duplicate).fixture(
        "NFL", "Buffalo Bills", "Los Angeles Rams", NFL_KICKOFF) is None


def test_nfl_fallback_rejects_started_or_finished():
    already_started = Getter(nfl_mapping([
        nfl_schedule_event(kickoff="2026-10-12T19:00:00Z"),
    ]))
    assert PublicContext(CLOCK, getter=already_started).fixture(
        "NFL", "Buffalo Bills", "Los Angeles Rams", NFL_KICKOFF) is None
    done = nfl_schedule_event()
    done["status"] = {"type": {"state": "post", "completed": True}}
    assert PublicContext(CLOCK, getter=Getter(nfl_mapping([done]))).fixture(
        "NFL", "Buffalo Bills", "Los Angeles Rams", NFL_KICKOFF) is None

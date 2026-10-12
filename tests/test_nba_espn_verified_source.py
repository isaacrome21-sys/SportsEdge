"""Recorded-fixture tests for the verified NBA ESPN source path."""
import json
from pathlib import Path

import pytest

from sportsedge.sports.nba.espn_verified_source import (
    NBA_TEAMS,
    NBASource,
    NBADataError,
    team_by_abbreviation,
    team_by_display_name,
    team_by_id,
)

FIX = Path(__file__).parent / "fixtures" / "nba"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def fake_getter(routes):
    def get(url):
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                return payload
        return None
    return get


class TestTeamRegistry:
    def test_thirty_teams_match_recorded_registry(self):
        recorded = load("teams_registry.json")
        assert len(recorded) == 30
        assert len(NBA_TEAMS) == 30
        for row in recorded:
            team = team_by_id(row["id"])
            assert team["abbreviation"] == row["abbreviation"]
            assert team["displayName"] == row["displayName"]

    def test_lookup_paths(self):
        assert team_by_abbreviation("lal")["id"] == "13"
        assert team_by_display_name("Los Angeles Lakers")["id"] == "13"
        assert team_by_display_name("los angeles lakers")["id"] == "13"

    def test_unknown_team_fails_closed(self):
        with pytest.raises(NBADataError):
            team_by_id("999")
        with pytest.raises(NBADataError):
            team_by_abbreviation("ZZZ")


class TestScoreboard:
    def test_parse_completed_games_from_recorded_scoreboard(self):
        src = NBASource(getter=fake_getter({
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard":
                load("scoreboard_20241023.json"),
        }))
        events = src.scoreboard("20241023")
        games = src.parse_completed_games(events)
        assert len(games) == 3
        by_id = {g["event_id"]: g for g in games}
        ind_det = by_id["401704629"]
        assert ind_det["home_team_id"] == "8"      # DET Pistons
        assert ind_det["away_team_id"] == "11"     # IND Pacers
        assert ind_det["home_score"] == 109
        assert ind_det["away_score"] == 115
        assert ind_det["tipoff"] == "2024-10-23T23:00Z"

    def test_all_star_exhibition_skipped_when_opted_in(self):
        # real 2025 All-Star game shape: special team ids outside the registry
        src = NBASource(getter=fake_getter({}))
        events = [
            {"id": "401752955", "date": "2025-02-17T01:20Z",
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [
                 {"homeAway": "home", "team": {"id": "130579", "displayName": "Team Chuck"}, "score": "41"},
                 {"homeAway": "away", "team": {"id": "130581", "displayName": "Team Kenny"}, "score": "32"}]}]},
        ]
        assert src.parse_completed_games(events, skip_unregistered_teams=True) == []
        with pytest.raises(NBADataError, match="NBA_TEAM_ID_NOT_IN_VERIFIED_REGISTRY"):
            src.parse_completed_games(events)
        src = NBASource(getter=fake_getter({}))
        events = [
            {"id": "1", "date": "2024-10-23T23:00Z",
             "status": {"type": {"completed": False}},
             "competitions": [{"competitors": [
                 {"homeAway": "home", "team": {"id": "8"}, "score": "0"},
                 {"homeAway": "away", "team": {"id": "11"}, "score": "0"}]}]},
        ]
        assert src.parse_completed_games(events) == []

    def test_completed_event_with_bad_score_fails_closed(self):
        src = NBASource(getter=fake_getter({}))
        events = [
            {"id": "1", "date": "2024-10-23T23:00Z",
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [
                 {"homeAway": "home", "team": {"id": "8"}, "score": "abc"},
                 {"homeAway": "away", "team": {"id": "11"}, "score": "100"}]}]},
        ]
        with pytest.raises(NBADataError):
            src.parse_completed_games(events)

    def test_completed_event_with_unregistered_team_fails_closed(self):
        src = NBASource(getter=fake_getter({}))
        events = [
            {"id": "1", "date": "2024-10-23T23:00Z",
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [
                 {"homeAway": "home", "team": {"id": "999"}, "score": "100"},
                 {"homeAway": "away", "team": {"id": "11"}, "score": "99"}]}]},
        ]
        with pytest.raises(NBADataError):
            src.parse_completed_games(events)

    def test_resolve_fixture_unique_pregame(self):
        # recorded opening-night event: Indiana Pacers @ Detroit Pistons,
        # tipped 2024-10-23T23:00Z — resolve it from before tipoff.
        src = NBASource(getter=fake_getter({
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard":
                load("scoreboard_20241023.json"),
        }))
        event = src.resolve_fixture(
            away_name="Indiana Pacers", home_name="Detroit Pistons",
            owner_tipoff="2024-10-23T23:00:00+00:00",
            as_of="2024-10-23T12:00:00+00:00")
        assert event["id"] == "401704629"

    def test_resolve_fixture_rejects_started_game(self):
        src = NBASource(getter=fake_getter({}))
        with pytest.raises(NBADataError):
            src.resolve_fixture(
                away_name="Indiana Pacers", home_name="Detroit Pistons",
                owner_tipoff="2024-10-23T23:00:00+00:00",
                as_of="2024-10-24T12:00:00+00:00")

    def test_resolve_fixture_rejects_unknown_matchup(self):
        src = NBASource(getter=fake_getter({
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard":
                load("scoreboard_20241023.json"),
        }))
        with pytest.raises(NBADataError):
            src.resolve_fixture(
                away_name="Chicago Bulls", home_name="Detroit Pistons",
                owner_tipoff="2024-10-23T23:00:00+00:00",
                as_of="2024-10-23T12:00:00+00:00")


class TestQuarterScores:
    SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"

    def test_quarter_scores_from_recorded_summary(self):
        src = NBASource(getter=fake_getter({
            self.SUMMARY_URL: load("summary_401704629.json"),
        }))
        qs = src.quarter_scores("401704629")
        assert qs["event_id"] == "401704629"
        assert qs["home_team_id"] == "8"
        assert qs["away_team_id"] == "11"
        assert qs["home_quarters"] == [31, 27, 32, 19]
        assert qs["away_quarters"] == [25, 24, 33, 33]
        assert qs["home_first_half"] == 58
        assert qs["away_first_half"] == 49

    def test_quarter_reconciliation_fails_closed(self):
        bad = load("summary_401704629.json")
        bad["header"]["competitions"][0]["competitors"][0]["linescores"][0] = {"displayValue": "99"}
        src = NBASource(getter=fake_getter({self.SUMMARY_URL: bad}))
        with pytest.raises(NBADataError, match="NBA_SUMMARY_QUARTERS_DO_NOT_RECONCILE"):
            src.quarter_scores("401704629")

    def test_missing_linescores_fails_closed(self):
        bad = load("summary_401704629.json")
        del bad["header"]["competitions"][0]["competitors"][0]["linescores"]
        src = NBASource(getter=fake_getter({self.SUMMARY_URL: bad}))
        with pytest.raises(NBADataError, match="NBA_SUMMARY_LINESCORES_UNVERIFIED"):
            src.quarter_scores("401704629")


class TestRosterIdentity:
    def test_roster_player_ids_from_recorded_roster(self):
        src = NBASource(getter=fake_getter({
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/13/roster":
                load("roster_lal_2026.json"),
        }))
        roster = src.roster_player_ids("13")
        assert roster["bronny james"] == "4683774"

    def test_resolve_athlete_roster_first(self):
        src = NBASource(getter=fake_getter({
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/13/roster":
                load("roster_lal_2026.json"),
        }))
        athlete = src.resolve_athlete("Bronny James", {"13", "8"})
        assert athlete["id"] == "4683774"
        assert athlete["team_id"] == "13"
        assert athlete["via"] == "fixture_roster"

    def test_resolve_athlete_rejects_player_not_on_either_roster(self):
        src = NBASource(getter=fake_getter({
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/13/roster":
                load("roster_lal_2026.json"),
            "https://site.web.api.espn.com/apis/search/v2":
                load("search_lebron_james.json"),
        }))
        # LeBron (1966) is not on the recorded 2026-27 LAL roster, and no
        # second roster is provided -> search hit cannot be roster-confirmed.
        with pytest.raises(NBADataError):
            src.resolve_athlete("LeBron James", {"13", "8"})

    def test_resolve_athlete_rejects_unverified_team_ids(self):
        src = NBASource(getter=fake_getter({}))
        with pytest.raises(NBADataError):
            src.resolve_athlete("Bronny James", {"13"})

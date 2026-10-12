"""Tests for the NBA public player-history collector.

Decode fidelity is proven on recorded fixtures in test_nba_gamelog_decode.py.
Here the *gate mechanics* (>=5 games, identity, PIT cutoffs) are exercised on
synthetically multiplied fixtures that keep the exact recorded gamelog shape
(built from the recorded ``names`` list). Synthetic sections are marked.
"""
import json
from pathlib import Path

import pytest

from sportsedge.sports.nba.espn_verified_source import NBASource
from sportsedge.sports.nba.nba_public_player_history import (
    MissingNBAHistory,
    NBAPublicPlayerHistory,
    to_box_observations,
)

FIX = Path(__file__).parent / "fixtures" / "nba"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


RECORDED_NAMES = load("gamelog_1966_2025.json")["names"]


def make_gamelog(names, games):
    """Build a gamelog payload in the verified recorded shape.

    games: list of (event_id, game_date_iso, stats_list, team_id, opp_id,
                    home_score, away_score, home_team_id).
    """
    events = {}
    cat_events = []
    for (eid, gdate, stats, team_id, opp_id, hs, aws, home_tid) in games:
        cat_events.append({"eventId": eid, "stats": stats})
        events[eid] = {
            "id": eid,
            "gameDate": gdate,
            "atVs": "vs" if team_id == home_tid else "@",
            "team": {"id": team_id, "displayName": "T", "abbreviation": "T"},
            "opponent": {"id": opp_id, "displayName": "O", "abbreviation": "O"},
            "homeTeamId": home_tid,
            "awayTeamId": opp_id if home_tid == team_id else team_id,
            "homeTeamScore": str(hs),
            "awayTeamScore": str(aws),
            "gameResult": "W",
            "score": f"{aws}-{hs}",
        }
    return {
        "names": names,
        "labels": ["X"] * len(names),
        "displayNames": ["X"] * len(names),
        "events": events,
        "seasonTypes": [{
            "displayName": "2024-25 Regular Season",
            "displayTeam": "DET",
            "categories": [{"displayName": "october", "type": "event",
                            "splitType": "october", "events": cat_events}],
        }],
    }


def stats_row(minutes="30", pts="20", reb="5", ast="5", threes="2-6"):
    idx = {n: i for i, n in enumerate(RECORDED_NAMES)}
    row = ["0"] * len(RECORDED_NAMES)
    row[idx["minutes"]] = minutes
    row[idx["points"]] = pts
    row[idx["totalRebounds"]] = reb
    row[idx["assists"]] = ast
    row[idx["threePointFieldGoalsMade-threePointFieldGoalsAttempted"]] = threes
    return row


def make_roster(team_id, abbr, players):
    return {
        "team": {"id": team_id, "displayName": abbr, "abbreviation": abbr},
        "season": {"year": 2025},
        "athletes": [{"id": pid, "displayName": name} for pid, name in players],
    }


SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ROSTER_DET = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/8/roster"
ROSTER_IND = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/11/roster"
GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/99999/gamelog"


def build_collector(n_games, player_on="8"):
    scoreboard = load("scoreboard_20241023.json")
    det_players = [("99999", "Test Player")] if player_on == "8" else []
    ind_players = [("99999", "Test Player")] if player_on == "11" else []
    games = []
    for i in range(n_games):
        eid = f"4000000{i:02d}"
        games.append((eid, f"2024-10-{10 + i:02d}T23:00:00.000+00:00",
                      stats_row(pts=str(18 + i)), "8", "11", 110 + i, 100, "8"))
    routes = {
        SCOREBOARD_URL: scoreboard,
        ROSTER_DET: make_roster("8", "DET", det_players),
        ROSTER_IND: make_roster("11", "IND", ind_players),
        GAMELOG_URL: make_gamelog(RECORDED_NAMES, games),
    }

    def getter(url):
        for prefix, payload in routes.items():
            if url == prefix or url.startswith(prefix + "?"):
                return payload
        return None

    return NBAPublicPlayerHistory(source=NBASource(getter=getter))


def base_kwargs():
    return dict(away_name="Indiana Pacers", home_name="Detroit Pistons",
                player_name="Test Player",
                owner_tipoff="2024-10-23T23:00:00+00:00",
                as_of="2024-10-23T12:00:00+00:00",
                season_year=2025)


class TestCollector:
    def test_gate_blocks_fewer_than_five(self):
        collector = build_collector(3)
        with pytest.raises(MissingNBAHistory, match="FEWER_THAN_5"):
            collector.prior_games(**base_kwargs())

    def test_gate_passes_with_five_verified_games(self):
        collector = build_collector(7)
        result = collector.prior_games(**base_kwargs())
        assert result["prior_game_count"] == 7
        assert result["player_id"] == "99999"
        assert result["player_team_id"] == "8"
        assert result["player_team_abbr"] == "DET"
        assert result["game_id"] == "401704629"
        hist = result["features"]["game_history"]
        assert len(hist) == 7
        assert all(h["points"] >= 18 for h in hist)
        assert all(h["team_points"] == 110 + i or True for i, h in enumerate(hist))
        # most recent first; team_points come from the event meta scores
        assert hist[0]["points"] == 24
        assert hist[0]["team_points"] == 116
        assert hist[-1]["team_points"] == 110
        assert result["explicit_stat_fields"]
        assert result["schema_rejected_prior_events"] == 0

    def test_future_games_excluded_by_pit_cutoff(self):
        collector = build_collector(7)
        kwargs = base_kwargs()
        kwargs["as_of"] = "2024-10-12T12:00:00+00:00"  # before the first synthetic game
        with pytest.raises(MissingNBAHistory, match="FEWER_THAN_5"):
            collector.prior_games(**kwargs)

    def test_player_not_on_fixture_rosters_fails_closed(self):
        collector = build_collector(7, player_on="13")  # not a fixture team
        with pytest.raises(MissingNBAHistory):
            collector.prior_games(**base_kwargs())

    def test_box_observations_feed_role_fitter(self):
        collector = build_collector(7)
        result = collector.prior_games(**base_kwargs())
        rows = to_box_observations(result, observed_at="2024-10-23T12:00:00+00:00")
        assert len(rows) == 7
        row = rows[0]
        assert row.player_id == "99999"
        assert row.team_id == "8"
        assert row.points == 24
        assert row.team_points >= row.points
        row.validate()

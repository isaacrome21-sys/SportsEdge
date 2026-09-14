from __future__ import annotations

from datetime import date

from sportsedge.dfs.sources.football_espn import EspnFootballContextClient
from sportsedge.dfs.sources.mlb_statsapi import MLBStatsApiContextClient
from sportsedge.dfs.types import DKPlayer


def _dk(pid: str, name: str, team: str, opp: str, pos: str) -> DKPlayer:
    return DKPlayer(pid, name, team, opp, (pos,), 5000)


def test_mlb_statsapi_enforces_only_fully_reconciled_posted_lineup_and_probable() -> None:
    schedule = {"dates": [{"games": [{"gamePk": 777, "gameDate": "2026-09-14T18:20:00Z"}]}]}
    home_names = [f"Cubs Hitter {i}" for i in range(1, 10)]
    away_names = [f"Cards Hitter {i}" for i in range(1, 10)]

    def box(names):
        return {
            "players": {
                f"ID{i}": {"person": {"id": i, "fullName": name}, "battingOrder": f"{i}00"}
                for i, name in enumerate(names, 1)
            }
        }

    feed = {
        "gameData": {
            "teams": {"home": {"abbreviation": "CHC"}, "away": {"abbreviation": "STL"}},
            "probablePitchers": {
                "home": {"id": 101, "fullName": "Cubs Starter"},
                "away": {"id": 102, "fullName": "Cards Starter"},
            },
            "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
            "datetime": {"dateTime": "2026-09-14T18:20:00Z"},
            "venue": {"id": 17, "name": "Wrigley Field"},
            "weather": {"condition": "Clear", "temp": 76, "wind": "8 mph, Out To RF"},
        },
        "liveData": {"boxscore": {"teams": {"home": box(home_names), "away": box(away_names)}}},
    }

    client = MLBStatsApiContextClient(getter=lambda url: feed if "/game/777/" in url else schedule)
    evidence = client.build_context(date(2026, 9, 14))
    players = [_dk(str(i), name, "CHC", "STL", "OF") for i, name in enumerate(home_names, 1)]
    players += [
        _dk("bench", "Cubs Bench", "CHC", "STL", "OF"),
        _dk("sp", "Cubs Starter", "CHC", "STL", "SP"),
        _dk("rp", "Cubs Other Pitcher", "CHC", "STL", "RP"),
    ]
    updated, diag = client.apply_to_players(players, evidence)
    by_name = {p.name: p for p in updated}
    assert not by_name["Cubs Hitter 1"].is_disabled
    assert by_name["Cubs Bench"].is_disabled
    assert not by_name["Cubs Starter"].is_disabled
    assert by_name["Cubs Other Pitcher"].is_disabled
    assert diag["confirmed_lineup_teams"] == ["CHC"]
    assert diag["probable_pitcher_teams"] == ["CHC"]


def test_mlb_lineup_name_mismatch_blocks_exclusion() -> None:
    evidence = MLBStatsApiContextClient(getter=lambda _: {}).build_context if False else None
    from sportsedge.dfs.sources.types import DfsContextEvidence
    from datetime import datetime, timezone

    ctx = DfsContextEvidence(
        sport="MLB",
        source="TEST",
        retrieved_at=datetime.now(timezone.utc),
        games=({
            "home": "CHC", "away": "STL", "status": {},
            "lineups": {"home": [{"order": i, "name": f"Starter {i}"} for i in range(1, 10)], "away": []},
            "probable_pitchers": {},
        },),
    )
    players = [_dk(str(i), f"Starter {i}", "CHC", "STL", "OF") for i in range(1, 9)]
    players += [_dk("mismatch", "Different Name", "CHC", "STL", "OF"), _dk("bench", "Bench", "CHC", "STL", "OF")]
    updated, diag = MLBStatsApiContextClient.apply_to_players(players, ctx)
    assert not any(p.is_disabled for p in updated)
    assert "CHC:LINEUP_MATCH_8_OF_9" in diag["reconciliation_blocks"]


def test_football_context_disables_only_explicit_hard_unavailable() -> None:
    scoreboard = {
        "events": [{
            "id": "401",
            "date": "2026-09-17T00:15:00Z",
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"id": "1", "abbreviation": "BUF"}},
                    {"homeAway": "away", "team": {"id": "2", "abbreviation": "DET"}},
                ],
                "status": {"type": {"name": "STATUS_SCHEDULED", "description": "Scheduled", "completed": False}},
                "venue": {"fullName": "Highmark Stadium"},
            }],
        }]
    }
    summary = {
        "injuries": [{
            "team": {"id": "1", "abbreviation": "BUF"},
            "injuries": [
                {"athlete": {"id": "11", "displayName": "Out Player"}, "status": "Out", "details": {"detail": "ankle"}},
                {"athlete": {"id": "12", "displayName": "Question Player"}, "status": "Questionable", "details": {"detail": "hamstring"}},
            ],
        }]
    }
    client = EspnFootballContextClient(getter=lambda url: summary if "summary?event=401" in url else scoreboard)
    evidence = client.build_context("NFL", date(2026, 9, 17))
    players = [
        _dk("11", "Out Player", "BUF", "DET", "WR"),
        _dk("12", "Question Player", "BUF", "DET", "WR"),
        _dk("13", "No Injury Row", "BUF", "DET", "RB"),
    ]
    updated, diag = client.apply_to_players(players, evidence)
    by_name = {p.name: p for p in updated}
    assert by_name["Out Player"].is_disabled
    assert not by_name["Question Player"].is_disabled
    assert not by_name["No Injury Row"].is_disabled
    assert diag["missing_injury_rows_are_unknown"] is True

"""Offline regression coverage for the NHL API research collector.

Fixtures are trimmed copies of real payloads captured from
api-web.nhle.com on 2026-10-24 (standings as of 2025-04-17, scores for
2026-10-23, EDM club stats for season 20242025). No test makes a
network request: live paths run against a recording fake opener.
"""
import io
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError

from scripts import collect_nhl_api as m

NOW = datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc)

SCORE_PAYLOAD = {
    "currentDate": "2026-10-23",
    "games": [
        {"id": 2026020166, "gameDate": "2026-10-23", "season": 20262027,
         "gameState": "OFF",
         "awayTeam": {"abbrev": "MTL", "score": 4},
         "homeTeam": {"abbrev": "CHI", "score": 1}},
        {"id": 2026020167, "gameDate": "2026-10-23", "season": 20262027,
         "gameState": "OFF",
         "awayTeam": {"abbrev": "TBL", "score": 3},
         "homeTeam": {"abbrev": "COL", "score": 6}},
        {"id": 2026020999, "gameDate": "2026-10-23", "season": 20262027,
         "gameState": "FUT",
         "awayTeam": {"abbrev": "EDM"},
         "homeTeam": {"abbrev": "CGY"}},
    ],
}

STANDINGS_PAYLOAD = {
    "standingsDateTimeUtc": "2025-04-18T04:00:00Z",
    "standings": [
        {"teamAbbrev": {"default": "EDM"},
         "teamName": {"default": "Edmonton Oilers"}, "seasonId": 20242025,
         "gamesPlayed": 82, "wins": 48, "losses": 29, "otLosses": 5,
         "points": 101, "goalFor": 259, "goalAgainst": 236},
        {"teamAbbrev": {"default": "WPG"},
         "teamName": {"default": "Winnipeg Jets"}, "seasonId": 20242025,
         "gamesPlayed": 82, "wins": 56, "losses": 22, "otLosses": 4,
         "points": 116, "goalFor": 277, "goalAgainst": 191},
    ],
}

CLUB_STATS_PAYLOAD = {
    "season": 20242025, "gameType": 2,
    "skaters": [
        {"playerId": 8477934, "firstName": {"default": "Leon"},
         "lastName": {"default": "Draisaitl"}, "positionCode": "C",
         "gamesPlayed": 71, "goals": 52, "assists": 54, "points": 106,
         "shots": 240},
    ],
    "goalies": [
        {"playerId": 8479973, "firstName": {"default": "Stuart"},
         "lastName": {"default": "Skinner"}, "gamesPlayed": 51,
         "gamesStarted": 50, "wins": 26, "losses": 18,
         "savePercentage": 0.895849, "goalsAgainstAverage": 2.81398,
         "shutouts": 3},
    ],
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def fake_opener(payload):
    def opener(request, timeout=None):
        return FakeResponse(json.dumps(payload).encode("utf-8"))
    return opener


def exploding_opener(request, timeout=None):
    raise AssertionError("network must not be touched")


class NhlApiCollectorTests(unittest.TestCase):
    def test_default_run_makes_zero_requests(self):
        out = m.collect("score", date="2026-10-23", opener=exploding_opener)
        self.assertEqual(out["status"], "NO_LIVE_CALL")
        self.assertEqual(out["requests"], 0)
        self.assertEqual(out["url"],
                         "https://api-web.nhle.com/v1/score/2026-10-23")

    def test_build_url_shapes(self):
        self.assertEqual(m.build_url("standings"),
                         "https://api-web.nhle.com/v1/standings/now")
        self.assertEqual(m.build_url("standings", date="2025-04-17"),
                         "https://api-web.nhle.com/v1/standings/2025-04-17")
        self.assertEqual(
            m.build_url("club-stats", team="EDM", season="20242025"),
            "https://api-web.nhle.com/v1/club-stats/EDM/20242025/2")

    def test_validators_fail_closed(self):
        for bad in ("2026-13-01", "10/23/2026", "now", 20261023):
            with self.assertRaises(m.IntakeRefusal):
                m.validate_date(bad)
        for bad in ("20242026", "2024-25", "1234567", 20242025):
            with self.assertRaises(m.IntakeRefusal):
                m.validate_season(bad)
        for bad in ("edm", "EDMONTON", "E", ""):
            with self.assertRaises(m.IntakeRefusal):
                m.validate_team(bad)
        with self.assertRaises(m.IntakeRefusal):
            m.validate_game_type(4)
        with self.assertRaises(m.IntakeRefusal):
            m.build_url("play-by-play")

    def test_normalize_scores_recorded_payload(self):
        rows = m.normalize_scores(SCORE_PAYLOAD)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], {
            "game_id": 2026020166, "game_date": "2026-10-23",
            "season": 20262027, "game_state": "OFF",
            "away_abbrev": "MTL", "away_score": 4,
            "home_abbrev": "CHI", "home_score": 1})
        self.assertEqual(rows[1]["away_score"], 3)
        self.assertEqual(rows[1]["home_score"], 6)
        self.assertIsNone(rows[2]["away_score"])  # not started yet

    def test_normalize_standings_recorded_payload(self):
        rows = m.normalize_standings(STANDINGS_PAYLOAD)
        self.assertEqual(rows[0], {
            "team_abbrev": "EDM", "team_name": "Edmonton Oilers",
            "season_id": 20242025, "games_played": 82, "wins": 48,
            "losses": 29, "ot_losses": 5, "points": 101,
            "goals_for": 259, "goals_against": 236})
        self.assertEqual(rows[1]["points"], 116)

    def test_normalize_club_stats_recorded_payload(self):
        out = m.normalize_club_stats(CLUB_STATS_PAYLOAD)
        self.assertEqual(out["season"], 20242025)
        skater = out["skaters"][0]
        self.assertEqual(skater["name"], "Leon Draisaitl")
        self.assertEqual((skater["goals"], skater["assists"],
                          skater["points"]), (52, 54, 106))
        goalie = out["goalies"][0]
        self.assertEqual(goalie["name"], "Stuart Skinner")
        self.assertEqual(goalie["wins"], 26)

    def test_live_collect_writes_research_envelope(self):
        with TemporaryDirectory() as tmp:
            out = m.collect("standings", date="2025-04-17", live=True,
                            out_dir=tmp, opener=fake_opener(STANDINGS_PAYLOAD),
                            now=NOW)
            self.assertEqual(out["status"], "RESEARCH_CAPTURED")
            self.assertEqual(out["rows"], 2)
            saved = json.loads((Path(tmp) / out["file"]).read_text())
        self.assertEqual(saved["source"], "nhl_api")
        self.assertTrue(saved["research_only"])
        self.assertFalse(saved["pricing_input"])
        self.assertFalse(saved["play_eligible"])
        self.assertIsNone(saved["model_p"])
        self.assertEqual(saved["payload"], STANDINGS_PAYLOAD)

    def test_http_error_fails_closed(self):
        def opener(request, timeout=None):
            raise HTTPError(request.full_url, 503, "unavailable", {}, None)
        with self.assertRaises(m.IntakeRefusal):
            m.collect("score", date="2026-10-23", live=True, opener=opener)


if __name__ == "__main__":
    unittest.main()

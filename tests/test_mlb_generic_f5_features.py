from __future__ import annotations

from datetime import date, datetime, timezone
import json
from urllib.parse import parse_qs, urlparse
import unittest

from sportsedge.f5_distribution import build_f5_distribution
from sportsedge.mlb_generic_features import MLBGenericHistorySource


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _inning(num: int, away: int, home: int):
    return {"num": num, "away": {"runs": away}, "home": {"runs": home}}


def _game(game_pk: int, day: int, away_f5: int, home_f5: int):
    innings = [
        _inning(1, away_f5, home_f5),
        _inning(2, 0, 0),
        _inning(3, 0, 0),
        _inning(4, 0, 0),
        _inning(5, 0, 0),
        _inning(6, 8, 7),
        _inning(7, 3, 2),
    ]
    return {
        "gamePk": game_pk,
        "gameDate": f"2026-09-{day:02d}T23:10:00Z",
        "officialDate": f"2026-09-{day:02d}",
        "status": {"abstractGameState": "Final"},
        "teams": {
            "away": {"team": {"id": 101}, "score": away_f5 + 11},
            "home": {"team": {"id": 202}, "score": home_f5 + 9},
        },
        "linescore": {"innings": innings},
    }


class MLBGenericF5FeatureTests(unittest.TestCase):
    def setUp(self):
        valid = [
            _game(9000 + i, i, i % 4, (i + 1) % 3)
            for i in range(1, 11)
        ]
        malformed = _game(9999, 11, 9, 9)
        malformed["linescore"]["innings"] = malformed["linescore"]["innings"][:4]
        self.payload = {"dates": [{"games": list(reversed(valid + [malformed]))}]}
        self.urls: list[str] = []

        def opener(request, timeout=0):
            url = request.full_url
            self.urls.append(url)
            parsed = urlparse(url)
            self.assertEqual(parsed.path, "/api/v1/schedule")
            query = parse_qs(parsed.query)
            self.assertEqual(query["hydrate"], ["linescore"])
            self.assertEqual(query["gameType"], ["R"])
            self.assertEqual(query["endDate"], ["2026-09-13"])
            self.assertIn(query["teamId"], (["101"], ["202"]))
            return _Response(self.payload)

        self.source = MLBGenericHistorySource(
            opener=opener,
            retrieved_at=datetime(2026, 9, 14, 20, 0, tzinfo=timezone.utc),
        )

    def test_f5_features_use_actual_strict_prior_innings_not_final_score_scaling(self):
        row = self.source.feature_row(
            game_pk=123456,
            market="F5_TOTALS",
            entity_id="123456",
            target_date=date(2026, 9, 14),
            away_team_id=101,
            home_team_id=202,
        )

        expected_away = [i % 4 for i in range(1, 11)]
        expected_home = [(i + 1) % 3 for i in range(1, 11)]
        self.assertEqual(row["away_f5_runs_for"], expected_away)
        self.assertEqual(row["away_f5_runs_against"], expected_home)
        self.assertEqual(row["home_f5_runs_for"], expected_home)
        self.assertEqual(row["home_f5_runs_against"], expected_away)
        self.assertNotIn("f5_away_mean_runs", row)
        self.assertNotIn("f5_home_mean_runs", row)
        self.assertEqual(row["source"], "MLB_STATSAPI_STRICT_PRIOR_F5_LINESCORE")
        self.assertEqual(len(self.urls), 2)

        distribution = build_f5_distribution(row)
        self.assertEqual(distribution.away_history_games, 10)
        self.assertEqual(distribution.home_history_games, 10)

    def test_f5_team_totals_resolves_on_same_actual_history_surface(self):
        row = self.source.feature_row(
            game_pk=123456,
            market="F5_TEAM_TOTALS",
            entity_id="101",
            target_date=date(2026, 9, 14),
            away_team_id=101,
            home_team_id=202,
            team_id=101,
        )
        self.assertEqual(row["market"], "F5_TEAM_TOTALS")
        self.assertEqual(row["team_id"], 101)
        self.assertEqual(len(row["away_f5_runs_for"]), 10)
        self.assertEqual(len(row["home_f5_runs_for"]), 10)


if __name__ == "__main__":
    unittest.main()

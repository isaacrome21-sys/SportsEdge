import json
import unittest
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

from sportsedge.mlb_f5_features import MLBF5HistorySource


class _Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.raw


def _game(game_pk, day, away_id, home_id, away_runs, home_runs, *, complete=True):
    innings = []
    for inning in range(1, 6 if complete else 5):
        innings.append({
            "num": inning,
            "teams": {
                "away": {"runs": away_runs[inning - 1]},
                "home": {"runs": home_runs[inning - 1]},
            },
        })
    return {
        "gamePk": game_pk,
        "officialDate": day,
        "status": {"abstractGameState": "Final"},
        "teams": {
            "away": {"team": {"id": away_id}},
            "home": {"team": {"id": home_id}},
        },
        "linescore": {
            "innings": innings,
            "teams": {"away": {"runs": 15}, "home": {"runs": 14}},
        },
    }


class MLBF5FeatureTests(unittest.TestCase):
    def _payload(self):
        games = []
        for index in range(10):
            games.append(_game(
                1000 + index,
                f"2026-08-{index + 1:02d}",
                10,
                20,
                [1, 0, index % 2, 0, 0],
                [0, 1, 0, 1 if index % 3 == 0 else 0, 0],
            ))
        games.append(_game(
            2000,
            "2026-08-11",
            10,
            20,
            [5, 5, 5, 5, 5],
            [5, 5, 5, 5, 5],
            complete=False,
        ))
        games.append(_game(
            3000,
            "2026-08-20",
            10,
            20,
            [9, 9, 9, 9, 9],
            [9, 9, 9, 9, 9],
        ))
        return {"dates": [{"games": games}]}

    def test_history_uses_actual_innings_one_through_five_only(self):
        seen_urls = []

        def opener(req, timeout=15):
            seen_urls.append(req.full_url)
            return _Response(self._payload())

        source = MLBF5HistorySource(
            opener=opener,
            retrieved_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
        )
        rows = source.team_rows(team_id=10, target_date=date(2026, 8, 20))
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["runs_for"], 1)
        self.assertEqual(rows[0]["runs_against"], 2)
        self.assertNotIn(2000, {row["game_pk"] for row in rows})
        self.assertNotIn(3000, {row["game_pk"] for row in rows})
        query = parse_qs(urlparse(seen_urls[0]).query)
        self.assertEqual(query["hydrate"], ["linescore"])
        self.assertEqual(query["endDate"], ["2026-08-19"])

    def test_matchup_feature_hash_binds_actual_prior_rows(self):
        def opener(req, timeout=15):
            return _Response(self._payload())

        source = MLBF5HistorySource(
            opener=opener,
            retrieved_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
        )
        feature = source.matchup_features(
            away_team_id=10,
            home_team_id=20,
            target_date=date(2026, 8, 20),
        )
        self.assertEqual(feature["away_history_games"], 10)
        self.assertEqual(feature["home_history_games"], 10)
        self.assertEqual(len(feature["feature_source_hash"]), 64)
        self.assertEqual(len(feature["features"]["away_f5_runs_for"]), 10)
        self.assertEqual(len(feature["features"]["home_f5_runs_for"]), 10)
        self.assertLess(max(feature["features"]["away_f5_runs_for"]), 15)


if __name__ == "__main__":
    unittest.main()

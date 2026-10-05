import json
import unittest
from datetime import date, datetime, timedelta, timezone
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


def _full_game(game_pk, day, away_id, home_id, away_runs, home_runs):
    assert len(away_runs) == len(home_runs)
    innings = []
    for index, (away, home) in enumerate(zip(away_runs, home_runs), 1):
        innings.append({
            "num": index,
            "teams": {"away": {"runs": away}, "home": {"runs": home}},
        })
    away_final = sum(away_runs)
    home_final = sum(home_runs)
    return {
        "gamePk": game_pk,
        "officialDate": day,
        "status": {"abstractGameState": "Final"},
        "teams": {
            "away": {"team": {"id": away_id}, "score": away_final},
            "home": {"team": {"id": home_id}, "score": home_final},
        },
        "linescore": {
            "innings": innings,
            "teams": {"away": {"runs": away_final}, "home": {"runs": home_final}},
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

    def _league_payload(self):
        games = []
        for index in range(100):
            day = (index % 18) + 1
            games.append(_game(
                8000 + index,
                f"2026-08-{day:02d}",
                100 + (index % 15),
                200 + (index % 15),
                [index % 3, 0, 1, 0, 0],
                [0, (index + 1) % 2, 0, 1, 0],
            ))
        # Same-day/future poison must never enter a target-date 2026-08-20 prior.
        games.append(_game(
            9999, "2026-08-20", 301, 302,
            [9, 9, 9, 9, 9], [9, 9, 9, 9, 9],
        ))
        return {"dates": [{"games": games}]}

    def _opener(self, seen_urls=None, direct_shape=False):
        def opener(req, timeout=15):
            if seen_urls is not None:
                seen_urls.append(req.full_url)
            query = parse_qs(urlparse(req.full_url).query)
            payload = self._payload() if "teamId" in query else self._league_payload()
            if direct_shape:
                for block in payload["dates"]:
                    for game in block["games"]:
                        for inning in game["linescore"]["innings"]:
                            teams = inning.pop("teams")
                            inning["away"] = teams["away"]
                            inning["home"] = teams["home"]
            return _Response(payload)
        return opener

    def test_history_uses_actual_innings_one_through_five_only(self):
        seen_urls = []

        source = MLBF5HistorySource(
            opener=self._opener(seen_urls),
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
        self.assertNotIn("gameType", query)
        self.assertEqual(query["startDate"], [
            (date(2026, 8, 20) - timedelta(days=240)).isoformat()
        ])
        self.assertEqual(query["endDate"], ["2026-08-19"])
        self.assertEqual([url for url in seen_urls if "teamId=" not in url], [])

    def test_matchup_preserves_live_team_window_and_uses_regular_370_day_league_prior(self):
        seen_urls = []
        source = MLBF5HistorySource(
            opener=self._opener(seen_urls),
            retrieved_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
        )
        source.matchup_features(
            away_team_id=10,
            home_team_id=20,
            target_date=date(2026, 8, 20),
        )
        team_urls = [url for url in seen_urls if "teamId=" in url]
        league_urls = [url for url in seen_urls if "teamId=" not in url]
        self.assertEqual(len(team_urls), 2)
        self.assertEqual(len(league_urls), 1)
        for url in team_urls:
            query = parse_qs(urlparse(url).query)
            self.assertNotIn("gameType", query)
            self.assertEqual(query["startDate"], [
                (date(2026, 8, 20) - timedelta(days=240)).isoformat()
            ])
        league_query = parse_qs(urlparse(league_urls[0]).query)
        self.assertEqual(league_query["gameType"], ["R"])
        self.assertEqual(league_query["startDate"], [
            (date(2026, 8, 20) - timedelta(days=370)).isoformat()
        ])
        self.assertEqual(league_query["endDate"], ["2026-08-19"])

    def test_matchup_feature_hash_binds_actual_prior_rows(self):
        source = MLBF5HistorySource(
            opener=self._opener(),
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
        self.assertEqual(feature["features"]["away_first_inning_runs_for"], [1] * 10)
        self.assertEqual(feature["features"]["home_first_inning_runs_for"], [0] * 10)
        self.assertLess(max(feature["features"]["away_f5_runs_for"]), 15)
        self.assertEqual(feature["features"]["league_prior_strength"], 30)
        self.assertGreaterEqual(feature["features"]["league_prior_halves"], 200)
        self.assertAlmostEqual(sum(feature["features"]["league_f5_pmf"].values()), 1.0, places=12)
        self.assertGreaterEqual(feature["features"]["league_first_inning_scoreless_rate"], 0.0)
        self.assertLessEqual(feature["features"]["league_first_inning_scoreless_rate"], 1.0)
        self.assertEqual(len(feature["league_prior_source_hash"]), 64)

    def test_current_statsapi_direct_inning_shape_is_accepted(self):
        source = MLBF5HistorySource(
            opener=self._opener(direct_shape=True),
            retrieved_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
        )
        feature = source.matchup_features(
            away_team_id=10,
            home_team_id=20,
            target_date=date(2026, 8, 20),
        )
        self.assertEqual(feature["away_history_games"], 10)
        self.assertEqual(feature["features"]["away_first_inning_runs_for"], [1] * 10)
        self.assertEqual(feature["features"]["home_first_inning_runs_for"], [0] * 10)

    def test_home_tie_then_permanent_bottom_six_lead_requires_eighteen_outs(self):
        games = []
        for index in range(10):
            games.append(_full_game(
                4000 + index,
                f"2026-08-{index + 1:02d}",
                10,
                20,
                [0, 0, 0, 0, 1, 0, 0, 0, 0],
                [0, 0, 0, 0, 1, 1, 0, 0, 0],
            ))
        payload = {"dates": [{"games": games}]}

        def opener(req, timeout=15):
            return _Response(payload)

        source = MLBF5HistorySource(
            opener=opener,
            retrieved_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
        )
        feature = source.win_credit_transition_features(
            team_id=20, target_date=date(2026, 8, 20)
        )
        self.assertEqual(feature["state_counts"], {"LEAD": 0, "TIE": 10, "TRAIL": 0})
        self.assertEqual(feature["paths"]["TIE"], [18] * 10)
        self.assertEqual(len(feature["feature_source_hash"]), 64)

    def test_away_tie_then_top_six_permanent_lead_requires_only_five_innings(self):
        games = []
        for index in range(10):
            games.append(_full_game(
                5000 + index,
                f"2026-08-{index + 1:02d}",
                10,
                20,
                [0, 0, 0, 0, 1, 1, 0, 0, 0],
                [0, 0, 0, 0, 1, 0, 0, 0, 0],
            ))
        payload = {"dates": [{"games": games}]}

        def opener(req, timeout=15):
            return _Response(payload)

        source = MLBF5HistorySource(opener=opener)
        feature = source.win_credit_transition_features(
            team_id=10, target_date=date(2026, 8, 20)
        )
        self.assertEqual(feature["paths"]["TIE"], [15] * 10)

    def test_f5_lead_lost_and_reclaimed_later_moves_credit_requirement(self):
        games = []
        for index in range(10):
            # Home leads 2-1 after five, away ties in top six, and home does not
            # acquire the permanent lead until bottom seven. Home starter must
            # therefore have completed the top of the seventh (21 outs).
            games.append(_full_game(
                6000 + index,
                f"2026-08-{index + 1:02d}",
                10,
                20,
                [0, 0, 0, 0, 1, 1, 0, 0, 0],
                [0, 0, 0, 0, 2, 0, 1, 0, 0],
            ))
        payload = {"dates": [{"games": games}]}

        def opener(req, timeout=15):
            return _Response(payload)

        source = MLBF5HistorySource(opener=opener)
        feature = source.win_credit_transition_features(
            team_id=20, target_date=date(2026, 8, 20)
        )
        self.assertEqual(feature["state_counts"]["LEAD"], 10)
        self.assertEqual(feature["paths"]["LEAD"], [21] * 10)

    def test_team_loss_has_no_win_credit_path(self):
        games = []
        for index in range(10):
            games.append(_full_game(
                7000 + index,
                f"2026-08-{index + 1:02d}",
                10,
                20,
                [0, 0, 0, 0, 0, 0, 0, 0, 0],
                [0, 0, 0, 0, 1, 0, 0, 0, 0],
            ))
        payload = {"dates": [{"games": games}]}

        def opener(req, timeout=15):
            return _Response(payload)

        source = MLBF5HistorySource(opener=opener)
        feature = source.win_credit_transition_features(
            team_id=10, target_date=date(2026, 8, 20)
        )
        self.assertEqual(feature["state_counts"]["TRAIL"], 10)
        self.assertEqual(feature["paths"]["TRAIL"], [None] * 10)


if __name__ == "__main__":
    unittest.main()

from datetime import date
import unittest

from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.hitter_joint_engine import price_hitter_market
from sportsedge.pitcher_joint_engine import price_pitcher_market
from sportsedge.generic_market_engine import generic_market_engine_adapter


class StubHistory(MLBGenericHistorySource):
    def __init__(self, rows):
        from datetime import datetime, timezone
        self.rows = rows
        self.retrieved_at = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
    def player_rows(self, *, player_id, group, target_date):
        return self.rows


class MLBPropJointFeatureTests(unittest.TestCase):
    def test_hitter_history_builds_joint_pool_accepted_by_engine(self):
        rows = []
        for i in range(12):
            rows.append({"date": date(2026, 9, i + 1), "stat": {
                "plateAppearances": 4, "hits": 1 + (i % 2), "doubles": i % 2,
                "triples": 0, "homeRuns": 0, "baseOnBalls": 0,
                "strikeOuts": 1, "rbi": i % 2, "runs": 1, "stolenBases": 0,
            }})
        src = StubHistory(rows)
        feature = src.feature_row(game_pk=1, market="TOTAL_BASES", entity_id="10",
            target_date=date(2026, 9, 29), away_team_id=1, home_team_id=2, player_id=10)
        self.assertEqual(len(feature["features"]["history_pool"]), 12)
        priced = price_hitter_market({"game_id":"1","market":"TOTAL_BASES","entity_id":"10",
            "line":1.5,"side":"OVER","features":feature["features"]})
        self.assertGreater(priced["model_p"], 0.0)
        self.assertLess(priced["model_p"], 1.0)
        self.assertEqual(priced["meta"]["posterior_prior"], "JEFFREYS_SETTLEMENT_DIRICHLET_0_5")

    def test_canonical_home_runs_delegates_to_joint_hitter_distribution(self):
        pool = []
        for i in range(12):
            hr = 1 if i in {2, 7} else 0
            pool.append({
                "plate_appearances": 4,
                "hits": 1 + hr,
                "singles": 1,
                "doubles": 0,
                "triples": 0,
                "home_runs": hr,
                "total_bases": 1 + 4 * hr,
                "rbi": hr,
                "runs": hr,
                "stolen_bases": 0,
                "walks": 0,
                "strikeouts": 1,
                "extra_base_hits": hr,
            })
        out = generic_market_engine_adapter({
            "game_id": "1",
            "market": "HOME_RUNS",
            "entity_id": "10",
            "line": 0.5,
            "side": "OVER",
            "feature_source_hash": "a" * 64,
            "features": {"history_pool": pool},
        })
        self.assertTrue(out["engine_version"].startswith("mlb_hitter_joint_empirical_bayes"))
        self.assertGreater(out["model_p"], 0.0)
        self.assertLess(out["model_p"], 1.0)

    def test_pitcher_history_builds_joint_pool_accepted_by_engine_without_certainty(self):
        rows = []
        for i in range(7):
            rows.append({"date": date(2026, 9, i + 1), "stat": {
                "gamesStarted": 1, "inningsPitched": "6.0", "strikeOuts": 5 + i % 3,
                "earnedRuns": 2, "hits": 5, "baseOnBalls": 2,
            }})
        src = StubHistory(rows)
        feature = src.feature_row(game_pk=1, market="PITCHER_OUTS", entity_id="20",
            target_date=date(2026, 9, 29), away_team_id=1, home_team_id=2, player_id=20)
        self.assertEqual(len(feature["features"]["history_pool"]), 7)
        priced = price_pitcher_market({"game_id":"1","market":"PITCHER_OUTS","entity_id":"20",
            "line":17.5,"side":"OVER","features":feature["features"]})
        self.assertAlmostEqual(priced["model_p"], 7.5 / 8.0)
        self.assertAlmostEqual(priced["meta"]["raw_empirical_p"], 1.0, places=12)
        self.assertEqual(priced["meta"]["posterior_prior"], "JEFFREYS_SETTLEMENT_DIRICHLET_0_5")


if __name__ == "__main__":
    unittest.main()

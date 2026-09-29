from datetime import date
import unittest

from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.hitter_joint_engine import price_hitter_market
from sportsedge.pitcher_joint_engine import price_pitcher_market


class StubHistory(MLBGenericHistorySource):
    def __init__(self, rows):
        self.rows = rows
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
        self.assertGreaterEqual(priced["model_p"], 0.0)

    def test_pitcher_history_builds_joint_pool_accepted_by_engine(self):
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
        self.assertEqual(priced["model_p"], 1.0)


if __name__ == "__main__":
    unittest.main()

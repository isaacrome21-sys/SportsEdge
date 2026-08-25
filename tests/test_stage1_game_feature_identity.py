import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.mlb_joint_mode_bridge import build_canonical_feature_row

UTC = timezone.utc
NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


class StubHistorySource:
    def __init__(self, retrieved_at):
        self.retrieved_at = retrieved_at

    def team_means(self, *, away_team_id, home_team_id, target_date):
        self.last_identity = (away_team_id, home_team_id, target_date)
        return 4.1, 4.6, 1.7


def game():
    return LiveGame(
        game_pk=777,
        away_team_id=1,
        home_team_id=2,
        away_probable_pitcher_id=None,
        home_probable_pitcher_id=None,
        away_lineup=TeamLineup(1, "away", (), (), False),
        home_lineup=TeamLineup(2, "home", (), (), False),
        status="Preview",
    )


def quote(market, entity_id, line, side):
    return {
        "game_id": "777",
        "period": "FG",
        "market": market,
        "entity_id": str(entity_id),
        "line": line,
        "side": side,
        "book_key": "draftkings",
        "is_alternate": False,
        "raw_market_name": {"MONEYLINE": "h2h", "RUN_LINE": "spreads", "TOTALS": "totals"}[market],
        "american_odds": -110,
        "retrieved_at": NOW,
        "ttl_seconds": 300,
    }


class Stage1GameFeatureIdentityTests(unittest.TestCase):
    def build_rows(self, source):
        target_date = NOW.date()
        g = game()
        return [
            build_canonical_feature_row(
                game=g,
                quote=quote("MONEYLINE", 2, 0.0, "HOME"),
                source=source,
                target_date=target_date,
            ),
            build_canonical_feature_row(
                game=g,
                quote=quote("RUN_LINE", 2, -1.5, "HOME"),
                source=source,
                target_date=target_date,
            ),
            build_canonical_feature_row(
                game=g,
                quote=quote("TOTALS", 777, 8.5, "OVER"),
                source=source,
                target_date=target_date,
            ),
        ]

    def test_ml_rl_totals_share_market_neutral_game_state_hash(self):
        rows = self.build_rows(StubHistorySource(NOW))
        self.assertEqual({row["market"] for row in rows}, {"MONEYLINE", "RUN_LINE", "TOTALS"})
        self.assertEqual(len({row["entity_id"] for row in rows}), 2)
        self.assertEqual({row["away_mean_runs"] for row in rows}, {4.1})
        self.assertEqual({row["home_mean_runs"] for row in rows}, {4.6})
        self.assertEqual(len({row["source_subset_hash"] for row in rows}), 1)

    def test_new_source_snapshot_changes_shared_game_state_hash(self):
        first = self.build_rows(StubHistorySource(NOW))
        second = self.build_rows(StubHistorySource(NOW + timedelta(minutes=1)))
        self.assertEqual(len({row["source_subset_hash"] for row in first}), 1)
        self.assertEqual(len({row["source_subset_hash"] for row in second}), 1)
        self.assertNotEqual(first[0]["source_subset_hash"], second[0]["source_subset_hash"])


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date, datetime, timezone

from sportsedge.engine_registry import engine_registry
from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.hitter_joint_engine import price_hitter_market
from sportsedge.live_slate import make_live_game
from sportsedge.mlb_joint_mode_bridge import build_canonical_feature_row
from sportsedge.mlb_source import GameSnapshot
from sportsedge.readiness import _behavioral_state

UTC = timezone.utc


def _lineup(start):
    return [{"player_id": start + i, "slot": i + 1, "sequence": 0} for i in range(9)]


def _game_without_joint_context():
    # HOME_RUNS generic baseline must not require venue or probable pitchers.
    snap = GameSnapshot(
        game_pk=777,
        game_date="2026-08-24T23:00:00Z",
        status="Preview",
        away_id=1,
        away_name="Away",
        home_id=2,
        home_name="Home",
        away_probable_pitcher_id=None,
        away_probable_pitcher_name=None,
        home_probable_pitcher_id=None,
        home_probable_pitcher_name=None,
        retrieved_at="2026-08-24T12:00:00+00:00",
        venue_id=None,
    )
    return make_live_game(snap, _lineup(100), _lineup(200))


class _GenericHRSource:
    retrieved_at = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)

    def feature_row(self, **kwargs):
        return {
            "generic_feature_version": "mlb_generic_feature_v1",
            "game_pk": kwargs["game_pk"],
            "market": kwargs["market"],
            "entity_id": kwargs["entity_id"],
            "team_id": kwargs["team_id"],
            "expected_count": 0.31,
            "source_subset_hash": "a" * 64,
            "retrieved_at": self.retrieved_at.isoformat(),
            "asof": self.retrieved_at.isoformat(),
            "source": "TEST_GENERIC_HR",
        }


class PR122MigrationCompatibilityTests(unittest.TestCase):
    def test_home_runs_runtime_stays_on_measured_generic_baseline(self):
        self.assertIs(engine_registry()["HOME_RUNS"], generic_market_engine_adapter)

    def test_home_runs_bridge_does_not_require_joint_only_context(self):
        row = build_canonical_feature_row(
            game=_game_without_joint_context(),
            quote={
                "game_id": "777", "period": "FG", "market": "HOME_RUNS",
                "entity_id": "100", "side": "OVER", "line": 0.5,
                "book_key": "draftkings", "raw_market_name": "Batter Home Runs",
                "is_alternate": False, "american_odds": 150,
                "retrieved_at": "2026-08-24T12:00:00Z", "ttl_seconds": 300,
            },
            source=_GenericHRSource(),
            target_date=date(2026, 8, 24),
        )
        self.assertEqual(row["expected_count"], 0.31)
        self.assertNotIn("features", row)

    def test_legacy_hits_shape_and_joint_hits_shape_are_both_supported(self):
        legacy = engine_registry()["HITS"]({
            "build_hash": "b" * 64, "game_id": "g", "market": "HITS",
            "entity_id": "b", "line": 0.5, "side": "OVER",
            "lineup_status": "CONFIRMED", "require_confirmed_lineup": False,
            "features": {"b_rate": 0.30, "p_rate": 0.27, "pa_pool": [3, 4, 4, 5]},
        })
        self.assertTrue(0.0 <= legacy["model_p"] <= 1.0)

        row = {
            "plate_appearances": 4, "hits": 1, "singles": 1, "doubles": 0,
            "triples": 0, "home_runs": 0, "total_bases": 1, "rbi": 0,
            "runs": 0, "stolen_bases": 0, "walks": 0, "strikeouts": 1,
            "extra_base_hits": 0,
        }
        joint_input = {
            "game_id": "g", "market": "HITS", "entity_id": "b",
            "line": 0.5, "side": "OVER", "feature_source_hash": "c" * 64,
            "features": {"history_pool": [dict(row) for _ in range(10)]},
        }
        routed = engine_registry()["HITS"](joint_input)
        direct = price_hitter_market(joint_input)
        self.assertEqual(routed["model_p"], direct["model_p"])
        self.assertEqual(routed["engine_version"], direct["engine_version"])

    def test_unmeasured_is_valid_but_not_behaviorally_complete(self):
        complete, status, cause = _behavioral_state(
            {"markets": {"X": {"status": "UNMEASURED", "root_cause": "NEW"}}}, "X"
        )
        self.assertFalse(complete)
        self.assertEqual(status, "UNMEASURED")
        self.assertEqual(cause, "NEW")


if __name__ == "__main__":
    unittest.main()

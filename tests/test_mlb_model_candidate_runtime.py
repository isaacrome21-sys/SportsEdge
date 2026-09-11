from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.orchestrator import run_candidate


class MLBModelCandidateRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 5, 0, tzinfo=timezone.utc)
        self.model_input = {
            "game_id": "123",
            "market": "TOTALS",
            "entity_id": "123",
            "line": 8.5,
            "side": "OVER",
            "away_mean_runs": 4.1,
            "home_mean_runs": 4.4,
        }
        self.quote = {
            "game_id": "123",
            "market": "TOTALS",
            "entity_id": "123",
            "line": 8.5,
            "side": "OVER",
            "american_odds": -110,
            "book_key": "draftkings",
            "sportsbook": "DraftKings",
            "retrieved_at": self.now - timedelta(seconds=20),
            "ttl_seconds": 180,
            "offer_id": "offer-1",
        }

    def _engine(self, model_input):
        return {
            "game_id": model_input["game_id"],
            "market": model_input["market"],
            "entity_id": model_input["entity_id"],
            "line": model_input["line"],
            "side": model_input["side"],
            "model_p": 0.56,
            "push_p": 0.02,
            "model_input_hash": "a" * 64,
            "engine_version": "TEST_MLB_ENGINE_V1",
        }

    def test_unpromoted_market_preserves_genuine_model_candidate_without_pair(self):
        result = run_candidate(
            model_input=self.model_input,
            quote=self.quote,
            paired_quote=None,
            deployment={"market": "TOTALS", "eligible": False, "stage": "VALIDATED_MATH", "reason": "fresh calibration required"},
            engine_fn=self._engine,
            ingestion_now=self.now,
            finalization_now=self.now,
        )
        self.assertEqual(result.bet_status, "MODEL_CANDIDATE")
        self.assertEqual(result.model_p, 0.56)
        self.assertEqual(result.push_probability, 0.02)
        self.assertEqual(result.model_input_hash, "a" * 64)
        self.assertIn("OFFICIAL_BLOCKED:fresh calibration required", result.reason)
        self.assertIsNone(result.decision)

    def test_candidate_identity_mismatch_fails_closed(self):
        bad = dict(self.quote, line=9.0)
        result = run_candidate(
            model_input=self.model_input,
            quote=bad,
            paired_quote=None,
            deployment={"market": "TOTALS", "eligible": False, "stage": "VALIDATED_MATH"},
            engine_fn=self._engine,
            ingestion_now=self.now,
            finalization_now=self.now,
        )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIsNone(result.model_p)
        self.assertIn("candidate mismatch: line", result.reason)

    def test_stale_offer_blocks_before_model_inference(self):
        called = []
        stale = dict(self.quote, retrieved_at=self.now - timedelta(minutes=10))
        result = run_candidate(
            model_input=self.model_input,
            quote=stale,
            paired_quote=None,
            deployment={"market": "TOTALS", "eligible": False, "stage": "VALIDATED_MATH"},
            engine_fn=lambda row: called.append(True) or self._engine(row),
            ingestion_now=self.now,
            finalization_now=self.now,
        )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertEqual(called, [])

    def test_market_price_cannot_enter_model_input(self):
        contaminated = dict(self.model_input, american_odds=-110)
        result = run_candidate(
            model_input=contaminated,
            quote=self.quote,
            paired_quote=None,
            deployment={"market": "TOTALS", "eligible": False, "stage": "VALIDATED_MATH"},
            engine_fn=self._engine,
            ingestion_now=self.now,
            finalization_now=self.now,
        )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIsNone(result.model_p)
        self.assertIn("sportsbook/market data prohibited", result.reason)


if __name__ == "__main__":
    unittest.main()

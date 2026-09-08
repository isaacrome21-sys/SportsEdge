from datetime import datetime, timezone
import unittest

from sportsedge.orchestrator import run_candidate


class WiredReadoutIdentityTests(unittest.TestCase):
    def test_wired_market_does_not_backfill_engine_identity(self):
        now = datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc)
        quote = {
            "game_id": "123",
            "event_id": "123",
            "game_number": 1,
            "event_home_team_id": "10",
            "event_away_team_id": "20",
            "market": "TOTALS",
            "entity_id": "123",
            "side": "OVER",
            "period": "FG",
            "line": 8.5,
            "book_key": "dk",
            "retrieved_at": now,
            "american_odds": -110,
            "is_alternate": False,
            "raw_market_name": "totals",
        }
        model_input = {
            "game_id": "123",
            "market": "TOTALS",
            "entity_id": "123",
            "side": "OVER",
            "line": 8.5,
        }

        def identity_free_engine(_):
            return {"model_p": 0.55, "push_p": 0.0}

        result = run_candidate(
            model_input=model_input,
            quote=quote,
            paired_quote=None,
            deployment={"market": "TOTALS", "eligible": False},
            engine_fn=identity_free_engine,
            ingestion_now=now,
            finalization_now=now,
        )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIn("ENGINE_READOUT_IDENTITY_MISSING:TOTALS", result.reason)


if __name__ == "__main__":
    unittest.main()

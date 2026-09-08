import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import Mock

from sportsedge.orchestrator import MLB_EXTERNAL_BINDING_MODE,run_candidate

NOW=datetime(2026,9,8,1,0,tzinfo=timezone.utc)


def quote(side):
    return {
        "game_id":"777",
        "event_id":"777",
        "game_number":1,
        "event_home_team_id":"10",
        "event_away_team_id":"20",
        "period":"FG",
        "market":"TOTALS",
        "entity_id":"777",
        "line":8.5,
        "side":side,
        "american_odds":-110,
        "book_key":"draftkings",
        "retrieved_at":NOW,
        "ttl_seconds":300,
    }


class OrchestratorBoundaryTests(unittest.TestCase):
    def test_missing_attestation_blocks_before_engine_executes(self):
        engine=Mock(side_effect=AssertionError("engine must not execute"))
        model_input={"game_id":"777","market":"TOTALS","entity_id":"777","line":8.5,"side":"OVER"}
        result=run_candidate(
            model_input=model_input,
            quote=quote("OVER"),
            paired_quote=quote("UNDER"),
            deployment={},
            engine_fn=engine,
            ingestion_now=NOW,
            finalization_now=NOW,
            candidate_binding_mode=MLB_EXTERNAL_BINDING_MODE,
        )
        self.assertEqual(result.bet_status,"BLOCKED")
        self.assertIn("MLB_EXTERNAL_BINDING_ATTESTATION_REQUIRED",result.reason)
        engine.assert_not_called()


if __name__=="__main__":
    unittest.main()

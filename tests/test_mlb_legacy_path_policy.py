from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sportsedge.engine_registry import EngineDispatchError, hitter_joint_adapter
from sportsedge.orchestrator import run_candidate

UTC=timezone.utc
NOW=datetime(2026,8,31,12,0,tzinfo=UTC)


def legacy_hits_input():
    return {
        "game_id":"g1","market":"HITS","entity_id":"p1","line":0.5,"side":"OVER",
        "build_hash":"a"*64,"lineup_status":"CONFIRMED","require_confirmed_lineup":False,
        "features":{"b_rate":0.25,"p_rate":0.24,"pa_pool":[4,4,5,4,3,4,5,4,4,5]},
    }


def quote():
    return {
        "game_id":"g1","market":"HITS","entity_id":"p1","line":0.5,"side":"OVER",
        "american_odds":-110,"book_key":"test","sportsbook":"Test",
        "retrieved_at":NOW-timedelta(seconds=10),"ttl_seconds":300,"offer_id":"legacy-hits",
    }


class MLBLegacyPathPolicyTests(unittest.TestCase):
    def test_legacy_payload_is_explicitly_tagged(self):
        output=hitter_joint_adapter(legacy_hits_input())
        self.assertEqual(output["runtime_path"],"LEGACY_COMPAT")
        self.assertEqual(output["market"],"HITS")
        self.assertEqual(output["engine_version"],"hits_engine_v1.3")

    @patch("sportsedge.orchestrator.require_production_edge_floor")
    def test_eligible_market_cannot_promote_through_legacy_payload_shape(self, _floor):
        result=run_candidate(
            model_input=legacy_hits_input(),quote=quote(),paired_quote=None,
            deployment={"market":"HITS","eligible":True,"stage":"DEPLOYED"},
            engine_fn=hitter_joint_adapter,ingestion_now=NOW,finalization_now=NOW,
        )
        self.assertEqual(result.bet_status,"BLOCKED")
        self.assertIsNone(result.model_p)
        self.assertIn("LEGACY_COMPAT_PATH_NOT_PROMOTABLE",result.reason)

    def test_mixed_legacy_and_joint_payload_fails_before_engine_selection(self):
        mixed=legacy_hits_input()
        mixed["features"]={**mixed["features"],"history_pool":[]}
        with self.assertRaisesRegex(EngineDispatchError,"AMBIGUOUS_PROP_PAYLOAD"):
            hitter_joint_adapter(mixed)


if __name__=="__main__": unittest.main()

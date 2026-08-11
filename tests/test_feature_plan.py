import unittest
from datetime import datetime, timezone

from sportsedge.feature_plan import FeaturePlanError, resolve_feature_plan

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)


def hit_plan():
    return [{
        "market": "HITS", "game_pk": 777, "player_id": 100, "team_id": 1,
        "wager_cutoff": "2026-08-10T23:00:00Z",
        "feature_fact_keys": {
            "b_rate": "b_rate:777:100",
            "p_rate": "p_rate:777:100",
            "pa_pool": "pa_pool:777:100",
        },
        "ttl_by_feature": {"b_rate": 3600, "p_rate": 3600, "pa_pool": 86400},
    }]


def facts():
    base = {"provider": "VALIDATED_FIXTURE", "event_time": "2026-08-10T19:00:00Z", "retrieved_at": "2026-08-10T19:59:00Z", "status": "CONFIRMED"}
    return [
        {**base, "source_id": "b1", "fact_key": "b_rate:777:100", "value": .245},
        {**base, "source_id": "p1", "fact_key": "p_rate:777:100", "value": .232},
        {**base, "source_id": "pa1", "fact_key": "pa_pool:777:100", "value": [4,4,5,3]},
    ]


class FeaturePlanTests(unittest.TestCase):
    def test_resolves_plan_to_versioned_feature_row(self):
        rows, failures = resolve_feature_plan(hit_plan(), sources=facts(), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(failures, [])
        self.assertEqual(rows[0]["market"], "HITS")
        self.assertEqual(rows[0]["source_lineup_status"], "CONFIRMED")
        self.assertEqual(len(rows[0]["source_subset_hash"]), 64)

    def test_missing_fact_is_explicit_failure(self):
        rows, failures = resolve_feature_plan(hit_plan(), sources=facts()[:-1], now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "MISSING")

    def test_duplicate_target_is_blocked_not_collapsed(self):
        plan = hit_plan() * 2
        rows, failures = resolve_feature_plan(plan, sources=facts(), now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(failures[0]["reason"], "DUPLICATE_PLAN_TARGET")

    def test_nonlist_contract_rejected(self):
        with self.assertRaises(FeaturePlanError):
            resolve_feature_plan({}, sources=facts(), now=NOW)
        with self.assertRaises(FeaturePlanError):
            resolve_feature_plan(hit_plan(), sources={}, now=NOW)


if __name__ == "__main__":
    unittest.main()

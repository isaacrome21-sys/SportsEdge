import threading
import unittest

from sportsedge.provider_resilience import (
    ProviderSpec,
    acquire_domains_concurrently,
    build_provider_plans,
    execute_provider_plan,
    forbid_negative_live_cache,
    model_p_provider_allowed,
    provider_manifest_sha,
    schema_fingerprint,
    validate_schema,
)
from sportsedge.shared_acquisition_contract import TrustClass


class ProviderResilienceTests(unittest.TestCase):
    def test_schema_missing_fields_fail_closed(self):
        check = validate_schema({"team": "BUF", "week": 1}, required_fields=("team", "week", "player_id"))
        self.assertFalse(check.ok)
        self.assertEqual(check.missing_fields, ("player_id",))
        self.assertEqual(len(check.fingerprint), 64)

    def test_schema_fingerprint_order_invariant(self):
        self.assertEqual(schema_fingerprint(["a", "b"]), schema_fingerprint(["b", "a", "a"]))

    def test_primary_and_fallback_are_deterministic(self):
        specs = [
            ProviderSpec("NFL", "fallback", "injuries", 20, TrustClass.MODEL_P_OBJECTIVE, 900),
            ProviderSpec("NFL", "official", "injuries", 10, TrustClass.MODEL_P_OBJECTIVE, 300),
            ProviderSpec("NFL", "context", "injuries", 30, TrustClass.CONTEXT_ONLY, 300),
        ]
        plan = build_provider_plans(specs)["INJURIES"]
        self.assertEqual(plan.primary.provider_name, "official")
        self.assertEqual([x.provider_name for x in plan.fallbacks], ["fallback", "context"])

    def test_market_context_cannot_become_model_p_source(self):
        spec = ProviderSpec("CFB", "public-splits", "market", 1, TrustClass.MARKET_ONLY, 60)
        self.assertFalse(model_p_provider_allowed(spec))

    def test_negative_current_cache_is_forbidden(self):
        self.assertTrue(forbid_negative_live_cache(event_has_started=False, payload_is_empty=True))
        self.assertFalse(forbid_negative_live_cache(event_has_started=True, payload_is_empty=True))
        self.assertFalse(forbid_negative_live_cache(event_has_started=False, payload_is_empty=False))

    def test_manifest_sha_changes_when_provider_contract_changes(self):
        a = [ProviderSpec("MLB", "NWS", "weather", 1, TrustClass.MODEL_P_OBJECTIVE, 900)]
        b = [ProviderSpec("MLB", "NWS", "weather", 1, TrustClass.MODEL_P_OBJECTIVE, 300)]
        self.assertNotEqual(provider_manifest_sha(a), provider_manifest_sha(b))

    def test_invalid_priority_fails_closed(self):
        with self.assertRaises(ValueError):
            build_provider_plans([ProviderSpec("MLB", "x", "weather", -1, TrustClass.CONTEXT_ONLY, 30)])

    def test_execute_plan_falls_back_after_transport_failure(self):
        specs = [
            ProviderSpec("NFL", "official", "injuries", 1, TrustClass.MODEL_P_OBJECTIVE, 300, ("team", "player_id")),
            ProviderSpec("NFL", "backup", "injuries", 2, TrustClass.MODEL_P_OBJECTIVE, 600, ("team", "player_id")),
        ]
        plan = build_provider_plans(specs)["INJURIES"]

        def broken():
            raise RuntimeError("provider down")

        outcome = execute_provider_plan(
            plan,
            {"official": broken, "backup": lambda: {"team": "BUF", "player_id": "00-1"}},
            require_model_p_objective=True,
        )
        self.assertEqual(outcome.status, "AVAILABLE")
        self.assertEqual(outcome.provider_name, "backup")
        self.assertEqual([x.status for x in outcome.attempts], ["SOURCE_FAILED", "AVAILABLE"])

    def test_context_fallback_cannot_satisfy_model_p_domain(self):
        specs = [
            ProviderSpec("NFL", "official", "injuries", 1, TrustClass.MODEL_P_OBJECTIVE, 300),
            ProviderSpec("NFL", "reported", "injuries", 2, TrustClass.CONTEXT_ONLY, 300),
        ]
        plan = build_provider_plans(specs)["INJURIES"]
        outcome = execute_provider_plan(
            plan,
            {"official": lambda: None, "reported": lambda: {"status": "questionable"}},
            require_model_p_objective=True,
        )
        self.assertEqual(outcome.status, "MISSING")
        self.assertIsNone(outcome.provider_name)
        self.assertEqual([x.status for x in outcome.attempts], ["MISSING", "REJECTED_TRUST"])

    def test_schema_failure_falls_through_to_next_provider(self):
        specs = [
            ProviderSpec("MLB", "primary", "weather", 1, TrustClass.MODEL_P_OBJECTIVE, 300, ("wind", "temp")),
            ProviderSpec("MLB", "backup", "weather", 2, TrustClass.MODEL_P_OBJECTIVE, 300, ("wind", "temp")),
        ]
        outcome = execute_provider_plan(
            build_provider_plans(specs)["WEATHER"],
            {"primary": lambda: {"wind": 12}, "backup": lambda: {"wind": 10, "temp": 81}},
            require_model_p_objective=True,
        )
        self.assertEqual(outcome.provider_name, "backup")
        self.assertEqual(outcome.attempts[0].status, "SCHEMA_FAILED")

    def test_independent_domains_execute_concurrently(self):
        specs = [
            ProviderSpec("NFL", "weather", "weather", 1, TrustClass.MODEL_P_OBJECTIVE, 300),
            ProviderSpec("NFL", "injury", "injuries", 1, TrustClass.MODEL_P_OBJECTIVE, 300),
        ]
        plans = build_provider_plans(specs)
        barrier = threading.Barrier(2, timeout=1.0)

        def synchronized(value):
            def inner():
                barrier.wait()
                return value
            return inner

        outcomes = acquire_domains_concurrently(
            plans,
            {
                "WEATHER": {"weather": synchronized({"wind": 5})},
                "INJURIES": {"injury": synchronized({"count": 0})},
            },
            model_p_domains=("WEATHER", "INJURIES"),
            max_workers=2,
        )
        self.assertEqual(set(outcomes), {"INJURIES", "WEATHER"})
        self.assertTrue(all(row.status == "AVAILABLE" for row in outcomes.values()))


if __name__ == "__main__":
    unittest.main()

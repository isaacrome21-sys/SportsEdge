import unittest

from sportsedge.provider_resilience import (
    ProviderSpec,
    build_provider_plans,
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


if __name__ == "__main__":
    unittest.main()

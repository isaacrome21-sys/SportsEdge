import unittest

from sportsedge.odds_keyring import OddsKeyringError, fetch_with_key_failover


class ProviderError(RuntimeError):
    def __init__(self, message, *, provider_code=None):
        super().__init__(message)
        self.provider_code = provider_code


class OddsKeyringTests(unittest.TestCase):
    def test_primary_success_uses_first_slot(self):
        calls = []
        result = fetch_with_key_failover(("k1", "k2", "k3"), lambda key: calls.append(key) or {"ok": True})
        self.assertEqual(result.key_slot, 1)
        self.assertEqual(result.failures, ())
        self.assertEqual(calls, ["k1"])

    def test_failure_rotates_in_order_without_exposing_key(self):
        calls = []
        def fetcher(key):
            calls.append(key)
            if key != "k2":
                raise RuntimeError("provider rejected credential")
            return "snapshot"
        result = fetch_with_key_failover(("k1", "k2", "k3"), fetcher)
        self.assertEqual(result.value, "snapshot")
        self.assertEqual(result.key_slot, 2)
        self.assertEqual(calls, ["k1", "k2"])
        self.assertEqual(len(result.failures), 1)
        rendered = repr(result.failures)
        self.assertNotIn("k1", rendered)
        self.assertNotIn("k2", rendered)
        self.assertNotIn("k3", rendered)

    def test_account_usage_exhaustion_short_circuits_after_first_slot(self):
        calls = []
        def fetcher(key):
            calls.append(key)
            raise ProviderError("quota exhausted", provider_code="OUT_OF_USAGE_CREDITS")
        with self.assertRaises(OddsKeyringError) as ctx:
            fetch_with_key_failover(("k1", "k2", "k3"), fetcher)
        self.assertEqual(calls, ["k1"])
        self.assertIn("ODDS_API_ALL_KEYS_FAILED", str(ctx.exception))
        self.assertIn("account_terminal=OUT_OF_USAGE_CREDITS", str(ctx.exception))
        self.assertIn("slot=1", str(ctx.exception))
        self.assertNotIn("slot=2", str(ctx.exception))
        self.assertNotIn("k1", str(ctx.exception))
        self.assertNotIn("k2", str(ctx.exception))
        self.assertNotIn("k3", str(ctx.exception))

    def test_account_usage_exhaustion_from_native_error_text_short_circuits(self):
        calls = []
        def fetcher(key):
            calls.append(key)
            raise RuntimeError("ODDS_API_FETCH_FAILED:events:HTTP_401:OUT_OF_USAGE_CREDITS")
        with self.assertRaises(OddsKeyringError):
            fetch_with_key_failover(("k1", "k2"), fetcher)
        self.assertEqual(calls, ["k1"])

    def test_non_account_auth_failure_still_rotates(self):
        calls = []
        def fetcher(key):
            calls.append(key)
            if key == "k1":
                raise ProviderError("credential revoked", provider_code="INVALID_API_KEY")
            return "snapshot"
        result = fetch_with_key_failover(("k1", "k2"), fetcher)
        self.assertEqual(result.value, "snapshot")
        self.assertEqual(result.key_slot, 2)
        self.assertEqual(calls, ["k1", "k2"])

    def test_duplicate_and_blank_keys_are_ignored(self):
        calls = []
        def fetcher(key):
            calls.append(key)
            raise RuntimeError("no")
        with self.assertRaises(OddsKeyringError) as ctx:
            fetch_with_key_failover(("", "same", "same", "backup"), fetcher)
        self.assertEqual(calls, ["same", "backup"])
        self.assertNotIn("same", str(ctx.exception))
        self.assertNotIn("backup", str(ctx.exception))

    def test_all_failed_is_explicit(self):
        with self.assertRaises(OddsKeyringError) as ctx:
            fetch_with_key_failover(("a", "b", "c"), lambda _: (_ for _ in ()).throw(ValueError("bad")))
        self.assertIn("ODDS_API_ALL_KEYS_FAILED", str(ctx.exception))
        self.assertIn("slot=1", str(ctx.exception))
        self.assertIn("slot=2", str(ctx.exception))
        self.assertIn("slot=3", str(ctx.exception))

    def test_missing_key_fails_closed(self):
        with self.assertRaises(OddsKeyringError):
            fetch_with_key_failover(("", "  "), lambda _: "never")


if __name__ == "__main__":
    unittest.main()

import unittest

from sportsedge.odds_keyring import OddsKeyringError, fetch_with_key_failover


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

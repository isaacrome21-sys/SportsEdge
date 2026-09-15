import json
from pathlib import Path
import unittest


class ProviderContractHardFailuresTests(unittest.TestCase):
    def test_required_failures_are_declared(self):
        failures = set(json.loads(Path("config/market_provider_contract_v1.json").read_text())["hard_failures"])
        self.assertIn("SOURCE_DOES_NOT_COVER_MARKET", failures)
        self.assertIn("SOURCE_BOOK_IDENTITY_MISSING_FOR_EXACT_BOOK_CONTRACT", failures)
        self.assertIn("SOURCE_TIMESTAMP_STALE", failures)
        self.assertIn("FALLBACK_MUST_NOT_INHERIT_PRIMARY_PROVIDER_IDENTITY", failures)
        self.assertIn("FETCH_TIME_MUST_NOT_SATISFY_SOURCE_NATIVE_FRESHNESS", failures)
        self.assertIn("CONSENSUS_PROVIDER_INELIGIBLE_FOR_CFBD_CONTEXT", failures)


if __name__ == "__main__":
    unittest.main()

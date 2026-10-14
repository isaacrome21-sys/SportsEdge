"""Research-only regression tests for malformed search-host metadata."""
import unittest
from sportsedge.source_fact_evidence import adjudicate_pregame_fact


class SearchHostRobustnessTests(unittest.TestCase):
    def test_malformed_hosts_fail_closed_without_exception(self):
        for hosts in (None, 7, True, {}, "mlb.com"):
            with self.subTest(hosts=hosts):
                result = adjudicate_pregame_fact(
                    event_id="fixture-1", subject_id=1, fact_kind="STARTER",
                    cutoff_utc="2026-10-13T23:00:00Z", evidence=[],
                    source_registry={"official": {"kind": "OFFICIAL", "hosts": hosts}},
                    search_log=[{
                        "channel": "OFFICIAL_WEB", "query": "starting pitcher",
                        "searched_at_utc": "2026-10-13T22:00:00Z",
                        "search_url": "https://www.mlb.com/"}],
                )
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertIn("OFFICIAL_WEB", result["missing_search_channels"])
                self.assertFalse(result["play_authority"])
                self.assertFalse(result["pricing_authority"])


if __name__ == "__main__":
    unittest.main()

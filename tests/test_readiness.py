import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.readiness import audit_readiness


class ReadinessTests(unittest.TestCase):
    def test_checked_in_registry_reports_hits_tb_runnable_but_not_deployed(self):
        out = audit_readiness()
        rows = {x["market"]: x for x in out["markets"]}
        for market in ("HITS", "TOTAL_BASES"):
            self.assertTrue(rows[market]["runtime_engine"])
            self.assertTrue(rows[market]["runnable_live"])
            self.assertFalse(rows[market]["official_bet_enabled"])
            self.assertIn("FIXTURE_CI_PENDING", rows[market]["blockers"])

    def test_unknown_runtime_market_is_not_claimed_runnable(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "deployments.json"
            p.write_text(json.dumps({
                "schema_version": 1,
                "markets": {"FOO": {"eligible": False, "stage": "VALIDATED_MATH", "reason": "test"}},
            }))
            out = audit_readiness(p)
        row = out["markets"][0]
        self.assertFalse(row["runtime_engine"])
        self.assertFalse(row["runnable_live"])
        self.assertIn("NO_RUNTIME_ENGINE", row["blockers"])


if __name__ == "__main__":
    unittest.main()

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "classify_cfb_market_context_operation.py"
spec = importlib.util.spec_from_file_location("cfb_op", SCRIPT)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


class CFBOperationalStatusTests(unittest.TestCase):
    def payload(self, status):
        return {"schema_version": mod.SCHEMA, "status": status}

    def test_valid_blocked_artifact_is_operationally_healthy(self):
        out = mod.classify(self.payload("BLOCKED_NO_ODDS"), 2)
        self.assertTrue(out["operationally_healthy"])
        self.assertEqual(out["operational_status"], "HEALTHY_DOMAIN_BLOCKED")
        self.assertTrue(out["domain_blocked"])

    def test_valid_no_bet_is_healthy(self):
        out = mod.classify(self.payload("VALID_NO_BET_SLATE"), 0)
        self.assertTrue(out["operationally_healthy"])
        self.assertEqual(out["operational_status"], "HEALTHY")

    def test_nonzero_without_recognized_blocked_artifact_is_failure(self):
        out = mod.classify(self.payload("AVAILABLE"), 2)
        self.assertFalse(out["operationally_healthy"])
        self.assertEqual(out["operational_status"], "OPERATIONAL_FAILURE")

    def test_bad_schema_is_failure_even_when_status_looks_blocked(self):
        out = mod.classify({"schema_version":"wrong","status":"BLOCKED"}, 2)
        self.assertFalse(out["operationally_healthy"])


if __name__ == "__main__":
    unittest.main()

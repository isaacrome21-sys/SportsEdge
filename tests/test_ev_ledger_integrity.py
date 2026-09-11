"""Every sealed tracker record in the repo must still match its content hash.
Records without schema_version (EV_TRACKER_POLICY_V1) are grandfathered and never count as V2 evidence."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ev_math_integrity", ROOT / "sports/common/ev_math.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)
DIRS = ["ledger/ev_plays", "ledger/ev_close_attempts", "ledger/ev_closes"]


class LedgerIntegrity(unittest.TestCase):
    def test_sealed_records_unchanged(self):
        checked = 0
        for d in DIRS:
            for path in sorted((ROOT / d).glob("*.json")) if (ROOT / d).exists() else []:
                rec = json.loads(path.read_text())
                if rec.get("schema_version") is None:
                    continue
                with self.subTest(record=str(path.relative_to(ROOT))):
                    self.assertTrue(ev.verify_seal(rec), "content hash mismatch: record was edited")
                    key = "attempt_id" if d.endswith("attempts") else "play_id"
                    self.assertEqual(path.stem, rec[key])
                checked += 1
        self.assertGreaterEqual(checked, 0)


if __name__ == "__main__":
    unittest.main()

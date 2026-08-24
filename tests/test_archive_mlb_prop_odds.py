import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_mlb_prop_odds.py"
SPEC = importlib.util.spec_from_file_location("archive_mlb_prop_odds", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class ArchiveMLBPropOddsTests(unittest.TestCase):
    def test_event_time_extraction_fails_closed(self):
        self.assertIsNone(mod._event_first_pitch({"name": "x"}))
        self.assertEqual(
            mod._event_first_pitch({"startDate": "2026-08-24T00:10:00Z"}),
            datetime(2026, 8, 24, 0, 10, tzinfo=timezone.utc),
        )

    def test_persist_is_immutable_plus_latest_pointer(self):
        payload = {
            "captured_at": "2026-08-24T00:00:00+00:00",
            "payload_sha256": "a" * 64,
            "pit_target_quote_count": 3,
            "market_counts": {"PITCHER_OUTS": 1, "PITCHER_ER": 1, "RBI": 1},
        }
        with tempfile.TemporaryDirectory() as td:
            immutable, latest = mod.persist_payload(payload, root=Path(td))
            self.assertTrue(immutable.exists())
            self.assertTrue(latest.exists())
            self.assertNotEqual(immutable, latest)
            self.assertIn("2026-08-24", str(immutable))

    def test_target_market_set_is_exact(self):
        self.assertEqual(mod.TARGET_MARKETS, {"PITCHER_OUTS", "PITCHER_ER", "RBI"})


if __name__ == "__main__":
    unittest.main()

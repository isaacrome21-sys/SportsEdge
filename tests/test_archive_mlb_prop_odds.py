import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_mlb_prop_odds.py"
SPEC = importlib.util.spec_from_file_location("archive_mlb_prop_odds", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def _snapshot(*, retrieved_at: str):
    return SimpleNamespace(
        quotes=(
            {
                "provider_event_id": "123",
                "market": "PITCHER_OUTS",
                "entity_name": "Pitcher A",
                "entity_name_normalized": "pitcher a",
                "side": "OVER",
                "selection": "Over",
                "line": 17.5,
                "american_odds": -110,
                "sportsbook": "DraftKings",
                "book_key": "draftkings_direct",
                "retrieved_at": retrieved_at,
                "ttl_seconds": 120,
                "is_alternate": False,
                "raw_market_name": "Outs Recorded",
                "provider": "DRAFTKINGS_WEB_RESEARCH",
            },
        ),
        failures=(),
        league_id=84240,
        base_url="https://example.invalid/",
    )


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

    def test_build_archive_accepts_strictly_pregame_target_quote(self):
        snap = _snapshot(retrieved_at="2026-08-24T00:00:00Z")
        events = {
            "123": {
                "provider_event_id": "123",
                "event_name": "Away @ Home",
                "first_pitch_at": "2026-08-24T00:10:00+00:00",
            }
        }
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=snap), patch.object(
            mod, "_event_index", return_value=(events, [])
        ):
            payload = mod.build_archive_payload(now=datetime(2026, 8, 24, 0, 1, tzinfo=timezone.utc))

        self.assertEqual(payload["pit_target_quote_count"], 1)
        self.assertEqual(payload["market_counts"]["PITCHER_OUTS"], 1)
        self.assertEqual(payload["rejected_target_count"], 0)
        row = payload["quotes"][0]
        self.assertTrue(row["pit_eligible"])
        self.assertEqual(row["quote_retrieved_at"], "2026-08-24T00:00:00+00:00")
        self.assertEqual(row["first_pitch_at"], "2026-08-24T00:10:00+00:00")
        self.assertEqual(len(payload["payload_sha256"]), 64)

    def test_build_archive_rejects_quote_at_or_after_first_pitch(self):
        snap = _snapshot(retrieved_at="2026-08-24T00:10:00Z")
        events = {
            "123": {
                "provider_event_id": "123",
                "event_name": "Away @ Home",
                "first_pitch_at": "2026-08-24T00:10:00+00:00",
            }
        }
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=snap), patch.object(
            mod, "_event_index", return_value=(events, [])
        ):
            payload = mod.build_archive_payload(now=datetime(2026, 8, 24, 0, 11, tzinfo=timezone.utc))

        self.assertEqual(payload["pit_target_quote_count"], 0)
        self.assertEqual(payload["rejected_target_count"], 1)
        self.assertEqual(payload["rejected_targets"][0]["reason"], "NOT_PREGAME")

    def test_build_archive_rejects_missing_event_time(self):
        snap = _snapshot(retrieved_at="2026-08-24T00:00:00Z")
        with patch.object(mod, "fetch_mlb_prop_quotes", return_value=snap), patch.object(
            mod, "_event_index", return_value=({}, [{"provider_event_id": "123", "reason": "FIRST_PITCH_MISSING"}])
        ):
            payload = mod.build_archive_payload(now=datetime(2026, 8, 24, 0, 1, tzinfo=timezone.utc))

        self.assertEqual(payload["pit_target_quote_count"], 0)
        self.assertEqual(payload["event_failure_count"], 1)
        self.assertEqual(payload["rejected_target_count"], 1)
        self.assertEqual(payload["rejected_targets"][0]["reason"], "EVENT_TIME_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()

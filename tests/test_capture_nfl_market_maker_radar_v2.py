import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.capture_nfl_market_maker_radar_v2 import (
    _timing_hygiene,
    capture,
)
from tests.test_capture_nfl_market_maker_radar import _dk, _fd, _pin

UTC = timezone.utc


class NFLDirectRadarCaptureV2Tests(unittest.TestCase):
    def test_provider_transports_start_concurrently_and_rows_carry_timing_provenance(self):
        barrier = threading.Barrier(3)

        def provider(event_factory, digest):
            def _fn(*, captured_at, out_root):
                barrier.wait(timeout=3)
                return [event_factory()], [{"raw_sha256": digest}], []
            return _fn

        funcs = {
            "pinnacle": provider(_pin, "p" * 64),
            "draftkings": provider(_dk, "d" * 64),
            "fanduel": provider(_fd, "f" * 64),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = capture(
                out_root=root,
                now=datetime(2026, 9, 14, 10, 10, tzinfo=UTC),
                provider_functions=funcs,
            )
            self.assertEqual(report["state"], "CAPTURED")
            self.assertEqual(report["transport_mode"], "CONCURRENT_PROVIDER_START")
            self.assertTrue(report["timing_hygiene"]["leadership_timing_eligible"])
            self.assertLessEqual(
                report["timing_hygiene"]["observed_cross_book_retrieval_skew_seconds"],
                report["timing_hygiene"]["max_cross_book_retrieval_skew_seconds"],
            )
            path = root / report["rows_relative_path"]
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            self.assertEqual(len(rows), 18)
            self.assertEqual({row["capture_id"] for row in rows}, {report["capture_id"]})
            self.assertEqual({row["book"] for row in rows}, {"pinnacle", "draftkings", "fanduel"})
            self.assertTrue(all(row["provider_request_started_at"] for row in rows))
            self.assertTrue(all(row["provider_retrieved_at"] for row in rows))
            self.assertTrue(all(row["leadership_timing_eligible"] is True for row in rows))
            self.assertTrue(all(row["provider_quote_age_seconds"] is None for row in rows))
            self.assertTrue(all(row["provider_quote_age_status"] == "UNKNOWN_PROVIDER_QUOTE_TIMESTAMP" for row in rows))
            self.assertTrue(all(row["timestamp_source"] == "CAPTURED_AT_SHARED_POLL_CLOCK" for row in rows))

    def test_cross_book_retrieval_skew_over_30_seconds_fails_timing_hygiene(self):
        providers = {
            "pinnacle": {"state": "REACHABLE", "retrieved_at": "2026-09-14T10:00:00Z"},
            "draftkings": {"state": "REACHABLE", "retrieved_at": "2026-09-14T10:00:10Z"},
            "fanduel": {"state": "REACHABLE", "retrieved_at": "2026-09-14T10:00:31Z"},
        }
        hygiene = _timing_hygiene(providers)
        self.assertEqual(hygiene["state"], "BLOCKED_CROSS_BOOK_RETRIEVAL_SKEW")
        self.assertFalse(hygiene["leadership_timing_eligible"])
        self.assertEqual(hygiene["observed_cross_book_retrieval_skew_seconds"], 31.0)


if __name__ == "__main__":
    unittest.main()

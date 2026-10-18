from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from sportsedge.mlb_source import (
    capture_mlb_source_bytes,
    fetch_boxscore,
    fetch_schedule,
)


class _Response:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.read_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        self.read_count += 1
        return self.raw


class _Opener:
    def __init__(self, schedule_raw: bytes, boxscore_raw: bytes):
        self.schedule_raw = schedule_raw
        self.boxscore_raw = boxscore_raw
        self.calls: list[str] = []
        self.responses: list[_Response] = []

    def __call__(self, url, timeout=15):
        text = str(url)
        self.calls.append(text)
        raw = self.boxscore_raw if "/boxscore" in text else self.schedule_raw
        response = _Response(raw)
        self.responses.append(response)
        return response


class SameFetchSourceCaptureTest(unittest.TestCase):
    def setUp(self):
        self.schedule = {
            "dates": [{
                "date": "2026-09-13",
                "games": [{
                    "gamePk": 777001,
                    "gameDate": "2026-09-13T18:20:00Z",
                    "gameNumber": 1,
                    "doubleHeader": "N",
                    "officialDate": "2026-09-13",
                    "venue": {"id": 17},
                    "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
                    "teams": {
                        "away": {
                            "team": {"id": 1, "name": "Away"},
                            "probablePitcher": {"id": 101, "fullName": "Away Starter"},
                        },
                        "home": {
                            "team": {"id": 2, "name": "Home"},
                            "probablePitcher": {"id": 202, "fullName": "Home Starter"},
                        },
                    },
                }],
            }],
        }
        self.boxscore = {
            "teams": {
                "away": {"players": {"ID11": {"person": {"id": 11, "fullName": "A"}, "battingOrder": "100"}}},
                "home": {"players": {"ID22": {"person": {"id": 22, "fullName": "H"}, "battingOrder": "100"}}},
            },
        }
        # Deliberately non-canonical formatting proves we hash/persist response bytes,
        # not a JSON reserialization of parsed data.
        self.schedule_raw = (json.dumps(self.schedule, separators=(", ", ": ")) + "\n").encode()
        self.boxscore_raw = ("  " + json.dumps(self.boxscore, separators=(",", ":")) + "\n").encode()

    def test_same_response_bytes_are_persisted_and_hashed(self):
        opener = _Opener(self.schedule_raw, self.boxscore_raw)
        observed = datetime(2026, 9, 13, 17, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            with patch("sportsedge.mlb_source._trusted_now", lambda: observed), \
                    capture_mlb_source_bytes(Path(td), clock=lambda: observed) as capture:
                games = fetch_schedule("2026-09-13", opener=opener)
                box = fetch_boxscore(777001, opener=opener)

            self.assertEqual(101, games[0].away_probable_pitcher_id)
            self.assertEqual(202, games[0].home_probable_pitcher_id)
            self.assertEqual(11, box["teams"]["away"]["players"]["ID11"]["person"]["id"])
            self.assertEqual(2, len(capture.records))
            self.assertEqual(2, len(opener.calls))
            self.assertTrue(all(response.read_count == 1 for response in opener.responses))

            schedule_record, boxscore_record = capture.records
            self.assertEqual("MLB_STATSAPI_SCHEDULE", schedule_record.source_kind)
            self.assertEqual("MLB_STATSAPI_BOXSCORE", boxscore_record.source_kind)
            self.assertEqual(777001, boxscore_record.game_pk)
            self.assertEqual(observed.isoformat(), schedule_record.observed_at_utc)
            self.assertEqual(observed.isoformat(), boxscore_record.observed_at_utc)
            self.assertEqual(hashlib.sha256(self.schedule_raw).hexdigest(), schedule_record.sha256)
            self.assertEqual(hashlib.sha256(self.boxscore_raw).hexdigest(), boxscore_record.sha256)
            self.assertEqual(self.schedule_raw, Path(schedule_record.path).read_bytes())
            self.assertEqual(self.boxscore_raw, Path(boxscore_record.path).read_bytes())

            manifest = capture.manifest()
            self.assertEqual("SAME_RESPONSE_BYTES_CONSUMED_BY_MODEL", manifest["capture_semantics"])
            self.assertFalse(manifest["promotion_authority"])
            self.assertFalse(manifest["retroactive_point_in_time_claim"])

    def test_default_receipt_clock_is_read_after_response_body(self):
        observed = datetime(2026, 9, 13, 17, 31, tzinfo=timezone.utc)
        events = []
        raw = self.schedule_raw

        class DelayedResponse(_Response):
            def read(self):
                events.append("body_received")
                return super().read()

        def trusted():
            events.append("clock_read")
            return observed

        with patch("sportsedge.mlb_source._trusted_now", trusted):
            games = fetch_schedule(
                "2026-09-13", opener=lambda *a, **kw: DelayedResponse(raw)
            )
        # trusted fetch-start reads (schedule + transport), body, then trusted receipt
        self.assertEqual(["clock_read", "clock_read", "body_received", "clock_read"], events)
        self.assertEqual("clock_read", events[-1])  # receipt read after the body
        self.assertEqual(observed.isoformat(), games[0].retrieved_at)

    def test_schedule_explicitly_requests_postseason_and_preserves_world_series(self):
        self.schedule["dates"][0]["games"][0]["gameType"] = "W"
        opener = _Opener(json.dumps(self.schedule).encode(), self.boxscore_raw)
        games = fetch_schedule("2026-09-13", opener=opener)
        query = parse_qs(urlparse(opener.calls[0]).query)
        self.assertEqual(["R,F,D,L,W,A,S,E"], query["gameType"])
        self.assertEqual("W", games[0].game_type)
        self.assertEqual(1, len(opener.calls))

    def test_direct_recorder_cannot_self_anchor_to_year_2000(self):
        from sportsedge.mlb_source import MLBSourceCapture, MLBSourceError
        now = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
        fake = datetime(2000, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            recorder = MLBSourceCapture(Path(td), clock=lambda: fake)
            with patch("sportsedge.mlb_source._trusted_now", lambda: now):
                with self.assertRaisesRegex(MLBSourceError, "RECEIPT_STALE_OR_REPLAYED"):
                    recorder.record(url="https://x/api/v1/schedule", raw=b"{}",
                                    fetch_started_at=fake, received_at=fake)
            self.assertEqual([], recorder.records)
            self.assertEqual([], list(Path(td).iterdir()))

    def test_direct_recorder_rejects_future_independent_anchor(self):
        from sportsedge.mlb_source import MLBSourceCapture, MLBSourceError
        now = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
        future = now + timedelta(hours=1)
        with tempfile.TemporaryDirectory() as td:
            recorder = MLBSourceCapture(Path(td), clock=lambda: future)
            with patch("sportsedge.mlb_source._trusted_now", lambda: now):
                with self.assertRaisesRegex(MLBSourceError, "RECEIPT_FUTURE_VS_SYSTEM_ANCHOR"):
                    recorder.record(url="https://x/api/v1/schedule", raw=b"{}",
                                    fetch_started_at=future, received_at=future)
            self.assertEqual([], recorder.records)

    def test_direct_recorder_rejects_stale_and_repeated_receipts(self):
        from sportsedge.mlb_source import MLBSourceCapture, MLBSourceError
        now = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
        prior = now - timedelta(minutes=2)
        with tempfile.TemporaryDirectory() as td:
            recorder = MLBSourceCapture(Path(td), clock=lambda: prior)
            with patch("sportsedge.mlb_source._trusted_now", lambda: now):
                with self.assertRaisesRegex(MLBSourceError, "RECEIPT_STALE_OR_REPLAYED"):
                    recorder.record(url="https://x/api/v1/schedule", raw=b"{}",
                                    fetch_started_at=prior, received_at=prior)
            current = MLBSourceCapture(Path(td), clock=lambda: now)
            with patch("sportsedge.mlb_source._trusted_now", lambda: now):
                current.record(url="https://x/api/v1/schedule", raw=b"{}",
                               fetch_started_at=now, received_at=now)
                with self.assertRaisesRegex(MLBSourceError, "RECEIPT_DUPLICATE_REPLAY"):
                    current.record(url="https://x/api/v1/schedule", raw=b"{}",
                                   fetch_started_at=now, received_at=now)
            self.assertEqual(1, len(current.records))

    def test_direct_recorder_requires_independent_clock_anchor(self):
        from sportsedge.mlb_source import MLBSourceCapture, MLBSourceError
        now = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            recorder = MLBSourceCapture(Path(td), clock=lambda: now)
            with patch("sportsedge.mlb_source._trusted_now", lambda: None):
                with self.assertRaisesRegex(MLBSourceError, "RECEIPT_ANCHOR_UNAVAILABLE"):
                    recorder.record(url="https://x/api/v1/schedule", raw=b"{}",
                                    fetch_started_at=now, received_at=now)
            self.assertEqual([], recorder.records)
            self.assertEqual([], list(Path(td).iterdir()))

    def test_journal_unchained_extra_metadata_fails_closed(self):
        from sportsedge import mlb_source as ms
        observed = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("sportsedge.mlb_source._trusted_now", lambda: observed):
                rec = ms.MLBSourceCapture(root, clock=lambda: observed)
                rec.record(url="https://x/api/v1/schedule", raw=b"{}",
                           fetch_started_at=observed, received_at=observed)
            journal = root / ms.RECEIPT_JOURNAL_NAME
            entry = json.loads(journal.read_text().strip())
            entry["unhashed_extra"] = "attacker-added"
            journal.write_text(json.dumps(entry) + "\n")
            with self.assertRaisesRegex(ms.MLBSourceError, "RECEIPT_JOURNAL_SCHEMA_DRIFT"):
                ms.verify_receipt_journal(root, verifier_now=observed)

    def test_journal_duplicate_json_key_fails_closed(self):
        from sportsedge import mlb_source as ms
        observed = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("sportsedge.mlb_source._trusted_now", lambda: observed):
                rec = ms.MLBSourceCapture(root, clock=lambda: observed)
                rec.record(url="https://x/api/v1/schedule", raw=b"{}",
                           fetch_started_at=observed, received_at=observed)
            journal = root / ms.RECEIPT_JOURNAL_NAME
            text = journal.read_text()
            original = '"url":"https://x/api/v1/schedule"'
            self.assertIn(original, text)
            journal.write_text(text.replace(original, original + "," + original, 1))
            with self.assertRaisesRegex(ms.MLBSourceError, "RECEIPT_JOURNAL_DUPLICATE_JSON_KEY"):
                ms.verify_receipt_journal(root, verifier_now=observed)

    def test_journal_unterminated_final_record_fails_closed(self):
        from sportsedge import mlb_source as ms
        observed = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("sportsedge.mlb_source._trusted_now", lambda: observed):
                rec = ms.MLBSourceCapture(root, clock=lambda: observed)
                rec.record(url="https://x/api/v1/schedule", raw=b"{}",
                           fetch_started_at=observed, received_at=observed)
            journal = root / ms.RECEIPT_JOURNAL_NAME
            self.assertTrue(journal.read_bytes().endswith(b"\n"))
            journal.write_bytes(journal.read_bytes()[:-1])
            with self.assertRaisesRegex(ms.MLBSourceError, "RECEIPT_JOURNAL_UNTERMINATED"):
                ms.verify_receipt_journal(root, verifier_now=observed)

    def test_journal_resigned_parent_path_fails_closed(self):
        from sportsedge import mlb_source as ms
        observed = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("sportsedge.mlb_source._trusted_now", lambda: observed):
                rec = ms.MLBSourceCapture(root, clock=lambda: observed)
                rec.record(url="https://x/api/v1/schedule", raw=b"{}",
                           fetch_started_at=observed, received_at=observed)
            journal = root / ms.RECEIPT_JOURNAL_NAME
            entry = json.loads(journal.read_text().strip())
            entry["file_name"] = "../outside.json"
            entry["record_sha256"] = ms._record_hash(entry)
            journal.write_text(json.dumps(entry) + "\n")
            with self.assertRaisesRegex(ms.MLBSourceError, "RECEIPT_RAW_PATH_UNSAFE"):
                ms.verify_receipt_journal(root, verifier_now=observed)

    def test_capture_is_opt_in(self):
        opener = _Opener(self.schedule_raw, self.boxscore_raw)
        observed = datetime(2026, 9, 13, 17, 30, tzinfo=timezone.utc)
        with patch("sportsedge.mlb_source._trusted_now", lambda: observed):
            fetch_schedule("2026-09-13", opener=opener)
        fetch_boxscore(777001, opener=opener)
        self.assertEqual(2, len(opener.calls))
        self.assertTrue(all(response.read_count == 1 for response in opener.responses))


if __name__ == "__main__":
    unittest.main()

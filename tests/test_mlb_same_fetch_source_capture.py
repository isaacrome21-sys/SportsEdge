from __future__ import annotations

from datetime import datetime, timezone
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

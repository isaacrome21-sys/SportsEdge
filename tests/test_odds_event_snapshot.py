import unittest
from datetime import datetime, timezone

from sportsedge.odds_event_snapshot import OddsEventSnapshot, acquire_mlb_event_snapshot


class Resp:
    def __init__(self, obj):
        import json
        self.raw = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


class OddsEventSnapshotTests(unittest.TestCase):
    def test_shared_snapshot_has_stable_explicit_provenance(self):
        events = [{
            "id": "evt-1",
            "commence_time": "2026-09-08T20:00:00Z",
            "away_team": "A",
            "home_team": "B",
        }]
        calls = []

        def opener(req, timeout=15):
            calls.append(req.full_url)
            return Resp(events)

        now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        a = acquire_mlb_event_snapshot(api_key="secret", opener=opener, acquired_at=now)
        b = acquire_mlb_event_snapshot(api_key="secret", opener=opener, acquired_at=now)

        self.assertEqual(a.provider, "THE_ODDS_API")
        self.assertEqual(a.source_path, "/sports/baseball_mlb/events")
        self.assertEqual(a.acquired_at_utc, now)
        self.assertEqual(a.payload_sha256, b.payload_sha256)
        self.assertEqual(len(a.payload_sha256), 64)
        self.assertEqual(a.event_by_id("evt-1")["home_team"], "B")
        self.assertEqual(len(calls), 2)

    def test_snapshot_rejects_missing_event_identity(self):
        snap = OddsEventSnapshot(
            provider="THE_ODDS_API",
            source_path="/sports/baseball_mlb/events",
            acquired_at_utc=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
            payload_sha256="0" * 64,
            events=({"id": "evt-1"},),
        )
        with self.assertRaises(Exception) as cm:
            snap.event_by_id("evt-2")
        self.assertIn("ODDS_EVENT_SNAPSHOT_EVENT_NOT_FOUND", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

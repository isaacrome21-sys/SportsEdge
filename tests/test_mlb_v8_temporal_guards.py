from __future__ import annotations

from datetime import date, datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from sportsedge import statcast_daily_source as statcast


ROOT = Path(__file__).resolve().parents[1]
REPLAY_PATH = ROOT / "scripts" / "build_mlb_v8_replay_archive.py"
_SPEC = importlib.util.spec_from_file_location("mlb_v8_replay_archive_temporal_test", REPLAY_PATH)
assert _SPEC is not None and _SPEC.loader is not None
replay = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(replay)


class _Response:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class MlbV8TemporalGuardTests(unittest.TestCase):
    def _write_snapshot(self, root: Path, *, returned: str, requested: str, commence: str) -> tuple[Path, bytes]:
        path = root / "snapshot.json"
        payload = {
            "timestamp": returned,
            "data": [{
                "id": "event-1",
                "commence_time": commence,
                "home_team": "Home",
                "away_team": "Away",
                "bookmakers": [],
            }],
        }
        raw = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        path.write_bytes(raw)
        path.with_name("snapshot.meta.json").write_text(json.dumps({
            "request_params_secret_free": {"date": requested},
            "payload_sha256": replay.sha256_bytes(raw),
        }))
        return path, raw

    def test_replay_t30_tolerance_is_one_sided(self):
        policy = {"canonical_capture_targets_minutes_before_first_pitch": [180, 90, 30, 10, 0]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            safe_dir = root / "safe"
            safe_dir.mkdir()
            safe_path, safe_raw = self._write_snapshot(
                safe_dir,
                returned="2026-09-02T18:30:00Z",
                requested="2026-09-02T18:30:00Z",
                commence="2026-09-02T19:06:00Z",  # T-36: 6 min early for T-30
            )
            eligible, reason, matches, _ = replay.verify_pit_snapshot(
                path=safe_path, raw=safe_raw, tier="A_PIT_SNAPSHOT", policy=policy
            )
            self.assertTrue(eligible)
            self.assertEqual(reason, "PIT_DECISION_TARGET_VERIFIED")
            self.assertEqual(matches[0]["canonical_target_minutes"], 30)
            self.assertEqual(matches[0]["target_delta_minutes"], 6.0)

            late_dir = root / "late"
            late_dir.mkdir()
            late_path, late_raw = self._write_snapshot(
                late_dir,
                returned="2026-09-02T18:30:00Z",
                requested="2026-09-02T18:30:00Z",
                commence="2026-09-02T18:54:06Z",  # T-24.1: 5.9 min AFTER T-30
            )
            eligible, reason, matches, _ = replay.verify_pit_snapshot(
                path=late_path, raw=late_raw, tier="A_PIT_SNAPSHOT", policy=policy
            )
            self.assertFalse(eligible)
            self.assertEqual(reason, "PIT_NO_CANONICAL_GAME_TARGET_MATCH")
            self.assertEqual(matches, [])

    def test_statcast_utc_rollover_cannot_admit_live_us_date(self):
        now = datetime(2026, 9, 3, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(statcast._strict_prior_day_end(now), date(2026, 9, 2))

        seen: dict[str, str] = {}
        csv_body = (
            "game_date,batter,pitcher,events,description\n"
            "2026-09-01,1,2,single,hit_into_play\n"
        )

        def opener(req, timeout=60):
            seen["url"] = req.full_url
            return _Response(csv_body)

        snapshot = statcast.fetch_daily_statcast(days=2, opener=opener, now=now)
        query = parse_qs(urlparse(seen["url"]).query)
        self.assertEqual(query["game_date_lt"], ["2026-09-02"])
        self.assertEqual(snapshot.end_date, "2026-09-02")
        self.assertNotEqual(query["game_date_lt"], ["2026-09-03"])

    def test_explicit_statcast_end_date_remains_deterministic(self):
        now = datetime(2026, 9, 3, 0, 30, tzinfo=timezone.utc)
        seen: dict[str, str] = {}
        csv_body = (
            "game_date,batter,pitcher,events,description\n"
            "2026-08-30,1,2,single,hit_into_play\n"
        )

        def opener(req, timeout=60):
            seen["url"] = req.full_url
            return _Response(csv_body)

        snapshot = statcast.fetch_daily_statcast(
            end_date=date(2026, 8, 31), days=2, opener=opener, now=now
        )
        query = parse_qs(urlparse(seen["url"]).query)
        self.assertEqual(query["game_date_lt"], ["2026-08-31"])
        self.assertEqual(snapshot.end_date, "2026-08-31")


if __name__ == "__main__":
    unittest.main()

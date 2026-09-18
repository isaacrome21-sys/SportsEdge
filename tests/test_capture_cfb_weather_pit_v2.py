import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

from scripts.capture_cfb_weather_pit_v2 import (
    CFBWeatherTransportError,
    _fetch_with_fallback,
    capture_weather,
    probe_transports,
)

UTC = timezone.utc


class _Response:
    def __init__(self, payload):
        self.raw = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def read(self): return self.raw


def _http_error(req, code):
    return HTTPError(req.full_url, code, "blocked", {"Server": "edge-test"}, BytesIO(b""))


class CFBWeatherV2Tests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 18, 23, 45, tzinfo=UTC)
        self.policy = {"windows": {
            "close": {"min_minutes_before_start": 2, "max_minutes_before_start": 20},
            "t0_prestart": {"min_minutes_before_start": 0, "max_minutes_before_start": 5},
            "decision": {"min_minutes_before_start": 45, "max_minutes_before_start": 120},
        }}

    def test_site_403_falls_back_to_cdn_and_hashes_exact_cdn_bytes(self):
        event = {
            "id": "401000001",
            "date": "2026-09-19T00:00:00Z",
            "competitions": [{
                "date": "2026-09-19T00:00:00Z",
                "status": {"type": {"state": "pre"}},
                "weather": {"temperature": 72, "displayValue": "Clear"},
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Home State"}},
                    {"homeAway": "away", "team": {"displayName": "Away Tech"}},
                ],
            }],
        }
        cdn_payload = {"content": {"sbData": {"events": [event]}}}
        cdn_raw = json.dumps(cdn_payload, separators=(",", ":")).encode()
        empty_cdn = {"content": {"sbData": {"events": []}}}
        summary = {"header": {"competitions": [{"status": {"type": {"state": "pre"}}}]}}

        def opener(req, timeout=20):
            url = req.full_url
            self.assertEqual(req.get_header("Accept"), "application/json")
            self.assertIn("SportsEdge-CFB-weather-PIT/2", req.get_header("User-agent"))
            if "site.api.espn.com" in url and "scoreboard" in url:
                raise _http_error(req, 403)
            if "cdn.espn.com" in url and "scoreboard" in url:
                return _Response(cdn_raw if "dates=20260918" in url else empty_cdn)
            if "site.api.espn.com" in url and "summary" in url:
                return _Response(summary)
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = capture_weather(now=self.now, policy=self.policy, out_dir=root, opener=opener, clock=lambda: self.now, pause=lambda _: None)
            self.assertEqual(report["observations_written"], 1)
            self.assertEqual(len(report["transport_fallbacks_observed"]), 2)
            self.assertTrue(all(x["http_status"] == 403 for x in report["transport_fallbacks_observed"]))
            row = json.loads((root / "history/cfb/weather/2026-09-19.ndjson").read_text())
            self.assertEqual(row["source"], "ESPN_CDN_SCOREBOARD")
            self.assertEqual(row["raw_sha256"], hashlib.sha256(cdn_raw).hexdigest())
            self.assertEqual((root / row["raw_relative_path"]).read_bytes(), cdn_raw)
            self.assertFalse(row["promotion_authority"])
            self.assertFalse(row["model_p_created"])

    def test_double_transport_failure_preserves_primary_and_fallback_identity(self):
        def opener(req, timeout=20):
            raise _http_error(req, 403)
        with self.assertRaises(CFBWeatherTransportError) as caught:
            _fetch_with_fallback(
                "https://site.api.espn.com/x",
                primary_source="ESPN_SITE_SCOREBOARD",
                fallback_url="https://cdn.espn.com/y",
                fallback_source="ESPN_CDN_SCOREBOARD",
                opener=opener,
                pause=lambda _: None,
            )
        exc = caught.exception
        self.assertEqual(exc.failure.source, "ESPN_CDN_SCOREBOARD")
        self.assertEqual(exc.failure.host, "cdn.espn.com")
        self.assertEqual(exc.failure.http_status, 403)
        self.assertEqual(exc.primary_failure.source, "ESPN_SITE_SCOREBOARD")
        self.assertEqual(exc.primary_failure.host, "site.api.espn.com")
        self.assertEqual(exc.primary_failure.http_status, 403)

    def test_probe_is_non_authoritative_and_distinguishes_hosts(self):
        def opener(req, timeout=20):
            if "site.api.espn.com" in req.full_url:
                raise _http_error(req, 403)
            return _Response({"content": {"sbData": {"events": []}}})
        report = probe_transports(opener=opener, now=self.now)
        self.assertFalse(report["site_ok"])
        self.assertTrue(report["cdn_ok"])
        self.assertFalse(report["promotion_authority"])
        self.assertFalse(report["model_p_created"])
        self.assertFalse(report["evidence_written"])
        self.assertEqual(report["checks"][0]["host"], "site.api.espn.com")
        self.assertEqual(report["checks"][1]["host"], "cdn.espn.com")


if __name__ == "__main__":
    unittest.main()

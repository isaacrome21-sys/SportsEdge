import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.probe_pinnacle_football_market_shape import probe

UTC = timezone.utc


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers = {"content-type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


class PinnacleFootballMarketShapeProbeTests(unittest.TestCase):
    def test_deterministic_first_market_matchup_and_raw_capture(self):
        calls = []

        def opener(request, timeout=30):
            calls.append(request.full_url)
            url = request.full_url
            if url.endswith("/sports/15/matchups"):
                return _Response([
                    {"id": 1, "hasMarkets": False, "name": "no markets"},
                    {"id": 22, "hasMarkets": True, "name": "first markets"},
                    {"id": 33, "hasMarkets": True, "name": "later markets"},
                ])
            if url.endswith("/matchups/22"):
                return _Response({"id": 22, "participants": [{"name": "Away"}, {"name": "Home"}]})
            if url.endswith("/matchups/22/markets/related/straight"):
                return _Response([{"key": "m;0", "prices": [{"price": -110}, {"price": 100}]}])
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(
                out_dir=Path(tmp),
                opener=opener,
                now=datetime(2026, 9, 14, 3, 5, tzinfo=UTC),
            )
            self.assertEqual(report["state"], "REACHABLE")
            self.assertEqual(report["selected_matchup"]["matchup_id"], 22)
            self.assertEqual(report["selection_rule"], "FIRST_PROVIDER_ORDERED_HASMARKETS_TRUE")
            self.assertEqual(set(report["captures"]), {"matchups", "matchup_detail", "straight_markets"})
            self.assertEqual(len(list((Path(tmp) / "raw" / "pinnacle").glob("*.json"))), 3)
            self.assertTrue(all(v is False for v in report["authority"].values()))
        self.assertEqual(len(calls), 3)

    def test_no_market_matchup_fails_closed(self):
        def opener(request, timeout=30):
            return _Response([{"id": 1, "hasMarkets": False}])

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["reason"], "PINNACLE_FOOTBALL_NO_MARKET_MATCHUP")
        self.assertTrue(all(v is False for v in report["authority"].values()))


if __name__ == "__main__":
    unittest.main()

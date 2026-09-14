import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.probe_direct_market_feeds import probe

UTC = timezone.utc


class _Response:
    def __init__(self, payload, *, status=200, content_type="application/json"):
        self._raw = json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


class DirectMarketFeedProbeTests(unittest.TestCase):
    def test_reachable_feeds_preserve_raw_and_zero_authority(self):
        calls = []

        def opener(request, timeout=30):
            calls.append(request)
            url = request.full_url
            if url.endswith("/sports"):
                return _Response([{"id": 15, "name": "Football", "matchupCount": 10}])
            if url.endswith("/sports/15/matchups"):
                return _Response(
                    [
                        {"id": 100, "hasMarkets": False},
                        {"id": 101, "hasMarkets": True, "startTime": "2026-09-14T17:00:00Z"},
                        {"id": 102, "hasMarkets": True, "startTime": "2026-09-14T20:00:00Z"},
                    ]
                )
            if url.endswith("/matchups/101"):
                return _Response(
                    {
                        "id": 101,
                        "startTime": "2026-09-14T17:00:00Z",
                        "participants": [
                            {"id": 1, "name": "Away", "alignment": "away"},
                            {"id": 2, "name": "Home", "alignment": "home"},
                        ],
                    }
                )
            if url.endswith("/matchups/101/markets/related/straight"):
                return _Response(
                    [
                        {
                            "id": 501,
                            "key": "s;0;m",
                            "prices": [
                                {"designation": "home", "price": -120},
                                {"designation": "away", "price": 105},
                            ],
                        }
                    ]
                )
            return _Response(
                {
                    "attachments": {
                        "events": {"1": {"eventId": 1}},
                        "markets": {"m": {"marketId": "m"}},
                        "runners": {"r": {"selectionId": 1}},
                    },
                    "layout": {},
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            report = probe(
                out_dir=out,
                opener=opener,
                now=datetime(2026, 9, 14, 3, 0, tzinfo=UTC),
            )
            self.assertEqual(report["contract"], "DIRECT_MARKET_PUBLIC_FEED_PROBE_V2")
            self.assertEqual(report["state"], "REACHABLE")
            pinnacle = report["providers"]["pinnacle"]
            self.assertEqual(pinnacle["football_sport_id"], 15)
            self.assertEqual(pinnacle["sample_matchup_id"], 101)
            self.assertEqual(
                pinnacle["discovery"]["selection_rule"],
                "FIRST_PROVIDER_ORDER_HAS_MARKETS_TRUE",
            )
            self.assertEqual(
                pinnacle["discovery"]["sample_straight_markets_shape"]["top_level_type"],
                "list",
            )
            self.assertEqual(
                report["providers"]["fanduel"]["shape"]["attachment_counts"]["events"],
                1,
            )
            self.assertEqual(len(list((out / "raw" / "pinnacle").glob("*.json"))), 4)
            self.assertTrue(list((out / "raw" / "fanduel").glob("*.json")))
            self.assertTrue(all(value is False for value in report["authority"].values()))
            rendered = json.dumps(report)
            self.assertNotIn("model_p_authority\": true", rendered.lower())

        self.assertEqual(len(calls), 5)
        for request in calls[:4]:
            headers = {k.lower(): v for k, v in request.header_items()}
            self.assertIn("x-api-key", headers)
        fanduel_headers = {k.lower(): v for k, v in calls[4].header_items()}
        self.assertEqual(fanduel_headers.get("x-sportsbook-region"), "NJ")

    def test_one_provider_failure_blocks_combined_probe_without_escalating_authority(self):
        def opener(request, timeout=30):
            if "arcadia.pinnacle.com" in request.full_url:
                raise OSError("network unavailable")
            return _Response({"attachments": {"events": {}}})

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["providers"]["pinnacle"]["state"], "BLOCKED")
        self.assertEqual(report["providers"]["fanduel"]["state"], "REACHABLE")
        self.assertTrue(all(value is False for value in report["authority"].values()))

    def test_missing_marketed_football_matchup_fails_closed(self):
        def opener(request, timeout=30):
            url = request.full_url
            if url.endswith("/sports"):
                return _Response([{"id": 15, "name": "Football"}])
            if url.endswith("/sports/15/matchups"):
                return _Response([{"id": 100, "hasMarkets": False}])
            return _Response({"attachments": {"events": {}}})

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(
            report["providers"]["pinnacle"]["reason"],
            "PINNACLE_FOOTBALL_MARKETED_MATCHUP_NOT_FOUND",
        )
        self.assertTrue(all(value is False for value in report["authority"].values()))

    def test_source_attribution_is_frozen(self):
        def opener(request, timeout=30):
            url = request.full_url
            if url.endswith("/sports"):
                return _Response([{"id": 15, "name": "Football"}])
            if url.endswith("/sports/15/matchups"):
                return _Response([{"id": 101, "hasMarkets": True}])
            if url.endswith("/matchups/101"):
                return _Response({"id": 101})
            if url.endswith("/matchups/101/markets/related/straight"):
                return _Response([])
            return _Response({"attachments": {}})

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener)
        source = report["upstream_reference"]
        self.assertEqual(source["repository"], "DanielTomaro13/sportsdata-mcp")
        self.assertEqual(source["license"], "MIT")
        self.assertEqual(source["reference_commit"], "8f723fc3fe2836ddb92829084b6aeab7c191a750")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.probe_fanduel_football_market_shape import (
    SELECTION_RULE,
    _is_upcoming_two_team_event,
    probe,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 14, 3, 30, tzinfo=UTC)


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


def _event(event_id=12345, *, name="Kansas City Chiefs @ Denver Broncos", start="2026-09-15T00:15:00Z"):
    return {
        "eventId": event_id,
        "name": name,
        "openDate": start,
        "competitionId": 111,
    }


class FanDuelFootballMarketShapeProbeTests(unittest.TestCase):
    def test_selector_requires_future_two_team_event(self):
        self.assertTrue(_is_upcoming_two_team_event(_event(), now=NOW))
        self.assertFalse(
            _is_upcoming_two_team_event(
                _event(start="2026-09-14T00:15:00Z"), now=NOW
            )
        )
        self.assertFalse(
            _is_upcoming_two_team_event(_event(name="Super Bowl Winner"), now=NOW)
        )
        missing_id = _event()
        missing_id.pop("eventId")
        self.assertFalse(_is_upcoming_two_team_event(missing_id, now=NOW))

    def test_content_page_to_event_page_capture_is_deterministic(self):
        calls = []

        def opener(request, timeout=30):
            calls.append(request)
            parsed = urlparse(request.full_url)
            query = parse_qs(parsed.query)
            if parsed.path.endswith("/sbapi/content-managed-page"):
                self.assertEqual(query["customPageId"], ["nfl"])
                self.assertEqual(query["page"], ["CUSTOM"])
                self.assertIn("_ak", query)
                return _Response(
                    {
                        "attachments": {
                            "events": {
                                "1": _event(1, name="Super Bowl Winner"),
                                "12345": _event(12345),
                                "67890": _event(
                                    67890,
                                    name="Buffalo Bills vs Miami Dolphins",
                                    start="2026-09-20T17:00:00Z",
                                ),
                            }
                        },
                        "layout": {"sections": []},
                    }
                )
            if parsed.path.endswith("/sbapi/event-page"):
                self.assertEqual(query["eventId"], ["12345"])
                self.assertIn("_ak", query)
                return _Response(
                    {
                        "attachments": {
                            "events": {"12345": _event(12345)},
                            "markets": {
                                "734.1": {
                                    "marketId": "734.1",
                                    "marketName": "Moneyline",
                                    "runners": [
                                        {"runnerName": "Kansas City Chiefs", "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": -120}}},
                                        {"runnerName": "Denver Broncos", "winRunnerOdds": {"americanDisplayOdds": {"americanOdds": 100}}},
                                    ],
                                }
                            },
                        },
                        "layout": {"tabs": [{"id": 1, "title": "All"}]},
                    }
                )
            raise AssertionError(request.full_url)

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener, now=NOW)
            self.assertEqual(report["state"], "REACHABLE")
            self.assertEqual(report["selection_rule"], SELECTION_RULE)
            self.assertEqual(report["selected_event"]["event_id"], 12345)
            self.assertEqual(report["selected_event"]["name"], "Kansas City Chiefs @ Denver Broncos")
            self.assertEqual(set(report["captures"]), {"content_page", "event_page"})
            self.assertEqual(report["captures"]["event_page"]["market_count"], 1)
            self.assertEqual(report["captures"]["event_page"]["market_container_type"], "dict")
            self.assertEqual(len(list((Path(tmp) / "raw" / "fanduel").glob("*.json"))), 2)
            self.assertTrue(all(v is False for v in report["authority"].values()))
        self.assertEqual(len(calls), 2)
        for request in calls:
            headers = {k.lower(): v for k, v in request.header_items()}
            self.assertEqual(headers.get("origin"), "https://sportsbook.fanduel.com")
            self.assertEqual(headers.get("x-sportsbook-region"), "NJ")

    def test_missing_event_markets_fails_closed(self):
        def opener(request, timeout=30):
            parsed = urlparse(request.full_url)
            if parsed.path.endswith("/sbapi/content-managed-page"):
                return _Response({"attachments": {"events": [_event()]}})
            if parsed.path.endswith("/sbapi/event-page"):
                return _Response({"attachments": {"markets": {}}})
            raise AssertionError(request.full_url)

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener, now=NOW)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["reason"], "FANDUEL_NFL_EVENT_PAGE_MARKETS_MISSING")
        self.assertTrue(all(v is False for v in report["authority"].values()))

    def test_no_upcoming_two_team_event_fails_closed(self):
        def opener(request, timeout=30):
            return _Response(
                {
                    "attachments": {
                        "events": [
                            _event(1, name="Super Bowl Winner"),
                            _event(2, start="2026-09-14T00:15:00Z"),
                        ]
                    }
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener, now=NOW)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["reason"], "FANDUEL_NFL_NO_UPCOMING_TWO_TEAM_EVENT")
        self.assertTrue(all(v is False for v in report["authority"].values()))


if __name__ == "__main__":
    unittest.main()

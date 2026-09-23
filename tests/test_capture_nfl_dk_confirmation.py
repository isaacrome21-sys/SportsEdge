#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import scripts.capture_nfl_dk_confirmation as cap


class PairMarketsTests(unittest.TestCase):
    def test_requires_both_sides_from_one_list(self):
        rows = [
            {"provider_event_id": "1", "home_team": "GB Packers", "away_team": "ATL Falcons",
             "commence_time": "2026-09-25T00:15:00Z", "market": "h2h", "point": None,
             "outcome": "ATL Falcons", "price_american": 220},
            {"provider_event_id": "1", "home_team": "GB Packers", "away_team": "ATL Falcons",
             "commence_time": "2026-09-25T00:15:00Z", "market": "h2h", "point": None,
             "outcome": "GB Packers", "price_american": -270},
        ]
        paired = cap.pair_markets(rows)
        self.assertEqual(len(paired), 1)
        self.assertEqual(len(paired[0]["sides"]), 2)

    def test_one_side_is_blocked(self):
        rows = [
            {"provider_event_id": "1", "home_team": "GB Packers", "away_team": "ATL Falcons",
             "commence_time": "2026-09-25T00:15:00Z", "market": "h2h", "point": None,
             "outcome": "ATL Falcons", "price_american": 220},
        ]
        with self.assertRaises(cap.Blocked) as ctx:
            cap.pair_markets(rows)
        self.assertEqual(ctx.exception.reason, "BLOCKED_MISSING_SIDE")


class FetchBlockedTests(unittest.TestCase):
    def test_403_is_blocked(self):
        def boom(*_a, **_k):
            raise HTTPError("https://x", 403, "Forbidden", hdrs=None, fp=None)

        with patch("scripts.capture_nfl_dk_confirmation.urlopen", side_effect=boom):
            with self.assertRaises(cap.Blocked) as ctx:
                cap.fetch_once()
        self.assertEqual(ctx.exception.reason, "HTTP_ERROR")


if __name__ == "__main__":
    unittest.main()

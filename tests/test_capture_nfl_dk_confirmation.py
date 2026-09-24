#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError

import scripts.capture_nfl_dk_confirmation as cap
from sportsedge.draftkings_game_market_source import RawDraftKingsBoard, normalize_board


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

    def test_spread_sign_is_preserved_per_team(self):
        payload = {
            "events": [{"id": "1", "name": "ATL Falcons @ GB Packers", "startEventDate": "2026-09-25T00:15:00Z"}],
            "markets": [{"id": "m1", "eventId": "1", "name": "Spread"}],
            "selections": [
                {"marketId": "m1", "label": "ATL Falcons +6.5", "points": 6.5, "displayOdds": {"american": "+110"}},
                {"marketId": "m1", "label": "GB Packers -6.5", "points": -6.5, "displayOdds": {"american": "-130"}},
            ],
        }
        raw = json.dumps(payload).encode()
        board = RawDraftKingsBoard(
            "americanfootball_nfl", "fixture", raw,
            datetime(2026, 9, 23, tzinfo=timezone.utc), payload,
        )
        rows = normalize_board(board)
        paired = cap.pair_markets(rows)
        sides = {x["outcome"]: x["point"] for x in paired[0]["sides"]}
        self.assertEqual(sides["ATL Falcons"], 6.5)
        self.assertEqual(sides["GB Packers"], -6.5)


class FetchBlockedTests(unittest.TestCase):
    def test_403_is_blocked_with_detail(self):
        def boom(*_a, **_k):
            raise HTTPError("https://x", 403, "Forbidden", hdrs=None, fp=None)

        with patch("scripts.capture_nfl_dk_confirmation.urlopen", side_effect=boom):
            with self.assertRaises(cap.Blocked) as ctx:
                cap.fetch_once()
        self.assertEqual(ctx.exception.reason, "HTTP_ERROR")
        self.assertIn("status=403", ctx.exception.detail)
        self.assertIn("Forbidden", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.probe_pinnacle_football_market_shape import (
    SELECTION_RULE,
    _is_upcoming_nfl_game,
    probe,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 14, 3, 5, tzinfo=UTC)


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


def _game(matchup_id=22, *, start="2026-09-15T00:15:00Z", status="pending"):
    return {
        "id": matchup_id,
        "league": {"id": 889, "name": "NFL"},
        "type": "matchup",
        "special": None,
        "startTime": start,
        "status": status,
        "hasMarkets": True,
        "totalMarketCount": 89,
        "participants": [
            {"name": "Kansas City Chiefs", "alignment": "home"},
            {"name": "Denver Broncos", "alignment": "away"},
        ],
        "periods": [
            {
                "period": 0,
                "status": "open",
                "hasMoneyline": True,
                "hasSpread": True,
                "hasTotal": True,
            }
        ],
    }


class PinnacleFootballMarketShapeProbeTests(unittest.TestCase):
    def test_structural_game_selector_rejects_specials_started_and_non_nfl(self):
        good = _game()
        self.assertTrue(_is_upcoming_nfl_game(good, now=NOW))

        special = dict(good, id=1, type="special", special={"category": "Player Props"})
        self.assertFalse(_is_upcoming_nfl_game(special, now=NOW))

        started = dict(good, id=2, startTime="2026-09-14T00:20:00Z", status="started")
        self.assertFalse(_is_upcoming_nfl_game(started, now=NOW))

        non_nfl = dict(good, id=3, league={"name": "NCAAF"})
        self.assertFalse(_is_upcoming_nfl_game(non_nfl, now=NOW))

        neutral = dict(
            good,
            id=4,
            participants=[
                {"name": "Over", "alignment": "neutral"},
                {"name": "Under", "alignment": "neutral"},
            ],
        )
        self.assertFalse(_is_upcoming_nfl_game(neutral, now=NOW))

    def test_deterministic_first_upcoming_nfl_game_and_straight_market_capture(self):
        calls = []

        def opener(request, timeout=30):
            calls.append(request.full_url)
            url = request.full_url
            if url.endswith("/sports/15/matchups"):
                return _Response([
                    {
                        "id": 1,
                        "league": {"name": "NFL"},
                        "type": "special",
                        "special": {"category": "Player Props"},
                        "startTime": "2026-09-15T00:15:00Z",
                        "status": "pending",
                        "hasMarkets": True,
                        "participants": [
                            {"name": "Over", "alignment": "neutral"},
                            {"name": "Under", "alignment": "neutral"},
                        ],
                        "periods": [],
                    },
                    _game(22),
                    _game(33, start="2026-09-20T17:00:00Z"),
                ])
            if url.endswith("/matchups/22/markets/related/straight"):
                return _Response(
                    [
                        {
                            "key": "m;0",
                            "matchupId": 22,
                            "period": 0,
                            "prices": [
                                {"designation": "home", "price": -110},
                                {"designation": "away", "price": 100},
                            ],
                        }
                    ]
                )
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener, now=NOW)
            self.assertEqual(report["state"], "REACHABLE")
            self.assertEqual(report["selected_matchup"]["matchup_id"], 22)
            self.assertEqual(report["selected_matchup"]["home_team"], "Kansas City Chiefs")
            self.assertEqual(report["selected_matchup"]["away_team"], "Denver Broncos")
            self.assertEqual(report["selection_rule"], SELECTION_RULE)
            self.assertEqual(set(report["captures"]), {"matchups", "straight_markets"})
            self.assertEqual(len(list((Path(tmp) / "raw" / "pinnacle").glob("*.json"))), 2)
            self.assertTrue(all(v is False for v in report["authority"].values()))
        self.assertEqual(len(calls), 2)

    def test_no_upcoming_nfl_game_fails_closed(self):
        def opener(request, timeout=30):
            return _Response(
                [
                    {
                        "id": 1,
                        "league": {"name": "NFL"},
                        "type": "special",
                        "special": {"category": "Futures"},
                        "startTime": "2026-09-15T00:15:00Z",
                        "status": "pending",
                        "hasMarkets": True,
                        "participants": [],
                        "periods": [],
                    }
                ]
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = probe(out_dir=Path(tmp), opener=opener, now=NOW)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["reason"], "PINNACLE_FOOTBALL_NO_UPCOMING_NFL_GAME_MATCHUP")
        self.assertTrue(all(v is False for v in report["authority"].values()))


if __name__ == "__main__":
    unittest.main()

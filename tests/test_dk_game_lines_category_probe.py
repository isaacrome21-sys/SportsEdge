import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.probe_dk_game_lines_categories import (
    DKCategoryProbeError,
    SPORTS,
    UPSTREAM_REFERENCE,
    discover_game_lines,
    probe_sport,
    validate_game_lines_board,
)

UTC = timezone.utc


class _Response:
    def __init__(self, payload, *, status=200):
        self._raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.status = status
        self.headers = {
            "content-type": "application/json",
            "Date": "Mon, 28 Sep 2026 04:00:00 GMT",
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


class DKGameLinesCategoryProbeTests(unittest.TestCase):
    def test_candidate_ids_are_discovery_only_and_source_bound(self):
        self.assertEqual(SPORTS["nba"]["league_id"], 42648)
        self.assertEqual(SPORTS["nhl"]["league_id"], 42133)
        self.assertEqual(UPSTREAM_REFERENCE["repository"], "sjhouston23/oddswrap")
        self.assertEqual(
            UPSTREAM_REFERENCE["commit"],
            "370291c8bfcc0f2032a40cda366d76604f3a29dc",
        )

    def test_discovers_exact_game_lines_name(self):
        out = discover_game_lines(
            {
                "categories": [
                    {"id": 100, "name": "Popular"},
                    {"id": 493, "name": "  Game   Lines  "},
                    {"id": 1216, "name": "Player Props"},
                ]
            }
        )
        self.assertEqual(out["category_id"], "493")
        self.assertEqual(out["category_name"], "Game   Lines")
        self.assertEqual(len(out["observed_categories"]), 3)

    def test_missing_or_duplicate_game_lines_fails_closed(self):
        with self.assertRaisesRegex(DKCategoryProbeError, "NOT_FOUND"):
            discover_game_lines({"categories": [{"id": 1, "name": "Popular"}]})
        with self.assertRaisesRegex(DKCategoryProbeError, "AMBIGUOUS"):
            discover_game_lines(
                {
                    "categories": [
                        {"id": 10, "name": "Game Lines"},
                        {"id": 11, "name": "game lines"},
                    ]
                }
            )

    def test_invalid_category_or_board_shape_fails_closed(self):
        with self.assertRaisesRegex(DKCategoryProbeError, "CATEGORIES_LIST_MISSING"):
            discover_game_lines({})
        with self.assertRaisesRegex(DKCategoryProbeError, "CATEGORY_ID_INVALID"):
            discover_game_lines({"categories": [{"id": "abc", "name": "Game Lines"}]})
        with self.assertRaisesRegex(DKCategoryProbeError, "SELECTIONS_LIST_MISSING"):
            validate_game_lines_board({"events": [], "markets": []})

    def test_successful_probe_preserves_both_raw_payloads_and_zero_authority(self):
        calls = []
        league = {
            "categories": [
                {"id": 77, "name": "Popular"},
                {"id": 493, "name": "Game Lines"},
            ],
            "subcategories": [{"id": 1, "categoryId": 493, "name": "Game"}],
        }
        board = {
            "events": [{"id": "e1", "name": "Away @ Home"}],
            "markets": [{"id": "m1", "eventId": "e1", "name": "Spread"}],
            "selections": [{"id": "s1", "marketId": "m1", "label": "Home"}],
        }

        def opener(request, timeout=20):
            calls.append(request.full_url)
            if request.full_url.endswith("/leagues/42648"):
                return _Response(league)
            if request.full_url.endswith("/leagues/42648/categories/493"):
                return _Response(board)
            raise AssertionError(request.full_url)

        clock = lambda: datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            report = probe_sport("nba", out_dir=out_dir, opener=opener, clock=clock)
            self.assertEqual(report["state"], "VERIFIED_DIAGNOSTIC_ONLY")
            self.assertEqual(report["discovery"]["category_id"], "493")
            self.assertEqual(report["discovery"]["category_id_status"], "DISCOVERED_NOT_FROZEN")
            self.assertEqual(report["game_lines_board"]["shape_counts"], {"events": 1, "markets": 1, "selections": 1})
            self.assertEqual(report["league_metadata"]["timestamp_semantics"], "SPORTSEDGE_HTTP_RESPONSE_RECEIPT_UPPER_BOUND")
            self.assertEqual(report["game_lines_board"]["timestamp_semantics"], "SPORTSEDGE_HTTP_RESPONSE_RECEIPT_UPPER_BOUND")
            self.assertTrue(all(value is False for value in report["authority"].values()))
            self.assertEqual(len(list((out_dir / "raw" / "nba").glob("*.json"))), 2)
        self.assertEqual(len(calls), 2)

    def test_failed_board_validation_stays_blocked_and_never_freezes_id(self):
        def opener(request, timeout=20):
            if request.full_url.endswith("/leagues/42133"):
                return _Response({"categories": [{"id": 812, "name": "Game Lines"}]})
            return _Response({"events": [], "markets": []})

        with tempfile.TemporaryDirectory() as tmp:
            report = probe_sport("nhl", out_dir=Path(tmp), opener=opener)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertIn("SELECTIONS_LIST_MISSING", report["reason"])
        self.assertNotIn("discovery", report)
        self.assertTrue(all(value is False for value in report["authority"].values()))

    def test_unsupported_sport_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(DKCategoryProbeError, "SPORT_UNSUPPORTED"):
                probe_sport("nfl", out_dir=Path(tmp))


if __name__ == "__main__":
    unittest.main()

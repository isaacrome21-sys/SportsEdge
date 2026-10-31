"""Adversarial controls for opt-in, non-admitted CFBD moneyline preservation."""
from __future__ import annotations

import json
import unittest

from sportsedge.sports.cfb import cfbd_issue_cache as cache
from sportsedge.sports.cfb.cfbd_moneyline_research_v1 import (
    SCHEMA,
    american_odds,
    normalize_moneyline_research,
    summarize_raw_coverage,
)


def game(lines, *, gid=314, start="2024-09-01T00:00:00Z"):
    return {
        "id": gid, "homeTeam": "Home U", "awayTeam": "Away U",
        "startDate": start, "lines": lines,
    }


class CFBMoneylineResearchCacheTests(unittest.TestCase):
    def test_strict_american_odds(self):
        for raw, expected in [(-110, -110), (100, 100), ("+125", 125),
                              ("-105", -105), (100.0, 100)]:
            with self.subTest(raw=raw):
                self.assertEqual(american_odds(raw), expected)

        invalid = (None, True, False, 0, 99, -99, 100.5, -110.1,
                   float("nan"), float("inf"), -float("inf"), "",
                   "EVEN", "100.0", "1e3", "+ 120", "105xyz", [], {})
        for raw in invalid:
            with self.subTest(raw=repr(raw)):
                self.assertIsNone(american_odds(raw))

    def test_preserves_all_whole_same_provider_pairs_without_spread(self):
        out = normalize_moneyline_research([game([
            {"provider": "consensus", "homeMoneyline": "+115",
             "awayMoneyline": "-135"},
            {"provider": "DraftKings", "homeMoneyline": -110,
             "awayMoneyline": 100},
            {"provider": "ESPN Bet", "homeMoneyline": None,
             "awayMoneyline": -120},
        ])])["314"]
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["source"], "CFBD_REST_LINES")
        self.assertEqual(out["status"], "UNVERIFIED_RAW_PAIRS")
        self.assertEqual([p["provider"] for p in out["pairs"]],
                         ["consensus", "DraftKings"])
        self.assertEqual(out["pairs"][1]["home_american"], -110)
        self.assertEqual(out["pairs"][1]["away_american"], 100)
        self.assertEqual(out["rejected_raw_rows"], 1)
        self.assertIsNone(out["quote_timestamp"])
        self.assertIsNone(out["original_response_receipt"])
        self.assertFalse(out["authenticated_draftkings"])
        self.assertFalse(out["market_admitted"])
        self.assertFalse(out["clv_authority"])
        self.assertFalse(out["betting_authority"])
        self.assertEqual(out["game_start_unverified"], "2024-09-01T00:00:00Z")
        self.assertNotIn("home_ml", out)
        self.assertNotIn("moneyline", out)
        json.dumps(out, allow_nan=False)

    def test_missing_and_malformed_pairs_fail_closed(self):
        for line, status in [
            ({"provider": "DraftKings", "spread": -3}, "NO_MONEYLINE_FIELDS"),
            ({"provider": "DraftKings", "homeMoneyline": 105},
             "NO_VALID_MONEYLINE_PAIR"),
            ({"provider": "DraftKings", "homeMoneyline": True,
              "awayMoneyline": -120}, "NO_VALID_MONEYLINE_PAIR"),
            ({"provider": "DraftKings", "homeMoneyline": float("inf"),
              "awayMoneyline": 110}, "NO_VALID_MONEYLINE_PAIR"),
            ({"provider": "", "homeMoneyline": 105,
              "awayMoneyline": -120}, "NO_VALID_MONEYLINE_PAIR"),
        ]:
            with self.subTest(line=line):
                out = normalize_moneyline_research([game([line])])["314"]
                self.assertEqual(out["status"], status)
                self.assertEqual(out["pairs"], [])
                self.assertFalse(out["market_admitted"])
                json.dumps(out, allow_nan=False)

    def test_never_pairs_prices_across_providers(self):
        lines = [
            {"provider": "DraftKings", "homeMoneyline": 110},
            {"provider": "Bovada", "awayMoneyline": -130},
        ]
        out = normalize_moneyline_research([game(lines)])["314"]
        self.assertEqual(out["status"], "NO_VALID_MONEYLINE_PAIR")
        self.assertEqual(out["pairs"], [])
        self.assertEqual(out["rejected_raw_rows"], 2)

    def test_conflicting_same_provider_rows_block_entire_game(self):
        lines = [
            {"provider": "DraftKings", "homeMoneyline": 120, "awayMoneyline": -140},
            {"provider": "DraftKings", "homeMoneyline": 130, "awayMoneyline": -150},
            {"provider": "Bovada", "homeMoneyline": 125, "awayMoneyline": -145},
        ]
        out = normalize_moneyline_research([game(lines)])["314"]
        self.assertEqual(out["status"], "CONFLICTING_PROVIDER_PRICE")
        self.assertEqual(out["pairs"], [])

    def test_duplicate_identical_provider_pair_dedupes(self):
        line = {"provider": "DraftKings", "homeMoneyline": -125, "awayMoneyline": 105}
        out = normalize_moneyline_research([game([line, dict(line)])])["314"]
        self.assertEqual(out["status"], "UNVERIFIED_RAW_PAIRS")
        self.assertEqual(len(out["pairs"]), 1)

    def test_bad_game_or_line_shape_is_never_silently_admitted(self):
        for bad in (None, [], "game"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "GAME_MAPPING"):
                    normalize_moneyline_research([bad])
        for gid in (None, 0, -1, True, "not-an-id", 3.5):
            with self.subTest(gid=gid):
                with self.assertRaisesRegex(ValueError, "GAME_ID"):
                    normalize_moneyline_research([game([], gid=gid)])
        for bad_lines in ({}, "not-a-list", [None]):
            with self.subTest(lines=bad_lines):
                with self.assertRaisesRegex(ValueError, "LINES_LIST|LINE_MAPPING"):
                    normalize_moneyline_research([game(bad_lines)])
        with self.assertRaisesRegex(ValueError, "GAME_DUPLICATE"):
            normalize_moneyline_research([game([]), game([])])

    def test_opt_in_cache_family_no_automatic_quota_or_spread_change(self):
        self.assertNotIn("ml_research_2024", cache.history_names())
        self.assertEqual(cache.SPECS["ml_research"][0], "/lines")
        payload = [game([{"provider": "DraftKings", "homeMoneyline": 110,
                         "awayMoneyline": -125}])]
        fetches, saved = [], []

        def fake_fetch(path, params, key):
            fetches.append((path, params, key))
            return payload

        rows = cache.ensure(
            ["ml_research_2024"], "fake", cache={}, budget=1,
            fetch=fake_fetch, save=lambda name, data: saved.append((name, data)),
            sleep=lambda _: None,
        )
        self.assertEqual(len(fetches), 1)
        self.assertEqual(saved[0][0], "ml_research_2024")
        self.assertEqual(rows["ml_research_2024"]["314"]["status"],
                         "UNVERIFIED_RAW_PAIRS")
        self.assertEqual(cache.decode_bodies([
            cache.encode_item("ml_research_2024", rows["ml_research_2024"])
        ])["ml_research_2024"], rows["ml_research_2024"])
        self.assertEqual(cache.normalize_lines([
            game([{"provider": "consensus", "spread": -3.5, "overUnder": 48.5}])
        ])["314"]["spread"], -3.5)
        self.assertNotIn("moneyline_research", cache.normalize_lines([
            game([{"provider": "consensus", "spread": -3.5}])
        ])["314"])

    def test_deterministic_raw_coverage_counts_without_admission(self):
        records = normalize_moneyline_research([
            game([], gid=1),
            game([{"provider": "DraftKings", "homeMoneyline": 110}], gid=2),
            game([{"provider": "DraftKings", "homeMoneyline": 110,
                   "awayMoneyline": -125},
                  {"provider": "Bovada", "homeMoneyline": 105,
                   "awayMoneyline": -120}], gid=3),
            game([{"provider": "DraftKings", "homeMoneyline": 110,
                   "awayMoneyline": -125},
                  {"provider": "DraftKings", "homeMoneyline": 120,
                   "awayMoneyline": -135}], gid=4),
        ])
        summary = summarize_raw_coverage(records)
        self.assertEqual(summary["games_seen"], 4)
        self.assertEqual(summary["games_with_raw_pairs"], 1)
        self.assertEqual(summary["raw_provider_pair_rows"], 2)
        self.assertEqual(summary["raw_provider_counts"],
                         {"Bovada": 1, "DraftKings": 1})
        self.assertEqual(summary["games_by_status"]["NO_MONEYLINE_FIELDS"], 1)
        self.assertEqual(summary["games_by_status"]["NO_VALID_MONEYLINE_PAIR"], 1)
        self.assertEqual(summary["games_by_status"]["CONFLICTING_PROVIDER_PRICE"], 1)
        self.assertEqual(summary["status"], "RAW_FIELD_COVERAGE_ONLY_NOT_ADMITTED")
        self.assertEqual(summary["verified_draftkings_quote_games"], 0)
        self.assertEqual(summary["source_quote_timestamps_verified"], 0)
        self.assertFalse(summary["moneyline_market_admitted"])
        self.assertFalse(summary["actual_roi_or_clv_authority"])
        self.assertEqual(summarize_raw_coverage({})["status"],
                         "EMPTY_NO_SOURCE_OBSERVATIONS")
        with self.assertRaisesRegex(ValueError, "ROW_SCHEMA"):
            summarize_raw_coverage({"1": {"schema": "FAKE"}})


if __name__ == "__main__":
    unittest.main()

import copy
import unittest
from sportsedge.oddspapi_check_c import (
    VERSION, C_VERSION, CheckCRefusal, evaluate_check_c, evaluate_c1, evaluate_c2)

SHA = "a" * 64


def c1():
    event = "synthetic-alcs-g6"
    quotes = []
    for market, team, price, line in (("MONEYLINE", "TB", -158, None),
                                      ("MONEYLINE", "CLE", 130, None),
                                      ("RUN_LINE", "TB", None, -1.5)):
        quotes.append({"canonical_event_id": event, "market": market,
                       "team": team, "bookmaker": "draftkings", "line": line,
                       "american_price": price, "captured_at_utc": "2026-10-20T23:00:00Z",
                       "source_sha256": SHA})
    return {"canonical_event_id": event, "league": "MLB", "series": "ALCS",
            "game_number": 6, "home_team": "TB", "away_team": "CLE",
            "actual_first_play": {"canonical_event_id": event,
                                  "actual_first_play_utc": "2026-10-20T23:01:00Z",
                                  "official_source_sha256": SHA}, "quotes": quotes}


def c2(market="MONEYLINE"):
    rows = []
    for i in range(200):
        season = str(2022 + i % 4)
        q = {"american_price": -110 if market == "MONEYLINE" else None,
             "line": None if market == "MONEYLINE" else 1.5}
        rows.append({"game_id": str(i), "season": season,
                     "game_start_utc": season + "-09-28T20:00:00Z",
                     "side": "OVER" if market == "TOTAL" else "HOME",
                     "sbr_bookmaker": "draftkings", "oddspapi_bookmaker": "draftkings",
                     "sbr_close": q, "oddspapi_candidate": copy.deepcopy(q),
                     "sbr_receipt_sha256": SHA, "oddspapi_receipt_sha256": SHA})
    return {"version": VERSION, "league": "MLB", "bookmaker": "draftkings",
            "market": market, "samples": rows,
            "cohort": {"most_recent_complete_season": "2025",
                       "final_week_start_utc": "2025-09-22T00:00:00Z",
                       "final_week_end_utc": "2025-09-29T00:00:00Z",
                       "final_week_game_ids": ["3"],
                       "official_schedule_snapshot_sha256": SHA,
                       "archive_manifest_sha256": SHA}}


class CheckCTests(unittest.TestCase):
    def test_combined_pass_never_admits(self):
        r = evaluate_check_c({"version": C_VERSION, "alcs_g6": c1(), "sbr_sample": c2()})
        self.assertTrue(r["numeric_c_bar_met_UNVERIFIED"])
        self.assertEqual(r["admission"], "NOT_ADMITTED")
        self.assertFalse(r["eligible"])

    def test_c1_requires_exact_prices_and_line(self):
        for index, field, bad in ((0, "american_price", -157), (1, "american_price", 131),
                                  (2, "line", 1.5)):
            p = c1()
            p["quotes"][index][field] = bad
            self.assertFalse(evaluate_c1(p)["numeric_c1_bar_met_UNVERIFIED"])

    def test_c1_exact_start_is_not_pregame(self):
        p = c1()
        p["quotes"][0]["captured_at_utc"] = p["actual_first_play"]["actual_first_play_utc"]
        self.assertFalse(evaluate_c1(p)["numeric_c1_bar_met_UNVERIFIED"])

    def test_c1_missing_quote_fails(self):
        p = c1()
        p["quotes"].pop()
        self.assertFalse(evaluate_c1(p)["numeric_c1_bar_met_UNVERIFIED"])

    def test_c1_duplicate_wrong_event_wrong_book_refuse(self):
        for kind in ("duplicate", "event", "book"):
            p = c1()
            if kind == "duplicate":
                p["quotes"].append(copy.deepcopy(p["quotes"][0]))
            elif kind == "event":
                p["actual_first_play"]["canonical_event_id"] = "other"
            else:
                p["quotes"][0]["bookmaker"] = "other"
            with self.assertRaises(CheckCRefusal):
                evaluate_c1(p)

    def test_c2_minimum_games(self):
        p = c2()
        p["samples"].pop()
        self.assertFalse(evaluate_c2(p)["numeric_c2_bar_met_UNVERIFIED"])

    def test_c2_four_seasons_required(self):
        p = c2()
        for r in p["samples"]:
            if r["season"] == "2022":
                r["season"] = "2023"
        self.assertFalse(evaluate_c2(p)["numeric_c2_bar_met_UNVERIFIED"])

    def test_c2_ml_97_boundary_missing_in_denominator(self):
        p = c2()
        for r in p["samples"][:6]:
            r["oddspapi_candidate"] = None
        r = evaluate_c2(p)
        self.assertTrue(r["numeric_c2_bar_met_UNVERIFIED"])
        self.assertEqual(r["cohort_comparison_denominator"], 200)
        p["samples"][6]["oddspapi_candidate"] = None
        self.assertFalse(evaluate_c2(p)["numeric_c2_bar_met_UNVERIFIED"])

    def test_c2_line_95_and_99_boundaries(self):
        p = c2("SPREAD")
        for row in p["samples"][:10]:
            row["oddspapi_candidate"]["line"] = 2.0
        for row in p["samples"][:2]:
            row["oddspapi_candidate"]["line"] = 2.5
        self.assertTrue(evaluate_c2(p)["numeric_c2_bar_met_UNVERIFIED"])
        p["samples"][2]["oddspapi_candidate"]["line"] = 2.5
        self.assertFalse(evaluate_c2(p)["numeric_c2_bar_met_UNVERIFIED"])

    def test_c2_no_gap_over_one(self):
        p = c2("TOTAL")
        p["samples"][0]["oddspapi_candidate"]["line"] = 3
        self.assertFalse(evaluate_c2(p)["numeric_c2_bar_met_UNVERIFIED"])

    def test_c2_missing_final_week_counts_failure(self):
        p = c2()
        p["cohort"]["final_week_game_ids"].append("absent")
        r = evaluate_c2(p)
        self.assertEqual(r["cohort_comparison_denominator"], 201)
        self.assertFalse(r["numeric_c2_bar_met_UNVERIFIED"])

    def test_c2_unknown_book_fails(self):
        p = c2()
        p["samples"][0]["sbr_bookmaker"] = None
        self.assertFalse(evaluate_c2(p)["numeric_c2_bar_met_UNVERIFIED"])

    def test_c2_duplicate_and_nba_season_refuse(self):
        for kind in ("duplicate", "season"):
            p = c2()
            if kind == "duplicate":
                p["samples"].append(copy.deepcopy(p["samples"][0]))
            else:
                p["samples"][0]["season"] = "2022-23"
            with self.assertRaises(CheckCRefusal):
                evaluate_c2(p)


if __name__ == "__main__":
    unittest.main()

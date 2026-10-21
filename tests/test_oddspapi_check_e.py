import copy
import unittest
from sportsedge.oddspapi_check_e import VERSION, CheckERefusal, evaluate_check_e


def payload(n=9):
    return {"version": VERSION, "cohort_manifest_sha256": "a" * 64,
            "cells": [{"sport": "NBA", "market": "PTS", "bookmaker": "draftkings",
                       "windows": [{"window_id": "w1", "expected_unit_ids": [str(i) for i in range(10)],
                                    "observed_unit_ids": [str(i) for i in range(n)]}]}]}


class CheckETests(unittest.TestCase):
    def test_exact_ninety_passes_never_admits(self):
        result = evaluate_check_e(payload())
        self.assertTrue(result["cells"][0]["numeric_e_bar_met_UNVERIFIED"])
        self.assertEqual(result["admission"], "NOT_ADMITTED")
        self.assertFalse(result["eligible"])

    def test_below_ninety_fails_and_missing_is_named(self):
        cell = evaluate_check_e(payload(8))["cells"][0]
        self.assertEqual(cell["status"], "FAIL")
        self.assertEqual(cell["windows"][0]["missing_unit_ids"], ["8", "9"])

    def test_no_pooling_across_windows(self):
        p = payload(8)
        w = copy.deepcopy(p["cells"][0]["windows"][0])
        w.update(window_id="w2", observed_unit_ids=w["expected_unit_ids"])
        p["cells"][0]["windows"].append(w)
        self.assertEqual(evaluate_check_e(p)["cells"][0]["status"], "FAIL")

    def test_unsampled_cell_explicit_no_data(self):
        p = payload()
        p["cells"].append({"sport": "MLB", "market": "K", "bookmaker": "draftkings", "windows": []})
        self.assertEqual(evaluate_check_e(p)["cells"][1]["status"], "NO_DATA")

    def test_empty_window_not_perfect_coverage(self):
        p = payload(0)
        p["cells"][0]["windows"][0]["expected_unit_ids"] = []
        self.assertEqual(evaluate_check_e(p)["cells"][0]["status"], "NO_DATA")

    def test_duplicates_and_foreign_units_refused(self):
        for field, values in (("observed_unit_ids", ["0", "0"]),
                              ("expected_unit_ids", ["0", "0"]),
                              ("observed_unit_ids", ["foreign"])):
            p = payload()
            p["cells"][0]["windows"][0][field] = values
            with self.assertRaises(CheckERefusal):
                evaluate_check_e(p)

    def test_duplicate_cell_or_window_refused(self):
        for kind in ("cell", "window"):
            p = payload()
            target = p["cells"] if kind == "cell" else p["cells"][0]["windows"]
            target.append(copy.deepcopy(target[0]))
            with self.assertRaises(CheckERefusal):
                evaluate_check_e(p)

    def test_no_threshold_override_or_empty_universe(self):
        p = payload()
        p["threshold"] = 0
        with self.assertRaises(CheckERefusal):
            evaluate_check_e(p)
        p = payload()
        p["cells"] = []
        with self.assertRaises(CheckERefusal):
            evaluate_check_e(p)


if __name__ == "__main__":
    unittest.main()

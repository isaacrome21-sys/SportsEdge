import copy
import unittest
from sportsedge.oddspapi_check_d_sections import VERSION, CheckDRefusal, evaluate_check_d_sections
from sportsedge.oddspapi_numeric_admission_ad import NumericAdmissionRefusal

SHA = "a" * 64


def payload():
    samples, closes, scan = [], [], []
    for i in range(20):
        event = "g" + str(i)
        anchor = {"canonical_event_id": event, "actual_first_play_utc": "2026-10-21T20:00:00Z",
                  "official_source_sha256": SHA}
        q = {"canonical_event_id": event, "market_id": "TOTAL", "bookmaker": "draftkings",
             "side": "OVER", "line": 8.5, "captured_at_utc": "2026-10-21T19:00:00Z", "source_sha256": SHA}
        dk = {**q, "american_price": -110}
        papi = {**q, "decimal_price": 1.909090909}
        samples.append({"sample_id": "s" + str(i).zfill(2), "dk": dk, "oddspapi": papi})
        closes.append({"canonical_event_id": event, "market_id": "TOTAL", "bookmaker": "draftkings",
                       "provider_created_at_utc": "2026-10-21T19:00:00Z", "candidate_sha256": f"{i:064x}",
                       "actual_first_play": anchor})
        scan.append({"scan_id": "q" + str(i), "quote": copy.deepcopy(papi),
                     "retrieved_at_utc": "2026-10-21T19:01:00Z", "actual_first_play": anchor,
                     "claimed_pregame": True})
    return {"version": VERSION, "cohort_manifest_sha256": SHA,
            "close_candidates": closes, "dk_samples": samples, "quote_scan": scan}


class CheckDTests(unittest.TestCase):
    def test_pass_never_admits_or_replaces_51(self):
        r = evaluate_check_d_sections(payload())
        self.assertTrue(r["numeric_sections_met_UNVERIFIED"])
        self.assertEqual(r["admission"], "NOT_ADMITTED")
        self.assertTrue(r["requires_separate_D_5_1"])

    def test_52_six_hours_inclusive_start_exclusive(self):
        p = payload()
        p["close_candidates"][0]["provider_created_at_utc"] = "2026-10-21T14:00:00Z"
        self.assertEqual(evaluate_check_d_sections(p)["sections"]["5.2"]["in_window"], 20)
        p["close_candidates"][0]["provider_created_at_utc"] = "2026-10-21T20:00:00Z"
        r = evaluate_check_d_sections(p)["sections"]["5.2"]
        self.assertEqual(r["in_window"], 19)
        self.assertTrue(r["numeric_bar_met_UNVERIFIED"])
        # Separate D5.1 still fails at 19/20; 5.2 cannot override it.

    def test_52_exact_95_and_below(self):
        p = payload()
        p["close_candidates"][0]["provider_created_at_utc"] = "2026-10-21T13:59:59Z"
        self.assertTrue(evaluate_check_d_sections(p)["sections"]["5.2"]["numeric_bar_met_UNVERIFIED"])
        p["close_candidates"][1]["provider_created_at_utc"] = "2026-10-21T13:59:59Z"
        self.assertFalse(evaluate_check_d_sections(p)["sections"]["5.2"]["numeric_bar_met_UNVERIFIED"])

    def test_52_missing_anchor_not_dropped(self):
        p = payload()
        p["close_candidates"][0]["actual_first_play"] = None
        r = evaluate_check_d_sections(p)["sections"]["5.2"]
        self.assertEqual((r["denominator"], r["in_window"]), (20, 19))

    def test_53_nine_not_ten(self):
        p = payload()
        p["dk_samples"] = p["dk_samples"][:9]
        self.assertFalse(evaluate_check_d_sections(p)["sections"]["5.3"]["numeric_bar_met_UNVERIFIED"])

    def test_53_same_instant_consistent_nonzero_offset(self):
        p = payload()
        for s in p["dk_samples"]:
            s["dk"]["captured_at_utc"] = "2026-10-21T14:00:00-05:00"
        r = evaluate_check_d_sections(p)["sections"]["5.3"]
        self.assertTrue(r["numeric_bar_met_UNVERIFIED"])
        self.assertEqual(r["single_declared_offset_difference_seconds"], 18000)

    def test_53_inconsistent_offsets_fail(self):
        p = payload()
        p["dk_samples"][0]["dk"]["captured_at_utc"] = "2026-10-21T14:00:00-05:00"
        self.assertFalse(evaluate_check_d_sections(p)["sections"]["5.3"]["numeric_bar_met_UNVERIFIED"])

    def test_53_tightest_selection_deterministic(self):
        p = payload()
        p["dk_samples"] = list(reversed(p["dk_samples"]))
        r = evaluate_check_d_sections(p)["sections"]["5.3"]
        self.assertEqual([s["sample_id"] for s in r["tightest_pairs"]], ["s" + str(i).zfill(2) for i in range(10)])

    def test_53_wrong_fixture_excluded_not_substituted(self):
        p = payload()
        p["dk_samples"] = p["dk_samples"][:10]
        p["dk_samples"][0]["oddspapi"]["canonical_event_id"] = "other"
        self.assertFalse(evaluate_check_d_sections(p)["sections"]["5.3"]["numeric_bar_met_UNVERIFIED"])

    def test_54_invalid_prices_retained_as_failures(self):
        for bad in (1, 0, -2, "NaN", "Infinity", True):
            p = payload()
            p["quote_scan"][0]["quote"]["decimal_price"] = bad
            r = evaluate_check_d_sections(p)["sections"]["5.4"]
            self.assertEqual((r["scanned"], r["failed"]), (20, 1))

    def test_54_future_and_poststart_quotes_fail(self):
        p = payload()
        p["quote_scan"][0]["quote"]["captured_at_utc"] = "2026-10-21T20:00:00Z"
        r = evaluate_check_d_sections(p)["sections"]["5.4"]
        self.assertEqual(set(r["rows"][0]["reasons"]), {"D_QUOTE_AFTER_RETRIEVAL", "D_POST_START_QUOTE_CLAIMED_PREGAME"})

    def test_54_conflicting_same_time_prices_fail(self):
        p = payload()
        q = copy.deepcopy(p["quote_scan"][0])
        q["scan_id"] = "other"
        q["quote"]["decimal_price"] = 2.2
        p["quote_scan"].append(q)
        self.assertFalse(evaluate_check_d_sections(p)["sections"]["5.4"]["numeric_bar_met_UNVERIFIED"])

    def test_duplicate_closes_and_pairs_refuse(self):
        for key in ("close_candidates", "dk_samples"):
            p = payload()
            row = copy.deepcopy(p[key][0])
            if key == "dk_samples":
                row["sample_id"] = "alias"
            else:
                row["candidate_sha256"] = "f" * 64
            p[key].append(row)
            with self.assertRaises(CheckDRefusal):
                evaluate_check_d_sections(p)

    def test_empty_arrays_never_pass(self):
        p = payload()
        for key in ("close_candidates", "dk_samples", "quote_scan"):
            p[key] = []
        self.assertFalse(evaluate_check_d_sections(p)["numeric_sections_met_UNVERIFIED"])

    def test_naive_timestamps_not_guessed(self):
        p = payload()
        p["dk_samples"][0]["dk"]["captured_at_utc"] = "2026-10-21T19:00:00"
        with self.assertRaises(NumericAdmissionRefusal):
            evaluate_check_d_sections(p)


if __name__ == "__main__":
    unittest.main()

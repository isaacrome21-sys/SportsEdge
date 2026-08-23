import unittest

from sportsedge.behavioral_acceptance import BehavioralAcceptanceError, analyze_challenger


class BehavioralAcceptanceTests(unittest.TestCase):
    def test_reports_mae_improvement_support_and_monotonicity(self):
        rows = [
            {"market": "BATTER_K", "line": 0.5, "side": "OVER", "expected_count": 0.7,
             "reference_p": 0.50, "incumbent_p": 0.46, "challenger_p": 0.49, "support_violation_p": 0.0},
            {"market": "BATTER_K", "line": 0.5, "side": "OVER", "expected_count": 1.0,
             "reference_p": 0.66, "incumbent_p": 0.612, "challenger_p": 0.655, "support_violation_p": 0.0},
        ]
        out = analyze_challenger(rows)
        self.assertGreater(out["mae_improvement"], 0.0)
        self.assertEqual(out["improved_rows"], 2)
        self.assertEqual(out["worsened_rows"], 0)
        self.assertEqual(out["max_support_violation_p"], 0.0)
        self.assertEqual(out["challenger_monotonicity_violations"], 0)

    def test_detects_adjacent_line_error_sign_reversal(self):
        rows = [
            {"market": "SINGLES", "line": 0.5, "side": "OVER", "expected_count": 0.9,
             "reference_p": 0.60, "incumbent_p": 0.56, "challenger_p": 0.595},
            {"market": "SINGLES", "line": 1.5, "side": "OVER", "expected_count": 0.9,
             "reference_p": 0.20, "incumbent_p": 0.23, "challenger_p": 0.205},
        ]
        out = analyze_challenger(rows)
        self.assertEqual(out["incumbent_adjacent_line_sign_reversals"], 1)
        self.assertEqual(out["challenger_adjacent_line_sign_reversals"], 1)

    def test_detects_challenger_monotonicity_failure(self):
        rows = [
            {"market": "BATTER_BB", "line": 0.5, "side": "OVER", "expected_count": 0.4,
             "reference_p": 0.30, "incumbent_p": 0.31, "challenger_p": 0.35},
            {"market": "BATTER_BB", "line": 0.5, "side": "OVER", "expected_count": 0.8,
             "reference_p": 0.50, "incumbent_p": 0.49, "challenger_p": 0.34},
        ]
        out = analyze_challenger(rows)
        self.assertEqual(out["challenger_monotonicity_violations"], 1)

    def test_rejects_invalid_probability(self):
        with self.assertRaises(BehavioralAcceptanceError):
            analyze_challenger([{
                "market": "TRIPLES", "line": 0.5, "side": "OVER",
                "reference_p": 1.2, "incumbent_p": 0.1, "challenger_p": 0.1,
            }])

    def test_does_not_invent_promotion_threshold(self):
        out = analyze_challenger([{
            "market": "DOUBLES", "line": 0.5, "side": "OVER", "expected_count": 0.3,
            "reference_p": 0.20, "incumbent_p": 0.208, "challenger_p": 0.201,
        }])
        self.assertNotIn("pass", out)
        self.assertNotIn("promote", out)


if __name__ == "__main__":
    unittest.main()

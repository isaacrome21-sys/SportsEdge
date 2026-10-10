import unittest

from scripts.audit_cfb_sdv_total_bias import audit, SCHEMA


def card(gaps, *, anomalous=True):
    results = []
    for i, gap in enumerate(gaps):
        line = 45.5
        model = line + gap
        results.extend([
            {
                "matchup": f"Away {i} @ Home {i}", "market": "TOTAL",
                "side": "OVER", "line": line, "home_mean": model / 2,
                "away_mean": model / 2, "edge": 0.15 if gap >= 0 else -0.15,
                "bet_status": "PASS",
                "reason": "EDGE_TOO_LARGE_SUSPECT" if anomalous else "BELOW_FLOOR",
                "devig": "PAIRED_PROPORTIONAL",
            },
            {
                "matchup": f"Away {i} @ Home {i}", "market": "TOTAL",
                "side": "UNDER", "line": line, "home_mean": model / 2,
                "away_mean": model / 2, "edge": -0.15 if gap >= 0 else 0.15,
                "bet_status": "PASS", "reason": "BELOW_FLOOR",
                "devig": "PAIRED_PROPORTIONAL",
            },
        ])
    return {
        "schema": "CFB_SDV_CARD_V2",
        "model_status": "MODEL_SDV_PUBLIC_LIVE_UNVALIDATED",
        "live_source_provenance": {
            "capture_time": "2026-10-10T00:16:08Z",
            "source_contract": "CFB_SDV_PUBLIC_PROSPECTIVE_2026_V1",
        },
        "results": results,
    }


class TotalsBiasAuditTest(unittest.TestCase):
    def test_four_same_direction_large_disagreements_flag_research(self):
        out = audit(card([6.0, 8.0, 5.5, 9.0]))
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["games_with_paired_totals"], 4)
        self.assertEqual(out["directional_bias_signal"], "MODEL_HIGH")
        self.assertEqual(out["mean_model_minus_market_points"], 7.12)
        self.assertTrue(out["research_review_required"])
        self.assertFalse(out["authority"]["bets_created"])

    def test_mixed_directions_do_not_flag(self):
        out = audit(card([7, -8, 6]))
        self.assertEqual(out["directional_bias_signal"], "NONE")
        self.assertFalse(out["research_review_required"])

    def test_insufficient_games_not_flagged(self):
        out = audit(card([7, 8]))
        self.assertEqual(out["directional_bias_signal"], "NONE")

    def test_anomalies_must_all_be_rejected_to_flag_review(self):
        out = audit(card([7, 8, 6], anomalous=False))
        self.assertEqual(out["directional_bias_signal"], "MODEL_HIGH")
        self.assertFalse(out["research_review_required"])

    def test_unpaired_totals_are_not_audited_as_market_edges(self):
        source = card([7, 8, 9])
        for row in source["results"]:
            row["devig"] = "UNPAIRED_RAW_IMPLIED"
        out = audit(source)
        self.assertEqual(out["games_with_paired_totals"], 0)
        self.assertFalse(out["research_review_required"])

    def test_sign_test_flags_slate_skew_when_one_game_is_near_line(self):
        # 10 of 13 above the line (one-sided p ~= 0.046), not all beyond 5 pts.
        gaps = [14.1, 14.3, 11.7, 7.5, 5.5, 4.1, 1.5, 1.9, 0.9, 0.6, -2.6, -0.3, -0.2]
        out = audit(card(gaps, anomalous=False))
        self.assertEqual(out["model_above_market"], 10)
        self.assertLess(out["sign_test_p_model_high"], 0.05)
        self.assertEqual(out["directional_bias_signal"], "MODEL_HIGH")
        self.assertFalse(out["research_review_required"])
        self.assertFalse(out["authority"]["bets_created"])

    def test_sign_test_needs_minimum_games(self):
        out = audit(card([1, 2, 3, 4, -1], anomalous=False))
        self.assertEqual(out["directional_bias_signal"], "NONE")

    def test_balanced_slate_not_flagged_by_sign_test(self):
        out = audit(card([3, -3, 2, -2, 4, -4, 1, -1, 2, -2], anomalous=False))
        self.assertEqual(out["directional_bias_signal"], "NONE")

    def test_sign_test_flags_model_low(self):
        out = audit(card([-2, -3, -1, -4, -2, -6, -1, -3, -2], anomalous=False))
        self.assertEqual(out["directional_bias_signal"], "MODEL_LOW")

    def test_duplicates_fail_closed(self):
        source = card([7, 8, 9])
        source["results"].append(dict(source["results"][0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_TOTAL"):
            audit(source)


if __name__ == "__main__":
    unittest.main()

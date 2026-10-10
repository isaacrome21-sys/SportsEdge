import copy
import unittest

from scripts.research_cfb_total_offset_shadow import (
    shadow_card, shadow_adjusted_means, over_probability,
)


def calibration():
    return {"schema": "CFB_TOTAL_OFFSET_CHRONO_RESEARCH_V1",
            "evidence_class": "RETROSPECTIVE_RESEARCH_ONLY",
            "offset_points": -2.5,
            "calibration_applied_in_production": False,
            "positive_ev_proven": False, "staking_authority": False}


def card():
    rows = [{"game_id": "g", "matchup": "Away @ Home", "market": "TOTAL",
             "side": side, "line": 45.5, "home_mean": 27.0, "away_mean": 25.0,
             "model_p": 0.65 if side == "OVER" else 0.35,
             "devig": "PAIRED_PROPORTIONAL", "bet_status": "PASS"}
            for side in ("OVER", "UNDER")]
    return {"schema": "CFB_SDV_CARD_V2",
            "model_status": "MODEL_SDV_PUBLIC_LIVE_UNVALIDATED",
            "combined_sigma": 17.0, "results": rows, "bets": 0}


class TotalsShadowTest(unittest.TestCase):
    def test_offset_changes_total_before_probability_not_spread_or_production(self):
        src = card()
        orig = copy.deepcopy(src)
        out = shadow_card(src, calibration())
        row = out["games"][0]
        self.assertEqual(src, orig)
        self.assertEqual(out["bet_count"], 0)
        self.assertFalse(out["bets_enabled"])
        self.assertEqual(row["original_model_total"], 52.0)
        self.assertEqual(row["shadow_model_total"], 49.5)
        self.assertEqual(row["original_model_margin"], row["shadow_model_margin"])
        self.assertLess(row["shadow_over_p"], row["original_over_p"])
        self.assertEqual(row["disposition"], "RESEARCH_ONLY_NO_BET")

    def test_requires_research_offset_not_unearned_authority(self):
        for change in ("calibration_applied_in_production", "positive_ev_proven", "staking_authority"):
            cal = calibration()
            cal[change] = True
            with self.assertRaisesRegex(ValueError, "RESEARCH_ONLY_REQUIRED"):
                shadow_card(card(), cal)
        cal = calibration()
        cal["offset_points"] = -17
        with self.assertRaisesRegex(ValueError, "SUSPECT"):
            shadow_card(card(), cal)

    def test_rejects_bad_and_unpaired_totals(self):
        c = card()
        c["results"] = c["results"][:1]
        with self.assertRaisesRegex(ValueError, "UNIQUE_OPPOSITES"):
            shadow_card(c, calibration())
        c = card()
        c["results"][1]["line"] = 46.5
        with self.assertRaisesRegex(ValueError, "LINE_MISMATCH"):
            shadow_card(c, calibration())
        c = card()
        c["results"][1]["home_mean"] = 36
        with self.assertRaisesRegex(ValueError, "SCORE_MISMATCH"):
            shadow_card(c, calibration())

    def test_symmetry_and_sigma_guard(self):
        self.assertEqual(shadow_adjusted_means(28, 21, -2), (27, 20))
        self.assertAlmostEqual(over_probability(50, 50, 17), .5)
        with self.assertRaisesRegex(ValueError, "SIGMA_INVALID"):
            over_probability(50, 50, 0)


if __name__ == "__main__":
    unittest.main()

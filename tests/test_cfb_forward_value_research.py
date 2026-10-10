"""Regression tests: forward CFB grading cannot use hindsight or promote bets."""
import unittest

from scripts.export_cfb_sdv_forward_snapshot import export_snapshot
from scripts.grade_cfb_sdv_forward_value import evaluate
from tests.test_cfb_sdv_forward_snapshot import card

SHA = "a" * 64


def fixture():
    inp = card()
    inp["results"].append({
        "game_id": "123", "matchup": "Away @ Home",
        "market": "TOTAL", "side": "UNDER", "line": 48.5,
        "home_mean": 28, "away_mean": 22, "start_ts": "2026-10-10T01:00:00Z"
    })
    for row in inp["results"]:
        recommended = row["side"] in {"HOME", "OVER"}
        p = 0.57 if recommended else 0.43
        row.update({
            "american_odds": -110,
            "model_p": p,
            "market_p": 0.5,
            "devig": "PAIRED_PROPORTIONAL",
            "bet_status": "LEAN" if recommended else "PASS",
        })
    return export_snapshot(inp, original_card_sha256=SHA)


def result(home=31, away=20):
    return {
        "game_id": "123", "home_points": home, "away_points": away,
        "kickoff_at": "2026-10-10T01:00:00Z",
        "settled_at": "2026-10-10T05:00:00Z",
        "source_sha256": "b" * 64,
    }


class ForwardValueResearchTest(unittest.TestCase):
    def test_predeclared_spread_total_win_and_no_bet_authority(self):
        report = evaluate([fixture()], [result()])
        self.assertEqual(report["markets"]["SPREAD"]["wins"], 1)
        self.assertEqual(report["markets"]["TOTAL"]["wins"], 1)
        self.assertAlmostEqual(report["markets"]["SPREAD"]["realized_roi_per_unit"], 100/110, places=4)
        self.assertFalse(report["positive_ev_proven"])
        self.assertFalse(report["sportsbook_price_receipt_verified"])
        self.assertFalse(report["bets_enabled"])

    def test_spread_push_and_total_loss(self):
        report = evaluate([fixture()], [result(home=17, away=24)])
        self.assertEqual(report["markets"]["SPREAD"]["losses"], 1)
        self.assertEqual(report["markets"]["TOTAL"]["losses"], 1)

    def test_unsettled_game_is_pending_not_a_winner(self):
        report = evaluate([fixture()], [])
        self.assertEqual(report["markets"]["SPREAD"]["pending_count"], 1)
        self.assertEqual(report["markets"]["SPREAD"]["settled_count"], 0)
        self.assertIsNone(report["markets"]["TOTAL"]["realized_roi_per_unit"])

    def test_late_prediction_rejected(self):
        snap = fixture()
        snap["games"][0]["scored_at"] = "2026-10-10T01:00:00Z"
        with self.assertRaisesRegex(ValueError, "CFB_VALUE_FORECAST_NOT_PREGAME"):
            evaluate([snap], [result()])

    def test_result_before_kickoff_rejected(self):
        r = result()
        r["settled_at"] = "2026-10-10T00:30:00Z"
        with self.assertRaisesRegex(ValueError, "CFB_VALUE_RESULT_NOT_AFTER_KICKOFF"):
            evaluate([fixture()], [r])

    def test_no_duplicate_game_cherry_picking(self):
        snap = fixture()
        with self.assertRaisesRegex(ValueError, "CFB_VALUE_GAME_DUPLICATE_OR_MISSING"):
            evaluate([snap, snap], [result()])

    def test_unpaired_and_expensive_quotes_never_selected(self):
        snap = fixture()
        quotes = snap["games"][0]["quoted_selections"]
        for q in quotes:
            q["devig"] = "UNPAIRED_RAW_IMPLIED"
        self.assertEqual(evaluate([snap], [result()])["markets"]["SPREAD"]["settled_count"], 0)
        snap = fixture()
        for q in snap["games"][0]["quoted_selections"]:
            q["american_odds"] = -180
            q["expected_roi_unvalidated"] = round(q["model_p"] * (1 + 100/180) - 1, 6)
        self.assertEqual(evaluate([snap], [result()])["markets"]["TOTAL"]["settled_count"], 0)

    def test_probability_or_ev_tamper_fails_closed(self):
        snap = fixture()
        snap["games"][0]["quoted_selections"][0]["expected_roi_unvalidated"] = 8.0
        with self.assertRaisesRegex(ValueError, "CFB_VALUE_EXPECTED_ROI_TAMPERED"):
            evaluate([snap], [result()])

    def test_settlement_receipt_and_identity_required(self):
        r = result()
        r["source_sha256"] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "CFB_VALUE_SHA256_INVALID"):
            evaluate([fixture()], [r])
        r = result()
        r["kickoff_at"] = "2026-10-10T02:00:00Z"
        with self.assertRaisesRegex(ValueError, "CFB_VALUE_KICKOFF_IDENTITY_MISMATCH"):
            evaluate([fixture()], [r])



    def test_integer_total_uses_archived_push_mass_and_settles_as_push(self):
        from tests.test_cfb_sdv_forward_snapshot import card
        inp = card()
        inp["results"].append({
            "game_id": "123", "matchup": "Away @ Home",
            "market": "TOTAL", "side": "UNDER", "line": 48.0,
            "home_mean": 28, "away_mean": 22, "start_ts": "2026-10-10T01:00:00Z"
        })
        for row in inp["results"]:
            if row["market"] == "TOTAL":
                row["line"] = 48.0
            recommended = row["side"] in {"HOME", "OVER"}
            row.update({
                "american_odds": -110,
                "model_p": 0.57 if recommended else 0.43,
                "market_p": 0.5,
                "model_push_p": 0.03 if row["market"] == "TOTAL" else 0.0,
                "devig": "PAIRED_PROPORTIONAL",
                "bet_status": "LEAN" if recommended else "PASS",
            })
        snap = export_snapshot(inp, original_card_sha256=SHA)
        total = [q for q in snap["games"][0]["quoted_selections"]
                 if q["market"] == "TOTAL" and q["side"] == "OVER"][0]
        expected = (1-.03) * (.57 * (1 + 100/110) - 1)
        self.assertAlmostEqual(total["expected_roi_unvalidated"], expected, places=5)
        report = evaluate([snap], [result(home=28, away=20)])
        self.assertEqual(report["markets"]["TOTAL"]["pushes"], 1)
        self.assertEqual(report["markets"]["TOTAL"]["realized_roi_per_unit"], 0.0)
        self.assertEqual(report["markets"]["TOTAL"]["records"][0]["model_push_p_unvalidated"], .03)
        self.assertFalse(report["positive_ev_proven"])

    def test_legacy_integer_total_without_push_mass_cannot_look_profitable(self):
        snap = fixture()
        for q in snap["games"][0]["quoted_selections"]:
            if q["market"] == "TOTAL":
                q["line"] = 48.0
        report = evaluate([snap], [result(home=28, away=20)])
        self.assertEqual(report["markets"]["TOTAL"]["settled_count"], 0)
        self.assertEqual(report["markets"]["SPREAD"]["settled_count"], 1)

    def test_illinois_college_excluded_from_forward_shadow(self):
        snap = fixture()
        snap["games"][0]["matchup"] = "Northern Illinois @ Home"
        report = evaluate([snap], [result()])
        self.assertEqual(report["markets"]["TOTAL"]["settled_count"], 0)
        self.assertEqual(report["markets"]["SPREAD"]["settled_count"], 0)

    def test_negative_push_mass_and_missing_conditional_basis_rejected(self):
        inp = card()
        inp["results"][0]["model_push_p"] = -0.1
        inp["results"][0].update({
            "american_odds": -110, "model_p": .55, "market_p": .5,
            "devig": "PAIRED_PROPORTIONAL", "bet_status": "LEAN"
        })
        with self.assertRaisesRegex(ValueError, "QUOTE_PUSH_INVALID"):
            export_snapshot(inp, original_card_sha256=SHA)
        snap = fixture()
        q = snap["games"][0]["quoted_selections"][0]
        q["model_prob_basis"] = "CONDITIONAL_WIN_GIVEN_NO_PUSH"
        with self.assertRaisesRegex(ValueError, "PUSH_BASIS_MISSING"):
            evaluate([snap], [result()])


if __name__ == "__main__":
    unittest.main()

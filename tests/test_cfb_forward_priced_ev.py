import copy
import unittest

from scripts.export_cfb_sdv_forward_snapshot import export_snapshot
from scripts.research_cfb_forward_priced_ev import (
    evaluate, outcome_probs, payout, raw_implied
)

HASH = "a" * 64


def card():
    return {
        "schema": "CFB_SDV_CARD_V2",
        "model_status": "MODEL_SDV_PUBLIC_LIVE_UNVALIDATED",
        "scored_at_utc": "2026-10-10T00:00:00Z",
        "combined_sigma": 17.0,
        "live_source_provenance": {
            "capture_time": "2026-10-09T23:55:00Z",
            "source_contract": "CFB_SDV_PUBLIC_PROSPECTIVE_2026_V1",
            "file_sha256": {f"asset_{i}.csv": f"{i + 1:x}" * 64 for i in range(8)},
        },
        "validated_markets": [], "bets": 0,
        "results": [
            {
                "game_id": "123", "matchup": "Away @ Home",
                "market": "TOTAL", "side": side, "line": 49.5,
                "american_odds": -110, "model_p": .55 if side == "OVER" else .45,
                "devig": "PAIRED_PROPORTIONAL",
                "home_mean": 27.0, "away_mean": 25.0,
                "start_ts": "2026-10-10T02:00:00Z",
                "bet_status": "PASS", "reason": "EDGE_TOO_LARGE_SUSPECT",
            } for side in ("OVER", "UNDER")
        ]
    }


def outcome(home=27, away=23):
    return {"game_id": "123", "home_points": home, "away_points": away,
            "status": "FINAL", "final_at": "2026-10-10T06:00:00Z",
            "outcome_source_sha256": "f" * 64}


def snap():
    return export_snapshot(card(), original_card_sha256=HASH)


class ForwardPricedEVTest(unittest.TestCase):
    def test_price_receipt_retained_without_fabricating_attestation(self):
        src = card()
        frozen = copy.deepcopy(src)
        snapshot = export_snapshot(src, original_card_sha256=HASH)
        self.assertEqual(src, frozen)
        self.assertEqual(snapshot["source_card_sha256"], HASH)
        self.assertFalse(snapshot["sportsbook_price_receipt_verified"])
        self.assertEqual(snapshot["combined_sigma"], 17.0)
        quotes = snapshot["games"][0]["paired_decision_quotes"]
        self.assertEqual({q["side"] for q in quotes}, {"OVER", "UNDER"})
        self.assertEqual({q["american_odds"] for q in quotes}, {-110})
        self.assertEqual(snapshot["games"][0]["decision_quote_captured_at_independently"], None)
        self.assertFalse(snapshot["games"][0]["decision_book_verified"])

    def test_pregame_shadow_choice_unchanged_after_settlement(self):
        snapshot = snap()
        before = evaluate(snapshot)
        after = evaluate(snapshot, [outcome()])
        self.assertEqual(before["shadow_candidates"], 1)
        self.assertEqual(after["settled_shadow_candidates"], 1)
        self.assertEqual(before["shadow_candidates"], after["shadow_candidates"])
        selected = [r for r in after["results"] if r["shadow_selected_before_settlement"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["side"], "OVER")
        self.assertEqual(selected[0]["result"], "WIN")
        self.assertAlmostEqual(after["settled_shadow_net_units"], 100 / 110, places=4)
        self.assertTrue(all(r["disposition"] == "SHADOW_RESEARCH_ONLY_NO_WAGER"
                            for r in after["results"]))
        self.assertFalse(after["bets_enabled"])
        self.assertFalse(after["real_positive_ev_proven"])

    def test_push_mass_at_integer_total_and_push_settlement(self):
        win, lose, push = outcome_probs(52.0, 17, "TOTAL", "OVER", 50.0)
        self.assertGreater(push, .02)
        self.assertAlmostEqual(win + lose + push, 1.0)
        win2, lose2, push2 = outcome_probs(52.0, 17, "TOTAL", "OVER", 50.5)
        self.assertEqual(push2, 0)
        self.assertAlmostEqual(win2 + lose2, 1.0)
        source = card()
        for r in source["results"]:
            r["line"] = 50.0
        snap_ = export_snapshot(source, original_card_sha256=HASH)
        grade = evaluate(snap_, [outcome(home=27, away=23)])
        selected = [r for r in grade["results"] if r["shadow_selected_before_settlement"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["result"], "PUSH")
        self.assertEqual(grade["settled_shadow_net_units"], 0)

    def test_nonpositive_price_ev_not_salvaged_by_devig_edge(self):
        # Book fair = .5, model p= .53: +3pp "edge" but at -110 ROI < 0.
        p = .53
        self.assertGreater(p - .5, .02)
        self.assertLess(p * payout(-110) - (1 - p), 0)
        self.assertAlmostEqual(raw_implied(-110), 110 / 210)

    def test_duplicate_outcomes_late_timestamp_and_tampering_rejected(self):
        before = snap()
        with self.assertRaisesRegex(ValueError, "SETTLEMENT_DUPLICATE"):
            evaluate(before, [outcome(), outcome()])
        after = outcome()
        after["final_at"] = "2026-10-09T23:59:59Z"
        with self.assertRaisesRegex(ValueError, "FINAL_BEFORE_KICKOFF"):
            evaluate(before, [after])
        tampered = copy.deepcopy(before)
        tampered["games"][0]["quote_source_card_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "SOURCE_CARD_HASH"):
            evaluate(tampered)

    def test_unpaired_quoted_side_never_generates_decision(self):
        source = card()
        source["results"] = source["results"][:1]
        snapshot = export_snapshot(source, original_card_sha256=HASH)
        self.assertEqual(snapshot["games"][0]["paired_decision_quotes"], [])
        report = evaluate(snapshot)
        self.assertEqual(report["shadow_candidates"], 0)

    def test_minus_165_cap_and_illinois_restriction(self):
        source = card()
        for r in source["results"]:
            r["american_odds"] = -166
        report = evaluate(export_snapshot(source, original_card_sha256=HASH))
        self.assertFalse(any(r["shadow_rule_eligible"] for r in report["results"]))
        source = card()
        for r in source["results"]:
            r["matchup"] = "Northern Illinois @ Home"
        report = evaluate(export_snapshot(source, original_card_sha256=HASH))
        self.assertTrue(all(r["illinois_college_excluded"] for r in report["results"]))
        self.assertEqual(report["shadow_candidates"], 0)

    def test_model_provenance_and_chronology_fail_closed(self):
        source = snap()
        source["games"][0]["scored_at"] = "2026-10-10T03:00:00Z"
        with self.assertRaisesRegex(ValueError, "NOT_PREGAME"):
            evaluate(source)
        source = snap()
        source["source_model_status"] = "MARKET_ONLY:CFBD_RATE_LIMITED"
        with self.assertRaisesRegex(ValueError, "NATIVE_MODEL_REQUIRED"):
            evaluate(source)
        source = snap()
        source["bets_enabled"] = True
        with self.assertRaisesRegex(ValueError, "AUTHORITY_INVALID"):
            evaluate(source)

    def test_original_market_side_and_total_symmetry(self):
        w, l, p = outcome_probs(52, 17, "TOTAL", "OVER", 49.5)
        w2, l2, p2 = outcome_probs(52, 17, "TOTAL", "UNDER", 49.5)
        self.assertAlmostEqual(w, l2)
        self.assertAlmostEqual(w2, l)
        self.assertEqual(p, 0)
        self.assertEqual(p2, 0)
        hw, hl, hp = outcome_probs(4, 17, "SPREAD", "HOME", -3)
        aw, al, ap = outcome_probs(4, 17, "SPREAD", "AWAY", 3)
        self.assertAlmostEqual(hw, al)
        self.assertAlmostEqual(hl, aw)
        self.assertAlmostEqual(hp, ap)


if __name__ == "__main__":
    unittest.main()

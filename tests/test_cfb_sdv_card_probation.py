"""Probation overlay: capped 0.25u tracking of LEANs, never BET/OFFICIAL, bias-guarded."""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cfb_card_v2_probation", ROOT / "scripts" / "run_cfb_sdv_card_v2.py")
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)
V2 = ROOT / "config" / "cfb_probation_policy_v2.json"  # legacy v2 behaviour stays pinned here; v3 has its own test


def row(matchup, market, side, edge, status="LEAN", odds=-110, devig="PAIRED_PROPORTIONAL"):
    return {"matchup": matchup, "market": market, "side": side, "line": 50.5, "edge": edge,
            "expected_roi": edge, "bet_status": status, "american_odds": odds, "devig": devig,
            "model_p": 0.5 + edge, "market_p": 0.5}


def payload(rows, status="MODEL_SDV_PUBLIC_LIVE_UNVALIDATED"):
    return {"schema": "CFB_SDV_CARD_V2", "model_status": status, "results": rows}


class ProbationTest(unittest.TestCase):
    def run_with(self, p, signal):
        with mock.patch.object(card, "_slate_total_bias_signal", return_value=signal):
            return card.apply_probation(p, V2)

    def test_high_bias_blocks_overs_keeps_unders(self):
        p = self.run_with(payload([row("A @ B", "TOTAL", "OVER", .10), row("C @ D", "TOTAL", "UNDER", .05)]), "MODEL_HIGH")
        over, under = p["results"]
        self.assertFalse(over["probation"])
        self.assertTrue(over["probation_block_reason"].startswith("TOTAL_IN_DIRECTION_OF_SLATE_BIAS"))
        self.assertTrue(under["probation"])
        self.assertEqual(under["stake_units"], 0.25)
        self.assertEqual(under["bet_status"], "LEAN")  # grading keys on LEAN; never upgraded to BET
        self.assertEqual(p["probation"]["count"], 1)
        self.assertFalse(p["probation"]["official"])

    def test_low_bias_blocks_unders(self):
        p = self.run_with(payload([row("A @ B", "TOTAL", "UNDER", .05)]), "MODEL_LOW")
        self.assertFalse(p["results"][0]["probation"])

    def test_unavailable_audit_blocks_totals_not_spreads(self):
        p = self.run_with(payload([row("A @ B", "TOTAL", "UNDER", .05), row("A @ B", "SPREAD", "HOME", .03)]), "UNAVAILABLE")
        self.assertFalse(p["results"][0]["probation"])
        self.assertTrue(p["results"][1]["probation"])

    def test_market_only_never_probation(self):
        p = self.run_with(payload([row("A @ B", "SPREAD", "HOME", .05)], status="MARKET_ONLY:CFBD_RATE_LIMITED"), "NONE")
        self.assertFalse(p["results"][0]["probation"])
        self.assertEqual(p["probation"]["count"], 0)

    def test_non_lean_rows_untouched(self):
        rows = [row("A @ B", "TOTAL", "UNDER", .2, status="PASS"), row("C @ D", "TOTAL", "UNDER", .01, status="TRACK")]
        p = self.run_with(payload(rows), "NONE")
        self.assertTrue(all("probation" not in r for r in p["results"]))

    def test_price_cap_and_pairing_enforced(self):
        rows = [row("A @ B", "SPREAD", "HOME", .05, odds=-170), row("C @ D", "SPREAD", "HOME", .05, devig="UNPAIRED_RAW_IMPLIED")]
        p = self.run_with(payload(rows), "NONE")
        self.assertEqual(p["probation"]["count"], 0)

    def test_per_market_cap_does_not_let_totals_fill_all_eight_slots(self):
        rows = ([row(f"Total{i} @ Home{i}", "TOTAL", "UNDER", .30 - i / 100) for i in range(10)]
                + [row(f"Spread{i} @ Away{i}", "SPREAD", "HOME", .15 - i / 100) for i in range(6)])
        p = self.run_with(payload(rows), "NONE")
        chosen = [r for r in p["results"] if r["probation"]]
        self.assertEqual(len(chosen), 8)
        self.assertEqual(sum(r["market"] == "TOTAL" for r in chosen), 5)
        self.assertEqual(sum(r["market"] == "SPREAD" for r in chosen), 3)
        self.assertEqual(p["probation"]["counts_by_market"]["TOTAL"], 5)
        self.assertEqual(p["probation"]["max_probation_per_slate"], 8)
        self.assertEqual(p["probation"]["max_probation_per_market"]["TOTAL"], 5)
        self.assertTrue(any(r.get("probation_block_reason") == "MARKET_TYPE_CAP" for r in p["results"]))
        self.assertTrue(all(r["bet_status"] == "LEAN" for r in chosen))

    def test_slate_cap_keeps_top_edges_across_markets(self):
        rows = ([row(f"Spread{i} @ A{i}", "SPREAD", "HOME", .09 - i / 100) for i in range(4)]
                + [row(f"Total{i} @ B{i}", "TOTAL", "UNDER", .12 - i / 100) for i in range(4)]
                + [row(f"Money{i} @ C{i}", "MONEYLINE", "HOME", .04 - i / 100) for i in range(4)])
        p = self.run_with(payload(rows), "NONE")
        self.assertEqual(sum(bool(r["probation"]) for r in p["results"]), 8)
        self.assertTrue(any(r.get("probation_block_reason") == "SLATE_CAP" for r in p["results"]))
        self.assertTrue(all(r.get("stake_units") == .25 for r in p["results"] if r["probation"]))
        self.assertFalse(p["probation"]["official"])

    def test_policy_hash_recorded(self):
        p = self.run_with(payload([]), "NONE")
        self.assertEqual(len(p["probation"]["policy_sha256"]), 64)
        self.assertEqual(p["probation"]["policy"], "CFB_PROBATION_POLICY_V2")
        import hashlib
        self.assertEqual(p["probation"]["policy_sha256"], hashlib.sha256(V2.read_bytes()).hexdigest())

    def test_v2_keeps_v1_kill_and_promotion_rules(self):
        import json
        old = json.loads((ROOT / "config/cfb_probation_policy_v1.json").read_text())
        new = json.loads((ROOT / "config/cfb_probation_policy_v2.json").read_text())
        self.assertEqual(new["kill_rule"], old["kill_rule"])
        self.assertEqual(new["promotion_rule"], old["promotion_rule"])
        self.assertEqual(new["stake_units"], old["stake_units"])
        self.assertEqual(new["never"], old["never"])

    def test_real_audit_wiring(self):
        rows = []
        for i in range(10):
            for side, e in (("OVER", .05), ("UNDER", -.05)):
                rows.append({"matchup": f"G{i} @ H{i}", "market": "TOTAL", "side": side, "line": 45.5,
                             "home_mean": 26.0, "away_mean": 26.0, "edge": e, "expected_roi": e,
                             "bet_status": "LEAN" if side == "OVER" else "PASS", "american_odds": -110,
                             "devig": "PAIRED_PROPORTIONAL", "reason": "X"})
        p = card.apply_probation(payload(rows), V2)
        self.assertEqual(p["probation"]["slate_total_bias_signal"], "MODEL_HIGH")
        self.assertEqual(p["probation"]["count"], 0)


if __name__ == "__main__":
    unittest.main()

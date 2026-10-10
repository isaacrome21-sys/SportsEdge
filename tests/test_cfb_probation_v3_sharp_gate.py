"""Probation v3: totals removed, model-edge sanity cap, DK must beat sharp no-vig fair."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cfb_card_v3_probation", ROOT / "scripts" / "run_cfb_sdv_card_v2.py")
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)


def row(market, side, edge, sharp=None, odds=-110):
    r = {"matchup": f"{market}{side}{edge}", "market": market, "side": side, "line": -3.5, "edge": edge,
         "expected_roi": edge, "bet_status": "LEAN", "american_odds": odds, "devig": "PAIRED_PROPORTIONAL"}
    if sharp is not None:
        r["sharp_fair_p"] = sharp
    return r


def run(rows):
    p = {"schema": "CFB_SDV_CARD_V2", "model_status": "MODEL_SDV_PUBLIC_LIVE_UNVALIDATED", "results": rows}
    with mock.patch.object(card, "_slate_total_bias_signal", return_value="NONE"):
        return card.apply_probation(p)


class V3Test(unittest.TestCase):
    def test_default_is_v3(self):
        self.assertEqual(json.loads(card.PROBATION_POLICY_PATH.read_text())["schema"], "CFB_PROBATION_POLICY_V3")

    def test_totals_never_eligible(self):
        r = run([row("TOTAL", "OVER", .05, sharp=.60)])["results"][0]
        self.assertFalse(r["probation"])
        self.assertEqual(r["probation_block_reason"], "MARKET_NOT_ELIGIBLE")

    def test_huge_model_edge_is_defect(self):
        r = run([row("SPREAD", "HOME", .20, sharp=.60)])["results"][0]
        self.assertEqual(r["probation_block_reason"], "MODEL_EDGE_ABOVE_SANITY_CAP")

    def test_no_sharp_reference_blocks(self):
        r = run([row("SPREAD", "HOME", .05)])["results"][0]
        self.assertEqual(r["probation_block_reason"], "NO_SHARP_REFERENCE")

    def test_dk_must_beat_sharp_fair(self):
        lose = run([row("SPREAD", "HOME", .05, sharp=.52)])["results"][0]   # 0.52*1.909-1 = -0.7%
        self.assertEqual(lose["probation_block_reason"], "DK_PRICE_DOES_NOT_BEAT_SHARP_FAIR")
        win = run([row("SPREAD", "HOME", .05, sharp=.55)])["results"][0]    # +5.0%
        self.assertTrue(win["probation"])

    def test_never_official(self):
        p = run([row("MONEYLINE", "AWAY", .04, sharp=.45, odds=140)])
        self.assertFalse(p["probation"]["official"])
        self.assertTrue(p["probation"]["sharp_reference_required"])


if __name__ == "__main__":
    unittest.main()

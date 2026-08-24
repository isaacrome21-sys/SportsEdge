import json
import unittest
from pathlib import Path

from sportsedge.engine_registry import engine_registry, resolve_manual_market_type
from sportsedge.hitter_joint_engine import HITTER_MARKETS
from sportsedge.pitcher_joint_engine import PITCHER_MARKETS
from sportsedge.quote_bridge import SUPPORTED_MARKETS


REQUESTED = {
    "MONEYLINE", "RUN_LINE", "TOTALS",
    "HITS", "HOME_RUNS", "TOTAL_BASES", "RBI", "RUNS", "STOLEN_BASES", "BATTER_BB",
    "EXTRA_BASE_HITS", "HITS_RUNS_RBIS", "HITS_RUNS_STOLEN_BASES", "RUNS_RBIS",
    "HITS_STOLEN_BASES", "HITS_WALKS_STOLEN_BASES",
    "PITCHER_K", "PITCHER_OUTS", "PITCHER_ER", "PITCHER_HITS_ALLOWED", "PITCHER_BB",
    "PITCHER_HITS_WALKS_ER", "EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB", "EITHER_PITCHER_ER",
}


class FullMLBMarketSurfaceTests(unittest.TestCase):
    def test_every_requested_market_is_quote_admitted_and_routable(self):
        self.assertTrue(REQUESTED <= SUPPORTED_MARKETS)
        self.assertTrue(REQUESTED <= set(engine_registry()))

    def test_every_requested_market_has_deployment_record(self):
        data = json.loads(Path("config/deployments.json").read_text())
        self.assertTrue(REQUESTED <= set(data["markets"]))
        for market in REQUESTED:
            self.assertFalse(data["markets"][market]["eligible"])

    def test_every_requested_market_is_declared_for_six_gate_evidence(self):
        data = json.loads(Path("config/mlb_validation_evidence.json").read_text())
        self.assertTrue(REQUESTED <= set(data["markets"]))

    def test_manual_aliases_cover_user_facing_market_families(self):
        aliases = {
            "ML": "MONEYLINE", "RL": "RUN_LINE", "O/U": "TOTALS",
            "BATTER_HITS": "HITS", "BATTER_HOME_RUNS": "HOME_RUNS",
            "BATTER_TOTAL_BASES": "TOTAL_BASES", "BATTER_RBI": "RBI",
            "BATTER_RUNS": "RUNS", "BATTER_STOLEN_BASES": "STOLEN_BASES",
            "BATTER_WALKS": "BATTER_BB", "XBH": "EXTRA_BASE_HITS",
            "H_R_RBI": "HITS_RUNS_RBIS", "H_R_SB": "HITS_RUNS_STOLEN_BASES",
            "R_RBI": "RUNS_RBIS", "H_SB": "HITS_STOLEN_BASES", "H_BB_SB": "HITS_WALKS_STOLEN_BASES",
            "PITCHER_STRIKEOUTS": "PITCHER_K", "OUTS_RECORDED": "PITCHER_OUTS",
            "PITCHER_EARNED_RUNS": "PITCHER_ER", "PITCHER_HITS_ALLOWED": "PITCHER_HITS_ALLOWED",
            "PITCHER_WALKS": "PITCHER_BB", "PITCHER_HITS_WALKS_ER": "PITCHER_HITS_WALKS_ER",
        }
        for raw, canonical in aliases.items():
            self.assertEqual(resolve_manual_market_type(raw), canonical)

    def test_overlapping_hitter_and_pitcher_surfaces_are_single_engine_families(self):
        registry = engine_registry()
        hitter_fns = {registry[m].__name__ for m in HITTER_MARKETS}
        pitcher_fns = {registry[m].__name__ for m in PITCHER_MARKETS}
        self.assertEqual(hitter_fns, {"hitter_joint_adapter"})
        self.assertEqual(pitcher_fns, {"pitcher_joint_adapter"})


if __name__ == "__main__":
    unittest.main()

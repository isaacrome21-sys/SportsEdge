import ast
from pathlib import Path
import unittest

from sportsedge.truth_gate import TruthGateError, decide_bet


PRODUCTION_PATHS = (
    "sportsedge/truth_gate.py",
    "sportsedge/orchestrator.py",
    "sportsedge/unified_card.py",
    "sportsedge/card_pipeline.py",
    "sportsedge/pitcher_card_pipeline.py",
    "sportsedge/auto_runner.py",
    "sportsedge/auto_native_odds.py",
    "sportsedge/runtime.py",
    "scripts/run_auto_mlb.py",
)


def _tree(path: str):
    return ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)


class TruthGateContractTests(unittest.TestCase):
    def test_no_production_function_exposes_min_edge_argument(self):
        offenders = []
        for path in PRODUCTION_PATHS:
            for node in ast.walk(_tree(path)):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
                    if "min_edge" in names:
                        offenders.append(f"{path}:{node.name}")
        self.assertEqual(offenders, [])

    def test_no_zero_default_for_edge_floor_arguments(self):
        offenders = []
        for path in PRODUCTION_PATHS:
            for node in ast.walk(_tree(path)):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                positional = [*node.args.posonlyargs, *node.args.args]
                defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
                pairs = list(zip(positional, defaults)) + list(zip(node.args.kwonlyargs, node.args.kw_defaults))
                for arg, default in pairs:
                    if "edge_floor" not in arg.arg or default is None:
                        continue
                    if isinstance(default, ast.Constant) and default.value in (0, 0.0):
                        offenders.append(f"{path}:{node.name}:{arg.arg}")
        self.assertEqual(offenders, [])

    def test_cli_has_no_production_min_edge_override(self):
        text = Path("scripts/run_auto_mlb.py").read_text(encoding="utf-8")
        self.assertNotIn("--min-edge", text)

    def test_cli_cannot_switch_production_floor_registry(self):
        text = Path("scripts/run_auto_mlb.py").read_text(encoding="utf-8")
        self.assertIn("production edge-floor config override is prohibited", text)
        self.assertIn("edge_floor_config_path=DEFAULT_EDGE_FLOOR_CONFIG", text)

    def test_orchestrator_is_the_only_truth_gate_decision_callsite(self):
        callsites = []
        for path in PRODUCTION_PATHS:
            tree = _tree(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id == "decide_bet":
                        callsites.append(path)
                    elif isinstance(func, ast.Attribute) and func.attr == "decide_bet":
                        callsites.append(path)
        self.assertEqual(callsites, ["sportsedge/orchestrator.py"])

    def test_orchestrator_resolves_floor_from_single_source(self):
        text = Path("sportsedge/orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("require_production_edge_floor", text)
        self.assertIn("edge_floor=float(floor.value_probability_points)", text)

    def test_push_is_neutral_in_ev_and_edge_is_conditional_on_non_push(self):
        decision = decide_bet(
            0.45, 100,
            fair_market_probability=0.50,
            bound=True, fresh=True, deployed=True,
            edge_floor=0.01,
            kelly_multiplier=1.0,
            push_probability=0.10,
        )
        # 45% win, 10% push, 45% loss is exactly 50/50 conditional on settlement.
        self.assertAlmostEqual(decision.conditional_model_probability, 0.50, places=12)
        self.assertAlmostEqual(decision.edge, 0.0, places=12)
        self.assertAlmostEqual(decision.ev_per_dollar, 0.0, places=12)
        self.assertAlmostEqual(decision.kelly_fraction, 0.0, places=12)
        self.assertEqual(decision.push_probability, 0.10)

    def test_push_aware_ev_does_not_treat_returned_stake_as_loss(self):
        decision = decide_bet(
            0.50, 100,
            fair_market_probability=0.50,
            bound=True, fresh=True, deployed=True,
            edge_floor=0.01,
            kelly_multiplier=1.0,
            push_probability=0.10,
        )
        # Loss mass is 0.40, so even-money EV is +0.10, not zero.
        self.assertAlmostEqual(decision.ev_per_dollar, 0.10, places=12)
        self.assertAlmostEqual(decision.conditional_model_probability, 0.50 / 0.90, places=12)
        self.assertGreater(decision.edge, 0.05)
        self.assertEqual(decision.bet_status, "OFFICIAL_BET")

    def test_invalid_push_mass_fails_closed(self):
        with self.assertRaises(TruthGateError):
            decide_bet(
                0.8, -110,
                fair_market_probability=0.5,
                bound=True, fresh=True, deployed=True,
                edge_floor=0.01,
                push_probability=0.3,
            )


if __name__ == "__main__":
    unittest.main()

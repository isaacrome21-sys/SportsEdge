import ast
from pathlib import Path


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


def test_no_production_function_exposes_min_edge_argument():
    offenders = []
    for path in PRODUCTION_PATHS:
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
                if "min_edge" in names:
                    offenders.append(f"{path}:{node.name}")
    assert offenders == []


def test_no_zero_default_for_edge_floor_arguments():
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
    assert offenders == []


def test_cli_has_no_production_min_edge_override():
    text = Path("scripts/run_auto_mlb.py").read_text(encoding="utf-8")
    assert "--min-edge" not in text


def test_orchestrator_is_the_only_truth_gate_decision_callsite():
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
    assert callsites == ["sportsedge/orchestrator.py"]


def test_orchestrator_resolves_floor_from_single_source():
    text = Path("sportsedge/orchestrator.py").read_text(encoding="utf-8")
    assert "require_production_edge_floor" in text
    assert "edge_floor=float(floor.value_probability_points)" in text

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_cfb_game_model_candidate_tested",
    ROOT / "scripts/run_cfb_game_model_candidate.py",
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def test_numeric_game_rows_are_forced_to_blocked_lean():
    report = {
        "results": [{
            "market": "SPREAD", "model_p": 0.58,
            "bet_status": "OFFICIAL_BET", "official_eligible": True,
        }],
        "summary": {"official_bets": 1},
    }
    out = MOD._candidateize(report)
    row = out["results"][0]
    assert row["presentation_label"] == "LEAN"
    assert row["decision_tier"] == "MODEL_CANDIDATE"
    assert row["bet_status"] == "BLOCKED"
    assert row["official_eligible"] is False
    assert row["promotion_authority"] is False
    assert out["summary"]["official_bets"] == 0


def test_current_production_game_registry_remains_unfrozen():
    registry = json.loads((ROOT / "config/cfb_game_model_freeze.json").read_text())
    assert registry["status"] == "UNFROZEN"
    assert registry["promotion_authority"] is False

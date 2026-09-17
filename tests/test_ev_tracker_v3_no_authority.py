import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v3_has_no_model_or_betting_authority():
    p = json.loads((ROOT / "config/ev_tracker_policy_v3.json").read_text())
    a = p["authority_boundaries"]
    assert a == {
        "creates_model_p": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False,
    }

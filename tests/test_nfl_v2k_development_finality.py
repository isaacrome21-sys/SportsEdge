import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "sportsedge/sports/nfl/NFL_V2K_DEVELOPMENT_FINAL_V1.json"


def test_nfl_v2k_development_is_final_and_fail_closed():
    value = json.loads(FINAL.read_text())
    assert value["status"] == "DEVELOPMENT_BUDGET_EXHAUSTED_NO_PASS"
    assert value["max_development_attempts"] == 5
    assert value["development_budget_units_used"] == 5
    assert value["development_budget_units_remaining"] == 0
    final = value["canonical_final_attempt"]
    assert final["candidate_family"] == "NFL_MARKET_CALIBRATION_LINE_G5"
    assert final["result"] == "FAIL"
    assert final["workflow_run_id"] == 37297530783
    assert final["artifact_id"] == 11340321865
    assert final["artifact_digest"] == "sha256:b712e0d8bdcb92af67ebfae59e423c076c0fbdac7a3319de9182f8e5a150edc2"
    assert final["diagnostics"]["spread"]["pass"] is False
    assert final["diagnostics"]["total"]["pass"] is False
    assert value["policy"]["additional_v2k_development_attempts_allowed"] is False
    assert not any(value["authority"].values())

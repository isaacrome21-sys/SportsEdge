import json
from pathlib import Path

FINAL = Path("sportsedge/sports/nfl/NFL_V2K_DEVELOPMENT_FINAL_V1.json")


def test_v2k_development_budget_is_exhausted_after_final_fail():
    value = json.loads(FINAL.read_text())
    assert value["status"] == "BUDGET_EXHAUSTED_NO_PASS"
    assert value["attempts_used"] == 5
    assert value["attempts_remaining"] == 0
    assert value["verdict"] == "ATTEMPT5_FAIL"
    assert value["canonical_run_id"] == 37297530783
    assert value["artifact_id"] == 11340321865
    assert value["spread"]["passed"] is False
    assert value["total"]["passed"] is False
    assert value["additional_development_attempts_allowed"] is False

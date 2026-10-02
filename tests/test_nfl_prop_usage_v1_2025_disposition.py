import json
from pathlib import Path

LOCK = Path("config/research/nfl_prop_usage_v1_2025_validation_lock.json")
DISP = Path("config/research/nfl_prop_usage_v1_2025_disposition.json")

def test_2025_prop_window_is_spent_and_not_reusable():
    lock=json.loads(LOCK.read_text())
    disp=json.loads(DISP.read_text())
    assert lock["status"] == "SPENT_TECHNICAL_FAILURE_NO_MODEL_SCORE"
    assert lock["validation_window"]["status"] == "SPENT_TECHNICAL_FAILURE"
    assert lock["validation_window"]["reusable"] is False
    assert lock["validation_window"]["model_scoring_completed"] is False
    assert lock["validation_window"]["statistical_result"] is None
    assert disp["governance"]["2025_reusable"] is False
    assert disp["governance"]["retry_2025"] is False
    assert disp["governance"]["statistical_pass_claimed"] is False
    assert disp["governance"]["statistical_fail_claimed"] is False
    assert disp["governance"]["next_validation_requires_fresh_predeclared_window"] is True

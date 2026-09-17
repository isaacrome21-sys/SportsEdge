from scripts.ev_tracker_v3_health_patch import DEGRADED, OK, exit_code


def test_zero_credits_is_degraded():
    assert exit_code(remaining_credits=0) == DEGRADED


def test_dead_slot_is_degraded():
    assert exit_code(remaining_credits=100, dead_slots=1) == DEGRADED


def test_401_is_degraded():
    assert exit_code(remaining_credits=100, error_codes=["ODDS_API_UNAUTHORIZED"]) == DEGRADED


def test_clean_health_is_ok():
    assert exit_code(remaining_credits=100) == OK

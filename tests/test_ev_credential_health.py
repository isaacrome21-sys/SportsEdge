from scripts.ev_credential_health import classify


def test_401_degrades_before_window():
    r = classify({"slots": [{"error_code": "ODDS_API_UNAUTHORIZED", "remaining_credits": 100}]})
    assert not r["healthy"] and r["state"] == "DEGRADED_CREDENTIAL" and not r["creates_evidence"]


def test_zero_credits_degrades_without_provider_outage_claim():
    r = classify({"slots": [{"remaining_credits": 0}]})
    assert not r["healthy"] and r["state"] == "DEGRADED_ZERO_CREDITS"


def test_dead_slot_degrades():
    r = classify({"slots": [{"remaining_credits": 50}, {"dead": True}]})
    assert not r["healthy"] and r["state"] == "DEGRADED_DEAD_SLOT"


def test_healthy_requires_no_known_degradation():
    r = classify({"slots": [{"remaining_credits": 100}]})
    assert r["healthy"] and r["state"] == "HEALTHY"

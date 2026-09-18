from scripts.ev_tracker_v3_gate import evaluate


def test_active_admits():
    r = evaluate({"state": "ACTIVE"})
    assert r["admit_evidence"] and not r["mutates_prior_records"]


def test_suspended_refuses():
    r = evaluate({"state": "SUSPENDED"})
    assert not r["admit_evidence"] and r["admission"] == "NOT_EVIDENCE"


def test_recovering_refuses():
    r = evaluate({"state": "RECOVERING", "recovery_streak": 2})
    assert not r["admit_evidence"] and r["admission"] == "NOT_EVIDENCE"

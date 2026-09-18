import pytest
from scripts.ev_v3_state import transition_record


def test_transition_requires_prior_and_current_hashes():
    with pytest.raises(ValueError):
        transition_record(from_state="ACTIVE", to_state="SUSPENDED", effective_at="2026-09-17T02:00:00Z",
                          reason_code="PROVIDER_OUTAGE", policy_id="EV_TRACKER_POLICY_V3", policy_sha256="",
                          prior_policy_id="EV_TRACKER_POLICY_V2", prior_policy_sha256="old")


def test_transition_is_append_only_and_nonretroactive():
    r = transition_record(from_state="ACTIVE", to_state="SUSPENDED", effective_at="2026-09-17T02:00:00Z",
                          reason_code="PROVIDER_OUTAGE", policy_id="EV_TRACKER_POLICY_V3", policy_sha256="new",
                          prior_policy_id="EV_TRACKER_POLICY_V2", prior_policy_sha256="old")
    assert r["append_only"] is True
    assert r["retroactive_effect"] is False
    assert r["prior_policy_sha256"] == "old"

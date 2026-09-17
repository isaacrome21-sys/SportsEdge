import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def test_manifest_moves_v2_to_superseded_and_v3_active():
    m = load("config/ev_tracker_policy_manifest.json")
    assert m["active"]["policy_id"] == "EV_TRACKER_POLICY_V3"
    assert any(x["policy_id"] == "EV_TRACKER_POLICY_V2" for x in m["superseded"])


def test_v3_is_n0_prospective_and_no_backfill():
    p = load("config/ev_tracker_policy_v3.json")
    a = load("config/ev_tracker_v3_activation.json")
    assert "n=0" in p["activation"]
    assert a["backfill"] == "FORBIDDEN"
    assert a["retroactive_reclassification"] == "FORBIDDEN"
    assert a["prior_history"] == "IMMUTABLE"


def test_recovery_k_is_frozen_at_three():
    p = load("config/ev_tracker_policy_v3.json")
    assert p["suspension"]["recovery"]["required_consecutive_successful_slates"] == 3
    assert p["suspension"]["recovery"]["capture_disposition"] == "NOT_EVIDENCE"


def test_manual_and_budget_cannot_suspend():
    p = load("config/ev_tracker_policy_v3.json")
    assert p["suspension"]["manual_lane_can_suspend"] is False
    assert "BUDGET_RESERVE_REACHED" in p["suspension"]["non_outage_codes"]
    assert p["budget"]["reserve_reached_is_provider_outage"] is False

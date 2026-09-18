import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nfl_suspension_is_prospective_machine_only_and_no_backfill():
    p = json.loads((ROOT / "config/nfl_confirmation_v3_suspension.json").read_text())
    assert p["activation"] == "PROSPECTIVE_ONLY_AFTER_MAIN_MERGE"
    assert p["machine_derived_only"] is True
    assert p["manual_lane_can_suspend"] is False
    assert p["provider_outage"]["budget_exhaustion_is_outage"] is False
    assert p["recovery"]["required_consecutive_successful_slates"] == 3
    assert p["recovery"]["recovery_captures"] == "NOT_EVIDENCE"
    assert p["history"]["prior_misses_immutable"] is True
    assert p["history"]["backfill"] == "FORBIDDEN"

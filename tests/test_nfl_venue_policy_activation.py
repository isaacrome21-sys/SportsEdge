import json
from pathlib import Path


def test_nfl_venue_policy_activation_is_main_only():
    policy = json.loads(Path("config/nfl_venue_policy_v1.json").read_text())
    assert policy["evidence_ref"] == "refs/heads/main"
    assert policy["activation_rule"] == "ACTIVE_ONLY_WHEN_EXACT_POLICY_BYTES_EXIST_ON_EVIDENCE_REF"
    freeze_record = policy["freeze_record"]
    assert "Feature-branch commits do not activate this policy" in freeze_record
    assert "refs/heads/main" in freeze_record

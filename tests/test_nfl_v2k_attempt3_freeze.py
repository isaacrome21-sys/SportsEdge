import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "sportsedge/sports/nfl/NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V3.json"

def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()

def test_attempt3_freeze_binds_exact_implementation_and_seed():
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert c["status"] == "FROZEN_ATTEMPT3_READY_FOR_DEVELOPMENT_VALIDATION"
    assert c["candidate_family"] == "NFL_V2K_CONTEXT_SKELETON_LOGRATIO_G3"
    assert int(c["simulation"]["root_seed"]) == 8538327727501875778
    assert c["simulation"]["paths_per_game"] == 50000
    assert c["simulation"]["absolute_floor"] == 10000
    assert c["attempt_budget"]["development_budget_units_used_before_attempt3"] == 2
    assert c["attempt_budget"]["development_budget_units_remaining_before_attempt3"] == 3
    assert c["attempt_budget"]["attempt3_scoring_allowed"] is True
    ident = c["implementation_identity"]
    assert ident["status"] == "FROZEN"
    for pkey, hkey in (
        ("core_path", "core_git_blob_sha1"),
        ("validation_path", "validation_git_blob_sha1"),
        ("runner_path", "runner_git_blob_sha1"),
        ("workflow_path", "workflow_git_blob_sha1"),
    ):
        assert _git_blob_sha(ROOT / ident[pkey]) == ident[hkey]

def test_attempt3_betting_authority_remains_false():
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for key in ("model_p", "pricing", "promotion", "staking", "production_release", "official", "untouched_readout"):
        assert c["authority"][key] is False

def test_attempt3_dispatch_bridge_is_owner_issue_and_exact_token_bound():
    text = (ROOT / ".github/workflows/nfl-v2k-attempt3-dispatch-bridge.yml").read_text(encoding="utf-8")
    assert "github.actor == github.repository_owner" in text
    assert "github.event.issue.number == 1561" in text
    assert "github.event.comment.body == 'CONSUME_ATTEMPT_3'" in text
    assert "inputs[confirm]=CONSUME_ATTEMPT_3" in text
    assert "-f ref=main" in text

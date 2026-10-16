"""Independent audit RED tests for grok/t211 @ 39794582e (#2359). Expected to FAIL until fixed."""
import hashlib, json
import pytest
from sportsedge import composite_card as cc
from sportsedge.capture_preflight import load_capture_receipts
from tests._capture_receipt_fixtures import write_store
from tests.test_composite_audit_findings_20261015 import build, ou, refused, row, iso


@pytest.mark.parametrize("status", ["PLAY NOW", "PLAYABLE", "LOCK", "BUY", "OFFICIALPICK", "play."])
def test_status_guard_is_allowlist_not_denylist(status):
    assert cc.authority_violation({"status": status}) is not None


@pytest.mark.parametrize("obj", [
    {"evaluation": {"Status": "PLAY"}},
    {"evaluation": {"recommendation": "PLAY"}},
    {"evaluation": {"STAKE": 5}},
    {"evaluation": {"units": 2}},
    {"evaluation": {"ev": 0.1, "kelly": 0.05}},
])
def test_nested_authority_and_ev_fields_refused(obj):
    assert cc.authority_violation(obj) is not None


def test_nested_status_play_in_child_evaluation_refused():
    rows = ou("a", "NYY@BOS", 0, 1)
    def ev(g, rs, as_of, ctx):
        return {"as_of_utc": as_of, "game_id": g,
                "rows": [{**cc.row_identity_dict(r), "game_id": r["game_id"], "status": "PRICED_RESEARCH",
                          "quote_captured_at": r["quote_captured_at"],
                          "evaluation": {"Status": "PLAY", "units": 3}} for r in rs]}
    with pytest.raises(cc.CompositeError):
        build(rows, evaluator=ev)


def test_thesis_id_survives_to_composite_grading():
    rows = ou("a", "G1", 0, 1, thesis_id="T") + ou("b", "G2", 0, 1, thesis_id="T")
    def ev(g, rs, as_of, ctx):
        return {"as_of_utc": as_of, "game_id": g,
                "rows": [{**cc.row_identity_dict(r), "game_id": r["game_id"], "status": "PRICED_RESEARCH",
                          "quote_captured_at": r["quote_captured_at"], "thesis_id": r["thesis_id"]} for r in rs]}
    try:
        comp = build(rows, evaluator=ev)
    except cc.CompositeError as e:
        pytest.fail(f"thesis_id rejected by child allowlist: {e}")
    g = cc.grade_composite(comp, {}, pin=comp["manifest_digest"])
    # grade output reports positions as an int (stacks as the list)
    assert g["positions"] == 1 and len(g["stacks"]) == 1


def test_raw_read_id_must_match_receipt_read_id(tmp_path):
    """Replay: an old raw read re-wrapped in a new receipt with a new read_id/captured_at."""
    rows = [row("x", "G1", 0)]
    root, _ = write_store(rows, tmp_path)
    rc = json.loads((root / "receipts/read-x.json").read_text())
    rc.update(receipt_id="rc-replay", read_id="read-replay", captured_at=iso(3600))
    rb = json.dumps(rc, sort_keys=True).encode()
    (root / "receipts/replay.json").write_bytes(rb)
    m = json.loads((root / "manifest.json").read_text())
    m["receipts"].append({"receipt_id": "rc-replay", "path": "receipts/replay.json",
                          "sha256": hashlib.sha256(rb).hexdigest()})
    mb = json.dumps(m, sort_keys=True).encode()
    (root / "manifest.json").write_bytes(mb)
    with pytest.raises(ValueError):
        load_capture_receipts(root, manifest_sha256=hashlib.sha256(mb).hexdigest())

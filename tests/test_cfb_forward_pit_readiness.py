import json
from pathlib import Path

from sportsedge.sports.cfb.forward_pit_readiness import audit_cfb_forward_pit_snapshot


def _classification(tmp_path: Path, **updates):
    payload = {
        "schema_version": 1,
        "sport": "CFB",
        "season": 2026,
        "captured_at_utc": "2026-09-12T11:01:28Z",
        "pit_classification": "FORWARD_SOURCE_SNAPSHOT_FROM_RETRIEVAL_TIME_ONLY",
        "point_in_time_from_capture_forward": True,
        "retroactive_point_in_time_claim": False,
        "promotion_evidence": False,
        "model_p_created": False,
        "eligibility_changed": False,
        "market_data_in_predictive_capture": False,
        "asset_count": 4,
        "assets": [
            {
                "dataset": dataset,
                "content_sha256": ch * 64,
                "manifest_sha256": mh * 64,
                "source_retrieved_at": "2026-09-12T11:01:27+00:00",
            }
            for dataset, ch, mh in [
                ("adv_drives", "a", "1"),
                ("adv_situational", "b", "2"),
                ("adv_team", "c", "3"),
                ("schedules", "d", "4"),
            ]
        ],
    }
    payload.update(updates)
    path = tmp_path / "classification.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_valid_forward_source_snapshot_stays_blocked_from_truth_gate(tmp_path):
    report = audit_cfb_forward_pit_snapshot(_classification(tmp_path))
    assert report["source_asof_ready"] is True
    assert report["truth_gate_ready"] is False
    assert report["promotion_authority"] is False
    assert report["model_p_created"] is False
    assert "PAIRED_MARKET_EVIDENCE_MISSING" in report["blockers"]
    assert "PROMOTION_EVIDENCE_NOT_ESTABLISHED" in report["blockers"]


def test_retroactive_claim_fails_closed(tmp_path):
    report = audit_cfb_forward_pit_snapshot(
        _classification(tmp_path, retroactive_point_in_time_claim=True)
    )
    assert report["source_asof_ready"] is False
    assert "RETROACTIVE_PIT_CLAIM_FORBIDDEN" in report["reasons"]
    assert report["truth_gate_ready"] is False


def test_late_source_retrieval_fails_closed(tmp_path):
    path = _classification(tmp_path)
    payload = json.loads(path.read_text())
    payload["assets"][0]["source_retrieved_at"] = "2026-09-12T11:01:29+00:00"
    path.write_text(json.dumps(payload))
    report = audit_cfb_forward_pit_snapshot(path)
    assert report["source_asof_ready"] is False
    assert "SOURCE_BINDING_INVALID" in report["reasons"]
    assert any("RETRIEVAL_AFTER_CAPTURE" in e for e in report["asset_errors"])


def test_market_presence_cannot_self_promote(tmp_path):
    report = audit_cfb_forward_pit_snapshot(
        _classification(tmp_path, market_data_in_predictive_capture=True)
    )
    assert report["paired_market_evidence_present"] is True
    assert report["truth_gate_ready"] is False
    assert "PROMOTION_EVIDENCE_NOT_ESTABLISHED" in report["blockers"]

import json
from hashlib import sha256
from pathlib import Path

from sportsedge.sports.cfb.forward_pit_readiness import audit_cfb_forward_pit_snapshot


def _manifest_sha(payload: dict) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _classification(
    tmp_path: Path,
    *,
    retrieved_at: str = "2026-09-12T11:01:27+00:00",
    **updates,
):
    source_root = tmp_path / "source"
    capture_root = tmp_path / "capture"
    capture_root.mkdir(parents=True, exist_ok=True)

    assets = []
    for index, dataset in enumerate(("adv_drives", "adv_situational", "adv_team", "schedules"), start=1):
        asset_name = "cfb_schedule_2026.csv" if dataset == "schedules" else f"{dataset}_2026.csv"
        cache_relative_path = f"{dataset}/2026/{asset_name}"
        source_path = source_root / cache_relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_bytes = f"dataset,value\n{dataset},{index}\n".encode("utf-8")
        source_path.write_bytes(source_bytes)
        content_sha = sha256(source_bytes).hexdigest()

        manifest = {
            "asset": {
                "asset_id": 1000 + index,
                "asset_name": asset_name,
                "dataset": dataset,
                "release_id": 2000 + index,
                "release_tag": f"espn_cfb_{dataset}",
                "season": 2026,
                "sha256": content_sha,
                "size": len(source_bytes),
                "usage": "PREDICTIVE_INPUT",
            },
            "cache_relative_path": cache_relative_path,
            "cache_reused": False,
            "content_sha256": content_sha,
            "contract": "CFB_SPORTSDATAVERSE_RELEASE_V1",
            "market_role": "PREDICTIVE_INPUT",
            "retrieved_at": retrieved_at,
            "row_count": 1,
        }
        manifest_sha = _manifest_sha(manifest)
        manifest["manifest_sha256"] = manifest_sha
        (source_path.parent / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        assets.append(
            {
                "dataset": dataset,
                "season": 2026,
                "release_tag": f"espn_cfb_{dataset}",
                "release_id": 2000 + index,
                "asset_id": 1000 + index,
                "asset_name": asset_name,
                "cache_relative_path": cache_relative_path,
                "content_sha256": content_sha,
                "manifest_sha256": manifest_sha,
                "source_retrieved_at": retrieved_at,
            }
        )

    payload = {
        "schema_version": 1,
        "sport": "CFB",
        "capture_git_sha": "a" * 40,
        "season": 2026,
        "captured_at_utc": "2026-09-12T11:01:28Z",
        "pit_classification": "FORWARD_SOURCE_SNAPSHOT_FROM_RETRIEVAL_TIME_ONLY",
        "point_in_time_from_capture_forward": True,
        "retroactive_point_in_time_claim": False,
        "promotion_evidence": False,
        "model_p_created": False,
        "eligibility_changed": False,
        "market_data_in_predictive_capture": False,
        "asset_count": len(assets),
        "assets": assets,
    }
    payload.update(updates)
    path = capture_root / "classification.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_valid_forward_source_snapshot_stays_blocked_from_truth_gate(tmp_path):
    report = audit_cfb_forward_pit_snapshot(_classification(tmp_path))
    assert report["source_asof_ready"] is True
    assert report["truth_gate_ready"] is False
    assert report["promotion_authority"] is False
    assert report["model_p_created"] is False
    assert report["paired_market_evidence_present"] is False
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
    report = audit_cfb_forward_pit_snapshot(
        _classification(tmp_path, retrieved_at="2026-09-12T11:01:29+00:00")
    )
    assert report["source_asof_ready"] is False
    assert "SOURCE_BINDING_INVALID" in report["reasons"]
    assert any("RETRIEVAL_AFTER_CAPTURE" in error for error in report["asset_errors"])


def test_same_second_subsecond_retrieval_before_capture_is_valid(tmp_path):
    report = audit_cfb_forward_pit_snapshot(
        _classification(
            tmp_path,
            retrieved_at="2026-09-12T11:01:28.125000+00:00",
            captured_at_utc="2026-09-12T11:01:28.900000Z",
        )
    )
    assert report["source_asof_ready"] is True
    assert not any("RETRIEVAL_AFTER_CAPTURE" in error for error in report["asset_errors"])
    assert report["truth_gate_ready"] is False


def test_predictive_market_contamination_fails_closed_and_is_not_paired_evidence(tmp_path):
    report = audit_cfb_forward_pit_snapshot(
        _classification(tmp_path, market_data_in_predictive_capture=True)
    )
    assert report["source_asof_ready"] is False
    assert "PREDICTIVE_MARKET_CONTAMINATION_FORBIDDEN" in report["reasons"]
    assert report["paired_market_evidence_present"] is False
    assert report["truth_gate_ready"] is False
    assert "PAIRED_MARKET_EVIDENCE_MISSING" in report["blockers"]


def test_source_byte_drift_fails_closed(tmp_path):
    path = _classification(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_path = tmp_path / "source" / payload["assets"][0]["cache_relative_path"]
    source_path.write_text("tampered\n", encoding="utf-8")

    report = audit_cfb_forward_pit_snapshot(path)
    assert report["source_asof_ready"] is False
    assert "SOURCE_BINDING_INVALID" in report["reasons"]
    assert any("CONTENT_SHA256_MISMATCH" in error for error in report["asset_errors"])


def test_manifest_drift_fails_closed(tmp_path):
    path = _classification(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_path = tmp_path / "source" / payload["assets"][0]["cache_relative_path"]
    manifest_path = source_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["row_count"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = audit_cfb_forward_pit_snapshot(path)
    assert report["source_asof_ready"] is False
    assert "SOURCE_BINDING_INVALID" in report["reasons"]
    assert any("MANIFEST_SHA256_MISMATCH" in error for error in report["asset_errors"])


def test_cache_path_traversal_fails_closed(tmp_path):
    path = _classification(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["assets"][0]["cache_relative_path"] = "../escape.csv"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_cfb_forward_pit_snapshot(path)
    assert report["source_asof_ready"] is False
    assert any("CACHE_PATH_INVALID" in error for error in report["asset_errors"])

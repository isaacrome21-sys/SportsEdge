from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from scripts.check_nrfi_durable_health import check


def _write(root: Path, *, prediction_time: str, settlement_time: str, settled: int = 1, eligible: bool = False) -> None:
    latest = root / "latest"
    latest.mkdir(parents=True)
    settlements = [
        {
            "game_id": str(100 + i),
            "source": "MLB_STATSAPI_LIVE_FEED_LINESCORE_V2",
            "settled_at_utc": settlement_time,
        }
        for i in range(settled)
    ]
    settlement_path = latest / "nrfi_v6_settlements.json"
    settlement_path.write_text(json.dumps(settlements, sort_keys=True, separators=(",", ":")) + "\n")
    report = {
        "generated_at_utc": settlement_time,
        "candidate_sha256": "candidate",
        "feature_contract_sha256": "feature",
        "selected_unique_games": settled,
        "settled_unique_games": settled,
        "state": "MODEL_ELIGIBLE" if eligible else "MODEL_NOT_ELIGIBLE",
        "markets": {"NRFI": {"eligible": eligible}, "YRFI": {"eligible": eligible}},
        "gates": {"integrity": {"violations": [], "pass": True}},
        "game_evidence": [
            {
                "game_id": str(100 + i),
                "generated_at_utc": prediction_time,
            }
            for i in range(settled)
        ],
    }
    report_path = latest / "nrfi_v6_forward_shadow_report.json"
    report_path.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    manifest = {
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "settlement_sha256": hashlib.sha256(settlement_path.read_bytes()).hexdigest(),
        "candidate_sha256": "candidate",
        "eligible": eligible,
        "generated_at_utc": settlement_time,
    }
    (latest / "nrfi_v6_forward_shadow_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )


def test_health_uses_evidence_time_not_report_execution_time(tmp_path: Path) -> None:
    _write(
        tmp_path,
        prediction_time="2026-08-30T12:00:00+00:00",
        settlement_time="2026-08-30T23:00:00+00:00",
    )
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    result = check(tmp_path, now, 36, 36)
    assert result["state"] == "HEALTHY"
    assert result["settled_unique_games"] == 1


def test_health_fails_when_actual_evidence_is_stale(tmp_path: Path) -> None:
    _write(
        tmp_path,
        prediction_time="2026-08-20T12:00:00+00:00",
        settlement_time="2026-08-20T23:00:00+00:00",
    )
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    result = check(tmp_path, now, 36, 36)
    assert result["state"] == "STALE"
    assert "CAPTURE_STALE" in result["problems"]
    assert "SETTLEMENT_STALE" in result["problems"]


def test_health_fails_closed_on_manifest_hash_mismatch(tmp_path: Path) -> None:
    _write(
        tmp_path,
        prediction_time="2026-08-30T12:00:00+00:00",
        settlement_time="2026-08-30T23:00:00+00:00",
    )
    manifest_path = tmp_path / "latest" / "nrfi_v6_forward_shadow_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["report_sha256"] = "bad"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(SystemExit, match="NRFI_DURABLE_REPORT_SHA_MISMATCH"):
        check(tmp_path, datetime(2026, 8, 31, 12, tzinfo=timezone.utc), 36, 36)

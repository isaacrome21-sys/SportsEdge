import json
from hashlib import sha256
from pathlib import Path

import pytest

from sportsedge.sports.mlb.the_odds_api_pairing import (
    MLBTheOddsAPIPairingError,
    audit_snapshot_pair,
)


def _write_snapshot(root: Path, name: str, *, ts: str, h2h_home: int = -120, spread_point: float = -1.5,
                    reconstructed: bool = False) -> Path:
    d = root / name
    d.mkdir()
    payload = {
        "timestamp": ts,
        "previous_timestamp": None,
        "next_timestamp": None,
        "data": [{
            "id": "game-1",
            "commence_time": "2026-06-06T00:10:00Z",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [{
                "key": "draftkings",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Home", "price": h2h_home},
                        {"name": "Away", "price": 105},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Home", "price": -110, "point": spread_point},
                        {"name": "Away", "price": -110, "point": -spread_point},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "price": -105, "point": 8.5},
                        {"name": "Under", "price": -115, "point": 8.5},
                    ]},
                ],
            }],
        }],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    (d / "snapshot.json").write_bytes(raw)
    meta = {
        "schema": "MLB_THE_ODDS_API_HISTORICAL_ARCHIVE_V1",
        "source": "THE_ODDS_API_HISTORICAL",
        "requested_at": ts,
        "provider_timestamp": ts,
        "payload_sha256": sha256(raw).hexdigest(),
        "interpolated": False,
        "reconstructed": reconstructed,
    }
    (d / "snapshot.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


def test_valid_exact_snapshots_are_ready_for_replay(tmp_path):
    decision = _write_snapshot(tmp_path, "decision", ts="2026-06-05T22:30:00Z")
    close = _write_snapshot(tmp_path, "close", ts="2026-06-06T00:05:00Z", h2h_home=-125)
    report = audit_snapshot_pair(decision, close)
    assert report["status"] == "READY_FOR_REPLAY"
    assert report["valid_pair_count"] == 6
    assert report["promotion_authority"] is False
    assert report["may_change_market_eligibility"] is False


def test_threshold_drift_is_not_forced_into_spread_pair(tmp_path):
    decision = _write_snapshot(tmp_path, "decision", ts="2026-06-05T22:30:00Z", spread_point=-1.5)
    close = _write_snapshot(tmp_path, "close", ts="2026-06-06T00:05:00Z", spread_point=-2.5)
    report = audit_snapshot_pair(decision, close)
    assert report["status"] == "READY_FOR_REPLAY"
    assert report["valid_pair_count"] == 4  # h2h + totals only; spread threshold changed


def test_close_after_first_pitch_fails_closed(tmp_path):
    decision = _write_snapshot(tmp_path, "decision", ts="2026-06-05T22:30:00Z")
    close = _write_snapshot(tmp_path, "close", ts="2026-06-06T00:11:00Z")
    report = audit_snapshot_pair(decision, close)
    assert report["status"] == "BLOCKED_PAIRED_MARKET_EVIDENCE"
    assert report["valid_pair_count"] == 0
    assert report["invalid_pair_count"] == 6


def test_reconstructed_archive_is_forbidden(tmp_path):
    decision = _write_snapshot(tmp_path, "decision", ts="2026-06-05T22:30:00Z", reconstructed=True)
    close = _write_snapshot(tmp_path, "close", ts="2026-06-06T00:05:00Z")
    with pytest.raises(MLBTheOddsAPIPairingError, match="RECONSTRUCTED_ARCHIVE_FORBIDDEN"):
        audit_snapshot_pair(decision, close)


def test_tampered_raw_bytes_fail_sha_binding(tmp_path):
    decision = _write_snapshot(tmp_path, "decision", ts="2026-06-05T22:30:00Z")
    close = _write_snapshot(tmp_path, "close", ts="2026-06-06T00:05:00Z")
    (decision / "snapshot.json").write_bytes(b"{}")
    with pytest.raises(MLBTheOddsAPIPairingError, match="ARCHIVE_SHA256_MISMATCH"):
        audit_snapshot_pair(decision, close)

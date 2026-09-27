import json
from hashlib import sha256
from pathlib import Path

from sportsedge.sports.mlb.the_odds_api_pairing import audit_snapshot_pair


def _write(root: Path, name: str, *, ts: str, price_shift: int = 0) -> Path:
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
                    {"key": "batter_hits", "outcomes": [
                        {"name": "Over", "description": "Player A", "price": -110 + price_shift, "point": 1.5},
                        {"name": "Under", "description": "Player A", "price": -120 + price_shift, "point": 1.5},
                        {"name": "Over", "description": "Player B", "price": 100 + price_shift, "point": 1.5},
                        {"name": "Under", "description": "Player B", "price": -130 + price_shift, "point": 1.5},
                    ]},
                    {"key": "pitcher_strikeouts", "outcomes": [
                        {"name": "Over", "description": "Pitcher A", "price": -105 + price_shift, "point": 5.5},
                        {"name": "Under", "description": "Pitcher A", "price": -115 + price_shift, "point": 5.5},
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
        "reconstructed": False,
    }
    (d / "snapshot.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


def test_same_threshold_different_players_remain_distinct(tmp_path):
    decision = _write(tmp_path, "decision", ts="2026-06-05T22:30:00Z")
    close = _write(tmp_path, "close", ts="2026-06-06T00:05:00Z", price_shift=5)
    report = audit_snapshot_pair(decision, close)

    assert report["status"] == "READY_FOR_REPLAY"
    assert report["candidate_identity_count"] == 6
    assert report["valid_pair_count"] == 6
    assert report["paired_quote_counts_by_market"] == {"HITS": 4, "PITCHER_K": 2}
    assert report["source_errors"] == []

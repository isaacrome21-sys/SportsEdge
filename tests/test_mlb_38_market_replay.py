import json
from hashlib import sha256
from pathlib import Path
import sys
import subprocess

from scripts.mlb_38_market_replay import main

ROOT = Path(__file__).resolve().parents[1]


def _snapshot(root: Path, name: str, *, timestamp: str, home_price: int, away_price: int) -> None:
    d = root / name
    d.mkdir(parents=True)
    payload = {
        "timestamp": timestamp,
        "previous_timestamp": None,
        "next_timestamp": None,
        "data": [{
            "id": "game-1",
            "commence_time": "2026-06-06T00:10:00Z",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Home", "price": home_price},
                        {"name": "Away", "price": away_price},
                    ],
                }],
            }],
        }],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    (d / "snapshot.json").write_bytes(raw)
    meta = {
        "schema": "MLB_THE_ODDS_API_HISTORICAL_ARCHIVE_V1",
        "source": "THE_ODDS_API_HISTORICAL",
        "requested_at": timestamp,
        "provider_timestamp": timestamp,
        "payload_sha256": sha256(raw).hexdigest(),
        "interpolated": False,
        "reconstructed": False,
    }
    (d / "snapshot.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_full_pipeline_emits_all_38_market_dispositions(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    archive.mkdir()
    _snapshot(archive, "decision", timestamp="2026-06-05T22:30:00Z", home_price=-120, away_price=105)
    _snapshot(archive, "close", timestamp="2026-06-06T00:05:00Z", home_price=-130, away_price=110)

    observations = [{
        "observation_key": "obs-1",
        "source_evidence_class": "LIVE_PROVIDER_QUOTE_ARCHIVE",
        "model_evidence_class": "LIVE_PIT_MODEL",
        "market": "MONEYLINE",
        "game_id": "game-1",
        "entity_id": "Home",
        "period": "FG",
        "is_alternate": False,
        "side": "HOME",
        "quote_ts": "2026-06-05T22:30:00Z",
        "first_pitch_ts": "2026-06-06T00:10:00Z",
        "candidate_p": 0.60,
        "settlement_book_key": "draftkings",
        "book_key": "draftkings",
        "book_rule_evidence_class": "LIVE_BOOK_RULE_CAPTURE",
        "official_fact_evidence_class": "LIVE_OFFICIAL_FACT_PROBE",
        "settlement_state": "SETTLEMENT_ELIGIBLE",
        "settled_outcome": "WIN",
    }]
    obs_path = tmp_path / "observations.json"
    obs_path.write_text(json.dumps({"observations": observations}), encoding="utf-8")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "mlb_38_market_replay.py",
        "--archive-root", str(archive),
        "--pit-observations", str(obs_path),
        "--policy", str(ROOT / "config" / "mlb_replay_policy_v1.json"),
        "--catalog", str(ROOT / "config" / "mlb_market_catalog.json"),
        "--out-dir", str(out_dir),
        "--policy-commit", subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip(),
    ])
    assert main() == 0

    replay = json.loads((out_dir / "promotion_replay.json").read_text(encoding="utf-8"))
    assert replay["eligible_row_count"] == 1
    assert replay["exclusion_count"] == 0
    assert replay["rows"][0]["book_key"] == "draftkings"
    assert replay["rows"][0]["close_no_vig_p"] is not None

    metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["canonical_market_count"] == 38
    assert len(metrics["policy_git_blob_sha"]) == 40
    assert len(metrics["policy_git_commit"]) == 40
    assert len(metrics["markets"]) == 38
    assert metrics["markets"]["MONEYLINE"]["n"] == 1
    assert metrics["markets"]["MONEYLINE"]["clv"]["status"] == "INSUFFICIENT_CLUSTERS_NO_IID_FALLBACK"
    assert metrics["markets"]["FIRST_HOME_RUN"]["status"] == "N_WAY_UNAUTHORIZED_V1"
    assert metrics["governance"]["forward_evidence_created"] is False

    coverage = json.loads((out_dir / "provider_coverage.json").read_text(encoding="utf-8"))
    assert coverage["status"] == "COMPLETE"
    assert coverage["direct_market_count"] == 26
    assert coverage["no_direct_market_count"] == 12

    matrix = json.loads((out_dir / "market_matrix.json").read_text(encoding="utf-8"))
    assert matrix["canonical_market_count"] == 38
    assert len(matrix["rows"]) == 38
    assert {row["market"] for row in matrix["rows"]} == set(metrics["markets"])
    assert all(row["forward_evidence_satisfied"] is False for row in matrix["rows"])
    assert all("replay_exclusion_count" in row for row in matrix["rows"])

    manifest = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED_EVIDENCE_PREPARATION_NOT_PROMOTION"
    assert manifest["canonical_market_count"] == 38
    assert manifest["governance"]["official_status_granted"] is False
    assert set(manifest["artifacts"]) == {
        "provider_coverage.json",
        "materialization_manifest.json",
        "promotion_replay.json",
        "scorer_input.csv",
        "metrics.json",
        "market_matrix.json",
    }

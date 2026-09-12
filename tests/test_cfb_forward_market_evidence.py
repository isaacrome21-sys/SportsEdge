import json
from hashlib import sha256
from pathlib import Path

from sportsedge.sports.cfb.forward_market_evidence import (
    SCHEMA,
    audit_cfb_forward_market_pair,
)


def _pair(tmp_path: Path, **updates) -> Path:
    root = tmp_path / "pair"
    raw_root = root / "raw"
    raw_root.mkdir(parents=True)
    decision_raw = b'{"snapshot":"decision"}\n'
    close_raw = b'{"snapshot":"close"}\n'
    (raw_root / "decision.json").write_bytes(decision_raw)
    (raw_root / "close.json").write_bytes(close_raw)

    identity = {
        "event_id": "2026_02_AWAY_HOME",
        "book": "DraftKings",
        "market": "SPREAD",
        "selection": "HOME",
        "threshold": -3.5,
    }

    def quote(label, quote_at, captured_at, price, raw_bytes):
        return {
            **identity,
            "price": price,
            "provider_quote_at_utc": quote_at,
            "captured_at_utc": captured_at,
            "raw_relative_path": f"raw/{label}.json",
            "raw_sha256": sha256(raw_bytes).hexdigest(),
            "synthetic": False,
            "reconstructed": False,
            "backfilled": False,
            "inferred": False,
            "derived_from_result": False,
        }

    payload = {
        "schema_version": SCHEMA,
        "sport": "CFB",
        "kickoff_utc": "2026-09-19T19:30:00Z",
        "identity": identity,
        "decision": quote("decision", "2026-09-19T15:00:00Z", "2026-09-19T15:00:02Z", -110, decision_raw),
        "close": quote("close", "2026-09-19T19:20:00Z", "2026-09-19T19:20:02Z", -108, close_raw),
        "promotion_authority": False,
        "may_create_model_p": False,
        "eligibility_changed": False,
        "official_status_granted": False,
    }
    payload.update(updates)
    path = root / "pair.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_valid_pair_is_market_evidence_only(tmp_path):
    report = audit_cfb_forward_market_pair(_pair(tmp_path))
    assert report["paired_market_evidence_present"] is True
    assert report["truth_gate_ready"] is False
    assert report["promotion_authority"] is False
    assert report["may_create_model_p"] is False
    assert report["official_status_granted"] is False
    assert "MODEL_P_REQUIRED_SEPARATELY" in report["blockers"]
    assert "PROMOTION_EVIDENCE_NOT_ESTABLISHED" in report["blockers"]


def test_decision_must_precede_close(tmp_path):
    path = _pair(tmp_path)
    payload = json.loads(path.read_text())
    payload["decision"]["provider_quote_at_utc"] = "2026-09-19T19:25:00Z"
    payload["decision"]["captured_at_utc"] = "2026-09-19T19:25:01Z"
    path.write_text(json.dumps(payload))
    report = audit_cfb_forward_market_pair(path)
    assert report["paired_market_evidence_present"] is False
    assert "DECISION_QUOTE_NOT_BEFORE_CLOSE" in report["reasons"]
    assert "DECISION_CAPTURE_NOT_BEFORE_CLOSE" in report["reasons"]


def test_close_must_be_pregame(tmp_path):
    path = _pair(tmp_path)
    payload = json.loads(path.read_text())
    payload["close"]["provider_quote_at_utc"] = "2026-09-19T19:31:00Z"
    payload["close"]["captured_at_utc"] = "2026-09-19T19:31:01Z"
    path.write_text(json.dumps(payload))
    report = audit_cfb_forward_market_pair(path)
    assert report["paired_market_evidence_present"] is False
    assert "CLOSE_NOT_PREGAME" in report["reasons"]


def test_threshold_identity_mismatch_fails_closed(tmp_path):
    path = _pair(tmp_path)
    payload = json.loads(path.read_text())
    payload["close"]["threshold"] = -4.0
    path.write_text(json.dumps(payload))
    report = audit_cfb_forward_market_pair(path)
    assert report["paired_market_evidence_present"] is False
    assert "CLOSE_THRESHOLD_MISMATCH" in report["reasons"]


def test_raw_byte_tampering_fails_closed(tmp_path):
    path = _pair(tmp_path)
    (path.parent / "raw" / "decision.json").write_text("tampered\n")
    report = audit_cfb_forward_market_pair(path)
    assert report["paired_market_evidence_present"] is False
    assert "DECISION_RAW_SHA256_MISMATCH" in report["reasons"]


def test_backfilled_quote_is_forbidden(tmp_path):
    path = _pair(tmp_path)
    payload = json.loads(path.read_text())
    payload["decision"]["backfilled"] = True
    path.write_text(json.dumps(payload))
    report = audit_cfb_forward_market_pair(path)
    assert report["paired_market_evidence_present"] is False
    assert "DECISION_BACKFILLED_FORBIDDEN" in report["reasons"]


def test_market_evidence_cannot_self_promote(tmp_path):
    path = _pair(tmp_path, promotion_authority=True)
    report = audit_cfb_forward_market_pair(path)
    assert report["paired_market_evidence_present"] is False
    assert "PROMOTION_AUTHORITY_MUST_BE_FALSE" in report["reasons"]


def test_moneyline_rejects_threshold(tmp_path):
    path = _pair(tmp_path)
    payload = json.loads(path.read_text())
    payload["identity"].update({"market": "MONEYLINE", "threshold": 0})
    for label in ("decision", "close"):
        payload[label].update({"market": "MONEYLINE", "threshold": 0})
    path.write_text(json.dumps(payload))
    report = audit_cfb_forward_market_pair(path)
    assert report["paired_market_evidence_present"] is False
    assert "MONEYLINE_THRESHOLD_FORBIDDEN" in report["reasons"]

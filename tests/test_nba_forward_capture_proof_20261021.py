"""No authority from copyable files; exact row conservation and price/timestamp tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import pytest

from scripts.audit_nba_capture_ledger import main as audit_cli_main
from sportsedge.forward_validation.nba_full_board_ledger import build_nba_props_entry_ledger
from sportsedge.nba_phone_prop_pricing import ENGINE_ID
from sportsedge.validation.nba_forward_capture_proof import (
    audit_capture, NbaCaptureAuditError, _sha,
)


def fixture():
    over = {"market": "PLAYER_POINTS", "side": "OVER", "line": 22.5,
            "odds": -110, "capture_id": "cap-oct21", "event_id": "event-1",
            "player_name": "Test Player", "book": "DraftKings",
            "event_start": "2026-10-21T19:30:00-05:00",
            "quote_captured_at": "2026-10-21T18:57:00-05:00"}
    under = {**over, "side": "UNDER", "odds": -105}
    raw = {"lines": [over, under]}
    priced = [
        {"status": "PRICED_RESEARCH", "coverage_market": "player_points",
         "side": row["side"], "line": 22.5, "odds": row["odds"],
         "player_id": "123", "player_name": "Test Player",
         "nba_prop_engine": {"engine_id": ENGINE_ID, "prior_games": 12},
         "p_over": 0.55, "p_under": 0.45, "p_push": 0.0}
        for row in raw["lines"]
    ]
    ledger = build_nba_props_entry_ledger(
        raw["lines"], priced, run_id="run-fixture",
        source_ref="asserted-screenshot-ref",
        recorded_at="2026-10-21T18:58:00-05:00",
        slate_date="2026-10-21")
    assert len(ledger["ledger"]) == 1
    return raw, ledger


def test_capture_only_does_not_invent_forward_records():
    raw, _ = fixture()
    result = audit_capture(raw)
    assert result["total_raw_rows"] == 2
    assert result["complete_pair_shape_groups"] == 1
    assert result["status"] == "CAPTURE_STRUCTURE_ONLY_NO_LEDGER"
    assert result["verified_model_family_count"] == 0
    assert result["forward_validation_credit"] == "NONE"
    assert result["canonical_raw_json_sha256"] == _sha(raw)
    assert "raw_file_bytes_sha256" not in result  # API never receives physical bytes
    assert "raw_capture_sha256" not in result  # ambiguous old name retired


def test_real_builder_produced_ledger_reconciles_without_promoting():
    raw, ledger = fixture()
    result = audit_capture(raw, ledger)
    assert result["ledger_rows_structurally_reconciled"] == 1
    assert result["status"] == "LEDGER_STRUCTURALLY_RECONCILED_NOT_SOURCE_ATTESTED"
    assert result["verified_market_admission"] is False
    assert result["play_authority"] is False


def test_any_unaccounted_capture_row_is_refused():
    raw, ledger = fixture()
    raw["lines"].append({**raw["lines"][0], "event_id": "other", "side": "OVER"})
    with pytest.raises(NbaCaptureAuditError, match="RAW_COUNT_MISMATCH"):
        audit_capture(raw, ledger)


def test_price_tamper_is_visible():
    raw, ledger = fixture()
    raw["lines"][1]["odds"] = +115
    with pytest.raises(NbaCaptureAuditError, match="PRICE_DRIFT"):
        audit_capture(raw, ledger)


def test_ledger_digest_is_byte_identity_not_attestation():
    raw, ledger = fixture()
    assert audit_capture(raw, ledger)["ledger_sha256"] == ledger["ledger_sha256"]
    ledger["ledger"][0]["entry_prices"]["UNDER"] = -120
    with pytest.raises(NbaCaptureAuditError, match="CONTENT_SHA_MISMATCH"):
        audit_capture(raw, ledger)


def test_stale_quote_at_recording_refuses_even_if_old_ledger_accepted_it():
    raw, ledger = fixture()
    ledger["ledger"][0]["recorded_at"] = "2026-10-21T19:03:00-05:00"
    ledger["ledger_sha256"] = _sha(ledger["ledger"])
    with pytest.raises(NbaCaptureAuditError, match="QUOTE_STALE_AT_RECORDING"):
        audit_capture(raw, ledger)


def test_altered_recorded_time_before_capture_refuses():
    raw, ledger = fixture()
    ledger["ledger"][0]["recorded_at"] = "2026-10-21T18:56:00-05:00"
    ledger["ledger_sha256"] = _sha(ledger["ledger"])
    with pytest.raises(NbaCaptureAuditError, match="NONCAUSAL_OR_POSTTIP"):
        audit_capture(raw, ledger)


def test_forged_authority_cannot_pass():
    raw, ledger = fixture()
    ledger["ledger"][0]["eligible"] = True
    ledger["ledger_sha256"] = _sha(ledger["ledger"])
    with pytest.raises(NbaCaptureAuditError, match="FALSE_BETTING_AUTHORITY"):
        audit_capture(raw, ledger)


def test_probabilities_must_conserve_mass():
    raw, ledger = fixture()
    ledger["ledger"][0]["model_p"]["OVER"] = 0.99
    ledger["ledger_sha256"] = _sha(ledger["ledger"])
    with pytest.raises(NbaCaptureAuditError, match="MODEL_PROBABILITIES_INVALID"):
        audit_capture(raw, ledger)


def test_missing_pair_cannot_masquerade_as_ledger_pair():
    raw, ledger = fixture()
    raw["lines"][1]["capture_id"] = "other-capture"
    with pytest.raises(NbaCaptureAuditError, match="PAIR_TO_CAPTURE_JOIN_AMBIGUOUS"):
        audit_capture(raw, ledger)


def test_semantic_digest_is_not_a_raw_byte_digest(tmp_path):
    raw, ledger = fixture()
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    pretty = json.dumps(raw, indent=2, ensure_ascii=True)
    assert canonical != pretty
    p1, p2 = tmp_path / "compact.json", tmp_path / "pretty.json"
    p1.write_text(canonical, encoding="utf-8")
    p2.write_text(pretty, encoding="utf-8")
    out1, out2 = tmp_path / "audit1.json", tmp_path / "audit2.json"
    assert audit_cli_main(["--raw-board", str(p1), "--out", str(out1)]) == 0
    assert audit_cli_main(["--raw-board", str(p2), "--out", str(out2)]) == 0
    a = json.loads(out1.read_text())
    b = json.loads(out2.read_text())
    assert a["canonical_raw_json_sha256"] == b["canonical_raw_json_sha256"]
    assert a["raw_file_bytes_sha256"] != b["raw_file_bytes_sha256"]
    assert a["raw_file_bytes_sha256"] == hashlib.sha256(p1.read_bytes()).hexdigest()
    assert b["raw_file_bytes_sha256"] == hashlib.sha256(p2.read_bytes()).hexdigest()
    assert a["verified_market_admission"] is False
    assert a["forward_validation_credit"] == "NONE"
    assert b["play_authority"] is False


def test_ledger_reconciliation_cli_keeps_file_and_semantic_digests_separate(tmp_path):
    raw, ledger = fixture()
    r = tmp_path / "raw.json"
    l = tmp_path / "ledger.json"
    o = tmp_path / "report.json"
    r.write_bytes(json.dumps(raw, indent=4).encode("utf-8"))
    l.write_text(json.dumps(ledger), encoding="utf-8")
    assert audit_cli_main(["--raw-board", str(r), "--ledger", str(l), "--out", str(o)]) == 0
    report = json.loads(o.read_text())
    assert report["raw_file_bytes_sha256"] == hashlib.sha256(r.read_bytes()).hexdigest()
    assert report["canonical_raw_json_sha256"] == _sha(raw)
    assert report["ledger_sha256"] == ledger["ledger_sha256"]
    assert report["forward_validation_credit"].startswith("NONE")
    assert report["provider_quote_authentication"] == "NOT_ESTABLISHED_FROM_INPUT"

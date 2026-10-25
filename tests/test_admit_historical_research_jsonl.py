import json
from datetime import datetime, timedelta, timezone

from scripts.admit_historical_research_jsonl import admit, run


def row():
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    ts = lambda hours: (now + timedelta(hours=hours)).isoformat()
    return dict(sport="MLB", market="ML", event_id="game-1", season=2025,
                event_start_ts=ts(4), decision_ts=ts(0), feature_asof_ts=ts(-1),
                outcome=1, model_p=0.55, benchmark_p=0.52,
                offered_decimal=2.0, selected=False, source_id="fixture",
                source_url="https://example.org/fixture", model_version="frozen-v1",
                model_run_id="run-1", feature_receipt_ts=ts(-1),
                prediction_receipt_ts=ts(0), quote_source="book-receipt",
                quote_receipt_ts=ts(0), outcome_source="official-final")


def test_admits_complete_receipts():
    assert admit(row()) is None


def test_rejects_future_quote():
    r = row()
    r["quote_receipt_ts"] = r["event_start_ts"]
    assert admit(r) == "RECEIPT_AFTER_DECISION"


def test_rejects_missing_price():
    r = row()
    r.pop("offered_decimal")
    assert admit(r) == "MISSING_OFFERED_PRICE"


def test_rejects_missing_provenance():
    r = row()
    r.pop("model_run_id")
    assert admit(r) == "MISSING_MODEL_RUN_ID"


def test_records_blocked_and_accepted(tmp_path):
    good = row()
    bad = {**good, "quote_receipt_ts": good["event_start_ts"]}
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n")
    accepted = tmp_path / "accepted.jsonl"
    blocked = tmp_path / "blocked.jsonl"
    assert run(source, accepted, blocked) == {"accepted": 1, "blocked": 1}
    assert json.loads(blocked.read_text())["reason"] == "RECEIPT_AFTER_DECISION"


def test_rejects_future_decision():
    from datetime import datetime, timedelta, timezone
    r = row()
    future = datetime.now(timezone.utc) + timedelta(days=1)
    r["decision_ts"] = future.isoformat()
    r["event_start_ts"] = (future + timedelta(hours=1)).isoformat()
    assert admit(r) == "DECISION_IN_FUTURE"


def test_rejects_duplicate_event_decision(tmp_path):
    r = row()
    source = tmp_path / "duplicate.jsonl"
    source.write_text(json.dumps(r) + "\n" + json.dumps(r) + "\n")
    accepted = tmp_path / "accepted.jsonl"
    blocked = tmp_path / "blocked.jsonl"
    assert run(source, accepted, blocked) == {"accepted": 1, "blocked": 1}
    assert json.loads(blocked.read_text())["reason"] == "DUPLICATE_SELECTION_DECISION"


def test_same_event_decision_different_selection_is_duplicate(tmp_path):
    first = {**row(), "selection": "HOME"}
    second = {**row(), "selection": "AWAY"}
    source = tmp_path / "selection-duplicates.jsonl"
    source.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n")
    accepted = tmp_path / "accepted.jsonl"
    blocked = tmp_path / "blocked.jsonl"
    assert run(source, accepted, blocked) == {"accepted": 1, "blocked": 1}
    assert json.loads(blocked.read_text())["reason"] == "DUPLICATE_SELECTION_DECISION"

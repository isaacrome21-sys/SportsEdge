"""#2166 review: post-read receipt, persisted verifiable bounds, restart/replay/tamper."""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from sportsedge import mlb_source as ms

T0 = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
URL = "https://x/api/v1/schedule"


def _seq(*times):
    seq = list(times)
    return lambda: seq.pop(0) if len(seq) > 1 else seq[0]


@contextmanager
def _trusted(*times):
    with patch.object(ms, "_trusted_now", _seq(*times)):
        yield


class _Delayed:
    """Response whose body completes 3s after fetch start (trusted clock advances)."""
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self.raw


def _capture_one(root, raw=b"{}", start=T0, end=T0 + timedelta(seconds=1), clock=None):
    rec = ms.MLBSourceCapture(root, clock=clock or (lambda: start))
    with _trusted(end):
        return rec, rec.record(url=URL, raw=raw, fetch_started_at=start, received_at=end)


def test_delayed_response_with_clock_injected_at_fetch_start_stamps_completion(tmp_path):
    end = T0 + timedelta(seconds=3)
    with _trusted(T0, end, end):  # start, receipt, anchor
        with ms.capture_mlb_source_bytes(tmp_path, clock=lambda: T0) as cap:
            ms._get_json(URL, lambda *a, **k: _Delayed(b"{}"))
    r = cap.records[0]
    assert r.observed_at_utc == end.isoformat() == r.received_at_utc
    assert r.fetch_started_at_utc == T0.isoformat()
    assert r.recorder_clock_assertion_utc == T0.isoformat()  # kept, non-evidentiary


def test_persisted_bounds_survive_independent_verifier(tmp_path):
    _capture_one(tmp_path)
    entries = ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(days=1))
    assert len(entries) == 1
    e = entries[0]
    assert e["fetch_started_at_utc"] == T0.isoformat()
    assert e["received_at_utc"] == e["observed_at_utc"]
    assert e["prev_record_sha256"] == ms.GENESIS_SHA256 and len(e["receipt_nonce"]) == 32


def test_restart_cannot_readmit_same_receipt(tmp_path):
    _capture_one(tmp_path)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_DUPLICATE_REPLAY"):
        _capture_one(tmp_path)
    # a genuinely new receipt after restart extends the chain
    rec, r2 = _capture_one(tmp_path, start=T0 + timedelta(seconds=5), end=T0 + timedelta(seconds=6))
    assert r2.sequence == 2
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))) == 2


def _rewrite(tmp_path, mutate):
    j = tmp_path / ms.RECEIPT_JOURNAL_NAME
    lines = [json.loads(x) for x in j.read_text().splitlines()]
    mutate(lines)
    j.write_text("".join(json.dumps(x) + "\n" for x in lines))


@pytest.mark.parametrize("field,value,reason", [
    ("received_at_utc", "2000-01-01T00:00:00+00:00", "TAMPERED"),
    ("observed_at_utc", "2026-10-13T15:59:59+00:00", "TAMPERED"),
    ("fetch_started_at_utc", "2099-01-01T00:00:00+00:00", "TAMPERED"),
    ("url", "https://x/api/v1/other", "TAMPERED"),
])
def test_edited_entry_fails_closed(tmp_path, field, value, reason):
    _capture_one(tmp_path)
    _rewrite(tmp_path, lambda ls: ls[0].__setitem__(field, value))
    with pytest.raises(ms.MLBSourceError, match=reason):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))
    with pytest.raises(ms.MLBSourceError):  # and a restarted recorder refuses the root
        ms.MLBSourceCapture(tmp_path)


def _resign(entry):
    entry["record_sha256"] = ms._record_hash(entry)


@pytest.mark.parametrize("field,value,reason", [
    ("received_at_utc", "2000-01-01T00:00:01+00:00", "OBSERVED_NOT_POST_READ"),
    ("observed_at_utc", "2026-10-13T16:00:00.500000+00:00", "OBSERVED_NOT_POST_READ"),
])
def test_resigned_out_of_bounds_entry_still_fails(tmp_path, field, value, reason):
    _capture_one(tmp_path)
    def m(ls):
        ls[0][field] = value; _resign(ls[0])
    _rewrite(tmp_path, m)
    with pytest.raises(ms.MLBSourceError, match=reason):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))


@pytest.mark.parametrize("start,end,reason", [
    (datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2000, 1, 1, 0, 0, 1, tzinfo=timezone.utc), "IMPLAUSIBLY_OLD"),
    (datetime(2099, 1, 1, tzinfo=timezone.utc), datetime(2099, 1, 1, 0, 0, 1, tzinfo=timezone.utc), "FUTURE_VS_VERIFIER"),
    (T0, T0 + timedelta(seconds=31), "FETCH_SPAN_UNBOUNDED"),
    (T0, T0 - timedelta(seconds=1), "BACKWARDS"),
])
def test_resigned_year_2000_2099_and_span_fail(tmp_path, start, end, reason):
    _capture_one(tmp_path)
    def m(ls):
        ls[0]["fetch_started_at_utc"] = start.isoformat()
        ls[0]["received_at_utc"] = ls[0]["observed_at_utc"] = end.isoformat()
        _resign(ls[0])
    _rewrite(tmp_path, m)
    with pytest.raises(ms.MLBSourceError, match=reason):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))


@pytest.mark.parametrize("field", ["fetch_started_at_utc", "received_at_utc", "receipt_nonce",
                                   "record_sha256", "prev_record_sha256", "sha256"])
def test_missing_field_fails_closed(tmp_path, field):
    _capture_one(tmp_path)
    _rewrite(tmp_path, lambda ls: ls[0].pop(field))
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_FIELD_MISSING"):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))


def test_duplicated_line_and_deleted_line_fail(tmp_path):
    _capture_one(tmp_path)
    _capture_one(tmp_path, start=T0 + timedelta(seconds=5), end=T0 + timedelta(seconds=6))
    _rewrite(tmp_path, lambda ls: ls.append(dict(ls[1])))
    with pytest.raises(ms.MLBSourceError):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))
    _rewrite(tmp_path, lambda ls: (ls.pop(), ls.pop(0)))
    with pytest.raises(ms.MLBSourceError, match="SEQUENCE_GAP|CHAIN_BROKEN"):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))


def test_raw_byte_tamper_detected(tmp_path):
    _, r = _capture_one(tmp_path, raw=b'{"a":1}')
    with open(r.path, "wb") as fh:
        fh.write(b'{"a":2}')
    with pytest.raises(ms.MLBSourceError, match="RAW_BYTES_TAMPERED"):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))


def test_historical_postgame_schedule_is_never_as_of_proof(tmp_path):
    _capture_one(tmp_path)  # fetched today (T0)
    entry = ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))[0]
    old_first_pitch = datetime(2025, 7, 1, 23, 5, tzinfo=timezone.utc)
    assert ms.receipt_supports_as_of(entry, old_first_pitch) is False
    assert ms.receipt_supports_as_of(entry, T0 + timedelta(hours=2)) is True
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_FIELD_MISSING"):
        ms.receipt_supports_as_of({}, T0)


def test_recorder_rejects_implausibly_old_start_even_if_fresh_receipt(tmp_path):
    rec = ms.MLBSourceCapture(tmp_path, clock=lambda: T0)
    with _trusted(T0):
        with pytest.raises(ms.MLBSourceError):
            rec.record(url=URL, raw=b"{}", fetch_started_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
                       received_at=T0)
    assert not (tmp_path / ms.RECEIPT_JOURNAL_NAME).exists()

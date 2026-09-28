from __future__ import annotations

import csv
import gzip
from hashlib import sha1
import io

import pytest

import scripts.audit_cfb_historical_lines_source as audit_mod


def _gzip_csv(fieldnames: list[str], rows: list[dict[str, object]]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return gzip.compress(buf.getvalue().encode("utf-8"), mtime=0)


def _blob_sha(raw: bytes) -> str:
    return sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def test_archive_without_quote_timestamp_stays_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    fields = [
        "game_id",
        "season",
        "date_time",
        "market_type",
        "lines",
        "opening_lines",
        "odds",
        "opening_odds",
        "book",
    ]
    raw = _gzip_csv(
        fields,
        [
            {
                "game_id": 1,
                "season": 2025,
                "date_time": "2025-09-01T00:00:00Z",
                "market_type": "spread",
                "lines": -3.5,
                "opening_lines": -2.5,
                "odds": "",
                "opening_odds": "",
                "book": "DraftKings",
            }
        ],
    )
    monkeypatch.setattr(audit_mod, "DATA_GIT_BLOB_SHA1", _blob_sha(raw))
    report = audit_mod.audit(raw)
    assert report["status"] == "CANDIDATE_ONLY_BLOCKED_NO_QUOTE_TIMESTAMP"
    assert report["quote_timestamp_columns"] == []
    assert report["closing_semantics_verified"] is False
    assert report["truth_gate_authority"] is False
    assert report["estimate_p_input_allowed"] is False


def test_quote_timestamp_presence_only_advances_to_crosscheck(monkeypatch: pytest.MonkeyPatch) -> None:
    fields = [
        "game_id",
        "season",
        "date_time",
        "quote_timestamp_utc",
        "market_type",
        "lines",
        "opening_lines",
        "book",
    ]
    raw = _gzip_csv(
        fields,
        [
            {
                "game_id": 1,
                "season": 2024,
                "date_time": "2024-09-01T00:00:00Z",
                "quote_timestamp_utc": "2024-08-31T23:40:00Z",
                "market_type": "total",
                "lines": 51.5,
                "opening_lines": 49.5,
                "book": "BookA",
            }
        ],
    )
    monkeypatch.setattr(audit_mod, "DATA_GIT_BLOB_SHA1", _blob_sha(raw))
    report = audit_mod.audit(raw)
    assert report["status"] == "CANDIDATE_TIMESTAMP_PRESENT_REQUIRES_INDEPENDENT_CLOSE_CROSSCHECK"
    assert report["quote_timestamp_columns"] == ["quote_timestamp_utc"]
    assert report["closing_semantics_verified"] is True
    assert report["truth_gate_authority"] is False


def test_unpinned_archive_bytes_fail_closed() -> None:
    raw = _gzip_csv(["season"], [{"season": 2025}])
    with pytest.raises(RuntimeError, match="GIT_BLOB_MISMATCH"):
        audit_mod.audit(raw)

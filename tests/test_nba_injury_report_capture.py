import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sportsedge.sports.nba import injury_report_capture as c

FX = Path(__file__).parent / "fixtures" / "nba_injury_reports"
MAN = json.loads((FX / "manifest.json").read_text())
SLOT = "2025-03-10_06PM"
RAW = base64.b64decode((FX / f"Injury-Report_{SLOT}.pdf.b64").read_text())
TXT = (FX / f"Injury-Report_{SLOT}.txt").read_text()
SLOT_UTC = datetime(2025, 3, 10, 22, 0, tzinfo=timezone.utc)  # 6 PM EDT slot label
LAST_TIP = datetime(2025, 3, 11, 2, 30, tzinfo=timezone.utc)


def rec(at, prev=c.GENESIS, lm=MAN[SLOT]["http_last_modified"], text=TXT, start=None):
    with patch.object(c, "_trusted_now", lambda: at):
        return c.capture_record(prev_hash=prev, slot_utc=SLOT_UTC, url=MAN[SLOT]["url"], raw=RAW,
                                extracted_text=text, http_status=200, http_last_modified=lm,
                                extractor="pdftotext", last_tipoff_utc=LAST_TIP,
                                fetch_started_at=start or at - timedelta(seconds=1))


def test_receipt_separate_from_header_effective_time_and_on_time():
    r = rec(datetime(2025, 3, 10, 22, 31, tzinfo=timezone.utc))
    assert r["effective_at_utc"] == "2025-03-10T22:30:00+00:00"
    assert r["received_at_utc"] == "2025-03-10T22:31:00+00:00"
    assert r["status"] == "ON_TIME" and r["usable"] and r["rows"] == 186
    assert r["pdf_sha256"] == MAN[SLOT]["pdf_sha256"] and r["participation"] == "UNKNOWN"
    assert r["permission"].startswith("UNVERIFIED")


def test_late_and_after_last_tipoff():
    assert rec(datetime(2025, 3, 10, 23, 30, tzinfo=timezone.utc))["status"] == "LATE"
    assert rec(datetime(2025, 3, 11, 3, 0, tzinfo=timezone.utc))["status"] == "AFTER_LAST_TIPOFF"


def test_missed_records_explicit():
    with patch.object(c, "_trusted_now", lambda: datetime(2025, 3, 11, 0, 0, tzinfo=timezone.utc)):
        m = c.missed_record(prev_hash=c.GENESIS, slot_utc=SLOT_UTC, url="u", reason="HTTP_403")
        assert m["status"] == "MISSED" and not m["usable"]
        with pytest.raises(c.CaptureError):
            c.missed_record(prev_hash=c.GENESIS, slot_utc=SLOT_UTC, url="u", reason="whatever")


def test_time_inconsistent_and_parse_failure_flagged_unusable():
    r = rec(datetime(2025, 3, 10, 22, 31, tzinfo=timezone.utc), lm="Mon, 10 Mar 2025 23:30:04 GMT")
    assert "TIME_INCONSISTENT" in r["flags"] and not r["usable"]
    bad = rec(datetime(2025, 3, 10, 22, 31, tzinfo=timezone.utc), text="garbage")
    assert bad["flags"][0].startswith("PARSE_FAILED") and not bad["usable"]


def test_receipt_before_effective_is_unusable():
    r = rec(datetime(2025, 3, 10, 22, 10, tzinfo=timezone.utc))  # before 22:30 header
    assert not r["usable"] and r["flags"][0].startswith("PARSE_FAILED:RECEIPT_BEFORE")


def test_hash_chain_with_external_anchor_detects_tampering():
    a = rec(datetime(2025, 3, 10, 22, 31, tzinfo=timezone.utc))
    with patch.object(c, "_trusted_now", lambda: datetime(2025, 3, 10, 23, 50, tzinfo=timezone.utc)):
        b = c.missed_record(prev_hash=a["line_sha256"], slot_utc=SLOT_UTC + timedelta(hours=1),
                            url="u", reason="NOT_PUBLISHED")
    head = b["line_sha256"]  # stored outside the log
    assert c.verify_chain([a, b], anchored_head=head)
    t = dict(a, received_at_utc="2025-03-10T22:00:00+00:00")
    assert not c.verify_chain([t, b], anchored_head=head)
    assert not c.verify_chain([a], anchored_head=head)  # truncation


def test_as_of_uses_receipt_time_only():
    a = rec(datetime(2025, 3, 10, 22, 31, tzinfo=timezone.utc))
    assert c.usable_as_of([a], datetime(2025, 3, 10, 22, 31, tzinfo=timezone.utc)) is None
    assert c.usable_as_of([a], datetime(2025, 3, 10, 22, 32, tzinfo=timezone.utc)) == a


def test_no_network_or_scheduler_surface():
    src = Path(c.__file__).read_text()
    for banned in ("urllib", "requests", "urlopen", "schedule", "cron", "boto3", "subprocess"):
        assert banned not in src.split('"""', 2)[2], banned

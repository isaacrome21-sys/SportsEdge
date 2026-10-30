from contextlib import nullcontext
from datetime import datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest

from scripts.parse_nba_injury_archive import parse_archive_pdf, parse_rows
from sportsedge.nba_injury_report import ET, slot_url

PDF = b"%PDF-1.7 test-only fixture"
PUBLISHED = datetime(2026, 10, 25, 11, 15, tzinfo=ET)


def receipt(**changes):
    r = dict(status="ARCHIVED", url=slot_url(PUBLISHED.date(), PUBLISHED.time()),
             report_time_et=PUBLISHED.isoformat(),
             fetched_at=(PUBLISHED + timedelta(minutes=2)).isoformat(),
             sha256=sha256(PDF).hexdigest())
    r.update(changes)
    return r


def pdf_factory(blob):
    assert blob == PDF
    page = SimpleNamespace(
        extract_text=lambda: "Injury Report: 10/25/26 11:15 AM\nPage 1 of 1",
        extract_tables=lambda: [[
            ["Game Date", "Game Time", "Matchup", "Team", "Player Name", "Current Status", "Reason"],
            ["10/25/2026", "07:00 (ET)", "BOS@NYK", "Boston Celtics", "Tatum, Jayson", "Out", "Injury/Illness - Foot"],
            ["", "", "", "", "Brown, Jaylen", "Questionable", "Injury/Illness - Knee"],
            ["", "", "", "New York Knicks", "", "", "NOT YET SUBMITTED"],
        ]],
    )
    return nullcontext(SimpleNamespace(pages=[page]))


def test_real_receipt_and_context_carry_without_price():
    rows = parse_archive_pdf(PDF, receipt(), open_pdf=pdf_factory,
                             decision_time=(PUBLISHED + timedelta(minutes=3)).isoformat())
    assert len(rows) == 2
    assert rows[0]["event_id"] == "NBA:2026-10-25:BOS@NYK"
    assert rows[1]["player"] == "Brown, Jaylen"
    assert rows[1]["team"] == "Boston Celtics"
    assert rows[1]["status"] == "Questionable"
    assert rows[0]["pit_at_decision"] is True
    assert rows[0]["pricing_eligible"] is False and rows[0]["ladder_status"] == "PAPER"
    assert rows[0]["source_sha256"] == sha256(PDF).hexdigest()


def test_no_decision_never_asserts_point_in_time_decision():
    rows = parse_archive_pdf(PDF, receipt(), open_pdf=pdf_factory)
    assert all(r["pit_at_decision"] is False for r in rows)


@pytest.mark.parametrize("bad_receipt,error", [
    ({"sha256": "x" * 64}, "PDF_SHA256_MISMATCH"),
    ({"status": "SLOT_NOT_PUBLISHED"}, "PDF_NOT_ARCHIVED"),
    ({"fetched_at": (PUBLISHED - timedelta(seconds=1)).isoformat()}, "FETCHED_BEFORE_PUBLICATION"),
    ({"report_time_et": "2026-10-25T11:15:00"}, "TIMESTAMP_OFFSET_REQUIRED"),
    ({"url": "https://not.nba.example/report.pdf"}, "PDF_URL_NOT_OFFICIAL_SLOT"),
])
def test_untrusted_receipts_refused(bad_receipt, error):
    with pytest.raises(ValueError, match=error):
        parse_archive_pdf(PDF, receipt(**bad_receipt), open_pdf=pdf_factory)


def test_decision_cutoff_checks_both_publication_and_actual_fetch():
    with pytest.raises(ValueError, match="NO_LOOKAHEAD"):
        parse_archive_pdf(PDF, receipt(), open_pdf=pdf_factory,
                          decision_time=(PUBLISHED + timedelta(minutes=1)).isoformat())
    with pytest.raises(ValueError, match="NO_LOOKAHEAD"):
        parse_archive_pdf(PDF, receipt(), open_pdf=pdf_factory,
                          decision_time=(PUBLISHED - timedelta(minutes=1)).isoformat())


def test_player_with_missing_status_fails_closed():
    rows = [[["10/25/2026", "07:00 (ET)", "BOS@NYK", "Boston Celtics", "Tatum, Jayson", "", "Foot"]]]
    with pytest.raises(ValueError, match="PLAYER_STATUS_UNRECOGNIZED"):
        parse_rows(rows)


def test_player_with_missing_event_context_fails_closed():
    with pytest.raises(ValueError, match="PLAYER_EVENT_CONTEXT_MISSING"):
        parse_rows([[["", "", "", "", "Player, A", "Out", "Foot"]]])


def test_extractor_title_must_match_receipt():
    wrong = SimpleNamespace(extract_text=lambda: "Injury Report: 10/25/26 11:30 AM",
                            extract_tables=lambda: [])
    with pytest.raises(ValueError, match="PDF_TITLE_TIME_MISMATCH"):
        parse_archive_pdf(PDF, receipt(), open_pdf=lambda b: nullcontext(SimpleNamespace(pages=[wrong])))

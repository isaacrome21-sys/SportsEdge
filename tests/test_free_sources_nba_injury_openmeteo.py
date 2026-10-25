"""NBA official injury-report archiver + Open-Meteo previous-runs adapter (research only)."""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from scripts.archive_nba_injury_reports import archive_day
from scripts.capture_open_meteo_previous_runs import main as meteo_main
from sportsedge.nba_injury_report import ET, InjuryReportError, day_slots, make_receipt, slot_label, slot_url
from sportsedge.open_meteo_previous_runs import VARIABLES, PreviousRunsError, hour_record, previous_runs_url

PDF = b"%PDF-1.7 fake report"


def test_slot_labels_and_url():
    assert slot_label(time(17, 30)) == "05_30PM"
    assert slot_label(time(0, 0)) == "12_00AM"
    assert slot_label(time(12, 15)) == "12_15PM"
    assert slot_url(date(2026, 10, 25), time(9, 45)).endswith("Injury-Report_2026-10-25_09_45AM.pdf")
    with pytest.raises(InjuryReportError):
        slot_label(time(17, 10))
    assert len(day_slots(date(2026, 10, 25), time(11, 0), time(12, 0))) == 5


def test_receipt_fail_closed():
    rt = datetime(2026, 10, 25, 17, 30, tzinfo=ET)
    ok = make_receipt(url="u", report_time=rt, fetched_at=rt + timedelta(minutes=5), http_status=200, body=PDF)
    assert ok.status == "ARCHIVED" and ok.bytes == len(PDF) and len(ok.sha256) == 64
    assert make_receipt(url="u", report_time=rt, fetched_at=rt, http_status=404, body=None).status == "SLOT_NOT_PUBLISHED"
    assert make_receipt(url="u", report_time=rt, fetched_at=rt, http_status=200, body=b"<html>").status == "NOT_A_PDF"
    with pytest.raises(InjuryReportError):
        make_receipt(url="u", report_time=rt, fetched_at=rt - timedelta(seconds=1), http_status=200, body=PDF)
    with pytest.raises(InjuryReportError):
        make_receipt(url="u", report_time=rt.replace(tzinfo=None), fetched_at=rt, http_status=200, body=PDF)
    with pytest.raises(InjuryReportError):
        make_receipt(url="u", report_time=rt, fetched_at=rt, http_status=500, body=None)


def test_archive_day_skips_future_and_done(tmp_path):
    now = datetime(2026, 10, 25, 11, 20, tzinfo=ET).astimezone(timezone.utc)
    calls = []

    def fetch(url):
        calls.append(url)
        return (200, PDF) if url.endswith("11_00AM.pdf") else (404, None)

    rows = archive_day(date(2026, 10, 25), time(11, 0), time(11, 45), tmp_path, fetch, lambda: now)
    assert [r["status"] for r in rows] == ["ARCHIVED", "SLOT_NOT_PUBLISHED"]  # 11:30, 11:45 are future
    assert (tmp_path / "2026-10-25" / "Injury-Report_2026-10-25_11_00AM.pdf").read_bytes() == PDF
    calls.clear()
    archive_day(date(2026, 10, 25), time(11, 0), time(11, 45), tmp_path, fetch, lambda: now)
    assert not any(c.endswith("11_00AM.pdf") for c in calls)  # archived slot not refetched


def _payload(lead=1, value=55.0):
    times = [f"2026-10-25T{h:02d}:00" for h in range(24)]
    hourly = {"time": times}
    for v in VARIABLES:
        hourly[f"{v}_previous_day{lead}"] = [value] * 24
    return {"hourly": hourly}


VALID = datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)


def test_previous_runs_url_and_record():
    url = previous_runs_url(30.285, -97.732, VALID, 2)
    assert "previous-runs-api.open-meteo.com" in url and "temperature_2m_previous_day2" in url
    rec = hour_record(_payload(), VALID, 1, decision_time=VALID - timedelta(hours=2))
    assert rec["historical_pit"] is False and rec["availability"] == "LEAD_TIME_BOUND"
    assert rec["available_no_later_than_utc"] == "2026-10-24T00:00:00+00:00"
    assert rec["values"]["temperature_2m"] == 55.0


@pytest.mark.parametrize("bad", [
    lambda: previous_runs_url(91, 0, VALID),
    lambda: previous_runs_url(0, 0, VALID.replace(tzinfo=None)),
    lambda: previous_runs_url(0, 0, VALID, 0),
    lambda: hour_record(_payload(), VALID, 1, decision_time=VALID - timedelta(days=2)),  # lead too short
    lambda: hour_record(_payload(value=float("nan")), VALID, 1),
    lambda: hour_record(_payload(lead=2), VALID, 1),  # series missing
    lambda: hour_record({"hourly": {"time": []}}, VALID, 1),
])
def test_previous_runs_fail_closed(bad):
    with pytest.raises(PreviousRunsError):
        bad()


def test_meteo_cli():
    args = ["--lat", "30.285", "--lon", "-97.732", "--valid", "2026-10-25T00:00:00Z"]
    assert meteo_main(args, fetch=lambda url: _payload()) == 0
    assert meteo_main(args + ["--decision", "2026-10-23T00:00:00Z"], fetch=lambda url: _payload()) == 2

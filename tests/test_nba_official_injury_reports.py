"""Offline adversarial tests for the unadmitted NBA injury PDF archive."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.collect_nba_official_injury_reports import (
    archive_pdf,
    discover_reports,
    latest_for_date,
    main,
    validate_pdf,
)


def _anchor(url: str) -> str:
    return f'<a href="{url}">report</a>'


def _report() -> dict[str, str]:
    return {
        "url": (
            "https://ak-static.cms.nba.com/referee/injury/"
            "Injury-Report_2026-10-24_10_15PM.pdf"
        ),
        "report_date_et": "2026-10-24",
        "filename_time_et": "2026-10-24T22:15:00-04:00",
    }


def test_official_link_allowlist_and_newest_selection() -> None:
    valid_old = (
        "https://ak-static.cms.nba.com/referee/injury/"
        "Injury-Report_2026-10-24_09_00PM.pdf"
    )
    valid_new = _report()["url"]
    html = "".join(
        _anchor(url)
        for url in (
            "https://evil.example/referee/injury/Injury-Report_2026-10-24_11_00PM.pdf",
            "http://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-24_11_00PM.pdf",
            "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-24_11_00PM.pdf?extra=1",
            valid_old,
            valid_new,
            valid_new,
        )
    )
    reports = discover_reports(html)
    assert [report["url"] for report in reports] == [valid_new, valid_old]
    assert latest_for_date(reports, "2026-10-24")["url"] == valid_new


def test_wrong_dates_or_missing_reports_fail_closed() -> None:
    reports = discover_reports(_anchor(_report()["url"]))
    with pytest.raises(ValueError, match="NO_OFFICIAL_REPORT_FOR_DATE"):
        latest_for_date(reports, "2026-10-25")
    with pytest.raises(ValueError):
        latest_for_date(reports, "10/24/2026")
    assert discover_reports("<html><body>No report</body></html>") == []


def test_malformed_official_filename_not_accepted() -> None:
    invalid_url = (
        "https://ak-static.cms.nba.com/referee/injury/"
        "Injury-Report_2026-02-30_10_15PM.pdf"
    )
    assert discover_reports(_anchor(invalid_url)) == []


def test_pdf_must_have_signature_and_end_marker() -> None:
    valid = b"%PDF-1.7\n1 0 obj\nendobj\n%%EOF"
    assert validate_pdf(valid) == hashlib.sha256(valid).hexdigest()
    with pytest.raises(ValueError, match="INVALID_PDF_BYTES"):
        validate_pdf(b"not a PDF")
    with pytest.raises(ValueError, match="INVALID_PDF_BYTES"):
        validate_pdf(b"%PDF-1.7\nno ending")


def test_archive_keeps_immutable_bytes_and_distinct_observation_receipts(
    tmp_path: Path,
) -> None:
    pdf = b"%PDF-1.7\n1 0 obj\nendobj\n%%EOF"
    first = archive_pdf(
        tmp_path, _report(), pdf, "2026-10-25T02:15:00+00:00",
        "2026-10-25T02:15:01+00:00",
    )
    second = archive_pdf(
        tmp_path, _report(), pdf, "2026-10-25T02:20:00+00:00",
        "2026-10-25T02:20:01+00:00",
    )
    assert first["model_p"] is None
    assert first["play_eligible"] is False
    assert first["pricing_input"] is False
    assert first["pit_available"] is False
    assert first["source_report_time_verified"] is False
    assert second["raw_pdf_sha256"] == first["raw_pdf_sha256"]
    assert len(list(tmp_path.glob("*.pdf"))) == 1
    receipts = [json.loads(f.read_text()) for f in tmp_path.glob("*.json")]
    assert len(receipts) == 2
    assert {item["pdf_received_at_utc"] for item in receipts} == {
        "2026-10-25T02:15:01+00:00",
        "2026-10-25T02:20:01+00:00",
    }


def test_archive_rejects_corrupted_existing_payload(tmp_path: Path) -> None:
    pdf = b"%PDF-1.7\n%%EOF"
    digest = hashlib.sha256(pdf).hexdigest()
    archive_path = tmp_path / f"2026-10-24_{digest}.pdf"
    archive_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="EXISTING_ARCHIVE_BYTES_CONFLICT"):
        archive_pdf(
            tmp_path, _report(), pdf,
            "2026-10-25T02:15:00+00:00",
            "2026-10-25T02:15:01+00:00",
        )
    assert archive_path.read_bytes() == b"tampered"
    assert not list(tmp_path.glob("*.json"))


def test_default_cli_does_not_call_network_or_write(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("offline CLI must not fetch")

    monkeypatch.setattr("scripts.collect_nba_official_injury_reports._fetch", forbidden)
    assert main(["--output-dir", str(tmp_path)]) == 0
    assert "DISABLED_REQUIRES_LIVE" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []

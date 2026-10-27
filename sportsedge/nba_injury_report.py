"""Official NBA injury report PDFs: URL slots + immutable receipts (research only).

The league publishes the official injury report as PDFs on a public static
host, several times per game day. The report time is in the file name
(US/Eastern), so every archived copy carries its own publication slot. This
module only builds slot URLs and receipts; it never parses player status and
never feeds pricing. Parsing and model use need separate review.

Receipt rules (fail closed):
* the fetch time must be offset-aware and not before the slot's report time;
* the body must be a PDF (``%PDF-`` magic), else ``NOT_A_PDF``;
* a 404/403 for a slot is ``SLOT_NOT_PUBLISHED`` (normal), never a guess.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BASE = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{day}_{slot}.pdf"
ET = ZoneInfo("America/New_York")
SCHEMA = "sportsedge.nba_injury_report_receipt.v1"


class InjuryReportError(ValueError):
    pass


def slot_label(at: time) -> str:
    """15-minute slot label used in the file name, e.g. 05_30PM."""
    if at.minute % 15 or at.second or at.microsecond:
        raise InjuryReportError(f"SLOT_NOT_QUARTER_HOUR:{at}")
    hour12 = at.hour % 12 or 12
    return f"{hour12:02d}_{at.minute:02d}{'AM' if at.hour < 12 else 'PM'}"


def slot_url(day: date, at: time) -> str:
    return BASE.format(day=day.isoformat(), slot=slot_label(at))


def day_slots(day: date, start: time = time(0, 0), end: time = time(23, 45)) -> list[tuple[datetime, str]]:
    """Every quarter-hour slot of ``day`` (ET) between start and end, with URL."""
    out = []
    cur = datetime.combine(day, start, tzinfo=ET)
    stop = datetime.combine(day, end, tzinfo=ET)
    while cur <= stop:
        out.append((cur, slot_url(day, cur.timetz().replace(tzinfo=None))))
        cur += timedelta(minutes=15)
    return out


@dataclass(frozen=True)
class Receipt:
    url: str
    report_time_et: str
    fetched_at: str
    status: str            # ARCHIVED | SLOT_NOT_PUBLISHED | NOT_A_PDF
    sha256: str | None = None
    bytes: int | None = None
    schema: str = SCHEMA

    def to_dict(self) -> dict:
        return asdict(self)


def make_receipt(*, url: str, report_time: datetime, fetched_at: datetime,
                 http_status: int, body: bytes | None) -> Receipt:
    if report_time.tzinfo is None or fetched_at.tzinfo is None:
        raise InjuryReportError("TIMESTAMP_TZ_REQUIRED")
    if fetched_at < report_time:
        raise InjuryReportError("FETCHED_BEFORE_REPORT_TIME")
    base = dict(url=url, report_time_et=report_time.astimezone(ET).isoformat(),
                fetched_at=fetched_at.isoformat())
    if http_status in (403, 404):
        return Receipt(status="SLOT_NOT_PUBLISHED", **base)
    if http_status != 200:
        raise InjuryReportError(f"HTTP_{http_status}")
    if not body or not body.startswith(b"%PDF-"):
        return Receipt(status="NOT_A_PDF", **base)
    return Receipt(status="ARCHIVED", sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), **base)

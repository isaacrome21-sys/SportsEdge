#!/usr/bin/env python3
"""Archive public NBA injury-report PDFs without making pricing claims.

No network request or filesystem mutation occurs unless --live is supplied.
Publication time inferred from a filename is NOT independently verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

INDEX_URL = "https://official.nba.com/nba-injury-report-2026-27-season/"
PDF_HOST = "ak-static.cms.nba.com"
REPORT_NAME = re.compile(
    r"^Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf$"
)
MAX_INDEX_BYTES = 4_000_000
MAX_PDF_BYTES = 15_000_000


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def discover_reports(index_html: str) -> list[dict[str, str]]:
    """Return strictly allowlisted official links, newest filename hint first."""
    parser = _Links()
    parser.feed(index_html)
    found: dict[str, dict[str, str]] = {}
    for href in parser.links:
        url = urljoin(INDEX_URL, href)
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != PDF_HOST
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/referee/injury/")
        ):
            continue
        match = REPORT_NAME.fullmatch(Path(parsed.path).name)
        if not match:
            continue
        date_text, hour, minute, meridiem = match.groups()
        try:
            filename_time = datetime.strptime(
                f"{date_text} {hour}:{minute}{meridiem}", "%Y-%m-%d %I:%M%p"
            ).replace(tzinfo=ZoneInfo("America/New_York"))
        except ValueError:
            continue
        found[url] = {
            "url": url,
            "report_date_et": date_text,
            "filename_time_et": filename_time.isoformat(),
        }
    return sorted(found.values(), key=lambda record: record["filename_time_et"], reverse=True)


def latest_for_date(reports: list[dict[str, str]], date_et: str) -> dict[str, str]:
    datetime.strptime(date_et, "%Y-%m-%d")
    matches = [record for record in reports if record["report_date_et"] == date_et]
    if not matches:
        raise ValueError("NO_OFFICIAL_REPORT_FOR_DATE")
    return max(matches, key=lambda record: record["filename_time_et"])


def validate_pdf(contents: bytes) -> str:
    if not contents.startswith(b"%PDF-") or b"%%EOF" not in contents[-2048:]:
        raise ValueError("INVALID_PDF_BYTES")
    if len(contents) > MAX_PDF_BYTES:
        raise ValueError("PDF_TOO_LARGE")
    return hashlib.sha256(contents).hexdigest()


def _fetch(url: str, maximum: int) -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": "SportsEdge-research-archive/1.0"})
    with urlopen(req, timeout=20) as response:
        if response.geturl() != url:
            raise ValueError("SOURCE_REDIRECT_NOT_ALLOWED")
        if response.status != 200:
            raise ValueError("HTTP_NOT_200")
        payload = response.read(maximum + 1)
    received_at = datetime.now(timezone.utc).isoformat()
    if len(payload) > maximum:
        raise ValueError("SOURCE_RESPONSE_TOO_LARGE")
    return payload, received_at


def archive_pdf(
    output_dir: Path,
    report: dict[str, str],
    pdf: bytes,
    index_received_at_utc: str,
    pdf_received_at_utc: str,
) -> dict[str, object]:
    """Preserve raw bytes by digest and each separate observation receipt.

    The source filename is a hint, never proof of when information was available.
    """
    raw_sha = validate_pdf(pdf)
    observed = datetime.fromisoformat(pdf_received_at_utc)
    if observed.tzinfo is None:
        raise ValueError("RECEIPT_TIMESTAMP_MISSING_OFFSET")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{report['report_date_et']}_{raw_sha}.pdf"
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != raw_sha:
            raise ValueError("EXISTING_ARCHIVE_BYTES_CONFLICT")
    else:
        with target.open("xb") as handle:
            handle.write(pdf)

    receipt: dict[str, object] = {
        "schema": "NBA_OFFICIAL_INJURY_PDF_RECEIPT_V1",
        "provider": "NBA_OFFICIAL",
        "index_url": INDEX_URL,
        "source_pdf_url": report["url"],
        "report_date_et": report["report_date_et"],
        "filename_time_et_hint_unverified": report["filename_time_et"],
        "index_received_at_utc": index_received_at_utc,
        "pdf_received_at_utc": pdf_received_at_utc,
        "raw_pdf_sha256": raw_sha,
        "raw_pdf_bytes": len(pdf),
        "raw_pdf_path": str(target),
        "extraction_state": "UNPARSED",
        "pit_available": False,
        "source_report_time_verified": False,
        "model_p": None,
        "pricing_input": False,
        "play_eligible": False,
        "staking_allowed": False,
        "research_only": True,
        "reason": "NO_PLAYER_EXTRACTION_OR_PIT_VERIFICATION",
    }
    # A duplicate PDF is not a duplicate observation: keep the new receipt time.
    stamp = observed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    receipt_file = output_dir / f"{report['report_date_et']}_{stamp}_{raw_sha[:12]}.json"
    with receipt_file.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly allow network and archive")
    parser.add_argument("--date", dest="date_et", help="Official report date, YYYY-MM-DD ET")
    parser.add_argument("--output-dir", type=Path, help="Local raw PDF/receipt archive")
    args = parser.parse_args(argv)
    if not args.live:
        print(json.dumps({"status": "DISABLED_REQUIRES_LIVE", "pricing_input": False}))
        return 0
    if args.output_dir is None:
        parser.error("--output-dir required with --live")
    date_et = args.date_et or datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    try:
        index, index_received = _fetch(INDEX_URL, MAX_INDEX_BYTES)
        report = latest_for_date(discover_reports(index.decode("utf-8")), date_et)
        pdf, pdf_received = _fetch(report["url"], MAX_PDF_BYTES)
        receipt = archive_pdf(args.output_dir, report, pdf, index_received, pdf_received)
    except (HTTPError, URLError, OSError, ValueError, UnicodeError) as exc:
        print(f"NBA_INJURY_ARCHIVE_BLOCKED: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Archive official NFL weekly injury-status HTML as unadmitted raw evidence.

A weekly injury report is NOT the 90-minute pregame official inactive list.
This opt-in collector does not parse player identity, infer active status, or
supply model/pricing input. Explicit --live and --output-dir are required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_HTML_BYTES = 12_000_000
SEASON_TYPES = {"REG": 18, "POST": 5}


def official_url(season: int, season_type: str, week: int) -> str:
    if not 2000 <= season <= 2100:
        raise ValueError("SEASON_OUT_OF_RANGE")
    if season_type not in SEASON_TYPES:
        raise ValueError("BAD_SEASON_TYPE")
    if not 1 <= week <= SEASON_TYPES[season_type]:
        raise ValueError("WEEK_OUT_OF_RANGE")
    return f"https://www.nfl.com/injuries/league/{season}/{season_type}{week}"


def inspect_report(raw: bytes, season: int, season_type: str, week: int) -> dict[str, object]:
    """Gross HTML shape only; player rows and publication completeness unverified."""
    official_url(season, season_type, week)
    if not raw or len(raw) > MAX_HTML_BYTES:
        raise ValueError("HTML_MISSING_OR_TOO_LARGE")
    if b"\x00" in raw or raw.startswith((b"%PDF", b"PK\x03\\x04")):
        raise ValueError("NOT_HTML")
    try:
        html = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("HTML_NOT_UTF8") from exc
    if not re.search(r"<html\b", html, re.I) or "</html>" not in html.lower():
        raise ValueError("HTML_DOCUMENT_INCOMPLETE")
    if not re.search(r"NFL Injury Report", html, re.I):
        raise ValueError("NOT_OFFICIAL_INJURY_REPORT")
    # Some pages render visible rows via client-side JavaScript. Absence of
    # these labels cannot establish 'no injuries' and must fail closed.
    if not all(re.search(rf"\b{re.escape(marker)}\b", html, re.I)
               for marker in ("Player", "Practice Status", "Game Status")):
        raise ValueError("INJURY_TABLE_NOT_OBSERVED")
    if not re.search(rf"\b{season}\b", html) or not re.search(
        rf"\bWeek\s+{week}\b", html, re.I
    ):
        raise ValueError("SEASON_WEEK_CONTEXT_UNVERIFIED")
    return {"html_bytes": len(raw), "player_rows_verified": None}


def archive_report(
    output_dir: Path, raw: bytes, received_at_utc: str,
    season: int, season_type: str, week: int,
) -> dict[str, object]:
    stats = inspect_report(raw, season, season_type, week)
    observed = datetime.fromisoformat(received_at_utc)
    if observed.tzinfo is None or observed.utcoffset() != timedelta(0):
        raise ValueError("RECEIPT_TIME_NOT_UTC")
    digest = hashlib.sha256(raw).hexdigest()
    url = official_url(season, season_type, week)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"nfl-injury-{season}-{season_type}{week}_{digest}.html"
    if archive_path.exists():
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != digest:
            raise ValueError("EXISTING_ARCHIVE_CONFLICT")
    else:
        with archive_path.open("xb") as dest:
            dest.write(raw)
    receipt: dict[str, object] = {
        "schema": "NFL_OFFICIAL_WEEKLY_INJURY_HTML_RECEIPT_V1",
        "source_url": url,
        "provider": "NFL_COM_PUBLIC_WEEKLY_INJURY_PAGE",
        "season": season,
        "season_type": season_type,
        "week": week,
        "received_at_utc": received_at_utc,
        "raw_sha256": digest,
        "raw_bytes": stats["html_bytes"],
        "raw_path": str(archive_path),
        "page_type": "WEEKLY_INJURY_NOT_GAMEDAY_INACTIVES",
        "parsed_players": None,
        "source_published_at_verified": False,
        "roster_completeness_verified": False,
        "player_id_crosswalk_verified": False,
        "pit_available": False,
        "pricing_input": False,
        "play_eligible": False,
        "model_p": None,
        "research_only": True,
        "redistribution_allowed": False,
        "reason": "WEEKLY_REPORT_ONLY_NO_AUTHENTICATED_INACTIVES_OR_IDENTITY",
    }
    ts = observed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    receipt_path = output_dir / f"nfl-injury-{season}-{season_type}{week}_{ts}_{digest[:12]}.json"
    with receipt_path.open("x", encoding="utf-8") as dest:
        json.dump(receipt, dest, sort_keys=True, indent=2)
        dest.write("\n")
    return receipt


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("REDIRECT_NOT_VERIFIED")


def _fetch_official(url: str) -> tuple[bytes, str]:
    opener = build_opener(_NoRedirect())
    req = Request(url, headers={"User-Agent": "SportsEdge-research-audit/1.0",
                                "Accept": "text/html", "Accept-Encoding": "identity"})
    with opener.open(req, timeout=30) as response:
        if response.status != 200:
            raise ValueError("HTTP_NOT_200")
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            raise ValueError("NOT_HTML_CONTENT_TYPE")
        raw = response.read(MAX_HTML_BYTES + 1)
    when = datetime.now(timezone.utc).isoformat()
    if len(raw) > MAX_HTML_BYTES:
        raise ValueError("HTML_TOO_LARGE")
    return raw, when


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--output-dir", type=Path)
    ap.add_argument("--season", type=int)
    ap.add_argument("--season-type", choices=sorted(SEASON_TYPES))
    ap.add_argument("--week", type=int)
    args = ap.parse_args(argv)
    if not args.live:
        print(json.dumps({"status": "DISABLED_REQUIRES_LIVE", "pricing_input": False}))
        return 0
    if args.output_dir is None or any(
        value is None for value in (args.season, args.season_type, args.week)
    ):
        ap.error("--output-dir, --season, --season-type, --week required with --live")
    try:
        url = official_url(args.season, args.season_type, args.week)
        raw, received_at = _fetch_official(url)
        receipt = archive_report(
            args.output_dir, raw, received_at, args.season, args.season_type, args.week
        )
    except (OSError, ValueError, HTTPError, URLError) as exc:
        print(f"NFL_INJURY_ARCHIVE_BLOCKED: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

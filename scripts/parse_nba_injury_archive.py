#!/usr/bin/env python3
"""Strict, research-only parser for archived NBA official injury PDFs.

Input is #2673's immutable PDF + receipt pair. Never reconstruct past status,
never feed production pricing, and never claim a decision-time PIT view unless
both publication AND actual fetch precede that decision.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.nba_injury_report import slot_url

ET = ZoneInfo("America/New_York")
TITLE = re.compile(r"Injury Report:\s*(\d{2}/\d{2}/\d{2}\s+\d{1,2}:\d{2}\s*[AP]M)", re.I)
STATUS = frozenset(("Out", "Doubtful", "Questionable", "Probable", "Available"))
SCHEMA = "sportsedge.nba_injury_player_archive.v1"


def instant(s: str) -> datetime:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise ValueError("TIMESTAMP_INVALID") from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("TIMESTAMP_OFFSET_REQUIRED")
    return d


def parse_rows(tables: list[list[list[str | None]]]) -> list[dict]:
    """Turn NBA's seven-column tables into context-complete player records.

    Blank cells inherit game date, matchup, team from the previous row. The
    raw PDF may wrap text, but missing identifiers/status always fail closed.
    """
    game_date = matchup = team = None
    out: list[dict] = []
    for table in tables:
        for values in table:
            if len(values) != 7:
                raise ValueError("PDF_COLUMNS_UNEXPECTED")
            v = [" ".join(str(x or "").split()) for x in values]
            if v[0].lower() == "game date" or v[4].lower() == "player name":
                continue
            if v[0]:
                try:
                    game_date = datetime.strptime(v[0], "%m/%d/%Y").date().isoformat()
                except ValueError as e:
                    raise ValueError("GAME_DATE_INVALID") from e
            matchup = v[2] or matchup
            team = v[3] or team
            player, status = v[4], v[5]
            if not player:
                continue
            if not (game_date and matchup and team):
                raise ValueError("PLAYER_EVENT_CONTEXT_MISSING")
            if not re.fullmatch(r"[A-Z]{2,3}@[A-Z]{2,3}", matchup):
                raise ValueError("MATCHUP_INVALID")
            if status not in STATUS:
                raise ValueError("PLAYER_STATUS_UNRECOGNIZED")
            out.append(dict(game_date=game_date, matchup=matchup, team=team,
                            player=player, status=status, reason=v[6]))
    return out


def parse_archive_pdf(data: bytes, receipt: dict, *, decision_time: str | None = None,
                      open_pdf=None) -> list[dict]:
    """Verify fetched bytes, NBA source, PDF title, and as-of timing."""
    if receipt.get("status") != "ARCHIVED" or not data.startswith(b"%PDF-"):
        raise ValueError("PDF_NOT_ARCHIVED")
    if hashlib.sha256(data).hexdigest() != receipt.get("sha256"):
        raise ValueError("PDF_SHA256_MISMATCH")
    published = instant(receipt["report_time_et"])
    fetched = instant(receipt["fetched_at"])
    if fetched < published:
        raise ValueError("FETCHED_BEFORE_PUBLICATION")
    if receipt.get("url") != slot_url(published.astimezone(ET).date(),
                                       published.astimezone(ET).time().replace(tzinfo=None)):
        raise ValueError("PDF_URL_NOT_OFFICIAL_SLOT")
    if decision_time is not None:
        decision = instant(decision_time)
        if published > decision or fetched > decision:
            raise ValueError("NO_LOOKAHEAD_RECEIPT_AFTER_DECISION")
    if open_pdf is None:
        import pdfplumber  # CI workflow installs pinned parser dependency
        open_pdf = lambda blob: pdfplumber.open(io.BytesIO(blob))
    with open_pdf(data) as pdf:
        pages = list(pdf.pages)
        if not pages:
            raise ValueError("PDF_EMPTY")
        text = pages[0].extract_text() or ""
        match = TITLE.search(text)
        if not match:
            raise ValueError("PDF_PUBLICATION_TITLE_MISSING")
        internal = datetime.strptime(match.group(1), "%m/%d/%y %I:%M %p").replace(tzinfo=ET)
        if internal != published.astimezone(ET):
            raise ValueError("PDF_TITLE_TIME_MISMATCH")
        tables = [table for page in pages for table in (page.extract_tables() or [])]
    if not tables:
        raise ValueError("PDF_NO_EXTRACTABLE_TABLE")
    records = parse_rows(tables)
    return [dict(schema=SCHEMA, **row, event_id=f"NBA:{row['game_date']}:{row['matchup']}",
                 source_url=receipt["url"], source_sha256=receipt["sha256"],
                 report_time_et=published.astimezone(ET).isoformat(),
                 fetched_at=fetched.isoformat(), decision_time=decision_time,
                 pit_at_decision=(decision_time is not None),
                 pricing_eligible=False, ladder_status="PAPER") for row in records]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--day", required=True, type=date.fromisoformat)
    p.add_argument("--archive-root", type=Path, default=Path("artifacts/nba_injury_reports"))
    p.add_argument("--decision-time", default=None)
    a = p.parse_args(argv)
    folder = a.archive_root / a.day.isoformat()
    logfile = folder / "receipts.jsonl"
    if not logfile.exists():
        print("REFUSED: NO_RECEIPTS", file=sys.stderr)
        return 2
    records = []
    try:
        for raw in logfile.read_text().splitlines():
            if not raw.strip():
                continue
            rec = json.loads(raw)
            if rec.get("status") != "ARCHIVED":
                continue
            filename = rec["url"].rsplit("/", 1)[-1]
            if not re.fullmatch(r"Injury-Report_\d{4}-\d{2}-\d{2}_\d{2}_\d{2}[AP]M\.pdf", filename):
                raise ValueError("PDF_FILENAME_UNSAFE")
            records.extend(parse_archive_pdf((folder / filename).read_bytes(), rec,
                                             decision_time=a.decision_time))
    except (ValueError, KeyError, OSError, ImportError) as e:
        print(f"REFUSED: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    output = folder / "players.jsonl"
    output.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))
    print(json.dumps({"source": "NBA_OFFICIAL_PDF", "research_only": True,
                      "players": len(records), "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

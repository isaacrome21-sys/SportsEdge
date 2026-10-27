#!/usr/bin/env python3
"""Archive one game day's official NBA injury report PDFs (research only).

Writes each published PDF to artifacts/nba_injury_reports/<day>/<slot>.pdf
plus one receipt line per slot in receipts.jsonl. Already-archived slots are
skipped. Unpublished slots are recorded as SLOT_NOT_PUBLISHED. No parsing, no
pricing, no key.

  python3 scripts/archive_nba_injury_reports.py --day 2026-10-25 --start 11:00 --end 19:30
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.nba_injury_report import day_slots, make_receipt  # noqa: E402

OUT = Path("artifacts/nba_injury_reports")


def _fetch(url: str) -> tuple[int, bytes | None]:
    req = urllib.request.Request(url, headers={"User-Agent": "SportsEdge-research/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, None


def archive_day(day: date, start: time, end: time, out: Path = OUT,
                fetch: Callable[[str], tuple[int, bytes | None]] = _fetch,
                now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> list[dict]:
    folder = out / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "receipts.jsonl"
    done = set()
    if log.exists():
        done = {json.loads(l)["url"] for l in log.read_text().splitlines()
                if l.strip() and json.loads(l)["status"] == "ARCHIVED"}
    written = []
    for report_time, url in day_slots(day, start, end):
        if url in done or report_time > now():
            continue
        status, body = fetch(url)
        receipt = make_receipt(url=url, report_time=report_time, fetched_at=now(),
                               http_status=status, body=body).to_dict()
        if receipt["status"] == "ARCHIVED":
            (folder / url.rsplit("/", 1)[-1]).write_bytes(body)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, sort_keys=True) + "\n")
        written.append(receipt)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--day", type=date.fromisoformat, required=True)
    p.add_argument("--start", type=time.fromisoformat, default=time(0, 0))
    p.add_argument("--end", type=time.fromisoformat, default=time(23, 45))
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args(argv)
    rows = archive_day(a.day, a.start, a.end, a.out)
    print(json.dumps({"archived": sum(r["status"] == "ARCHIVED" for r in rows), "checked": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

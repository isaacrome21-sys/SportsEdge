#!/usr/bin/env python3
"""Capture paired MLB moneylines from a public rendered DraftKings page.

Research evidence only.  The rendered DOM is joined fail-closed to the official
MLB schedule before an immutable T60/T30/T10 observation can be written.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.dk_rendered_page_fetcher import fetch_rendered_board
from sportsedge.mlb_rendered_moneyline_capture import (
    EVIDENCE_DISPOSITION,
    RenderedMLBCaptureBlocked,
    adapt_rendered_moneylines,
    persist_create_only,
)
from sportsedge.mlb_source import fetch_schedule

DEFAULT_URL = "https://sportsbook.draftkings.com/leagues/baseball/mlb"
DEFAULT_OUTPUT_DIR = "data/mlb_forward_capture"
CHICAGO = ZoneInfo("America/Chicago")


def _time(value: str) -> datetime:
    out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if out.tzinfo is None or out.utcoffset() is None:
        raise RenderedMLBCaptureBlocked("OBSERVED_AT_TIMEZONE_REQUIRED")
    return out


def capture(
    *,
    url: str = DEFAULT_URL,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    rendered_fetcher: Callable = fetch_rendered_board,
    schedule_fetcher: Callable = fetch_schedule,
    artifact_binder: Callable | None = None,
) -> dict:
    if artifact_binder is None:
        from sportsedge.mlb_model_artifact import mlb_model_artifact_sha256

        artifact_binder = mlb_model_artifact_sha256
    try:
        artifact = artifact_binder()
    except Exception as exc:
        raise RenderedMLBCaptureBlocked("BLOCKED_ARTIFACT", str(exc)) from exc
    board = rendered_fetcher(url, sport_key="baseball_mlb")
    observed = _time(board.get("observed_at_utc"))
    slate_date = observed.astimezone(CHICAGO).date().isoformat()
    schedule = schedule_fetcher(slate_date, now=observed)
    rows = adapt_rendered_moneylines(
        board, schedule, model_artifact_sha256=artifact
    )
    paths = persist_create_only(rows, output_dir)
    return {
        "status": "RETAINED" if paths else "ALREADY_CAPTURED",
        "evidence_disposition": EVIDENCE_DISPOSITION,
        "promotion_authority": False,
        "source_class": "DRAFTKINGS_RENDERED_PAGE_V1",
        "slate_date_ct": slate_date,
        "observations_eligible": len(rows),
        "observations_retained": len(paths),
        "paths": paths,
        "page_html_sha256": board.get("page_html_sha256"),
        "observed_at_utc": board.get("observed_at_utc"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        result = capture(url=args.url, output_dir=args.output_dir)
    except RenderedMLBCaptureBlocked as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": exc.reason,
            "detail": exc.detail,
            "promotion_authority": False,
        }, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

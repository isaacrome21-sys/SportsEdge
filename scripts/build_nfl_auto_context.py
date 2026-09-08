#!/usr/bin/env python3
"""Build a source-driven NFL AUTO context slate with no operator game list."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys
from urllib.request import urlopen

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.auto_slate import build_nfl_auto_context_slate
from sportsedge.sports.nfl.full_auto import build_nfl_full_auto_slate
from sportsedge.sports.nfl.history import NFLVERSE_SCHEDULE_CSV


class _BytesResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _url(req) -> str:
    return req if isinstance(req, str) else str(req.full_url)


def _opener(schedule_file: Path | None):
    if schedule_file is None:
        return urlopen
    try:
        frozen = schedule_file.read_bytes()
    except OSError as exc:
        raise SystemExit("NFL_AUTO_CONTEXT_SCHEDULE_FILE_UNREADABLE") from exc
    if not frozen:
        raise SystemExit("NFL_AUTO_CONTEXT_SCHEDULE_FILE_EMPTY")

    def open_source(req, timeout=20):
        if _url(req) == NFLVERSE_SCHEDULE_CSV:
            return _BytesResponse(frozen)
        return urlopen(req, timeout=timeout)

    return open_source


def _depth_source(path: Path | None, explicit_uri: str | None):
    if path is None:
        if explicit_uri not in (None, ""):
            raise SystemExit("NFL_AUTO_CONTEXT_DEPTH_URI_WITHOUT_FILE")
        return None, None, None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SystemExit("NFL_AUTO_CONTEXT_DEPTH_FILE_UNREADABLE") from exc
    if not raw:
        raise SystemExit("NFL_AUTO_CONTEXT_DEPTH_FILE_EMPTY")
    try:
        text = raw.decode("utf-8-sig")
        rows = [dict(row) for row in csv.DictReader(io.StringIO(text))]
    except Exception as exc:
        raise SystemExit("NFL_AUTO_CONTEXT_DEPTH_FILE_INVALID") from exc
    if not rows:
        raise SystemExit("NFL_AUTO_CONTEXT_DEPTH_FILE_EMPTY_ROWS")
    uri = str(explicit_uri or "").strip()
    if not uri:
        match = re.fullmatch(r"depth_charts_(20[0-9]{2})\.csv", path.name)
        if match is None:
            raise SystemExit("NFL_AUTO_CONTEXT_DEPTH_SOURCE_URI_REQUIRED")
        season = match.group(1)
        uri = (
            "https://github.com/nflverse/nflverse-data/releases/download/"
            f"depth_charts/depth_charts_{season}.csv"
        )
    if not uri.startswith("https://"):
        raise SystemExit("NFL_AUTO_CONTEXT_DEPTH_SOURCE_URI_INVALID")
    return rows, uri, sha256(raw).hexdigest()


def _asof(value: str | None) -> datetime:
    if value in (None, ""):
        return datetime.now(timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit("NFL_AUTO_CONTEXT_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise SystemExit("NFL_AUTO_CONTEXT_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof")
    parser.add_argument("--schedule-file", type=Path)
    parser.add_argument("--depth-file", type=Path)
    parser.add_argument("--depth-source-uri")
    parser.add_argument("--min-lead-minutes", type=int, default=0)
    parser.add_argument("--horizon-minutes", type=int, default=24 * 60)
    parser.add_argument("--game-type", action="append", dest="game_types")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/football/nfl_auto_context.json"),
    )
    args = parser.parse_args()
    pit = _asof(args.asof)
    opener = _opener(args.schedule_file)
    depth_rows, depth_uri, depth_sha = _depth_source(args.depth_file, args.depth_source_uri)
    common = dict(
        as_of=pit,
        mode="AUTO",
        min_lead_minutes=args.min_lead_minutes,
        horizon_minutes=args.horizon_minutes,
        game_types=tuple(args.game_types or ["REG"]),
        opener=opener,
    )
    if depth_rows is None:
        payload = build_nfl_full_auto_slate(**common)
    else:
        payload = build_nfl_auto_context_slate(
            **common,
            depth_chart_rows=depth_rows,
            depth_chart_source_uri=depth_uri,
            depth_chart_source_sha256=depth_sha,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "as_of_utc": payload["as_of_utc"],
                "collection_mode": payload["collection_mode"],
                "game_count": payload["game_count"],
                "out": str(args.out),
                "depth_chart_source_sha256": payload["depth_chart_source_sha256"],
                "depth_chart_status": (payload.get("automation") or {}).get("depth_chart_status"),
                "model_p_eligible": payload["model_p_eligible"],
                "truth_gate_eligible": payload["truth_gate_eligible"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

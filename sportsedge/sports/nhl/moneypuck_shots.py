"""MoneyPuck listed shot ZIP -> game-level shot/xG research receipts.

MoneyPuck.com data page: listed downloads are non-commercial, with attribution;
other uses require permission. This module NEVER scrapes or downloads. Source
is postgame/unknown-vintage: NOT historical PIT, NEVER a pricing input.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zipfile import BadZipFile, ZipFile

SCHEMA = "sportsedge.nhl.moneypuck_game_shots.v1"
MAX_UNCOMPRESSED = 400_000_000
REQUIRED = {"shotID", "game_id", "team", "event", "xGoal"}
EVENTS = {"SHOT", "GOAL", "MISS"}
DATA_PAGE = "https://moneypuck.com/data.htm"


class MoneyPuckError(ValueError):
    pass


def source_url(season_start: int) -> str:
    if isinstance(season_start, bool) or not isinstance(season_start, int) or not 2007 <= season_start <= 2025:
        raise MoneyPuckError("SEASON_UNLISTED")
    return f"https://peter-tanner.com/moneypuck/downloads/shots_{season_start}.zip"


def _utc(text: str | datetime) -> datetime:
    try:
        d = text if isinstance(text, datetime) else datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MoneyPuckError("FETCH_TIME_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise MoneyPuckError("FETCH_TIME_OFFSET_REQUIRED")
    return d.astimezone(timezone.utc)


def ingest_shot_zip(archive: bytes, *, season_start: int, fetched_at: str | datetime) -> dict:
    """Parse only an already-obtained *listed* ZIP and hash its exact bytes."""
    url = source_url(season_start)
    fetched = _utc(fetched_at)
    if fetched > datetime.now(timezone.utc):
        raise MoneyPuckError("FETCH_TIME_IN_FUTURE")
    if not isinstance(archive, bytes) or not archive:
        raise MoneyPuckError("ARCHIVE_BYTES_MISSING")
    try:
        zf = ZipFile(io.BytesIO(archive))
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
            raise MoneyPuckError("ZIP_EXPECTS_SINGLE_CSV")
        if not 0 < members[0].file_size <= MAX_UNCOMPRESSED:
            raise MoneyPuckError("CSV_SIZE_REFUSED")
        grouped = defaultdict(lambda: {"shots": 0, "goals": 0, "xg": 0.0})
        shot_ids = set()
        with zf.open(members[0]) as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""))
            if reader.fieldnames is None or not REQUIRED.issubset(set(reader.fieldnames)):
                raise MoneyPuckError("SHOT_COLUMNS_MISSING")
            count = 0
            for row in reader:
                shot_id, game_id = str(row.get("shotID") or "").strip(), str(row.get("game_id") or "").strip()
                team, event = str(row.get("team") or "").strip().upper(), str(row.get("event") or "").strip().upper()
                if not shot_id or shot_id in shot_ids or not re.fullmatch(r"[0-9]{8,12}", game_id):
                    raise MoneyPuckError("SHOT_ID_OR_GAME_ID_INVALID")
                shot_ids.add(shot_id)
                if not re.fullmatch(r"[A-Z]{2,4}", team) or event not in EVENTS:
                    raise MoneyPuckError("TEAM_OR_EVENT_INVALID")
                try:
                    xg = float(row["xGoal"])
                except (TypeError, ValueError) as exc:
                    raise MoneyPuckError("XG_INVALID") from exc
                if not math.isfinite(xg) or not 0 <= xg <= 1:
                    raise MoneyPuckError("XG_RANGE_INVALID")
                rec = grouped[(game_id, team)]
                rec["shots"] += 1
                rec["goals"] += int(event == "GOAL")
                rec["xg"] += xg
                count += 1
        if count == 0:
            raise MoneyPuckError("SHOT_ROWS_EMPTY")
    except (BadZipFile, EOFError) as exc:
        raise MoneyPuckError("ZIP_INVALID") from exc
    games = [{"game_id": g, "team": t, "shots_unblocked_attempts_excluding_blocked": v["shots"],
              "goals_shot_events": v["goals"], "xg": round(v["xg"], 8)}
             for (g, t), v in sorted(grouped.items())]
    return {
        "schema": SCHEMA, "source": "MoneyPuck", "source_url": url,
        "source_data_page": DATA_PAGE, "fetched_at_utc": fetched.isoformat(),
        "sha256": hashlib.sha256(archive).hexdigest(), "season_start": season_start,
        "shot_count": count, "rows": games,
        "source_publication_time": None, "historical_pit": False,
        "completeness": "UNVERIFIED_NO_GAME_FINAL_ATTESTATION",
        "pricing_input": False, "play_eligible": False,
        "license_scope": "NON_COMMERCIAL_ONLY_WITH_ATTRIBUTION_OTHER_USE_REQUIRES_APPROVAL",
        "attribution": "MoneyPuck.com",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip-file", type=Path, required=True)
    ap.add_argument("--season-start", type=int, required=True)
    ap.add_argument("--fetched-at", required=True, help="Real UTC-offset fetch timestamp, not game time")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        receipt = ingest_shot_zip(args.zip_file.read_bytes(), season_start=args.season_start,
                                  fetched_at=args.fetched_at)
    except (OSError, MoneyPuckError) as exc:
        ap.exit(2, f"REFUSED: {exc}\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.out.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, sort_keys=True, indent=2)
    except FileExistsError:
        ap.exit(2, "REFUSED: OUTPUT_EXISTS\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

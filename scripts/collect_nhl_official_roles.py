#!/usr/bin/env python3
from __future__ import annotations

"""Collect official NHL skater SOG/goal/assist role-history receipts.

For each completed game this collector pairs the official Gamecenter boxscore
with the official play-by-play response.  Exact raw response SHA-256 values and
actual retrieval timestamps are bound into each normalized player-game row.
Historical downloads are development data, not retroactive betting evidence.
"""

import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sportsedge.sports.nhl.official_boxscore_source import BOXSCORE_ENDPOINT
from sportsedge.sports.nhl.official_pbp_source import OFFICIAL_PBP_PREFIX
from sportsedge.sports.nhl.official_role_source import build_official_player_role_observations
from sportsedge.sports.nhl.role_history import NHLPlayerGameRoleObservation

SCORE_ENDPOINT = "https://api-web.nhle.com/v1/score/{date}"
USER_AGENT = "SportsEdge-NHL-Research/1.0 (+https://github.com/isaacrome21-sys/SportsEdge)"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def fetch_json(url: str, *, timeout: float = 20.0, retries: int = 3) -> tuple[Mapping[str, Any], bytes, str]:
    if retries < 1:
        raise ValueError("retries must be positive")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public NHL HTTPS host
                raw = response.read()
            captured_at = datetime.now(timezone.utc).isoformat()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("NHL endpoint returned non-object JSON")
            return payload, raw, captured_at
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.5 * (2 ** attempt))
    assert last_error is not None
    raise RuntimeError(f"failed NHL fetch after {retries} attempts: {url}: {last_error}") from last_error


def discover_completed_game_ids(start: date, end: date, *, allowed_game_types: set[int]) -> tuple[str, ...]:
    if end < start:
        raise ValueError("end date must be on/after start date")
    if not allowed_game_types:
        raise ValueError("allowed_game_types cannot be empty")
    cursor = start
    ids: set[str] = set()
    seen_dates: set[date] = set()
    while cursor <= end:
        if cursor in seen_dates:
            raise RuntimeError("NHL score date traversal repeated a date")
        seen_dates.add(cursor)
        payload, _, _ = fetch_json(SCORE_ENDPOINT.format(date=cursor.isoformat()))
        games = payload.get("games")
        if not isinstance(games, list):
            raise ValueError("official NHL score payload missing games list")
        for game in games:
            if not isinstance(game, Mapping):
                raise ValueError("official NHL score game row must be an object")
            row_date = date.fromisoformat(str(game.get("gameDate") or cursor.isoformat()))
            game_type = int(game.get("gameType") or 0)
            state = str(game.get("gameState") or "").upper()
            game_id = str(game.get("id") or "").strip()
            if start <= row_date <= end and game_id and game_type in allowed_game_types and state in {"OFF", "FINAL"}:
                ids.add(game_id)
        next_date = payload.get("nextDate")
        if next_date:
            candidate = date.fromisoformat(str(next_date))
            cursor = candidate if candidate > cursor else cursor + timedelta(days=1)
        else:
            cursor += timedelta(days=1)
    return tuple(sorted(ids))


def collect_game_roles(game_id: str) -> tuple[NHLPlayerGameRoleObservation, ...]:
    box_uri = BOXSCORE_ENDPOINT.format(game_id=game_id)
    pbp_uri = f"{OFFICIAL_PBP_PREFIX}{game_id}/play-by-play"
    box_payload, box_raw, box_captured = fetch_json(box_uri)
    pbp_payload, pbp_raw, pbp_captured = fetch_json(pbp_uri)
    return build_official_player_role_observations(
        boxscore_payload=box_payload,
        pbp_payload=pbp_payload,
        boxscore_captured_at=box_captured,
        pbp_captured_at=pbp_captured,
        boxscore_raw_sha256=sha256(box_raw).hexdigest(),
        pbp_raw_sha256=sha256(pbp_raw).hexdigest(),
        boxscore_source_uri=box_uri,
        pbp_source_uri=pbp_uri,
        source_version="nhl-web-api-v1",
    )


def _load_existing(path: Path) -> dict[tuple[str, str], NHLPlayerGameRoleObservation]:
    if not path.exists():
        return {}
    rows: dict[tuple[str, str], NHLPlayerGameRoleObservation] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = NHLPlayerGameRoleObservation(**json.loads(line))
        except Exception as exc:
            raise ValueError(f"invalid existing role JSONL row {line_number}: {exc}") from exc
        key = (row.game_id, row.player_id)
        if key in rows:
            raise ValueError(f"duplicate existing player-game role:{key}")
        rows[key] = row
    return rows


def _write_jsonl(path: Path, rows: Mapping[tuple[str, str], NHLPlayerGameRoleObservation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r.puck_drop, r.game_id, r.team_id, r.player_id))
    text = "".join(json.dumps(asdict(row), sort_keys=True, separators=(",", ":")) + "\n" for row in ordered)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect official NHL player role history for SportsEdge development")
    parser.add_argument("--start-date", required=True, type=_parse_date)
    parser.add_argument("--end-date", required=True, type=_parse_date)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--game-type", action="append", type=int, dest="game_types", help="Allowed NHL game type; repeatable (default: 2,3)")
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--max-games", type=int, default=None)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    allowed = set(args.game_types or (2, 3))
    discovered = discover_completed_game_ids(args.start_date, args.end_date, allowed_game_types=allowed)
    existing = _load_existing(args.output)
    complete_games = {game_id for game_id, _ in existing}
    pending = tuple(game_id for game_id in discovered if game_id not in complete_games)
    if args.max_games is not None:
        if args.max_games < 0:
            parser.error("--max-games must be nonnegative")
        pending = pending[:args.max_games]

    failures: list[tuple[str, str]] = []
    new_rows = 0
    for index, game_id in enumerate(pending, start=1):
        try:
            rows = collect_game_roles(game_id)
            for row in rows:
                existing[(row.game_id, row.player_id)] = row
            new_rows += len(rows)
        except Exception as exc:
            failures.append((game_id, f"{type(exc).__name__}: {exc}"))
        if args.sleep_seconds > 0 and index < len(pending):
            time.sleep(max(0.0, args.sleep_seconds))
    _write_jsonl(args.output, existing)

    print(
        f"games_discovered={len(discovered)} pending={len(pending)} rows={len(existing)} "
        f"new_rows={new_rows} failures={len(failures)} output={args.output}",
        file=sys.stderr,
    )
    for game_id, reason in failures:
        print(f"FAILED {game_id}: {reason}", file=sys.stderr)
    return 2 if failures and not args.allow_partial else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

"""Collect official NHL completed-game boxscores as development receipts.

This collector uses only public NHL endpoints documented by public MIT-licensed
API reference repositories.  It preserves the exact raw response SHA-256 and the
actual retrieval timestamp.  Historical rows fetched now are retrospective
model-development inputs, not retroactive PIT evidence for old decisions.
"""

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sportsedge.sports.nhl.official_boxscore_source import (
    BOXSCORE_ENDPOINT,
    NHLOfficialCompletedGame,
    build_official_completed_game,
    completed_game_from_json_dict,
    raw_sha256,
)

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
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=timeout) as response:  # noqa: S310 - fixed public NHL HTTPS host
                raw = response.read()
            captured_at = datetime.now(timezone.utc).isoformat()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("NHL endpoint returned a non-object JSON payload")
            return payload, raw, captured_at
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.5 * (2 ** attempt))
    assert last_error is not None
    raise RuntimeError(f"failed NHL fetch after {retries} attempts: {url}: {last_error}") from last_error


def discover_completed_game_ids(
    start: date, end: date, *, fetcher: Callable[[str], tuple[Mapping[str, Any], bytes, str]] = fetch_json,
    allowed_game_types: set[int] | None = None,
) -> tuple[str, ...]:
    if end < start:
        raise ValueError("end date must be on/after start date")
    allowed = {2, 3} if allowed_game_types is None else {int(x) for x in allowed_game_types}
    if not allowed:
        raise ValueError("allowed_game_types cannot be empty")

    cursor = start
    game_ids: set[str] = set()
    seen_dates: set[date] = set()
    while cursor <= end:
        if cursor in seen_dates:
            raise RuntimeError("NHL score date traversal repeated a date")
        seen_dates.add(cursor)
        payload, _, _ = fetcher(SCORE_ENDPOINT.format(date=cursor.isoformat()))
        games = payload.get("games")
        if not isinstance(games, list):
            raise ValueError("official NHL score payload missing games list")
        for row in games:
            if not isinstance(row, Mapping):
                raise ValueError("official NHL score game row must be an object")
            game_date = str(row.get("gameDate") or cursor.isoformat())
            try:
                row_date = date.fromisoformat(game_date)
            except ValueError as exc:
                raise ValueError(f"invalid official NHL gameDate:{game_date}") from exc
            if not start <= row_date <= end:
                continue
            game_type = int(row.get("gameType") or 0)
            state = str(row.get("gameState") or "").upper()
            game_id = str(row.get("id") or "").strip()
            if game_id and game_type in allowed and state in {"OFF", "FINAL"}:
                game_ids.add(game_id)

        next_date = payload.get("nextDate")
        if next_date:
            try:
                candidate = date.fromisoformat(str(next_date))
            except ValueError as exc:
                raise ValueError(f"invalid official NHL nextDate:{next_date}") from exc
            cursor = candidate if candidate > cursor else cursor + timedelta(days=1)
        else:
            cursor += timedelta(days=1)
    return tuple(sorted(game_ids))


def collect_completed_games(
    game_ids: tuple[str, ...], *, fetcher: Callable[[str], tuple[Mapping[str, Any], bytes, str]] = fetch_json,
    sleep_seconds: float = 0.05,
) -> tuple[list[NHLOfficialCompletedGame], list[tuple[str, str]]]:
    games: list[NHLOfficialCompletedGame] = []
    failures: list[tuple[str, str]] = []
    for index, game_id in enumerate(game_ids, start=1):
        url = BOXSCORE_ENDPOINT.format(game_id=game_id)
        try:
            payload, raw, captured_at = fetcher(url)
            games.append(build_official_completed_game(
                payload=payload,
                captured_at=captured_at,
                raw_sha256=raw_sha256(raw),
                source_uri=url,
                source_version="nhl-web-api-v1",
            ))
        except Exception as exc:  # retain explicit per-game failure evidence
            failures.append((game_id, f"{type(exc).__name__}: {exc}"))
        if sleep_seconds > 0 and index < len(game_ids):
            time.sleep(sleep_seconds)
    games.sort(key=lambda g: (g.start_time_utc, g.game_id))
    return games, failures


def _load_existing(path: Path) -> dict[str, NHLOfficialCompletedGame]:
    if not path.exists():
        return {}
    out: dict[str, NHLOfficialCompletedGame] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            game = completed_game_from_json_dict(json.loads(line))
        except Exception as exc:
            raise ValueError(f"invalid existing JSONL row {line_number}: {exc}") from exc
        if game.game_id in out:
            raise ValueError(f"duplicate existing game id:{game.game_id}")
        out[game.game_id] = game
    return out


def _write_jsonl(path: Path, games: Mapping[str, NHLOfficialCompletedGame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(games.values(), key=lambda g: (g.start_time_utc, g.game_id))
    text = "".join(json.dumps(g.as_json_dict(), sort_keys=True, separators=(",", ":")) + "\n" for g in ordered)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect official NHL final boxscores for SportsEdge development")
    parser.add_argument("--start-date", required=True, type=_parse_date)
    parser.add_argument("--end-date", required=True, type=_parse_date)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--game-type", action="append", type=int, dest="game_types", help="Allowed NHL game type; repeatable (default: 2,3)")
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--allow-partial", action="store_true", help="Exit 0 even when some boxscores fail; failures are still emitted")
    parser.add_argument("--max-games", type=int, default=None, help="Optional deterministic probe limit after game-id discovery")
    args = parser.parse_args()

    allowed = set(args.game_types or (2, 3))
    discovered = discover_completed_game_ids(args.start_date, args.end_date, allowed_game_types=allowed)
    existing = _load_existing(args.output)
    pending = tuple(game_id for game_id in discovered if game_id not in existing)
    if args.max_games is not None:
        if args.max_games < 0:
            parser.error("--max-games must be nonnegative")
        pending = pending[:args.max_games]

    print(f"discovered={len(discovered)} existing={len(existing)} pending={len(pending)}", file=sys.stderr)
    collected, failures = collect_completed_games(pending, sleep_seconds=max(0.0, args.sleep_seconds))
    for game in collected:
        existing[game.game_id] = game
    _write_jsonl(args.output, existing)

    for game_id, reason in failures:
        print(f"FAILED {game_id}: {reason}", file=sys.stderr)
    print(f"wrote={len(existing)} new={len(collected)} failures={len(failures)} output={args.output}", file=sys.stderr)
    if failures and not args.allow_partial:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

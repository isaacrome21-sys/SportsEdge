"""Explicit historical MLB StatsAPI acquisition for offline research only.

Not a live odds collector, PIT capture mechanism or backfill of market evidence.
Each response is retained unmodified and hashed by the downstream manifest CLI.
Requires a manually selected historical date, not current or future dates.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import urlopen

API = "https://statsapi.mlb.com/api/v1"


def _fetch_json(url: str) -> tuple[bytes, dict]:
    with urlopen(url, timeout=25) as response:
        raw = response.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ValueError("RESPONSE_TOO_LARGE")
    return raw, json.loads(raw)


def acquire_historical_date(day: str, output_dir: str | Path) -> dict:
    target = date.fromisoformat(day)
    observed = datetime.now(timezone.utc)
    observed_at = observed.isoformat()
    if target >= observed.astimezone(timezone.utc).date():
        raise ValueError("DATE_NOT_HISTORICAL")
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError("OUTPUT_DIRECTORY_EXISTS")
    url = f"{API}/schedule?sportId=1&date={target.isoformat()}&gameType=R"
    raw, schedule = _fetch_json(url)
    games = [g for d in schedule.get("dates", []) for g in d.get("games", [])]
    if not games:
        raise ValueError("NO_SCHEDULED_GAMES")
    ids = []
    for game in games:
        pk = game.get("gamePk")
        if not isinstance(pk, int) or isinstance(pk, bool) or pk <= 0:
            raise ValueError("INVALID_SCHEDULE_GAME_ID")
        if game.get("status", {}).get("abstractGameState") != "Final":
            raise ValueError("NON_FINAL_SCHEDULE_GAME")
        ids.append(pk)
    if len(set(ids)) != len(ids):
        raise ValueError("DUPLICATE_SCHEDULE_GAME")
    # Acquire all bytes before creating the destination. Partial or failed
    # network retrieval cannot publish an apparently complete manifest.
    fetched = []
    for pk in ids:
        game_url = f"{API}/game/{pk}/feed/live"
        feed_raw, feed = _fetch_json(game_url)
        if feed.get("gamePk") != pk or feed.get("gameData", {}).get("game", {}).get("pk") != pk:
            raise ValueError("FEED_GAME_ID_MISMATCH")
        if feed.get("gameData", {}).get("status", {}).get("abstractGameState") != "Final":
            raise ValueError("NON_FINAL_FEED_GAME")
        scheduled = feed.get("gameData", {}).get("datetime", {}).get("dateTime")
        if not isinstance(scheduled, str):
            raise ValueError("MISSING_FEED_START_TIME")
        started = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        if started.tzinfo is None or started.astimezone(timezone.utc) >= observed:
            raise ValueError("FUTURE_OR_NAIVE_FEED_START")
        fetched.append((pk, feed_raw))
    output.mkdir(parents=True, exist_ok=False)
    (output / "schedule.json").write_bytes(raw)
    names = []
    for pk, data in fetched:
        name = f"game-{pk}.json"
        (output / name).write_bytes(data)
        names.append(name)
    manifest = {
        "schema": "MLB_FINAL_FEED_MANIFEST_V1",
        "source_url": url,
        "observed_at": observed_at,
        "feed_paths": names,
        "research_only": True,
        "no_pit_market_evidence": True,
        "historical_result_availability_verified": False,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"games": len(ids), "manifest": str(output / "manifest.json"),
            "research_only": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Historical YYYY-MM-DD")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    result = acquire_historical_date(args.date, args.output_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

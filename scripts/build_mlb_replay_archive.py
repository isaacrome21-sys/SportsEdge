#!/usr/bin/env python3
"""Build a provenance-preserving MLB March-August replay odds archive.

The default mode is PLAN and consumes no paid odds credits. ``--execute`` is
explicit and bounded by ``--max-estimated-credits``. The only network adapter in
this file that is enabled for direct acquisition is the official The Odds API
historical featured-market endpoint; other legitimate sources are registered for
licensed/manual import in ``sportsedge.mlb_evidence_archive`` and are never
silently scraped.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.mlb_evidence_archive import (
    EvidenceRow,
    PIT_TIMESTAMPED,
    SOURCE_REGISTRY,
    append_jsonl,
    bytes_sha256,
    canonical_json_sha256,
    iso_utc,
)

MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
ODDS_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "baseball_mlb"
DEFAULT_START = "2026-03-01"
DEFAULT_END = "2026-08-31"
DEFAULT_MARKETS = ("h2h", "spreads", "totals")
DEFAULT_CHECKPOINTS = ("T-90", "CLOSE_PRESTART")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_iso(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise ValueError("timestamp missing")
    out = datetime.fromisoformat(text)
    if out.tzinfo is None or out.utcoffset() is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _get_json(url: str, *, timeout: int = 30) -> tuple[bytes, Mapping[str, str]]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-V8-Replay/1.0"})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
    return raw, headers


def fetch_regular_season_schedule(start: date, end: date) -> tuple[list[dict[str, Any]], str, str]:
    params = urlencode({
        "sportId": 1,
        "gameType": "R",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "hydrate": "team",
    })
    uri = f"{MLB_SCHEDULE}?{params}"
    raw, _ = _get_json(uri, timeout=60)
    payload = json.loads(raw)
    games: list[dict[str, Any]] = []
    for d in payload.get("dates", []):
        for game in d.get("games", []):
            if not game.get("gameDate"):
                continue
            status = str(((game.get("status") or {}).get("abstractGameState") or "")).lower()
            games.append({
                "game_pk": str(game.get("gamePk")),
                "commence_time_utc": iso_utc(game["gameDate"], "gameDate"),
                "home_team": str((((game.get("teams") or {}).get("home") or {}).get("team") or {}).get("name") or ""),
                "away_team": str((((game.get("teams") or {}).get("away") or {}).get("team") or {}).get("name") or ""),
                "status": status,
            })
    return games, uri, sha256(raw).hexdigest()


def checkpoint_target(commence: datetime, checkpoint: str) -> datetime:
    c = checkpoint.upper()
    if c == "T-180":
        return commence - timedelta(minutes=180)
    if c == "T-90":
        return commence - timedelta(minutes=90)
    if c == "T-60":
        return commence - timedelta(minutes=60)
    if c == "T-30":
        return commence - timedelta(minutes=30)
    if c in {"T0", "CLOSE_PRESTART"}:
        return commence - timedelta(seconds=1)
    raise ValueError(f"unsupported checkpoint:{checkpoint}")


def build_plan(games: Iterable[Mapping[str, Any]], checkpoints: Iterable[str], *, market_count: int, region_count: int) -> dict[str, Any]:
    targets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    game_count = 0
    for raw in games:
        game_count += 1
        commence = _parse_iso(raw["commence_time_utc"])
        for cp in checkpoints:
            target = checkpoint_target(commence, cp)
            targets[target.isoformat()].append({"checkpoint": cp, **dict(raw)})
    unique = len(targets)
    estimated_credits = unique * 10 * int(market_count) * max(1, int(region_count))
    return {
        "game_count": game_count,
        "unique_snapshot_requests": unique,
        "market_count": int(market_count),
        "region_count": max(1, int(region_count)),
        "estimated_provider_credits": estimated_credits,
        "targets": targets,
    }


def _keys() -> list[str]:
    keys: list[str] = []
    for name in ("SPORTSEDGE_ODDS_API_KEY", "SPORTSEDGE_ODDS_API_KEY_2", "SPORTSEDGE_ODDS_API_KEY_3", "SPORTSEDGE_ODDS_API_KEY_4"):
        value = os.environ.get(name, "").strip()
        if value and value not in keys:
            keys.append(value)
    return keys


def _historical_url(*, key: str, timestamp: str, regions: str, markets: str, bookmakers: str | None) -> tuple[str, str]:
    public_params: dict[str, Any] = {
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "dateFormat": "iso",
        "date": timestamp,
    }
    if bookmakers:
        public_params["bookmakers"] = bookmakers
    private_params = {**public_params, "apiKey": key}
    public_uri = f"{ODDS_BASE}/historical/sports/{SPORT_KEY}/odds?{urlencode(public_params)}"
    private_uri = f"{ODDS_BASE}/historical/sports/{SPORT_KEY}/odds?{urlencode(private_params)}"
    return private_uri, public_uri


def fetch_historical_snapshot(*, timestamp: str, regions: str, markets: str, bookmakers: str | None) -> tuple[bytes, Mapping[str, str], str, int]:
    keys = _keys()
    if not keys:
        raise RuntimeError("THE_ODDS_API_KEY_REQUIRED")
    attempts: list[str] = []
    for slot, key in enumerate(keys, start=1):
        private_uri, public_uri = _historical_url(key=key, timestamp=timestamp, regions=regions, markets=markets, bookmakers=bookmakers)
        try:
            raw, headers = _get_json(private_uri, timeout=45)
            return raw, headers, public_uri, slot
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            attempts.append(f"slot={slot}:HTTP_{exc.code}:{body}")
            if exc.code not in {401, 403, 429}:
                break
        except URLError as exc:
            attempts.append(f"slot={slot}:URL:{exc.reason}")
        except Exception as exc:
            attempts.append(f"slot={slot}:{type(exc).__name__}:{exc}")
    raise RuntimeError("THE_ODDS_API_HISTORICAL_FETCH_FAILED:" + "|".join(attempts))


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").lower().replace(".", "").split())


def _match_game(event: Mapping[str, Any], wanted: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    event_home = _norm_name(event.get("home_team"))
    event_away = _norm_name(event.get("away_team"))
    event_time = _parse_iso(event.get("commence_time"))
    best: tuple[float, Mapping[str, Any]] | None = None
    for game in wanted:
        if _norm_name(game.get("home_team")) != event_home or _norm_name(game.get("away_team")) != event_away:
            continue
        delta = abs((_parse_iso(game.get("commence_time_utc")) - event_time).total_seconds())
        if delta <= 20 * 60 and (best is None or delta < best[0]):
            best = (delta, game)
    return None if best is None else best[1]


def _side(event: Mapping[str, Any], market: str, outcome: Mapping[str, Any]) -> tuple[str, str | None]:
    name = str(outcome.get("name") or "")
    description = str(outcome.get("description") or "").strip() or None
    if market == "totals" or name.lower() in {"over", "under", "yes", "no"}:
        return name.lower(), description
    if _norm_name(name) == _norm_name(event.get("home_team")):
        return "home", description
    if _norm_name(name) == _norm_name(event.get("away_team")):
        return "away", description
    return name.lower().replace(" ", "_"), description


def normalize_featured_snapshot(
    *, raw: bytes, public_uri: str, target_games: list[dict[str, Any]], collected_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(raw)
    snapshot_ts = iso_utc(payload.get("timestamp"), "snapshot timestamp")
    rows: list[dict[str, Any]] = []
    matched_events = 0
    for event in payload.get("data") or []:
        if not isinstance(event, Mapping):
            continue
        game = _match_game(event, target_games)
        if game is None:
            continue
        matched_events += 1
        checkpoint = str(game["checkpoint"])
        for book in event.get("bookmakers") or []:
            book_key = str(book.get("key") or "").strip() or None
            for market in book.get("markets") or []:
                market_key = str(market.get("key") or "").strip()
                provider_update = market.get("last_update") or book.get("last_update")
                for outcome in market.get("outcomes") or []:
                    price = outcome.get("price")
                    if price in (None, ""):
                        continue
                    side, participant = _side(event, market_key, outcome)
                    line = outcome.get("point")
                    row = EvidenceRow(
                        source_name="THE_ODDS_API",
                        source_uri=public_uri,
                        source_record_sha256=bytes_sha256(raw),
                        collected_at_utc=collected_at.isoformat().replace("+00:00", "Z"),
                        observed_at_utc=snapshot_ts,
                        event_id=str(game["game_pk"]),
                        commence_time_utc=str(game["commence_time_utc"]),
                        home_team=str(game["home_team"]),
                        away_team=str(game["away_team"]),
                        market=market_key,
                        side=side,
                        bookmaker=book_key,
                        american_odds=float(price),
                        line=None if line in (None, "") else float(line),
                        participant=participant,
                        checkpoint=checkpoint,
                        evidence_class=PIT_TIMESTAMPED,
                        provider_last_update_utc=None if not provider_update else iso_utc(provider_update, "provider update"),
                        provider_event_id=str(event.get("id") or "") or None,
                        source_tier="A_PIT_PROVIDER_SNAPSHOT",
                        metadata={
                            "provider_snapshot_timestamp": snapshot_ts,
                            "requested_checkpoint_target": checkpoint_target(_parse_iso(game["commence_time_utc"]), checkpoint).isoformat().replace("+00:00", "Z"),
                            "historical_snapshot_semantics": "closest_snapshot_at_or_before_requested_date",
                        },
                    ).as_record()
                    rows.append(row)
    meta = {"snapshot_timestamp": snapshot_ts, "matched_events": matched_events, "row_count": len(rows)}
    return rows, meta


def write_manifest(root: Path, *, args: argparse.Namespace, schedule_uri: str, schedule_sha: str, plan: Mapping[str, Any], acquisition: list[Mapping[str, Any]]) -> Path:
    manifest = {
        "schema_version": "mlb_replay_manifest_v8_1",
        "created_at_utc": _utcnow().isoformat().replace("+00:00", "Z"),
        "period": {"start": args.start, "end": args.end},
        "game_type": "REGULAR_SEASON_ONLY",
        "schedule_source": {"name": "MLB_STATSAPI", "uri": schedule_uri, "sha256": schedule_sha},
        "requested_markets": list(args.markets.split(",")),
        "requested_checkpoints": list(args.checkpoints.split(",")),
        "regions": args.regions,
        "bookmakers": args.bookmakers,
        "plan": {k: v for k, v in plan.items() if k != "targets"},
        "acquisition": acquisition,
        "source_registry_sha256": canonical_json_sha256(SOURCE_REGISTRY),
        "promotion_semantics": "RAW_ARCHIVE_DOES_NOT_PROMOTE_ANY_MARKET",
        "decision_close_rule": "SPREAD_TOTAL_PROP_CLV_REQUIRES_EXACT_ORIGINAL_THRESHOLD_AT_CLOSE",
    }
    manifest["manifest_sha256"] = canonical_json_sha256(manifest)
    path = root / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS))
    parser.add_argument("--checkpoints", default=",".join(DEFAULT_CHECKPOINTS))
    parser.add_argument("--regions", default="us")
    parser.add_argument("--bookmakers", default="")
    parser.add_argument("--output-root", default="artifacts/mlb_replay_2026_mar_aug")
    parser.add_argument("--max-estimated-credits", type=int, default=0, help="Hard preflight cap. 0 means PLAN ONLY unless --plan-only is used.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--limit-snapshots", type=int, default=0, help="Testing/probe limit after deterministic target sort.")
    parser.add_argument("--print-source-registry", action="store_true")
    args = parser.parse_args(argv)

    if args.print_source_registry:
        print(json.dumps(SOURCE_REGISTRY, indent=2, sort_keys=True))
        return 0

    start, end = _parse_date(args.start), _parse_date(args.end)
    if end < start:
        parser.error("end before start")
    markets = [x.strip() for x in args.markets.split(",") if x.strip()]
    checkpoints = [x.strip().upper() for x in args.checkpoints.split(",") if x.strip()]
    regions = [x.strip() for x in args.regions.split(",") if x.strip()]
    if not markets or not checkpoints:
        parser.error("markets/checkpoints required")

    games, schedule_uri, schedule_sha = fetch_regular_season_schedule(start, end)
    plan = build_plan(games, checkpoints, market_count=len(markets), region_count=len(regions))
    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "plan.json").write_text(json.dumps({k: v for k, v in plan.items() if k != "targets"}, indent=2, sort_keys=True) + "\n")

    print(json.dumps({k: v for k, v in plan.items() if k != "targets"}, sort_keys=True))
    if args.plan_only or not args.execute:
        write_manifest(root, args=args, schedule_uri=schedule_uri, schedule_sha=schedule_sha, plan=plan, acquisition=[])
        return 0

    estimated = int(plan["estimated_provider_credits"])
    if args.max_estimated_credits <= 0 or estimated > args.max_estimated_credits:
        raise SystemExit(f"BACKFILL_CREDIT_CAP_BLOCKED estimated={estimated} cap={args.max_estimated_credits}")

    acquisition: list[dict[str, Any]] = []
    canonical_path = root / "canonical" / "the_odds_api_featured.jsonl"
    targets = sorted(plan["targets"].items())
    if args.limit_snapshots > 0:
        targets = targets[: args.limit_snapshots]

    for index, (target_iso, target_games) in enumerate(targets, start=1):
        requested = _parse_iso(target_iso).isoformat().replace("+00:00", "Z")
        collected = _utcnow()
        raw, headers, public_uri, slot = fetch_historical_snapshot(
            timestamp=requested,
            regions=",".join(regions),
            markets=",".join(markets),
            bookmakers=args.bookmakers or None,
        )
        raw_sha = bytes_sha256(raw)
        stamp = requested.replace(":", "").replace("-", "")
        raw_path = root / "raw" / "the_odds_api" / f"snapshot_{stamp}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
        normalized, meta = normalize_featured_snapshot(raw=raw, public_uri=public_uri, target_games=target_games, collected_at=collected)
        append_jsonl(canonical_path, normalized)
        acquisition.append({
            "request_index": index,
            "requested_at_or_before": requested,
            "target_game_count": len(target_games),
            "raw_path": str(raw_path),
            "raw_sha256": raw_sha,
            "key_slot": slot,
            "provider_request_cost": headers.get("x-requests-last"),
            "provider_requests_remaining": headers.get("x-requests-remaining"),
            **meta,
        })
        print(json.dumps(acquisition[-1], sort_keys=True))

    write_manifest(root, args=args, schedule_uri=schedule_uri, schedule_sha=schedule_sha, plan=plan, acquisition=acquisition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

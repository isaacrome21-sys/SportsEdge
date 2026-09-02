#!/usr/bin/env python3
"""Canonicalize SportsEdge's raw forward MLB odds into immutable V8 evidence rows."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.mlb_evidence_archive import (
    EvidenceRow,
    FORWARD_EPOCH_UTC,
    PIT_TIMESTAMPED,
    append_jsonl,
    bytes_sha256,
    canonical_json_sha256,
    iso_utc,
)

MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
FORWARD_EPOCH = datetime.fromisoformat(FORWARD_EPOCH_UTC.replace("Z", "+00:00"))
RAW_URI = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"


def _utc(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    out = datetime.fromisoformat(text)
    if out.tzinfo is None or out.utcoffset() is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _json_get(url: str) -> bytes:
    with urlopen(Request(url, headers={"Accept":"application/json","User-Agent":"SportsEdge-V8-Forward/1.0"}), timeout=30) as response:
        return response.read()


def _schedule(slate: str) -> list[dict[str, Any]]:
    uri = f"{MLB_SCHEDULE}?" + urlencode({"sportId":1,"date":slate,"gameType":"R","hydrate":"team"})
    payload = json.loads(_json_get(uri))
    out = []
    for d in payload.get("dates", []):
        for game in d.get("games", []):
            if not game.get("gameDate"):
                continue
            out.append({
                "game_pk": str(game.get("gamePk")),
                "commence_time_utc": iso_utc(game["gameDate"], "gameDate"),
                "home_team": str((((game.get("teams") or {}).get("home") or {}).get("team") or {}).get("name") or ""),
                "away_team": str((((game.get("teams") or {}).get("away") or {}).get("team") or {}).get("name") or ""),
            })
    return out


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().replace(".", "").split())


def _match(event: Mapping[str, Any], schedule: list[dict[str, Any]]) -> dict[str, Any] | None:
    home, away = _norm(event.get("home_team")), _norm(event.get("away_team"))
    commence = _utc(event.get("commence_time"))
    best = None
    for game in schedule:
        if _norm(game["home_team"]) != home or _norm(game["away_team"]) != away:
            continue
        delta = abs((_utc(game["commence_time_utc"]) - commence).total_seconds())
        if delta <= 20 * 60 and (best is None or delta < best[0]):
            best = (delta, game)
    return None if best is None else best[1]


def _status_rows(raw_root: Path) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for path in raw_root.glob("status/*/*.json"):
        try:
            row = json.loads(path.read_text())
        except Exception:
            continue
        raw_file = str(row.get("raw_file") or "")
        if raw_file:
            out[raw_file] = row
    return out


def _checkpoint(raw_path: Path, status: Mapping[str, Any]) -> str:
    value = str(status.get("capture_window") or "").strip()
    if value:
        return "CLOSE_PRESTART" if value == "T0" else value.replace("m", "")
    parent = raw_path.parent.name.lower()
    if "minus180" in parent: return "T-180"
    if "minus90" in parent: return "T-90"
    if parent == "t0": return "CLOSE_PRESTART"
    return "UNCLASSIFIED"


def _side(event: Mapping[str, Any], market: str, outcome: Mapping[str, Any]) -> tuple[str, str | None]:
    name = str(outcome.get("name") or "")
    participant = str(outcome.get("description") or "").strip() or None
    if market == "totals" or name.lower() in {"over","under","yes","no"}:
        return name.lower(), participant
    if _norm(name) == _norm(event.get("home_team")): return "home", participant
    if _norm(name) == _norm(event.get("away_team")): return "away", participant
    return name.lower().replace(" ", "_"), participant


def canonicalize(raw_root: Path, output_root: Path) -> dict[str, Any]:
    statuses = _status_rows(raw_root)
    rows_written = 0
    raw_files = 0
    skipped_pre_epoch = 0
    unmatched_events = 0
    poststart_events_rejected = 0
    manifests = []
    schedule_cache: dict[str, list[dict[str, Any]]] = {}

    for raw_path in sorted(raw_root.glob("20??-??-??/*/game_odds_*.json")):
        status = statuses.get(str(raw_path))
        if not status:
            continue
        observed = _utc(status.get("run_at_utc"))
        if observed < FORWARD_EPOCH:
            skipped_pre_epoch += 1
            continue
        slate = str(status.get("slate_date_ct") or raw_path.parts[-3])
        schedule_cache.setdefault(slate, _schedule(slate))
        raw = raw_path.read_bytes()
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        raw_files += 1
        checkpoint = _checkpoint(raw_path, status)
        canonical_rows = []
        for event in payload:
            if not isinstance(event, Mapping):
                continue
            game = _match(event, schedule_cache[slate])
            if game is None:
                unmatched_events += 1
                continue
            if observed >= _utc(game["commence_time_utc"]):
                poststart_events_rejected += 1
                continue
            for book in event.get("bookmakers") or []:
                for market in book.get("markets") or []:
                    market_key = str(market.get("key") or "")
                    provider_update = market.get("last_update") or book.get("last_update")
                    for outcome in market.get("outcomes") or []:
                        if outcome.get("price") in (None, ""):
                            continue
                        side, participant = _side(event, market_key, outcome)
                        line = outcome.get("point")
                        canonical_rows.append(EvidenceRow(
                            source_name="SPORTSEDGE_V8_FORWARD",
                            source_uri=RAW_URI,
                            source_record_sha256=bytes_sha256(raw),
                            collected_at_utc=observed.isoformat().replace("+00:00","Z"),
                            observed_at_utc=observed.isoformat().replace("+00:00","Z"),
                            event_id=game["game_pk"],
                            commence_time_utc=game["commence_time_utc"],
                            home_team=game["home_team"], away_team=game["away_team"],
                            market=market_key, side=side,
                            bookmaker=str(book.get("key") or "") or None,
                            american_odds=float(outcome["price"]),
                            line=None if line in (None, "") else float(line),
                            participant=participant,
                            checkpoint=checkpoint,
                            evidence_class=PIT_TIMESTAMPED,
                            provider_last_update_utc=None if not provider_update else iso_utc(provider_update, "provider last update"),
                            provider_event_id=str(event.get("id") or "") or None,
                            source_tier="A_FORWARD_IMMUTABLE",
                            metadata={
                                "upstream_provider":"THE_ODDS_API",
                                "raw_file":str(raw_path),
                                "capture_status_sha256":canonical_json_sha256(status),
                                "forward_epoch_utc":FORWARD_EPOCH_UTC,
                            },
                        ).as_record())
        day_path = output_root / slate / "market_snapshots.jsonl"
        rows_written += append_jsonl(day_path, canonical_rows)
        manifests.append({
            "raw_file": str(raw_path),
            "raw_sha256": bytes_sha256(raw),
            "checkpoint": checkpoint,
            "observed_at_utc": observed.isoformat().replace("+00:00","Z"),
            "canonical_row_count": len(canonical_rows),
        })

    manifest = {
        "schema_version":"mlb_v8_forward_manifest_v1",
        "forward_epoch_utc":FORWARD_EPOCH_UTC,
        "raw_file_count":raw_files,
        "rows_written":rows_written,
        "skipped_pre_epoch":skipped_pre_epoch,
        "unmatched_events":unmatched_events,
        "poststart_events_rejected":poststart_events_rejected,
        "snapshots":manifests,
        "promotion_semantics":"COLLECTION_ONLY_NO_AUTOMATIC_PROMOTION",
        "close_pair_rule":"EXACT_ORIGINAL_THRESHOLD_REQUIRED_FOR_SPREAD_TOTAL_PROP_CLV",
    }
    manifest["manifest_sha256"] = canonical_json_sha256(manifest)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv=None) -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--raw-root", default="artifacts/raw_odds")
    p.add_argument("--output-root", default="artifacts/v8_forward")
    args=p.parse_args(argv)
    manifest=canonicalize(Path(args.raw_root), Path(args.output_root))
    print(json.dumps(manifest, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

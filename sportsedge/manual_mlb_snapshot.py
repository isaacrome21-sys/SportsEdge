from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib, json
from pathlib import Path
from typing import Any, Mapping
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .generic_card_pipeline import run_generic_card
from .live_slate import LiveGame, TeamLineup
from .mlb_generic_features import GAME_MARKETS, MLBGenericHistorySource
from .mlb_history_cache import MLBHistoryCachedOpener
from .mlb_source import fetch_schedule, parse_game_start
from .quote_bridge import validate_canonical_quote
from .runtime import parse_timestamp

CT = ZoneInfo("America/Chicago")
DEVIG_METHOD = "MULTIPLICATIVE_V1"

class ManualSnapshotError(ValueError): pass

def _text(v, name):
    out = str(v or "").strip()
    if not out: raise ManualSnapshotError(f"{name} is required")
    return out

def _sha(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def resolve_game(snapshot: Mapping[str, Any], opener=urlopen):
    g = snapshot.get("game")
    if not isinstance(g, Mapping): raise ManualSnapshotError("game object is required")
    away, home = _text(g.get("away_team"), "away_team"), _text(g.get("home_team"), "home_team")
    start = parse_timestamp(_text(g.get("scheduled_start_ct"), "scheduled_start_ct"))
    captured = parse_timestamp(_text(snapshot.get("captured_at"), "captured_at")).astimezone(timezone.utc)
    game_number = int(g["game_number"]) if g.get("game_number") is not None else None
    rows = fetch_schedule(start.astimezone(CT).date().isoformat(), opener=opener, now=captured)
    matches = []
    for r in rows:
        if str(r.away_name) != away or str(r.home_name) != home: continue
        if game_number is not None and r.game_number is not None and int(r.game_number) != game_number: continue
        if abs((parse_game_start(r.game_date) - start.astimezone(timezone.utc)).total_seconds()) > 120: continue
        matches.append(r)
    if len(matches) != 1: raise ManualSnapshotError(f"MANUAL_GAME_RESOLUTION_FAILED: found={len(matches)}")
    r = matches[0]
    if captured >= parse_game_start(r.game_date): raise ManualSnapshotError("MANUAL_SNAPSHOT_NOT_PREGAME")
    if str(r.status) != "Preview": raise ManualSnapshotError(f"MLB_GAME_NOT_PREVIEW: {r.status}")
    return r, captured

def quote_rows(snapshot: Mapping[str, Any], game_pk: int, captured: datetime):
    source, book = _text(snapshot.get("source"), "source"), _text(snapshot.get("book_key"), "book_key")
    offers = snapshot.get("offers")
    if not isinstance(offers, list) or not offers: raise ManualSnapshotError("offers must be non-empty")
    out = []
    for i, o in enumerate(offers):
        if not isinstance(o, Mapping): raise ManualSnapshotError(f"offers[{i}] malformed")
        market = _text(o.get("market"), "market").upper()
        if market not in GAME_MARKETS: raise ManualSnapshotError(f"unsupported manual market: {market}")
        out.append(validate_canonical_quote({
            "game_id": str(game_pk), "period": _text(o.get("period"), "period").upper(),
            "market": market, "entity_id": str(game_pk), "line": o.get("line"),
            "side": _text(o.get("side"), "side").upper(), "american_odds": o.get("american_odds"),
            "book_key": book, "is_alternate": bool(o.get("is_alternate", False)),
            "raw_market_name": _text(o.get("raw_market_name"), "raw_market_name"),
            "retrieved_at": captured, "ttl_seconds": int(o.get("ttl_seconds", 300)),
            "sportsbook": book, "selection": str(o.get("selection") or o.get("side") or ""),
            "source_url": source,
        }))
    return out

def run_manual_mlb_snapshot(snapshot: Mapping[str, Any], *, opener=urlopen, registry_path="config/deployments.json", edge_floor_config_path="config/truth_gate_floors.json", kelly_multiplier=0.25, history_cache_dir: str|Path|None=None):
    if int(snapshot.get("schema_version", 0)) != 1: raise ManualSnapshotError("schema_version must be 1")
    g, captured = resolve_game(snapshot, opener=opener)
    quotes = quote_rows(snapshot, g.game_pk, captured)
    live = LiveGame(g.game_pk, g.away_id, g.home_id, g.away_probable_pitcher_id, g.home_probable_pitcher_id,
                    TeamLineup(g.away_id,"away",(),(),False), TeamLineup(g.home_id,"home",(),(),False),
                    g.game_number, g.double_header, g.venue_id, g.official_date, g.status)
    hist_opener = MLBHistoryCachedOpener(target_date=captured.astimezone(CT).date(), cache_dir=history_cache_dir, opener=opener)
    hist = MLBGenericHistorySource(opener=hist_opener, retrieved_at=captured)
    target_date = datetime.fromisoformat(str(g.official_date)).date() if g.official_date else captured.astimezone(CT).date()
    features, seen = [], set()
    for q in quotes:
        m = str(q["market"])
        if m in seen: continue
        seen.add(m)
        features.append(hist.feature_row(game_pk=g.game_pk, market=m, entity_id=str(g.game_pk), target_date=target_date,
                                         away_team_id=int(g.away_id), home_team_id=int(g.home_id)))
    results = run_generic_card(games=[live], feature_rows=features, quotes=quotes, ingestion_now=captured, finalization_now=captured,
                               registry_path=registry_path, edge_floor_config_path=edge_floor_config_path, kelly_multiplier=kelly_multiplier)
    return {"schema_version":1, "run_type":"USER_SUPPLIED_MARKET_SNAPSHOT", "source":snapshot.get("source"),
            "book_key":snapshot.get("book_key"), "captured_at_utc":captured.isoformat(), "snapshot_sha256":_sha(snapshot),
            "devig_method":DEVIG_METHOD,
            "resolved_game":{"game_pk":int(g.game_pk),"away_team":g.away_name,"home_team":g.home_name,"game_number":g.game_number,
                             "scheduled_start_utc":parse_game_start(g.game_date).isoformat()},
            "feature_lineage":[{"market":f["market"],"source":f.get("source"),"source_subset_hash":f.get("source_subset_hash")} for f in features],
            "results":[asdict(r) for r in results]}

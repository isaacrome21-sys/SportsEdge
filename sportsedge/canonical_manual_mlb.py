from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib, json
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .engine_registry import resolve_manual_market_type
from .generic_card_pipeline import run_generic_card
from .live_slate import LiveGame, TeamLineup
from .manual_quote import ManualQuote, validate_manual_quote
from .mlb_generic_features import MLBGenericHistorySource
from .mlb_history_cache import MLBHistoryCachedOpener
from .mlb_source import fetch_schedule, parse_game_start
from .quote_bridge import validate_canonical_quote

class CanonicalManualMLBError(ValueError): pass

CHICAGO_TZ = ZoneInfo("America/Chicago")

def _sha(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

def _norm_team(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace(".", "").split())

def _schedule_date_for_quote(row: ManualQuote) -> str:
    # validate_manual_quote normalizes timestamps to UTC. Resolve the schedule
    # using the same Chicago-local slate date enforced by the live workflow so
    # late-evening games do not roll into the following UTC calendar date.
    return row.first_pitch_at.astimezone(CHICAGO_TZ).date().isoformat()

def _resolve_game(row: ManualQuote, opener=urlopen):
    rows = fetch_schedule(_schedule_date_for_quote(row), opener=opener, now=row.observed_at)
    game_key = str(row.game_id).strip()
    matches = [g for g in rows if str(g.game_pk) == game_key]
    if not matches and "@" in game_key:
        away_key, home_key = (_norm_team(v) for v in game_key.split("@", 1))
        matches = [
            g for g in rows
            if _norm_team(g.away_name) == away_key and _norm_team(g.home_name) == home_key
        ]
    if len(matches) != 1: raise CanonicalManualMLBError(f"MANUAL_GAME_RESOLUTION_FAILED: game_id={row.game_id} found={len(matches)}")
    g = matches[0]
    scheduled = parse_game_start(g.game_date)
    if abs((scheduled - row.first_pitch_at.astimezone(timezone.utc)).total_seconds()) > 120: raise CanonicalManualMLBError("MANUAL_FIRST_PITCH_MISMATCH")
    if row.observed_at.astimezone(timezone.utc) >= scheduled: raise CanonicalManualMLBError("MANUAL_QUOTE_NOT_PREGAME")
    return g

def _side(market_type: str, side: str) -> str:
    s = side.upper()
    if market_type == "FIRST_INNING_TOTAL":
        if s == "OVER": return "YES"
        if s == "UNDER": return "NO"
        raise CanonicalManualMLBError("FIRST_INNING_TOTAL side must be OVER/UNDER")
    return s

def _pair(row: ManualQuote, market: str, entity_id: str, *, resolved_game_id: str | None = None) -> list[dict[str, Any]]:
    period = "1ST" if row.market_type == "FIRST_INNING_TOTAL" else ("F5" if row.market_type.startswith("FIRST_FIVE_") else "FG")
    paired_line = -row.line if row.market_type in {"RUN_LINE", "FIRST_FIVE_RUN_LINE"} else row.line
    game_id = str(resolved_game_id or row.game_id)
    def q(side: str, price: int, line: float):
        return validate_canonical_quote({"game_id":game_id,"period":period,"market":market,"entity_id":entity_id,"line":line,
            "side":_side(row.market_type, side),"american_odds":price,"book_key":row.book,"is_alternate":False,
            "raw_market_name":row.market_type,"retrieved_at":row.observed_at,"ttl_seconds":3600,"sportsbook":row.book,
            "selection":side,"source_url":"MANUAL"})
    return [q(row.side,row.price,row.line), q(row.paired_side,row.paired_price,paired_line)]

def run_canonical_manual_mlb(rows: Iterable[Mapping[str, Any]], *, opener=urlopen, registry_path="config/deployments.json",
                             edge_floor_config_path="config/truth_gate_floors.json", kelly_multiplier=0.25,
                             history_cache_dir: str|Path|None=None) -> dict[str, Any]:
    raw = list(rows)
    if not raw: raise CanonicalManualMLBError("manual rows must be non-empty")
    parsed = [validate_manual_quote(r) for r in raw]
    if len({r.game_id for r in parsed}) != 1: raise CanonicalManualMLBError("one game_id per run is required")
    if len({r.first_pitch_at for r in parsed}) != 1: raise CanonicalManualMLBError("all rows must share first_pitch_at")
    g = _resolve_game(max(parsed, key=lambda r: r.observed_at), opener=opener)
    live = LiveGame(g.game_pk,g.away_id,g.home_id,g.away_probable_pitcher_id,g.home_probable_pitcher_id,
                    TeamLineup(g.away_id,"away",(),(),False),TeamLineup(g.home_id,"home",(),(),False),
                    g.game_number,g.double_header,g.venue_id,g.official_date,g.status)
    captured = max(r.observed_at for r in parsed).astimezone(timezone.utc)
    hist = MLBGenericHistorySource(opener=MLBHistoryCachedOpener(target_date=captured.date(),cache_dir=history_cache_dir,opener=opener), retrieved_at=captured)
    target_date = datetime.fromisoformat(str(g.official_date)).date() if g.official_date else captured.date()
    quotes, features, resolutions, seen = [], [], [], set()
    for row in parsed:
        market = resolve_manual_market_type(row.market_type)
        entity_id = row.subject_id or str(g.game_pk)
        if row.market_type.startswith("PITCHER_") and not row.subject_id: raise CanonicalManualMLBError(f"subject_id required for {row.market_type}")
        quotes.extend(_pair(row, market, entity_id, resolved_game_id=str(g.game_pk)))
        key = (market, entity_id)
        if key not in seen:
            seen.add(key)
            features.append(hist.feature_row(game_pk=g.game_pk,market=market,entity_id=entity_id,target_date=target_date,
                away_team_id=int(g.away_id),home_team_id=int(g.home_id),player_id=int(row.subject_id) if row.subject_id else None))
        resolutions.append({"market_type":row.market_type,"engine_market":market,"subject_id":row.subject_id,"observed_at":row.observed_at.isoformat()})
    results = run_generic_card(games=[live],feature_rows=features,quotes=quotes,ingestion_now=captured,finalization_now=captured,
        registry_path=registry_path,edge_floor_config_path=edge_floor_config_path,kelly_multiplier=kelly_multiplier)
    return {"schema_version":2,"run_type":"CANONICAL_MANUAL_QUOTES","source":"MANUAL","observed_at_utc":captured.isoformat(),
        "snapshot_sha256":_sha(raw),"resolved_game":{"game_pk":int(g.game_pk),"away_team":g.away_name,"home_team":g.home_name,
        "scheduled_start_utc":parse_game_start(g.game_date).isoformat()},"market_resolution":resolutions,
        "feature_lineage":[{"market":f["market"],"entity_id":f["entity_id"],"source":f.get("source"),"source_subset_hash":f.get("source_subset_hash")} for f in features],
        "results":[asdict(r) for r in results]}

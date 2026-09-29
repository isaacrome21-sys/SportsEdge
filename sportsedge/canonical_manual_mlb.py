from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib, json
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.request import urlopen
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from .mlb_empirical_support import support_evidence
from .engine_registry import resolve_manual_market_type
from .generic_card_pipeline import run_generic_card
from .live_slate import LiveGame, TeamLineup
from .manual_quote import ManualQuote, validate_manual_quote
from .mlb_all_market_features import EITHER_PITCHER_MARKETS, MLBAllMarketHistorySource
from .mlb_history_cache import MLBHistoryCachedOpener
from .mlb_source import fetch_schedule, parse_game_start
from .quote_bridge import validate_canonical_quote

class CanonicalManualMLBError(ValueError): pass

CHICAGO_TZ = ZoneInfo("America/Chicago")
TEAM_TOTAL_MARKETS = frozenset({"TEAM_TOTALS", "F5_TEAM_TOTALS"})
PLAYER_MARKETS = frozenset({
    "HOME_RUNS","HITS","TOTAL_BASES","RBI","RUNS","STOLEN_BASES","BATTER_BB","EXTRA_BASE_HITS",
    "SINGLES","DOUBLES","TRIPLES","BATTER_K","HITS_RUNS_RBIS","HITS_RUNS_STOLEN_BASES","RUNS_RBIS",
    "HITS_STOLEN_BASES","HITS_WALKS_STOLEN_BASES","PITCHER_K","PITCHER_OUTS","PITCHER_ER",
    "PITCHER_HITS_ALLOWED","PITCHER_BB","PITCHER_HITS_WALKS_ER","FIRST_HOME_RUN","PITCHER_RECORD_WIN",
})

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

def _norm_person(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())

def _resolve_subject(row: ManualQuote, *, opener=urlopen) -> tuple[str | None, int | None]:
    if not row.subject_name and row.subject_id:
        url = f"https://statsapi.mlb.com/api/v1/people/{quote_plus(str(row.subject_id))}?hydrate=currentTeam"
        try:
            with opener(url, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CanonicalManualMLBError(f"MANUAL_SUBJECT_LOOKUP_FAILED:{row.subject_id}") from exc
        matches = payload.get("people", [])
        if len(matches) != 1:
            raise CanonicalManualMLBError(f"MANUAL_SUBJECT_RESOLUTION_FAILED:{row.subject_id}")
        person = matches[0]
        team = person.get("currentTeam") or {}
        team_id = team.get("id")
        if isinstance(team_id, bool) or not isinstance(team_id, int) or team_id <= 0:
            raise CanonicalManualMLBError(f"MANUAL_SUBJECT_TEAM_INVALID:{row.subject_id}")
        return str(row.subject_id), team_id
    if not row.subject_name:
        return None, None
    url = f"https://statsapi.mlb.com/api/v1/people/search?names={quote_plus(row.subject_name)}&active=true&sportIds=1&hydrate=currentTeam"
    try:
        with opener(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CanonicalManualMLBError(f"MANUAL_SUBJECT_LOOKUP_FAILED:{row.subject_name}") from exc
    target = _norm_person(row.subject_name)
    matches = [p for p in payload.get("people", []) if _norm_person(p.get("fullName")) == target]
    if len(matches) != 1:
        raise CanonicalManualMLBError(f"MANUAL_SUBJECT_RESOLUTION_FAILED: subject_name={row.subject_name} found={len(matches)}")
    person_id = matches[0].get("id")
    if isinstance(person_id, bool) or not isinstance(person_id, int) or person_id <= 0:
        raise CanonicalManualMLBError(f"MANUAL_SUBJECT_ID_INVALID:{row.subject_name}")
    supplied = str(row.subject_id) if row.subject_id else None
    if supplied is not None and supplied != str(person_id):
        raise CanonicalManualMLBError(f"MANUAL_SUBJECT_ID_NAME_MISMATCH:{row.subject_name}")
    team = matches[0].get("currentTeam") or {}
    team_id = team.get("id")
    if isinstance(team_id, bool) or (team_id is not None and (not isinstance(team_id, int) or team_id <= 0)):
        raise CanonicalManualMLBError(f"MANUAL_SUBJECT_TEAM_INVALID:{row.subject_name}")
    return str(person_id), team_id

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
    resolved_subjects: list[tuple[str | None, int | None]] = []
    subject_errors: list[str | None] = []
    for row in parsed:
        try:
            pid, tid = _resolve_subject(row, opener=opener)
            if pid and tid is not None and tid not in {g.away_id, g.home_id}:
                raise CanonicalManualMLBError(f"MANUAL_SUBJECT_TEAM_NOT_IN_GAME:{row.subject_name or pid}")
            resolved_subjects.append((pid, tid))
            subject_errors.append(None)
        except CanonicalManualMLBError as exc:
            resolved_subjects.append((None, None))
            subject_errors.append(str(exc))
    # This is only fallback membership evidence from the sportsbook's prop board.
    # It is not a projected batting order and carries no batting-slot information.
    away_projected = tuple(sorted({int(pid) for (pid, tid), row, err in zip(resolved_subjects, parsed, subject_errors) if not err and pid and tid == g.away_id and not row.market_type.startswith("PITCHER_")}))
    home_projected = tuple(sorted({int(pid) for (pid, tid), row, err in zip(resolved_subjects, parsed, subject_errors) if not err and pid and tid == g.home_id and not row.market_type.startswith("PITCHER_")}))
    live = LiveGame(g.game_pk,g.away_id,g.home_id,g.away_probable_pitcher_id,g.home_probable_pitcher_id,
                    TeamLineup(g.away_id,"away",away_projected,(),False),TeamLineup(g.home_id,"home",home_projected,(),False),
                    g.game_number,g.double_header,g.venue_id,g.official_date,g.status)
    captured = max(r.observed_at for r in parsed).astimezone(timezone.utc)
    hist = MLBAllMarketHistorySource(opener=MLBHistoryCachedOpener(target_date=captured.date(),cache_dir=history_cache_dir,opener=opener), retrieved_at=captured)
    target_date = datetime.fromisoformat(str(g.official_date)).date() if g.official_date else captured.date()
    quotes, features, resolutions, seen = [], [], [], set()
    blocked_subject_rows: list[dict[str, Any]] = []
    for row, (subject_id, subject_team_id), subject_error in zip(parsed, resolved_subjects, subject_errors):
        market = resolve_manual_market_type(row.market_type)
        if subject_error:
            entity = str(row.subject_id or row.subject_name or "UNRESOLVED")
            for side, price, line in ((row.side, row.price, row.line), (row.paired_side, row.paired_price, -row.line if row.market_type in {"RUN_LINE","FIRST_FIVE_RUN_LINE"} else row.line)):
                blocked_subject_rows.append({"game_id":str(g.game_pk),"market":market,"entity_id":entity,"line":line,"side":_side(row.market_type, side),
                    "american_odds":price,"model_p":None,"bet_status":"BLOCKED","reason":subject_error,"book_key":row.book,"sportsbook":row.book,
                    "quote_retrieved_at":row.observed_at.isoformat()})
            resolutions.append({"market_type":row.market_type,"engine_market":market,"subject_id":row.subject_id,"subject_name":row.subject_name,
                "observed_at":row.observed_at.isoformat(),"resolution_status":"BLOCKED","reason":subject_error})
            continue
        is_player_market = market in PLAYER_MARKETS
        if is_player_market and not subject_id:
            raise CanonicalManualMLBError(f"subject_id or subject_name required for {row.market_type}")
        feature_team_id = subject_team_id
        if market in TEAM_TOTAL_MARKETS:
            if row.team_side not in {"HOME", "AWAY"}:
                raise CanonicalManualMLBError(f"team_side HOME/AWAY required for {row.market_type}")
            feature_team_id = int(g.home_id if row.team_side == "HOME" else g.away_id)
            entity_id = str(feature_team_id)
        elif market in EITHER_PITCHER_MARKETS:
            if g.away_probable_pitcher_id is None or g.home_probable_pitcher_id is None:
                raise CanonicalManualMLBError(f"both probable pitchers required for {row.market_type}")
            entity_id = f"{int(g.away_probable_pitcher_id)}|{int(g.home_probable_pitcher_id)}"
            feature_team_id = None
        else:
            entity_id = subject_id or str(g.game_pk)
        quotes.extend(_pair(row, market, entity_id, resolved_game_id=str(g.game_pk)))
        key = (market, entity_id)
        if key not in seen:
            seen.add(key)
            features.append(hist.feature_row(game_pk=g.game_pk,market=market,entity_id=entity_id,target_date=target_date,
                away_team_id=int(g.away_id),home_team_id=int(g.home_id),player_id=int(subject_id) if subject_id else None,
                team_id=feature_team_id,away_pitcher_id=g.away_probable_pitcher_id,home_pitcher_id=g.home_probable_pitcher_id))
        resolutions.append({"market_type":row.market_type,"engine_market":market,"subject_id":subject_id,"subject_name":row.subject_name,
            "team_side":row.team_side,"entity_id":entity_id,"observed_at":row.observed_at.isoformat()})
    results = run_generic_card(games=[live],feature_rows=features,quotes=quotes,ingestion_now=captured,finalization_now=captured,
        registry_path=registry_path,edge_floor_config_path=edge_floor_config_path,kelly_multiplier=kelly_multiplier)
    # Attach support evidence after pricing; engine inputs/outputs are unchanged.
    feature_by_key = {(str(f["market"]), str(f["entity_id"])): f for f in features}
    result_rows = [asdict(r) for r in results]
    for result in result_rows:
        feature = feature_by_key.get((str(result["market"]), str(result["entity_id"])), {})
        evidence = support_evidence(feature, result)
        if evidence is not None:
            result["empirical_evidence"] = evidence
    return {"schema_version":2,"run_type":"CANONICAL_MANUAL_QUOTES","source":"MANUAL","observed_at_utc":captured.isoformat(),
        "snapshot_sha256":_sha(raw),"resolved_game":{"game_pk":int(g.game_pk),"away_team":g.away_name,"home_team":g.home_name,
        "scheduled_start_utc":parse_game_start(g.game_date).isoformat()},"market_resolution":resolutions,
        "feature_lineage":[{"market":f["market"],"entity_id":f["entity_id"],"source":f.get("source"),"source_subset_hash":f.get("source_subset_hash")} for f in features],
        "lineup_membership_tier":"DK_PROP_LISTED","results":result_rows + blocked_subject_rows}
"""Fully automated MLB slate orchestration with fail-closed live-source guards.

Validated HITS/TOTAL_BASES/PITCHER_BB continue through the frozen feature bridge.
Expanded markets use a separate price-independent generic pregame feature contract.
No Model_P is ever derived from sportsbook price or implied probability.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from math import isfinite
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from .feature_bridge import FeatureBridgeError, parse_source_fact, resolve_feature_row
from .generic_card_pipeline import GENERIC_MARKETS
from .live_slate import LiveGame, TeamLineup, lineup_from_rows
from .market_surface import (
    CoverageSlot,
    DEFAULT_MARKET_SURFACE_PATH,
    build_market_grid,
    compose_card_status,
    compose_run_status,
    load_market_surface,
)
from .mlb_source import fetch_boxscore, fetch_schedule, parse_confirmed_lineup, parse_game_start
from .prediction_journal import normalize_legacy_block_reason
from .quote_bridge import QuoteBridgeError, validate_canonical_quote
from .runtime import parse_timestamp
from .unified_card import UnifiedCardResult, run_unified_card

CHICAGO_TZ = ZoneInfo("America/Chicago")
VALIDATED_BRIDGE_MARKETS = frozenset({"HITS", "TOTAL_BASES", "PITCHER_BB"})
GENERIC_FEATURE_MARKETS = frozenset(set(GENERIC_MARKETS) | {"PITCHER_BB"})
ENGINE_CAPABLE_MARKETS = frozenset(set(GENERIC_MARKETS) | set(VALIDATED_BRIDGE_MARKETS))
BANNED_GENERIC_KEYS = frozenset({
    "sportsbook_probability", "implied_probability", "market_probability",
    "american_odds", "decimal_odds", "sportsbook_price", "dk_probability",
})


class AutoRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutoCardResult:
    source_index: int
    game_id: str
    market: str
    entity_id: str
    line: Any
    side: str
    american_odds: Any
    model_p: float | None
    bet_status: str
    reason: str
    shadow_status: str | None = None
    implied_probability: float | None = None
    edge: float | None = None
    ev_per_dollar: float | None = None
    model_input_hash: str | None = None
    distribution_sha256: str | None = None
    readout_sha256: str | None = None
    readout_version: str | None = None
    engine_version: str | None = None
    seed_policy: str | None = None
    mc_paths: int | None = None
    book_key: str | None = None
    sportsbook: str | None = None
    quote_retrieved_at: str | None = None
    offer_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class AutoRunReport:
    slate_date_ct: str
    generated_at_utc: str
    run_status: str
    card_status: str
    results: tuple[AutoCardResult, ...]
    coverage_slots: tuple[CoverageSlot, ...]
    source_failures: tuple[dict[str, Any], ...]
    market_surface_version: str


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AutoRunnerError("NOW_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def _http_json(url: str, *, opener: Callable = urlopen, token: str | None = None) -> Any:
    if not isinstance(url, str) or not url.strip():
        raise AutoRunnerError("PROVIDER_URL_MISSING")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url.strip(), headers=headers)
    try:
        with opener(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise AutoRunnerError(f"PROVIDER_FETCH_FAILED: {url}") from exc


def _snapshot_list(name: str, value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise AutoRunnerError(f"{name}_SNAPSHOT_NOT_LIST")
    out: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AutoRunnerError(f"{name}_SNAPSHOT_ROW_MALFORMED")
        out.append(item)
    return out


def _canonical_quotes(raw_quotes: list[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], dict[int, str]]:
    quotes: list[Mapping[str, Any]] = []
    failures: dict[int, str] = {}
    seen: set[tuple[str, str, str, str, str, str, str, bool, int]] = set()
    for i, raw in enumerate(raw_quotes):
        try:
            q = validate_canonical_quote(raw)
            key = (
                q["game_id"], q["period"], q["market"], q["entity_id"], repr(q["line"]),
                q["side"], q["book_key"], q["is_alternate"], q["american_odds"],
            )
            if key in seen:
                raise QuoteBridgeError("duplicate sportsbook offer")
            seen.add(key)
            quotes.append({"source_index": i, **q})
        except Exception as exc:
            failures[i] = f"{type(exc).__name__}: {exc}"
    return quotes, failures


def _projected_index(rows: list[Mapping[str, Any]]) -> dict[tuple[int, int, str], Mapping[str, Any]]:
    out: dict[tuple[int, int, str], Mapping[str, Any]] = {}
    for row in rows:
        try:
            game_pk = int(row["game_pk"]); team_id = int(row["team_id"]); side = str(row["side"])
        except Exception as exc:
            raise AutoRunnerError("PROJECTED_LINEUP_IDENTITY_MALFORMED") from exc
        if game_pk <= 0 or team_id <= 0 or side not in {"away", "home"}:
            raise AutoRunnerError("PROJECTED_LINEUP_IDENTITY_MALFORMED")
        key = (game_pk, team_id, side)
        if key in out:
            raise AutoRunnerError("PROJECTED_LINEUP_DUPLICATE")
        out[key] = row
    return out


def _projected_lineup(envelope: Mapping[str, Any] | None, *, team_id: int, side: str, now: datetime) -> TeamLineup:
    if envelope is None:
        return TeamLineup(team_id, side, (), (), False)
    try:
        retrieved = parse_timestamp(envelope.get("retrieved_at"))
    except Exception as exc:
        raise AutoRunnerError("PROJECTED_LINEUP_TIMESTAMP_INVALID") from exc
    if retrieved > now:
        raise AutoRunnerError("PROJECTED_LINEUP_FUTURE_RETRIEVAL")
    ttl = envelope.get("ttl_seconds", 900)
    if isinstance(ttl, bool):
        raise AutoRunnerError("PROJECTED_LINEUP_TTL_INVALID")
    try:
        ttl = float(ttl)
    except (TypeError, ValueError) as exc:
        raise AutoRunnerError("PROJECTED_LINEUP_TTL_INVALID") from exc
    if not isfinite(ttl) or ttl <= 0 or (now - retrieved).total_seconds() > ttl:
        raise AutoRunnerError("PROJECTED_LINEUP_STALE")
    rows = envelope.get("rows")
    if not isinstance(rows, list):
        raise AutoRunnerError("PROJECTED_LINEUP_ROWS_MALFORMED")
    validated = lineup_from_rows(team_id, side, rows)
    if set(validated.batting_slots) != set(range(1, 10)) or len(validated.player_ids) != 9:
        raise AutoRunnerError("PROJECTED_LINEUP_INCOMPLETE")
    return TeamLineup(validated.team_id, validated.side, validated.player_ids, validated.batting_slots, False)


def _live_game(snapshot, *, boxscore: Mapping[str, Any], projected: dict[tuple[int, int, str], Mapping[str, Any]], now: datetime) -> LiveGame:
    def side_lineup(side: str, team_id: int) -> TeamLineup:
        confirmed_rows = parse_confirmed_lineup(dict(boxscore), side)
        confirmed = lineup_from_rows(team_id, side, confirmed_rows)
        if confirmed.confirmed:
            return confirmed
        return _projected_lineup(projected.get((snapshot.game_pk, team_id, side)), team_id=team_id, side=side, now=now)
    return LiveGame(
        game_pk=snapshot.game_pk, away_team_id=snapshot.away_id, home_team_id=snapshot.home_id,
        away_probable_pitcher_id=snapshot.away_probable_pitcher_id, home_probable_pitcher_id=snapshot.home_probable_pitcher_id,
        away_lineup=side_lineup("away", snapshot.away_id), home_lineup=side_lineup("home", snapshot.home_id),
        game_number=snapshot.game_number, double_header=snapshot.double_header, venue_id=snapshot.venue_id,
        official_date=snapshot.official_date, status=snapshot.status,
    )


def _feature_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    try:
        game_id = str(int(row["game_pk"]))
        market = str(row["market"])
        entity = row.get("entity_id", row.get("player_id"))
        if entity is None:
            raise ValueError("missing entity")
        entity_id = str(entity)
    except Exception as exc:
        raise AutoRunnerError("FEATURE_ENVELOPE_IDENTITY_MALFORMED") from exc
    if int(game_id) <= 0 or not entity_id or not market:
        raise AutoRunnerError("FEATURE_ENVELOPE_IDENTITY_MALFORMED")
    return game_id, entity_id, market


def _feature_envelopes(rows: list[Mapping[str, Any]]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    out: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = _feature_identity(row)
        if key in out:
            raise AutoRunnerError("FEATURE_ENVELOPE_DUPLICATE")
        out[key] = row
    return out


def _resolve_feature(envelope: Mapping[str, Any], *, now: datetime, game_start: datetime) -> dict[str, Any]:
    sources = envelope.get("sources")
    if not isinstance(sources, list):
        raise FeatureBridgeError("MALFORMED", {"field": "sources"})
    for raw in sources:
        fact = parse_source_fact(raw)
        if fact.event_time > fact.retrieved_at:
            raise FeatureBridgeError("IMPOSSIBLE_SOURCE_CHRONOLOGY", {"source_id": fact.source_id, "fact_key": fact.fact_key})
        if fact.retrieved_at > game_start:
            raise FeatureBridgeError("POST_CUTOFF_RETRIEVAL", {"source_id": fact.source_id, "fact_key": fact.fact_key})
    return resolve_feature_row(
        market=str(envelope.get("market")), game_pk=int(envelope.get("game_pk")),
        player_id=int(envelope.get("player_id")), team_id=int(envelope.get("team_id")),
        feature_fact_keys=envelope.get("feature_fact_keys") or {}, sources=sources,
        ttl_by_feature=envelope.get("ttl_by_feature") or {}, now=now, wager_cutoff=game_start,
    )


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_keys(item)


def _resolve_generic_feature(row: Mapping[str, Any], *, now: datetime, game_start: datetime) -> dict[str, Any]:
    if str(row.get("market")) not in GENERIC_FEATURE_MARKETS:
        raise AutoRunnerError("GENERIC_FEATURE_MARKET_UNSUPPORTED")
    if BANNED_GENERIC_KEYS.intersection(_walk_keys(row)):
        raise AutoRunnerError("GENERIC_FEATURE_MARKET_DATA_PROHIBITED")
    version = str(row.get("generic_feature_version", ""))
    if version != "mlb_generic_feature_v1":
        raise AutoRunnerError("GENERIC_FEATURE_VERSION_INVALID")
    try:
        retrieved = parse_timestamp(row.get("retrieved_at"))
        asof = parse_timestamp(row.get("asof"))
    except Exception as exc:
        raise AutoRunnerError("GENERIC_FEATURE_TIMESTAMP_INVALID") from exc
    if retrieved > now or asof > now:
        raise AutoRunnerError("GENERIC_FEATURE_FUTURE_TIMESTAMP")
    if retrieved > game_start or asof >= game_start:
        raise AutoRunnerError("GENERIC_FEATURE_POST_CUTOFF")
    out = dict(row)
    out["game_pk"] = int(row["game_pk"])
    out["entity_id"] = str(row.get("entity_id", row.get("player_id")))
    return out


def _blocked(index: int, raw: Mapping[str, Any] | None, reason: str) -> AutoCardResult:
    raw = raw or {}
    return AutoCardResult(index, str(raw.get("game_id", "UNKNOWN")), str(raw.get("market", "UNKNOWN")), str(raw.get("entity_id", "UNKNOWN")), raw.get("line"), str(raw.get("side", "UNKNOWN")), raw.get("american_odds"), None, "BLOCKED", reason)


def _convert(index: int, result: UnifiedCardResult) -> AutoCardResult:
    return AutoCardResult(
        index, result.game_id, result.market, result.entity_id, result.line, result.side,
        result.american_odds, result.model_p, result.bet_status, result.reason,
        result.shadow_status, result.implied_probability, result.edge, result.ev_per_dollar,
        result.model_input_hash, result.distribution_sha256,
        result.readout_sha256, result.readout_version,
        result.engine_version, result.seed_policy, result.mc_paths,
        result.book_key, result.sportsbook, result.quote_retrieved_at, result.offer_id,
    )


def run_auto_mlb(*, quote_url: str, feature_url: str, projected_lineups_url: str | None = None, provider_token: str | None = None, now: datetime | None = None, opener: Callable = urlopen, registry_path: str = "config/deployments.json", require_confirmed_lineup: bool = True, edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG, kelly_multiplier: float = 0.25, market_surface_path: str = DEFAULT_MARKET_SURFACE_PATH) -> AutoRunReport:
    current = _aware_utc(now or datetime.now(timezone.utc))
    slate_date_ct = current.astimezone(CHICAGO_TZ).date().isoformat()
    surface_version, market_specs = load_market_surface(market_surface_path)
    raw_quote_rows = _snapshot_list("QUOTE", _http_json(quote_url, opener=opener, token=provider_token))
    feature_rows_raw = _snapshot_list("FEATURE", _http_json(feature_url, opener=opener, token=provider_token))
    projected_raw: list[Mapping[str, Any]] = []
    if projected_lineups_url:
        projected_raw = _snapshot_list("PROJECTED_LINEUP", _http_json(projected_lineups_url, opener=opener, token=provider_token))
    canonical_quotes, quote_failures = _canonical_quotes(raw_quote_rows)
    projected = _projected_index(projected_raw)
    envelopes = _feature_envelopes(feature_rows_raw)
    schedule = fetch_schedule(slate_date_ct, opener=opener, now=current)
    snapshots = {str(g.game_pk): g for g in schedule}
    games: list[LiveGame] = []
    game_failures: dict[str, str] = {}
    for snap in schedule:
        game_id = str(snap.game_pk)
        try:
            start = parse_game_start(snap.game_date)
            if snap.status != "Preview":
                raise AutoRunnerError("GAME_NOT_PREGAME")
            if current >= start:
                raise AutoRunnerError("GAME_CLOCK_NOT_PREGAME")
            boxscore = fetch_boxscore(snap.game_pk, opener=opener)
            games.append(_live_game(snap, boxscore=boxscore, projected=projected, now=current))
        except Exception as exc:
            game_failures[game_id] = f"{type(exc).__name__}: {exc}"
    resolved_features: list[dict[str, Any]] = []
    feature_failures: dict[tuple[str, str, str], str] = {}
    for q in canonical_quotes:
        game_id, entity_id, market = q["game_id"], q["entity_id"], q["market"]
        identity = (game_id, entity_id, market)
        if game_id in game_failures:
            continue
        snap = snapshots.get(game_id)
        if snap is None:
            continue
        try:
            env = envelopes.get(identity)
            if env is None:
                raise FeatureBridgeError("MISSING", {"detail": "feature envelope missing"})
            game_start = parse_game_start(snap.game_date)
            if market == "PITCHER_BB" and env.get("generic_feature_version") == "mlb_generic_feature_v1":
                resolved = _resolve_generic_feature(env, now=current, game_start=game_start)
            elif market in VALIDATED_BRIDGE_MARKETS:
                resolved = _resolve_feature(env, now=current, game_start=game_start)
            elif market in GENERIC_MARKETS:
                resolved = _resolve_generic_feature(env, now=current, game_start=game_start)
            else:
                raise AutoRunnerError("FEATURE_MARKET_UNSUPPORTED")
            resolved_features.append(resolved)
        except Exception as exc:
            feature_failures[identity] = f"{type(exc).__name__}: {exc}"
    q_for_runner = [{k: v for k, v in q.items() if k != "source_index"} for q in canonical_quotes]
    unified = run_unified_card(games=games, feature_rows=resolved_features, quotes=q_for_runner, ingestion_now=current, finalization_now=current, registry_path=registry_path, require_confirmed_lineup=require_confirmed_lineup, edge_floor_config_path=edge_floor_config_path, kelly_multiplier=kelly_multiplier)
    output: dict[int, AutoCardResult] = {}
    for i, reason in quote_failures.items():
        output[i] = _blocked(i, raw_quote_rows[i], reason)
    for q, result in zip(canonical_quotes, unified):
        i = int(q["source_index"]); identity = (q["game_id"], q["entity_id"], q["market"])
        if q["game_id"] in game_failures:
            output[i] = _blocked(i, q, game_failures[q["game_id"]])
        elif snapshots.get(q["game_id"]) is None:
            output[i] = _blocked(i, q, "MLB_GAME_ID_NOT_FOUND")
        elif identity in feature_failures:
            output[i] = _blocked(i, q, feature_failures[identity])
        else:
            output[i] = _convert(i, result)
    results = tuple(output[i] for i in range(len(raw_quote_rows)))
    source_failures = tuple({"source_index": result.source_index, "reason": result.reason} for result in results if result.bet_status == "BLOCKED" and result.model_p is None)
    grid_games = tuple((str(s.game_pk), parse_game_start(s.game_date)) for s in schedule)
    coverage_slots = build_market_grid(
        games=grid_games,
        specs=market_specs,
        quotes=canonical_quotes,
        engine_capable_markets=ENGINE_CAPABLE_MARKETS,
        feature_failures=feature_failures,
        result_rows=results,
        now=current,
    )
    all_results_blocked = bool(results) and all(r.bet_status == "BLOCKED" for r in results)
    status = "BLOCKED" if all_results_blocked else compose_run_status(coverage_slots)
    card_status = compose_card_status(slot.decision_status for slot in coverage_slots)
    return AutoRunReport(
        slate_date_ct=slate_date_ct,
        generated_at_utc=current.isoformat(),
        run_status=status,
        card_status=card_status,
        results=results,
        coverage_slots=coverage_slots,
        source_failures=source_failures,
        market_surface_version=surface_version,
    )


def report_to_dict(report: AutoRunReport) -> dict[str, Any]:
    return {
        "slate_date_ct": report.slate_date_ct,
        "generated_at_utc": report.generated_at_utc,
        "run_status": report.run_status,
        "card_status": report.card_status,
        "market_surface_version": report.market_surface_version,
        "coverage_slots": [asdict(x) for x in report.coverage_slots],
        "results": [normalize_legacy_block_reason(asdict(x)) for x in report.results],
        "source_failures": list(report.source_failures),
    }

"""Automatic MLB runner for the coherent joint market surface.

This entrypoint reuses the existing live schedule/lineup/quote guards but builds
price-independent joint features from MLB StatsAPI directly. No external feature
snapshot is required for the joint prop path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Mapping, Any
from urllib.request import urlopen

from .auto_runner import (
    AutoCardResult,
    AutoRunReport,
    CHICAGO_TZ,
    ENGINE_CAPABLE_MARKETS,
    _aware_utc,
    _blocked,
    _canonical_quotes,
    _convert,
    _http_json,
    _live_game,
    _projected_index,
    _snapshot_list,
)
from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from .market_surface import (
    DEFAULT_MARKET_SURFACE_PATH,
    build_market_grid,
    compose_card_status,
    compose_run_status,
    load_market_surface,
)
from .mlb_generic_features import MLBGenericHistorySource
from .mlb_joint_mode_bridge import build_feature_rows_for_quotes
from .mlb_source import fetch_boxscore, fetch_schedule, parse_game_start
from .unified_card import run_unified_card


def run_auto_joint_mlb(
    *,
    quote_url: str,
    projected_lineups_url: str | None = None,
    provider_token: str | None = None,
    now: datetime | None = None,
    opener: Callable = urlopen,
    registry_path: str = "config/deployments.json",
    require_confirmed_lineup: bool = True,
    edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG,
    kelly_multiplier: float = 0.25,
    market_surface_path: str = DEFAULT_MARKET_SURFACE_PATH,
) -> AutoRunReport:
    current = _aware_utc(now or datetime.now(timezone.utc))
    slate_date = current.astimezone(CHICAGO_TZ).date()
    slate_date_ct = slate_date.isoformat()
    surface_version, market_specs = load_market_surface(market_surface_path)
    raw_quote_rows = _snapshot_list("QUOTE", _http_json(quote_url, opener=opener, token=provider_token))
    canonical_quotes, quote_failures = _canonical_quotes(raw_quote_rows)

    projected_raw: list[Mapping[str, Any]] = []
    if projected_lineups_url:
        projected_raw = _snapshot_list("PROJECTED_LINEUP", _http_json(projected_lineups_url, opener=opener, token=provider_token))
    projected = _projected_index(projected_raw)

    schedule = fetch_schedule(slate_date_ct, opener=opener, now=current)
    snapshots = {str(g.game_pk): g for g in schedule}
    games = []
    game_failures: dict[str, str] = {}
    for snap in schedule:
        game_id = str(snap.game_pk)
        try:
            start = parse_game_start(snap.game_date)
            if snap.status != "Preview":
                raise RuntimeError("GAME_NOT_PREGAME")
            if current >= start:
                raise RuntimeError("GAME_CLOCK_NOT_PREGAME")
            boxscore = fetch_boxscore(snap.game_pk, opener=opener)
            games.append(_live_game(snap, boxscore=boxscore, projected=projected, now=current))
        except Exception as exc:
            game_failures[game_id] = f"{type(exc).__name__}: {exc}"

    source = MLBGenericHistorySource(opener=opener, retrieved_at=current)
    usable_quotes = [
        q for q in canonical_quotes
        if q["game_id"] not in game_failures and q["game_id"] in snapshots
    ]
    feature_rows: list[dict[str, Any]] = []
    feature_failures: dict[tuple[str, str, str], str] = {}
    resolved_feature_identities: set[tuple[str, str, str]] = set()
    for q in usable_quotes:
        identity = (str(q["game_id"]), str(q["entity_id"]), str(q["market"]))
        # Paired prices are two sportsbook propositions for one predictive
        # state. Normalize them to one canonical feature row before entering
        # the shared card core, matching manual/hybrid semantics exactly.
        if identity in resolved_feature_identities:
            continue
        game = next((g for g in games if str(g.game_pk) == identity[0]), None)
        if game is None:
            continue
        try:
            rows = build_feature_rows_for_quotes(
                games=[game], quotes=[q], source=source, target_date=slate_date
            )
            feature_rows.extend(rows)
            resolved_feature_identities.add(identity)
        except Exception as exc:
            feature_failures[identity] = f"{type(exc).__name__}: {exc}"

    runner_quotes = [{k: v for k, v in q.items() if k != "source_index"} for q in canonical_quotes]
    unified = run_unified_card(
        games=games,
        feature_rows=feature_rows,
        quotes=runner_quotes,
        ingestion_now=current,
        finalization_now=current,
        registry_path=registry_path,
        require_confirmed_lineup=require_confirmed_lineup,
        edge_floor_config_path=edge_floor_config_path,
        kelly_multiplier=kelly_multiplier,
    )

    output: dict[int, AutoCardResult] = {}
    for i, reason in quote_failures.items():
        output[i] = _blocked(i, raw_quote_rows[i], reason)
    for q, result in zip(canonical_quotes, unified):
        i = int(q["source_index"])
        identity = (str(q["game_id"]), str(q["entity_id"]), str(q["market"]))
        if q["game_id"] in game_failures:
            output[i] = _blocked(i, q, game_failures[q["game_id"]])
        elif q["game_id"] not in snapshots:
            output[i] = _blocked(i, q, "MLB_GAME_ID_NOT_FOUND")
        elif identity in feature_failures:
            output[i] = _blocked(i, q, feature_failures[identity])
        else:
            output[i] = _convert(i, result)

    results = tuple(output[i] for i in range(len(raw_quote_rows)))
    source_failures = tuple(
        {"source_index": result.source_index, "reason": result.reason}
        for result in results
        if result.bet_status == "BLOCKED" and result.model_p is None
    )
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

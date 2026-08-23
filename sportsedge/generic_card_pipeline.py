"""Fail-closed card pipeline for the expanded MLB market surface."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from .deployments import load_registry
from .devig import multiplicative_devig, validate_pair
from .engine_registry import engine_registry
from .generic_market_engine import BINARY_MARKETS, COUNT_MARKETS, GAME_MARKETS, PA_BOUNDED_COUNT_MARKETS
from .live_slate import LiveGame
from .orchestrator import run_candidate
from .quote_bridge import validate_canonical_quote
from .truth_gate import american_to_decimal

GENERIC_MARKETS = frozenset(GAME_MARKETS | COUNT_MARKETS | BINARY_MARKETS)
BATTER_GENERIC_MARKETS = frozenset({
    "HOME_RUNS", "RBI", "RUNS", "HITS_RUNS_RBIS", "SINGLES", "DOUBLES",
    "TRIPLES", "BATTER_BB", "BATTER_K", "STOLEN_BASES", "FIRST_HOME_RUN",
})
PITCHER_GENERIC_MARKETS = frozenset({
    "PITCHER_K", "PITCHER_HITS_ALLOWED", "PITCHER_ER", "PITCHER_OUTS",
    "PITCHER_RECORD_WIN",
})

@dataclass(frozen=True)
class GenericCardResult:
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

def _game_index(games: list[LiveGame]) -> dict[str, LiveGame]:
    out: dict[str, LiveGame] = {}
    for game in games:
        key = str(game.game_pk)
        if key in out:
            raise ValueError("duplicate live game_pk")
        out[key] = game
    return out

def _feature_index(rows: list[Mapping[str, Any]]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    out: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        market = str(row.get("market", ""))
        if market not in GENERIC_MARKETS:
            continue
        game_id = str(row.get("game_pk", row.get("game_id", "")))
        entity_id = str(row.get("entity_id", row.get("player_id", "")))
        if not game_id or not entity_id:
            continue
        key = (game_id, entity_id, market)
        if key in out:
            if dict(out[key]) != dict(row):
                raise ValueError(f"conflicting generic feature identity {key}")
            continue
        out[key] = row
    return out

def _lineup_team(game: LiveGame, entity_id: str) -> int:
    try:
        pid = int(entity_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("player entity_id must be numeric MLB id") from exc
    away = pid in game.away_lineup.player_ids
    home = pid in game.home_lineup.player_ids
    if away and home:
        raise ValueError("player appears in both lineups")
    if away:
        return int(game.away_team_id)
    if home:
        return int(game.home_team_id)
    raise ValueError("player not present in MLB lineup snapshot")

def _bind_entity(game: LiveGame, market: str, entity_id: str, feature: Mapping[str, Any]) -> None:
    if market in BATTER_GENERIC_MARKETS:
        live_team = _lineup_team(game, entity_id)
        feature_team = feature.get("team_id")
        if feature_team is not None and int(feature_team) != live_team:
            raise ValueError("PLAYER_TEAM_MISMATCH")
        return
    if market in PITCHER_GENERIC_MARKETS:
        try:
            pid = int(entity_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("pitcher entity_id must be numeric MLB id") from exc
        if pid not in {game.away_probable_pitcher_id, game.home_probable_pitcher_id}:
            raise ValueError("NON_PROBABLE_PITCHER")

def _model_input(*, game: LiveGame, quote: Mapping[str, Any], feature: Mapping[str, Any]) -> dict[str, Any]:
    market = str(quote["market"])
    entity_id = str(quote["entity_id"])
    _bind_entity(game, market, entity_id, feature)
    if str(feature.get("game_pk", feature.get("game_id"))) != str(game.game_pk):
        raise ValueError("feature game identity mismatch")
    if str(feature.get("entity_id", feature.get("player_id"))) != entity_id:
        raise ValueError("feature entity identity mismatch")
    if str(feature.get("market")) != market:
        raise ValueError("feature market mismatch")

    if market in COUNT_MARKETS:
        model_features = {"expected_count": feature.get("expected_count")}
        if market in PA_BOUNDED_COUNT_MARKETS:
            model_features["projected_pa"] = feature.get("projected_pa")
    elif market in BINARY_MARKETS:
        model_features = {"event_probability": feature.get("event_probability")}
    else:
        if market.startswith("F5_"):
            model_features = {
                "f5_away_mean_runs": feature.get("f5_away_mean_runs"),
                "f5_home_mean_runs": feature.get("f5_home_mean_runs"),
            }
        else:
            model_features = {
                "away_mean_runs": feature.get("away_mean_runs"),
                "home_mean_runs": feature.get("home_mean_runs"),
            }
        if market not in {"TOTALS", "F5_TOTALS"}:
            model_features["total_line"] = feature.get("total_line", 0.0)
        if market in {"NRFI", "YRFI"}:
            model_features["first_inning_share"] = feature.get("first_inning_share", 1.0 / 9.0)

    out = {
        "game_id": str(game.game_pk), "market": market, "entity_id": entity_id,
        "line": quote.get("line"), "side": quote.get("side"), **model_features,
    }
    if feature.get("source_subset_hash") is not None:
        out["feature_source_hash"] = feature["source_subset_hash"]
    return out

def _validated_quotes(quotes: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    out = []
    for raw in quotes:
        try:
            out.append(validate_canonical_quote(raw))
        except Exception:
            continue
    return out

def _paired_quote(candidate: Mapping[str, Any], quotes: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    matches = []
    for quote in quotes:
        if quote is candidate or dict(quote) == dict(candidate):
            continue
        try:
            validate_pair(candidate, quote)
            matches.append(quote)
        except Exception:
            continue
    if len(matches) != 1:
        raise ValueError(f"PAIRED_PRICE_REQUIRED_FOR_DEVIG: found={len(matches)}")
    return matches[0]

def _shadow(model_p: float | None, quote: Mapping[str, Any], opposite: Mapping[str, Any]) -> tuple[str | None, float | None, float | None, float | None]:
    if model_p is None:
        return None, None, None, None
    try:
        fair = multiplicative_devig(quote, opposite).candidate_fair_probability
        dec = american_to_decimal(quote["american_odds"])
        p = float(model_p)
        if not isfinite(p) or not 0 <= p <= 1:
            raise ValueError("invalid Model_P")
        edge = p - fair
        ev = p * (dec - 1.0) - (1.0 - p)
        return ("SHADOW_BET" if edge > 0 and ev > 0 else "SHADOW_PASS", fair, edge, ev)
    except Exception:
        return None, None, None, None

def run_generic_card(*, games: list[LiveGame], feature_rows: list[Mapping[str, Any]], quotes: list[Mapping[str, Any]], ingestion_now: datetime, finalization_now: datetime, registry_path: str = "config/deployments.json", edge_floor_config_path: str = "config/truth_gate_floors.json", kelly_multiplier: float = 0.25) -> list[GenericCardResult]:
    games_by_id = _game_index(games)
    features = _feature_index(feature_rows)
    deployments = load_registry(registry_path)["markets"]
    engines = engine_registry()
    valid_quotes = _validated_quotes(quotes)
    results: list[GenericCardResult] = []
    for raw in quotes:
        try:
            quote = validate_canonical_quote(raw)
            market = str(quote["market"])
            if market not in GENERIC_MARKETS:
                raise ValueError(f"unsupported generic market: {market}")
            opposite = _paired_quote(quote, valid_quotes)
            game = games_by_id.get(str(quote["game_id"]))
            if game is None:
                raise ValueError("MLB_GAME_ID_NOT_FOUND")
            key = (str(quote["game_id"]), str(quote["entity_id"]), market)
            feature = features.get(key)
            if feature is None:
                raise ValueError("generic feature row missing")
            model_input = _model_input(game=game, quote=quote, feature=feature)
            engine = engines.get(market)
            deployment = deployments.get(market)
            if engine is None or deployment is None:
                raise ValueError("market missing engine/deployment registration")
            shadow_output = dict(engine(model_input))
            if "model_p" not in shadow_output:
                raise ValueError("engine output missing model_p")
            model_p = float(shadow_output["model_p"])
            shadow_status, implied, edge, ev = _shadow(model_p, quote, opposite)
            run = run_candidate(model_input=model_input, quote=quote, paired_quote=opposite, deployment=deployment, engine_fn=engine, ingestion_now=ingestion_now, finalization_now=finalization_now, edge_floor_config_path=edge_floor_config_path, kelly_multiplier=kelly_multiplier)
            results.append(GenericCardResult(str(quote["game_id"]), market, str(quote["entity_id"]), quote["line"], str(quote["side"]), quote["american_odds"], model_p, run.bet_status, run.reason, shadow_status, implied, edge, ev))
        except Exception as exc:
            try:
                quote = validate_canonical_quote(raw)
                identity = (str(quote["game_id"]), str(quote["market"]), str(quote["entity_id"]), quote["line"], str(quote["side"]), quote["american_odds"])
            except Exception:
                identity = ("UNKNOWN", "UNKNOWN", "UNKNOWN", None, "UNKNOWN", None)
            results.append(GenericCardResult(*identity, None, "BLOCKED", f"{type(exc).__name__}: {exc}"))
    return results

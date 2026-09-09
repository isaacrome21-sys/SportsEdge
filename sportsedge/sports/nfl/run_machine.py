"""Canonical SportsEdge NFL MANUAL / HYBRID / AUTOMATIC run machine.

This module is the production convergence boundary above NFL M2.  Input ownership
may differ by mode, but every mode converges on the same frozen model artifact,
strictly-as-of live feature payload, observed sportsbook snapshot, one M2 score
distribution per game, and downstream market read-outs.

Safety invariants owned here:
* the frozen M2 artifact is bound to the runtime code Git SHA;
* training-source and live-feature source hashes are retained separately;
* execution and feature snapshots are strictly pregame and never from the future;
* live feature snapshots must be recent enough for the existing 120-minute live
  feature horizon;
* sportsbook snapshots must have an explicit observation timestamp, must be
  observed before execution and kickoff, and expire after 180 seconds by default;
* sportsbook lines/prices are applied only after the M2 score distribution exists;
* MONEYLINE / SPREAD / TOTAL are the only modeled NFL markets.  Nothing here
  promotes player props or turns context/trends into Model_P;
* all priced NFL rows remain betting-BLOCKED until independent promotion evidence
  and a frozen Truth Gate floor permit deployment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Callable, Mapping, Sequence

from .m2 import (
    NFL_M2_FEATURE_CONTRACT,
    PRODUCTION_NFL_M2_MODEL_ID,
    derive_nfl_m2_score_distribution,
    price_nfl_m2_game_markets,
)
from .model_artifact import load_nfl_m2_model_artifact

VALID_MODES = frozenset({"AUTO_SELECT", "MANUAL", "HYBRID", "AUTOMATIC"})
SUPPORTED_GAME_MARKETS = frozenset({"MONEYLINE", "SPREAD", "TOTAL"})
NFL_MACHINE_VERSION = "NFL_RUN_MACHINE_V1"
DEFAULT_QUOTE_TTL_SECONDS = 180
# The canonical live-feature builder targets games in a 120-minute horizon.  A
# snapshot older than that horizon is not treated as current production input.
DEFAULT_FEATURE_TTL_SECONDS = 120 * 60
DEFAULT_BOOK_KEY = "draftkings"

FeatureBuilder = Callable[[], Mapping[str, Any]]
OddsFetcher = Callable[[], Mapping[str, Any]]


class NFLRunMachineError(ValueError):
    pass


@dataclass(frozen=True)
class NFLMachineResult:
    game_id: str
    market: str
    side: str
    line: float | None
    american_odds: float | None
    model_p: float | None
    push_p: float | None
    fair_market_p: float | None
    raw_implied_p: float | None
    hold: float | None
    edge: float | None
    ev_per_dollar: float | None
    bet_status: str
    engine_status: str
    reason: str
    model_artifact_sha256: str | None
    model_code_git_sha: str | None
    training_source_manifest_sha256: str | None
    live_feature_source_manifest_sha256: str | None
    live_feature_asof_ts: str | None
    distribution_sha256: str | None
    book_key: str | None
    sportsbook: str | None
    quote_observed_at: str | None
    provider_event_id: str | None


@dataclass(frozen=True)
class NFLMachineReport:
    mode: str
    generated_at_utc: str
    run_status: str
    machine_version: str
    results: tuple[NFLMachineResult, ...]
    summary: dict[str, Any]
    model_artifact_sha256: str
    model_code_git_sha: str
    training_source_manifest_sha256: str
    live_feature_source_manifest_sha256: str
    live_feature_asof_ts: str
    quote_observed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _aware(value: datetime | str, error: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        raw = str(value or "").strip().replace("Z", "+00:00")
        if not raw:
            raise NFLRunMachineError(error)
        try:
            out = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise NFLRunMachineError(error) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLRunMachineError(error)
    return out.astimezone(timezone.utc)


def _canonical_hash(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NFLRunMachineError("NFL_CANONICAL_HASH_INPUT_INVALID") from exc
    return sha256(raw).hexdigest()


def _sha256_text(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise NFLRunMachineError(error)
    return raw


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 40 or any(ch not in "0123456789abcdef" for ch in raw):
        raise NFLRunMachineError(error)
    return raw


def _positive_int(value: Any, error: str) -> int:
    if isinstance(value, bool):
        raise NFLRunMachineError(error)
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise NFLRunMachineError(error) from exc
    if out <= 0:
        raise NFLRunMachineError(error)
    return out


def _american_decimal(odds: Any) -> float:
    try:
        value = float(odds)
    except (TypeError, ValueError) as exc:
        raise NFLRunMachineError("NFL_AMERICAN_ODDS_INVALID") from exc
    if not isfinite(value) or (-100.0 < value < 100.0):
        raise NFLRunMachineError("NFL_AMERICAN_ODDS_INVALID")
    return 1.0 + (100.0 / abs(value) if value < 0 else value / 100.0)


def _raw_implied(odds: Any) -> float:
    return 1.0 / _american_decimal(odds)


def _resolve_mode(
    mode: str,
    *,
    live_features: Mapping[str, Any] | None,
    odds_snapshot: Mapping[str, Any] | None,
) -> str:
    selected = str(mode or "AUTO_SELECT").strip().upper()
    if selected not in VALID_MODES:
        raise NFLRunMachineError(f"NFL_RUN_MODE_UNSUPPORTED:{selected}")
    if selected != "AUTO_SELECT":
        return selected
    supplied = int(live_features is not None) + int(odds_snapshot is not None)
    if supplied == 2:
        return "MANUAL"
    if supplied == 1:
        return "HYBRID"
    return "AUTOMATIC"


def _load_bound_model(
    artifact_payload: Mapping[str, Any],
    *,
    runtime_code_git_sha: str,
) -> tuple[Any, str, str, str]:
    if not isinstance(artifact_payload, Mapping):
        raise NFLRunMachineError("NFL_MODEL_ARTIFACT_REQUIRED")
    runtime_sha = _git_sha(runtime_code_git_sha, "NFL_RUNTIME_CODE_GIT_SHA_INVALID")
    artifact = dict(artifact_payload)
    try:
        model = load_nfl_m2_model_artifact(artifact, expected_code_git_sha=runtime_sha)
    except ValueError as exc:
        raise NFLRunMachineError(str(exc)) from exc
    artifact_sha = _canonical_hash(artifact)
    training_sha = _sha256_text(
        artifact.get("source_manifest_sha256"),
        "NFL_MODEL_ARTIFACT_SOURCE_SHA256_INVALID",
    )
    if artifact.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise NFLRunMachineError("NFL_MODEL_ARTIFACT_MODEL_ID_MISMATCH")
    if artifact.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise NFLRunMachineError("NFL_MODEL_ARTIFACT_FEATURE_CONTRACT_MISMATCH")
    return model, artifact_sha, runtime_sha, training_sha


def _validate_live_features(
    payload: Mapping[str, Any],
    *,
    current: datetime,
    feature_ttl_seconds: int,
) -> tuple[str, datetime, list[dict[str, Any]]]:
    if not isinstance(payload, Mapping) or str(payload.get("sport") or "").lower() != "nfl":
        raise NFLRunMachineError("NFL_LIVE_FEATURE_PAYLOAD_INVALID")
    source_hash = _sha256_text(
        payload.get("source_manifest_sha256"),
        "NFL_LIVE_FEATURE_SOURCE_HASH_INVALID",
    )
    asof = _aware(payload.get("asof_ts"), "NFL_LIVE_FEATURE_ASOF_INVALID")
    if asof > current:
        raise NFLRunMachineError("NFL_LIVE_FEATURE_FROM_FUTURE")
    if (current - asof).total_seconds() > feature_ttl_seconds:
        raise NFLRunMachineError("NFL_LIVE_FEATURE_SNAPSHOT_STALE")
    games = payload.get("games")
    if not isinstance(games, list) or not games:
        raise NFLRunMachineError("NFL_LIVE_FEATURE_GAMES_EMPTY")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in games:
        if not isinstance(raw, Mapping):
            raise NFLRunMachineError("NFL_LIVE_FEATURE_GAME_INVALID")
        row = dict(raw)
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            raise NFLRunMachineError("NFL_LIVE_FEATURE_GAME_ID_MISSING")
        if game_id in seen:
            raise NFLRunMachineError(f"NFL_LIVE_FEATURE_GAME_DUPLICATE:{game_id}")
        seen.add(game_id)
        start = _aware(row.get("game_start_ts"), f"NFL_GAME_START_INVALID:{game_id}")
        if current >= start:
            raise NFLRunMachineError(f"NFL_GAME_NOT_PREGAME:{game_id}")
        if asof >= start:
            raise NFLRunMachineError(f"NFL_LIVE_FEATURE_SNAPSHOT_NOT_PREGAME:{game_id}")
        for side in ("home", "away"):
            features = row.get(f"{side}_features")
            if not isinstance(features, Mapping):
                raise NFLRunMachineError(f"NFL_M2_{side.upper()}_FEATURES_REQUIRED:{game_id}")
            feature_asof = _aware(
                features.get("feature_asof_ts"),
                f"NFL_M2_{side.upper()}_FEATURE_ASOF_INVALID:{game_id}",
            )
            if feature_asof > current:
                raise NFLRunMachineError(f"NFL_M2_{side.upper()}_FEATURE_FROM_FUTURE:{game_id}")
            if feature_asof >= start:
                raise NFLRunMachineError(f"NFL_M2_{side.upper()}_FEATURE_NOT_PREGAME:{game_id}")
            if feature_asof > asof:
                raise NFLRunMachineError(f"NFL_M2_{side.upper()}_FEATURE_AFTER_SNAPSHOT:{game_id}")
        for field in ("home_team", "away_team", "provider_home_team", "provider_away_team"):
            if not str(row.get(field) or "").strip():
                raise NFLRunMachineError(f"NFL_GAME_IDENTITY_MISSING:{game_id}:{field}")
        rows.append(row)
    return source_hash, asof, rows


def _validate_odds_snapshot(
    payload: Mapping[str, Any],
    *,
    current: datetime,
) -> tuple[datetime, list[dict[str, Any]], str | None]:
    if not isinstance(payload, Mapping):
        raise NFLRunMachineError("NFL_ODDS_SNAPSHOT_REQUIRED")
    observed = _aware(payload.get("observed_at"), "NFL_ODDS_OBSERVED_AT_REQUIRED")
    if observed > current:
        raise NFLRunMachineError("NFL_ODDS_OBSERVED_FROM_FUTURE")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise NFLRunMachineError("NFL_ODDS_EVENTS_EMPTY")
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            raise NFLRunMachineError("NFL_ODDS_EVENT_INVALID")
        rows.append(dict(event))
    source = str(payload.get("source") or "").strip() or None
    return observed, rows, source


def _event_for_game(game: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    home = str(game.get("provider_home_team") or "").strip()
    away = str(game.get("provider_away_team") or "").strip()
    start = _aware(game.get("game_start_ts"), "NFL_GAME_START_INVALID")
    matches: list[dict[str, Any]] = []
    for raw in events:
        if str(raw.get("home_team") or "").strip() != home:
            continue
        if str(raw.get("away_team") or "").strip() != away:
            continue
        try:
            event_start = _aware(raw.get("commence_time"), "NFL_ODDS_EVENT_START_INVALID")
        except NFLRunMachineError:
            continue
        if event_start == start:
            matches.append(dict(raw))
    if not matches:
        raise NFLRunMachineError(f"NFL_ODDS_EVENT_NOT_FOUND:{game.get('game_id')}")
    if len(matches) != 1:
        raise NFLRunMachineError(f"NFL_ODDS_EVENT_AMBIGUOUS:{game.get('game_id')}")
    event = matches[0]
    if str(event.get("sport_key") or "") not in ("", "americanfootball_nfl"):
        raise NFLRunMachineError("NFL_ODDS_SPORT_KEY_MISMATCH")
    if not str(event.get("id") or "").strip():
        raise NFLRunMachineError("NFL_ODDS_EVENT_ID_MISSING")
    return event


def _book(event: Mapping[str, Any], book_key: str) -> Mapping[str, Any]:
    books = event.get("bookmakers")
    if not isinstance(books, list):
        raise NFLRunMachineError("NFL_ODDS_BOOKMAKERS_MISSING")
    matches = [
        row for row in books
        if isinstance(row, Mapping) and str(row.get("key") or "").strip().lower() == book_key.lower()
    ]
    if len(matches) != 1:
        raise NFLRunMachineError(f"NFL_ODDS_BOOKMAKER_COUNT_INVALID:{book_key}")
    return matches[0]


def _market(book: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    markets = book.get("markets")
    if not isinstance(markets, list):
        raise NFLRunMachineError("NFL_ODDS_MARKETS_MISSING")
    matches = [
        row for row in markets
        if isinstance(row, Mapping) and str(row.get("key") or "").strip().lower() == key.lower()
    ]
    if len(matches) != 1:
        raise NFLRunMachineError(f"NFL_ODDS_MARKET_COUNT_INVALID:{key}")
    return matches[0]


def _outcomes(market: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = market.get("outcomes")
    if not isinstance(rows, list):
        raise NFLRunMachineError("NFL_ODDS_OUTCOMES_MISSING")
    out = [row for row in rows if isinstance(row, Mapping)]
    if len(out) != len(rows):
        raise NFLRunMachineError("NFL_ODDS_OUTCOME_INVALID")
    return out


def _finite_float(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLRunMachineError(error) from exc
    if not isfinite(out):
        raise NFLRunMachineError(error)
    return out


def _event_quotes(
    game: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    book_key: str,
) -> tuple[list[dict[str, Any]], str | None]:
    book = _book(event, book_key)
    sportsbook = str(book.get("title") or book.get("key") or "").strip() or None
    provider_home = str(game.get("provider_home_team") or "").strip()
    provider_away = str(game.get("provider_away_team") or "").strip()
    canonical_home = str(game.get("home_team") or "").strip()
    canonical_away = str(game.get("away_team") or "").strip()

    h2h = {str(x.get("name") or "").strip(): x for x in _outcomes(_market(book, "h2h"))}
    if provider_home not in h2h or provider_away not in h2h:
        raise NFLRunMachineError("NFL_MONEYLINE_PAIR_MISSING")

    spreads = {str(x.get("name") or "").strip(): x for x in _outcomes(_market(book, "spreads"))}
    if provider_home not in spreads or provider_away not in spreads:
        raise NFLRunMachineError("NFL_SPREAD_PAIR_MISSING")
    home_spread = _finite_float(spreads[provider_home].get("point"), "NFL_SPREAD_LINE_INVALID")
    away_spread = _finite_float(spreads[provider_away].get("point"), "NFL_SPREAD_LINE_INVALID")
    if abs(home_spread + away_spread) > 1e-9:
        raise NFLRunMachineError("NFL_SPREAD_COMPLEMENT_MISMATCH")

    totals = {str(x.get("name") or "").strip().lower(): x for x in _outcomes(_market(book, "totals"))}
    if "over" not in totals or "under" not in totals:
        raise NFLRunMachineError("NFL_TOTAL_PAIR_MISSING")
    total_over = _finite_float(totals["over"].get("point"), "NFL_TOTAL_LINE_INVALID")
    total_under = _finite_float(totals["under"].get("point"), "NFL_TOTAL_LINE_INVALID")
    if abs(total_over - total_under) > 1e-9:
        raise NFLRunMachineError("NFL_TOTAL_LINE_MISMATCH")

    return [
        {"market": "MONEYLINE", "side": "HOME", "selection": canonical_home, "line": None,
         "american_odds": _finite_float(h2h[provider_home].get("price"), "NFL_AMERICAN_ODDS_INVALID")},
        {"market": "MONEYLINE", "side": "AWAY", "selection": canonical_away, "line": None,
         "american_odds": _finite_float(h2h[provider_away].get("price"), "NFL_AMERICAN_ODDS_INVALID")},
        {"market": "SPREAD", "side": "HOME", "selection": canonical_home, "line": home_spread,
         "american_odds": _finite_float(spreads[provider_home].get("price"), "NFL_AMERICAN_ODDS_INVALID")},
        {"market": "SPREAD", "side": "AWAY", "selection": canonical_away, "line": away_spread,
         "american_odds": _finite_float(spreads[provider_away].get("price"), "NFL_AMERICAN_ODDS_INVALID")},
        {"market": "TOTAL", "side": "OVER", "selection": "OVER", "line": total_over,
         "american_odds": _finite_float(totals["over"].get("price"), "NFL_AMERICAN_ODDS_INVALID")},
        {"market": "TOTAL", "side": "UNDER", "selection": "UNDER", "line": total_under,
         "american_odds": _finite_float(totals["under"].get("price"), "NFL_AMERICAN_ODDS_INVALID")},
    ], sportsbook


def _distribution_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    return _canonical_hash([dict(row) for row in rows])


def _readout(
    readouts: Mapping[str, Any],
    *,
    market: str,
    side: str,
) -> tuple[float, float]:
    if market == "MONEYLINE":
        return float(readouts["moneyline"][side.lower()]), float(readouts["moneyline"]["tie"])
    if market == "SPREAD":
        return float(readouts["spread"][side.lower()]), float(readouts["spread"]["push"])
    if market == "TOTAL":
        return float(readouts["total"][side.lower()]), float(readouts["total"]["push"])
    raise NFLRunMachineError(f"NFL_NO_ENGINE:{market}")


def _pair_economics(
    pair: Sequence[Mapping[str, Any]],
    model_probabilities: Mapping[str, tuple[float, float]],
    *,
    stale: bool,
) -> list[dict[str, Any]]:
    if len(pair) != 2:
        raise NFLRunMachineError("NFL_PAIRED_PRICE_REQUIRED_FOR_DEVIG")
    raw = [_raw_implied(row["american_odds"]) for row in pair]
    implied_sum = sum(raw)
    if implied_sum <= 0.0:
        raise NFLRunMachineError("NFL_PAIRED_PRICE_REQUIRED_FOR_DEVIG")
    hold = implied_sum - 1.0
    out: list[dict[str, Any]] = []
    for index, row in enumerate(pair):
        key = str(row["side"])
        model_p, push_p = model_probabilities[key]
        fair = raw[index] / implied_sum
        non_push = 1.0 - push_p
        if non_push <= 0.0:
            raise NFLRunMachineError("NFL_SETTLED_SAMPLE_SPACE_EMPTY")
        settled_model_p = model_p / non_push
        loss_p = max(0.0, 1.0 - model_p - push_p)
        ev = model_p * (_american_decimal(row["american_odds"]) - 1.0) - loss_p
        out.append({
            **dict(row),
            "model_p": model_p,
            "push_p": push_p,
            "raw_implied_p": None if stale else raw[index],
            "fair_market_p": None if stale else fair,
            "hold": None if stale else hold,
            "edge": None if stale else settled_model_p - fair,
            "ev_per_dollar": None if stale else ev,
            "reason": "NFL_QUOTE_STALE" if stale else "NFL_PROMOTION_EVIDENCE_REQUIRED",
        })
    return out


def _summary(results: Sequence[NFLMachineResult]) -> dict[str, Any]:
    return {
        "quote_count": len(results),
        "priced": sum(row.engine_status == "PRICED" for row in results),
        "stale": sum(row.reason == "NFL_QUOTE_STALE" for row in results),
        "blocked": sum(row.bet_status == "BLOCKED" for row in results),
        "official_bets": sum(row.bet_status == "OFFICIAL_BET" for row in results),
        "markets_seen": sorted({row.market for row in results}),
        "games_seen": sorted({row.game_id for row in results}),
    }


def _run_canonical(
    *,
    mode: str,
    now: datetime,
    artifact_payload: Mapping[str, Any],
    runtime_code_git_sha: str,
    live_features: Mapping[str, Any],
    odds_snapshot: Mapping[str, Any],
    book_key: str,
    quote_ttl_seconds: int,
    feature_ttl_seconds: int,
) -> NFLMachineReport:
    current = _aware(now, "NFL_NOW_TIMEZONE_REQUIRED")
    quote_ttl = _positive_int(quote_ttl_seconds, "NFL_QUOTE_TTL_INVALID")
    feature_ttl = _positive_int(feature_ttl_seconds, "NFL_FEATURE_TTL_INVALID")
    model, artifact_sha, code_sha, training_sha = _load_bound_model(
        artifact_payload,
        runtime_code_git_sha=runtime_code_git_sha,
    )
    live_sha, live_asof, games = _validate_live_features(
        live_features,
        current=current,
        feature_ttl_seconds=feature_ttl,
    )
    observed_at, events, snapshot_source = _validate_odds_snapshot(odds_snapshot, current=current)
    quote_age = (current - observed_at).total_seconds()
    stale = quote_age > quote_ttl

    results: list[NFLMachineResult] = []
    for game in games:
        game_id = str(game["game_id"])
        start = _aware(game.get("game_start_ts"), f"NFL_GAME_START_INVALID:{game_id}")
        if observed_at >= start:
            raise NFLRunMachineError(f"NFL_QUOTE_NOT_PREGAME:{game_id}")
        event = _event_for_game(game, events)

        # This is the model/market firewall.  M2 consumes the market-blind game
        # row first; no sportsbook line or price exists in this call.
        try:
            distribution = tuple(derive_nfl_m2_score_distribution(model, dict(game)))
        except ValueError as exc:
            raise NFLRunMachineError(str(exc)) from exc
        if not distribution:
            raise NFLRunMachineError("NFL_SCORE_DISTRIBUTION_EMPTY")
        distribution_sha = _distribution_hash(distribution)

        quotes, sportsbook = _event_quotes(game, event, book_key=book_key)
        by_market = {market: [row for row in quotes if row["market"] == market] for market in SUPPORTED_GAME_MARKETS}
        home_spread = next(row["line"] for row in by_market["SPREAD"] if row["side"] == "HOME")
        total_line = next(row["line"] for row in by_market["TOTAL"] if row["side"] == "OVER")
        try:
            readouts = price_nfl_m2_game_markets(
                distribution,
                spread_line=float(home_spread),
                total_line=float(total_line),
            )
        except ValueError as exc:
            raise NFLRunMachineError(str(exc)) from exc

        for market in ("MONEYLINE", "SPREAD", "TOTAL"):
            pair = by_market[market]
            probabilities = {
                str(row["side"]): _readout(readouts, market=market, side=str(row["side"]))
                for row in pair
            }
            economics = _pair_economics(pair, probabilities, stale=stale)
            for row in economics:
                results.append(NFLMachineResult(
                    game_id=game_id,
                    market=market,
                    side=str(row["side"]),
                    line=None if row["line"] is None else float(row["line"]),
                    american_odds=float(row["american_odds"]),
                    model_p=float(row["model_p"]),
                    push_p=float(row["push_p"]),
                    fair_market_p=None if row["fair_market_p"] is None else float(row["fair_market_p"]),
                    raw_implied_p=None if row["raw_implied_p"] is None else float(row["raw_implied_p"]),
                    hold=None if row["hold"] is None else float(row["hold"]),
                    edge=None if row["edge"] is None else float(row["edge"]),
                    ev_per_dollar=None if row["ev_per_dollar"] is None else float(row["ev_per_dollar"]),
                    bet_status="BLOCKED",
                    engine_status="PRICED",
                    reason=str(row["reason"]),
                    model_artifact_sha256=artifact_sha,
                    model_code_git_sha=code_sha,
                    training_source_manifest_sha256=training_sha,
                    live_feature_source_manifest_sha256=live_sha,
                    live_feature_asof_ts=live_asof.isoformat(),
                    distribution_sha256=distribution_sha,
                    book_key=book_key,
                    sportsbook=sportsbook or snapshot_source,
                    quote_observed_at=observed_at.isoformat(),
                    provider_event_id=str(event.get("id") or "") or None,
                ))

    ordered = tuple(sorted(results, key=lambda row: (row.game_id, row.market, row.side)))
    if not ordered:
        raise NFLRunMachineError("NFL_RUN_RESULTS_EMPTY")
    # Even a technically healthy M2/quote run remains blocked at the wager layer
    # until promotion evidence and a frozen floor exist.
    run_status = "BLOCKED"
    return NFLMachineReport(
        mode=mode,
        generated_at_utc=current.isoformat(),
        run_status=run_status,
        machine_version=NFL_MACHINE_VERSION,
        results=ordered,
        summary=_summary(ordered),
        model_artifact_sha256=artifact_sha,
        model_code_git_sha=code_sha,
        training_source_manifest_sha256=training_sha,
        live_feature_source_manifest_sha256=live_sha,
        live_feature_asof_ts=live_asof.isoformat(),
        quote_observed_at=observed_at.isoformat(),
    )


def run_nfl_machine(
    *,
    mode: str = "AUTO_SELECT",
    model_artifact: Mapping[str, Any],
    runtime_code_git_sha: str,
    now: datetime,
    live_features: Mapping[str, Any] | None = None,
    odds_snapshot: Mapping[str, Any] | None = None,
    feature_builder: FeatureBuilder | None = None,
    odds_fetcher: OddsFetcher | None = None,
    book_key: str = DEFAULT_BOOK_KEY,
    quote_ttl_seconds: int = DEFAULT_QUOTE_TTL_SECONDS,
    feature_ttl_seconds: int = DEFAULT_FEATURE_TTL_SECONDS,
) -> NFLMachineReport:
    """Resolve mode-owned inputs, then execute the single canonical NFL path.

    MANUAL owns both frozen feature and odds snapshots.
    HYBRID owns exactly one snapshot and acquires the other through an injected
    production source callback.  This supports both operator-supplied prices and
    operator-supplied features without creating a second model path.
    AUTOMATIC acquires both snapshots through injected production callbacks.
    """
    current = _aware(now, "NFL_NOW_TIMEZONE_REQUIRED")
    selected = _resolve_mode(mode, live_features=live_features, odds_snapshot=odds_snapshot)

    if selected == "MANUAL":
        if live_features is None or odds_snapshot is None:
            raise NFLRunMachineError("NFL_MANUAL_REQUIRES_FEATURES_AND_ODDS")
        features = live_features
        odds = odds_snapshot
    elif selected == "HYBRID":
        supplied = int(live_features is not None) + int(odds_snapshot is not None)
        if supplied != 1:
            raise NFLRunMachineError("NFL_HYBRID_REQUIRES_EXACTLY_ONE_OPERATOR_SNAPSHOT")
        if live_features is None:
            if feature_builder is None:
                raise NFLRunMachineError("NFL_HYBRID_FEATURE_BUILDER_REQUIRED")
            features = feature_builder()
        else:
            features = live_features
        if odds_snapshot is None:
            if odds_fetcher is None:
                raise NFLRunMachineError("NFL_HYBRID_ODDS_FETCHER_REQUIRED")
            odds = odds_fetcher()
        else:
            odds = odds_snapshot
    elif selected == "AUTOMATIC":
        if live_features is not None or odds_snapshot is not None:
            raise NFLRunMachineError("NFL_AUTOMATIC_OPERATOR_SNAPSHOTS_PROHIBITED")
        if feature_builder is None:
            raise NFLRunMachineError("NFL_AUTOMATIC_FEATURE_BUILDER_REQUIRED")
        if odds_fetcher is None:
            raise NFLRunMachineError("NFL_AUTOMATIC_ODDS_FETCHER_REQUIRED")
        features = feature_builder()
        odds = odds_fetcher()
    else:
        raise NFLRunMachineError(f"NFL_RUN_MODE_UNREACHABLE:{selected}")

    if not isinstance(features, Mapping):
        raise NFLRunMachineError("NFL_FEATURE_BUILDER_OUTPUT_INVALID")
    if not isinstance(odds, Mapping):
        raise NFLRunMachineError("NFL_ODDS_FETCHER_OUTPUT_INVALID")
    clean_book = str(book_key or "").strip().lower()
    if not clean_book:
        raise NFLRunMachineError("NFL_BOOK_KEY_REQUIRED")
    return _run_canonical(
        mode=selected,
        now=current,
        artifact_payload=model_artifact,
        runtime_code_git_sha=runtime_code_git_sha,
        live_features=features,
        odds_snapshot=odds,
        book_key=clean_book,
        quote_ttl_seconds=quote_ttl_seconds,
        feature_ttl_seconds=feature_ttl_seconds,
    )


def run_it_nfl(**kwargs: Any) -> NFLMachineReport:
    return run_nfl_machine(**kwargs)

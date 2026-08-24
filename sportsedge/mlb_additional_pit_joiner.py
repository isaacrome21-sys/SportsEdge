"""Join the seven additional MLB PIT quote families into canonical observations.

PR #131 archives these markets after exact provider-event/player binding.  The
original PR #129 joiner is intentionally count-prop-specific, so this module keeps
that path unchanged while giving the additional archive an equally strict join.
No settlement outcome is trusted from upstream input; it is derived from verified
official facts only after book-rule evidence passes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .additional_mlb_odds_source import CANONICAL_MARKETS
from .mlb_pit_joiner import (
    MLBPITJoinError,
    _MISSING_RULE_CLASS,
    _SYNTHETIC_CLASS,
    _LIVE_FACT_CLASS,
    _LIVE_MODEL_CLASS,
    _LIVE_RULE_CLASS,
    _duplicate_keys,
    _fact_index,
    _index_unique,
    _line_key,
    _model_index,
    _required_rules_by_market,
    _rules_hash,
    _rules_match_sportsbook,
    asdict_compat,
    observation_key,
)
from .mlb_pit_observation import content_sha256, normalize_pit_observation
from .mlb_settlement_evidence import (
    canonical_bytes,
    classify_observation_settlement,
    official_fact_coverage,
)
from .odds_api_source import EVENT_TIME_TOLERANCE_SECONDS, normalize_name

ARCHIVE_TYPE = "MLB_ADDITIONAL_PIT_QUOTES"


def _parse_ts(value: Any, name: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise MLBPITJoinError(f"{name} required")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBPITJoinError(f"{name} invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBPITJoinError(f"{name} timezone required")
    return dt.astimezone(timezone.utc)


def _verify_archive(payload: Mapping[str, Any]) -> tuple[str, str, list[Mapping[str, Any]]]:
    if str(payload.get("archive_type") or "") != ARCHIVE_TYPE:
        raise MLBPITJoinError(f"{ARCHIVE_TYPE} archive required")
    source_class = str(payload.get("evidence_class") or "").upper()
    if source_class not in {"LIVE_PROVIDER_QUOTE_ARCHIVE", _SYNTHETIC_CLASS}:
        raise MLBPITJoinError("archive evidence_class unsupported")
    digest = str(payload.get("payload_sha256") or "").lower()
    if len(digest) != 64:
        raise MLBPITJoinError("archive payload_sha256 required")
    without_hash = {k: v for k, v in payload.items() if k != "payload_sha256"}
    if content_sha256(without_hash) != digest:
        raise MLBPITJoinError("ARCHIVE_PAYLOAD_HASH_MISMATCH")
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        raise MLBPITJoinError("archive quotes must be list")
    return source_class, digest, quotes


def _bind_odds_api_event(quote: Mapping[str, Any], games: Iterable[Mapping[str, Any]]) -> str:
    event = quote.get("provider_event_snapshot")
    if not isinstance(event, Mapping):
        raise MLBPITJoinError("PROVIDER_EVENT_SNAPSHOT_REQUIRED")
    event_hash = str(quote.get("provider_event_sha256") or "").lower()
    if len(event_hash) != 64 or content_sha256(dict(event)) != event_hash:
        raise MLBPITJoinError("PROVIDER_EVENT_HASH_MISMATCH")

    away = normalize_name(event.get("away_team"))
    home = normalize_name(event.get("home_team"))
    if not away or not home or away == home:
        raise MLBPITJoinError("PROVIDER_EVENT_TEAM_IDENTITY_MISSING")
    commence = _parse_ts(event.get("commence_time"), "provider_event.commence_time")

    matches: list[str] = []
    for game in games:
        if not isinstance(game, Mapping):
            continue
        if normalize_name(game.get("away_name")) != away or normalize_name(game.get("home_name")) != home:
            continue
        start = _parse_ts(game.get("first_pitch_ts"), "game_candidate.first_pitch_ts")
        if abs((start - commence).total_seconds()) > EVENT_TIME_TOLERANCE_SECONDS:
            continue
        game_id = str(game.get("game_id") or "").strip()
        if game_id:
            matches.append(game_id)
    unique = set(matches)
    if not unique:
        raise MLBPITJoinError("PROVIDER_EVENT_GAME_NOT_FOUND")
    if len(unique) != 1:
        raise MLBPITJoinError("PROVIDER_EVENT_GAME_AMBIGUOUS")
    return next(iter(unique))


def _verify_archive_identity(quote: Mapping[str, Any], game_id: str) -> str:
    if str(quote.get("game_id") or "") != str(game_id):
        raise MLBPITJoinError("ARCHIVED_CANONICAL_GAME_MISMATCH")
    snapshot = quote.get("canonical_game_snapshot")
    snapshot_hash = str(quote.get("canonical_game_snapshot_sha256") or "").lower()
    if not isinstance(snapshot, Mapping) or len(snapshot_hash) != 64:
        raise MLBPITJoinError("CANONICAL_GAME_SNAPSHOT_REQUIRED")
    if content_sha256(dict(snapshot)) != snapshot_hash:
        raise MLBPITJoinError("CANONICAL_GAME_SNAPSHOT_HASH_MISMATCH")
    if str(snapshot.get("game_id") or "") != str(game_id):
        raise MLBPITJoinError("CANONICAL_GAME_SNAPSHOT_ID_MISMATCH")

    entity_id = str(quote.get("entity_id") or "").strip()
    if not entity_id:
        raise MLBPITJoinError("CANONICAL_ENTITY_ID_REQUIRED")
    binding = {
        "provider_event_id": str(quote.get("provider_event_id") or ""),
        "provider_event_sha256": str(quote.get("provider_event_sha256") or ""),
        "canonical_game_id": str(game_id),
        "canonical_entity_id": entity_id,
        "canonical_game_snapshot_sha256": snapshot_hash,
        "resolver_contract": "EXACT_NORMALIZED_TEAM_TIME_AND_PARTICIPANT_IDENTITY",
    }
    binding_hash = str(quote.get("identity_binding_sha256") or "").lower()
    if len(binding_hash) != 64 or content_sha256(binding) != binding_hash:
        raise MLBPITJoinError("IDENTITY_BINDING_HASH_MISMATCH")
    return entity_id


def _verify_entity(
    *,
    market: str,
    entity_id: str,
    game: Mapping[str, Any],
    player_candidates: Iterable[Mapping[str, Any]],
) -> None:
    if market in {"F5_MONEYLINE", "F5_RUN_LINE"}:
        team_ids = {str(game.get("away_team_id") or ""), str(game.get("home_team_id") or "")}
        if entity_id not in team_ids:
            raise MLBPITJoinError("CANONICAL_TEAM_ENTITY_NOT_REPRODUCIBLE")
        return
    if market in {"F5_TOTALS", "NRFI", "YRFI"}:
        if entity_id != str(game.get("game_id") or ""):
            raise MLBPITJoinError("CANONICAL_GAME_ENTITY_NOT_REPRODUCIBLE")
        return
    if market in {"FIRST_HOME_RUN", "PITCHER_RECORD_WIN"}:
        matches = {
            str(row.get("player_id") or "")
            for row in player_candidates
            if isinstance(row, Mapping) and str(row.get("player_id") or "") == entity_id
        }
        if len(matches) != 1:
            raise MLBPITJoinError("CANONICAL_PLAYER_ENTITY_NOT_REPRODUCIBLE")
        return
    raise MLBPITJoinError("ADDITIONAL_MARKET_IDENTITY_UNSUPPORTED")


def _binary_outcome(event_true: bool, side: Any) -> str:
    direction = str(side or "").upper()
    if direction not in {"YES", "NO"}:
        raise MLBPITJoinError("BINARY_SIDE_MUST_BE_YES_OR_NO")
    won = event_true if direction == "YES" else not event_true
    return "WIN" if won else "LOSS"


def _f5_moneyline_outcome(facts: Mapping[str, Any], side: Any) -> str:
    f5 = facts.get("f5")
    if not isinstance(f5, Mapping):
        raise MLBPITJoinError("F5_FACTS_MISSING")
    away = float(f5["away_runs"])
    home = float(f5["home_runs"])
    direction = str(side or "").upper()
    if direction in {"HOME", "HOME_ML"}:
        selected, other = home, away
    elif direction in {"AWAY", "AWAY_ML"}:
        selected, other = away, home
    else:
        raise MLBPITJoinError("F5_MONEYLINE_SIDE_INVALID")
    if selected == other:
        return "PUSH"
    return "WIN" if selected > other else "LOSS"


def _f5_run_line_outcome(facts: Mapping[str, Any], line: Any, side: Any) -> str:
    f5 = facts.get("f5")
    if not isinstance(f5, Mapping):
        raise MLBPITJoinError("F5_FACTS_MISSING")
    away = float(f5["away_runs"])
    home = float(f5["home_runs"])
    spread = float(line)
    direction = str(side or "").upper()
    if direction in {"HOME", "HOME_RL"}:
        selected, other = home, away
    elif direction in {"AWAY", "AWAY_RL"}:
        selected, other = away, home
    else:
        raise MLBPITJoinError("F5_RUN_LINE_SIDE_INVALID")
    adjusted = selected + spread
    if abs(adjusted - other) <= 1e-12:
        return "PUSH"
    return "WIN" if adjusted > other else "LOSS"


def _f5_total_outcome(facts: Mapping[str, Any], line: Any, side: Any) -> str:
    f5 = facts.get("f5")
    if not isinstance(f5, Mapping):
        raise MLBPITJoinError("F5_FACTS_MISSING")
    total = float(f5["away_runs"]) + float(f5["home_runs"])
    threshold = float(line)
    direction = str(side or "").upper()
    if direction not in {"OVER", "UNDER"}:
        raise MLBPITJoinError("F5_TOTAL_SIDE_INVALID")
    if abs(total - threshold) <= 1e-12:
        return "PUSH"
    won = total > threshold if direction == "OVER" else total < threshold
    return "WIN" if won else "LOSS"


def _derive_outcome(facts: Mapping[str, Any], market: str, entity_id: str, line: Any, side: Any) -> str:
    if market == "F5_MONEYLINE":
        return _f5_moneyline_outcome(facts, side)
    if market == "F5_RUN_LINE":
        return _f5_run_line_outcome(facts, line, side)
    if market == "F5_TOTALS":
        return _f5_total_outcome(facts, line, side)
    if market in {"NRFI", "YRFI"}:
        first = facts.get("first_inning")
        if not isinstance(first, Mapping):
            raise MLBPITJoinError("FIRST_INNING_FACTS_MISSING")
        value = first.get("nrfi") if market == "NRFI" else first.get("yrfi")
        if type(value) is not bool:
            raise MLBPITJoinError("FIRST_INNING_BINARY_FACT_MISSING")
        normalized_side = "YES" if str(side or "").upper() in {"NRFI", "YRFI"} else side
        return _binary_outcome(value, normalized_side)
    if market == "FIRST_HOME_RUN":
        first_hr = facts.get("first_home_run")
        if not isinstance(first_hr, Mapping) or type(first_hr.get("occurred")) is not bool:
            raise MLBPITJoinError("FIRST_HOME_RUN_FACT_MISSING")
        event_true = bool(first_hr["occurred"]) and str(first_hr.get("batter_id") or "") == entity_id
        return _binary_outcome(event_true, side)
    if market == "PITCHER_RECORD_WIN":
        winner = facts.get("winning_pitcher")
        if not isinstance(winner, Mapping) or not str(winner.get("pitcher_id") or ""):
            raise MLBPITJoinError("WINNING_PITCHER_FACT_MISSING")
        return _binary_outcome(str(winner.get("pitcher_id")) == entity_id, side)
    raise MLBPITJoinError("ADDITIONAL_SETTLEMENT_INTERPRETER_MISSING")


def join_additional_archive(
    *,
    archive_payload: Mapping[str, Any],
    game_candidates: Iterable[Mapping[str, Any]],
    player_candidates_by_game: Mapping[str, Iterable[Mapping[str, Any]]],
    model_rows: Iterable[Mapping[str, Any]],
    official_fact_reports: Iterable[Mapping[str, Any]],
    settlement_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    source_class, quote_source_hash, quotes = _verify_archive(archive_payload)
    games = [dict(row) for row in game_candidates if isinstance(row, Mapping)]
    game_by_id = _index_unique(games, "game_id")
    model_idx = _model_index(model_rows)
    fact_idx = _fact_index(official_fact_reports)
    settlement_list = [dict(row) for row in settlement_rows if isinstance(row, Mapping)]
    settlement_idx = _index_unique(settlement_list, "observation_key")
    settlement_duplicates = _duplicate_keys(settlement_list, "observation_key")
    required_rules_by_market = _required_rules_by_market()

    joined: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for source_index, quote in enumerate(quotes):
        if not isinstance(quote, Mapping):
            failures.append({"source_index": source_index, "reason": "QUOTE_NOT_OBJECT"})
            continue
        try:
            if quote.get("pit_eligible") is not True:
                raise MLBPITJoinError("QUOTE_NOT_PIT_ELIGIBLE")
            market = str(quote.get("market") or "").upper()
            if market not in CANONICAL_MARKETS:
                raise MLBPITJoinError("ADDITIONAL_ARCHIVE_MARKET_REQUIRED")

            game_id = _bind_odds_api_event(quote, games)
            game = game_by_id.get(game_id)
            if game is None:
                raise MLBPITJoinError("CANONICAL_GAME_ROW_NOT_UNIQUE")
            entity_id = _verify_archive_identity(quote, game_id)
            _verify_entity(
                market=market,
                entity_id=entity_id,
                game=game,
                player_candidates=player_candidates_by_game.get(game_id, ()),
            )

            model_key = (
                game_id,
                market,
                entity_id,
                _line_key(quote.get("line")),
                str(quote.get("side") or "").upper(),
            )
            model = model_idx.get(model_key)
            if model is None:
                raise MLBPITJoinError("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS")
            model_class = str(model.get("evidence_class") or "").strip().upper()
            if model_class not in {_LIVE_MODEL_CLASS, _SYNTHETIC_CLASS}:
                raise MLBPITJoinError("MODEL_EVIDENCE_CLASS_REQUIRED")

            fact_report = fact_idx.get(game_id)
            if fact_report is None:
                raise MLBPITJoinError("OFFICIAL_FACT_REPORT_NOT_FOUND_OR_AMBIGUOUS")
            fact_class = str(fact_report.get("evidence_class") or "").strip().upper()
            if fact_class not in {_LIVE_FACT_CLASS, _SYNTHETIC_CLASS}:
                raise MLBPITJoinError("OFFICIAL_FACT_EVIDENCE_CLASS_REQUIRED")
            facts = fact_report.get("facts")
            if not isinstance(facts, Mapping):
                raise MLBPITJoinError("OFFICIAL_FACTS_PAYLOAD_MISSING")
            facts_hash = str(fact_report.get("facts_sha256") or "").lower()
            if len(facts_hash) != 64 or hashlib.sha256(canonical_bytes(dict(facts))).hexdigest() != facts_hash:
                raise MLBPITJoinError("OFFICIAL_FACTS_HASH_MISMATCH")

            quote_ts = str(quote.get("quote_retrieved_at") or quote.get("retrieved_at") or "")
            obs_key = observation_key(
                game_id=game_id,
                market=market,
                entity_id=entity_id,
                line=quote.get("line"),
                side=quote.get("side"),
                book_key=quote.get("book_key"),
                quote_ts=quote_ts,
            )
            if obs_key in settlement_duplicates:
                raise MLBPITJoinError("SETTLEMENT_EVIDENCE_AMBIGUOUS")
            settlement = settlement_idx.get(obs_key)

            required_rules = required_rules_by_market.get(market)
            if required_rules is None:
                raise MLBPITJoinError("SETTLEMENT_RULE_CONTRACT_MISSING")
            sportsbook = str(quote.get("sportsbook") or "DraftKings")
            if settlement is None:
                rule_class = _MISSING_RULE_CLASS
                rule_evidence: Mapping[str, Any] | None = None
                ambiguity_reasons: list[str] = []
                void_reasons: list[str] = []
            else:
                rule_class = str(settlement.get("evidence_class") or "").strip().upper()
                if rule_class not in {_LIVE_RULE_CLASS, _SYNTHETIC_CLASS}:
                    raise MLBPITJoinError("BOOK_RULE_EVIDENCE_CLASS_REQUIRED")
                candidate = settlement.get("book_rule_evidence")
                rule_evidence = candidate if isinstance(candidate, Mapping) else None
                ambiguity_reasons = [str(x) for x in settlement.get("ambiguity_reasons", ()) if str(x)]
                void_reasons = [str(x) for x in settlement.get("void_reasons", ()) if str(x)]

            book_valid, _ = _rules_match_sportsbook(
                required_rules=required_rules,
                evidence=rule_evidence,
                sportsbook=sportsbook,
            )
            rules_hash = _rules_hash(
                required_rules=required_rules,
                evidence=rule_evidence,
                sportsbook=sportsbook,
            )
            fact_state = str((official_fact_coverage(facts).get(market) or {}).get("state") or "OFFICIAL_FACTS_MISSING")
            settlement_state = classify_observation_settlement(
                official_fact_state=fact_state,
                book_rules_validated=book_valid,
                ambiguity_reasons=ambiguity_reasons,
            )
            if settlement_state == "SETTLEMENT_ELIGIBLE" and void_reasons:
                settlement_state = "VOID"

            settled_outcome = None
            if settlement_state == "SETTLEMENT_ELIGIBLE":
                settled_outcome = _derive_outcome(
                    facts, market, entity_id, quote.get("line"), quote.get("side")
                )

            raw = {
                "market": market,
                "game_id": game_id,
                "entity_id": entity_id,
                "quote_ts": quote_ts,
                "first_pitch_ts": quote.get("first_pitch_at"),
                "line": quote.get("line"),
                "side": quote.get("side"),
                "sportsbook": sportsbook,
                "book_key": quote.get("book_key") or "draftkings",
                "source_evidence_class": source_class,
                "model_evidence_class": model_class,
                "official_fact_evidence_class": fact_class,
                "book_rule_evidence_class": rule_class,
                "quote_source_hash": quote_source_hash,
                "provider_event_hash": quote.get("provider_event_sha256"),
                "identity_binding_hash": quote.get("identity_binding_sha256"),
                "history_asof_ts": model.get("history_asof_ts"),
                "history_source_hash": model.get("history_source_hash"),
                "model_input_hash": model.get("model_input_hash"),
                "official_facts_hash": facts_hash,
                "settlement_rules_hash": rules_hash,
                "settlement_state": settlement_state,
                "settled_outcome": settled_outcome,
                "candidate_p": model.get("candidate_p"),
                "incumbent_p": model.get("incumbent_p"),
            }
            normalized = normalize_pit_observation(raw)
            joined.append({"observation_key": obs_key, "source_index": source_index, **asdict_compat(normalized)})
        except Exception as exc:
            failures.append(
                {
                    "source_index": source_index,
                    "provider_event_id": quote.get("provider_event_id"),
                    "market": quote.get("market"),
                    "entity_id": quote.get("entity_id"),
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            )

    return {
        "schema_version": 1,
        "archive_type": ARCHIVE_TYPE,
        "archive_payload_sha256": quote_source_hash,
        "source_quote_count": len(quotes),
        "joined_observation_count": len(joined),
        "failure_count": len(failures),
        "observations": joined,
        "failures": failures,
    }

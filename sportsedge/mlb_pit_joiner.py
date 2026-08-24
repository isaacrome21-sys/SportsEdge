"""Join archived MLB prop quotes into strict PIT observation candidates.

The join is deterministic and fail-closed. Provider identities are resolved using
exact team/time and exact normalized participant matching; model rows must match the
actual line/side; official-fact and settlement evidence remain separate inputs.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping

from .mlb_pit_observation import (
    bind_participant_to_player,
    bind_provider_event_to_game,
    content_sha256,
    normalize_pit_observation,
)
from .mlb_settlement_evidence import canonical_bytes


class MLBPITJoinError(ValueError):
    pass


def _line_key(value: Any) -> str:
    try:
        return format(float(value), ".12g")
    except (TypeError, ValueError) as exc:
        raise MLBPITJoinError("line must be numeric") from exc


def observation_key(
    *,
    game_id: Any,
    market: Any,
    entity_id: Any,
    line: Any,
    side: Any,
    book_key: Any,
    quote_ts: Any,
) -> str:
    payload = {
        "game_id": str(game_id),
        "market": str(market).upper(),
        "entity_id": str(entity_id),
        "line": _line_key(line),
        "side": str(side).upper(),
        "book_key": str(book_key),
        "quote_ts": str(quote_ts),
    }
    return content_sha256(payload)


def _index_unique(rows: Iterable[Mapping[str, Any]], key_name: str) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get(key_name) or "").strip()
        if not key:
            continue
        if key in out:
            duplicates.add(key)
        else:
            out[key] = row
    for key in duplicates:
        out.pop(key, None)
    return out


def _model_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("game_id") or ""),
        str(row.get("market") or "").upper(),
        str(row.get("entity_id") or ""),
        _line_key(row.get("line")),
        str(row.get("side") or "").upper(),
    )


def _model_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str, str, str], Mapping[str, Any]]:
    out: dict[tuple[str, str, str, str, str], Mapping[str, Any]] = {}
    dup: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = _model_key(row)
        if key in out:
            dup.add(key)
        else:
            out[key] = row
    for key in dup:
        out.pop(key, None)
    return out


def _fact_game_id(row: Mapping[str, Any]) -> str:
    direct = str(row.get("game_id") or row.get("game_pk") or "").strip()
    if direct:
        return direct
    facts = row.get("facts")
    if isinstance(facts, Mapping):
        return str(facts.get("game_id") or facts.get("game_pk") or "").strip()
    return ""


def _fact_index(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = _fact_game_id(row)
        if not key:
            continue
        if key in out:
            duplicates.add(key)
        else:
            out[key] = row
    for key in duplicates:
        out.pop(key, None)
    return out


def _either_pitcher_entity(game: Mapping[str, Any]) -> str:
    away = str(game.get("away_probable_pitcher_id") or "").strip()
    home = str(game.get("home_probable_pitcher_id") or "").strip()
    if not away or not home or away == home:
        raise MLBPITJoinError("EITHER_PITCHER_CANONICAL_IDS_REQUIRED")
    return f"{away}|{home}"


def join_prop_archive(
    *,
    archive_payload: Mapping[str, Any],
    game_candidates: Iterable[Mapping[str, Any]],
    player_candidates_by_game: Mapping[str, Iterable[Mapping[str, Any]]],
    model_rows: Iterable[Mapping[str, Any]],
    official_fact_reports: Iterable[Mapping[str, Any]],
    settlement_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    if str(archive_payload.get("archive_type") or "") != "MLB_PROP_PIT_QUOTES":
        raise MLBPITJoinError("MLB_PROP_PIT_QUOTES archive required")
    source_class = str(archive_payload.get("evidence_class") or "").upper()
    if source_class not in {"LIVE_PROVIDER_QUOTE_ARCHIVE", "SYNTHETIC_CONTRACT_TEST"}:
        raise MLBPITJoinError("archive evidence_class unsupported")
    quote_source_hash = str(archive_payload.get("payload_sha256") or "").lower()
    if len(quote_source_hash) != 64:
        raise MLBPITJoinError("archive payload_sha256 required")
    archive_without_hash = {
        key: value for key, value in archive_payload.items() if key != "payload_sha256"
    }
    if content_sha256(archive_without_hash) != quote_source_hash:
        raise MLBPITJoinError("ARCHIVE_PAYLOAD_HASH_MISMATCH")

    games = [dict(row) for row in game_candidates if isinstance(row, Mapping)]
    game_by_id = _index_unique(games, "game_id")
    model_idx = _model_index(model_rows)
    fact_idx = _fact_index(official_fact_reports)
    settlement_idx = _index_unique(settlement_rows, "observation_key")

    joined: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    quotes = archive_payload.get("quotes")
    if not isinstance(quotes, list):
        raise MLBPITJoinError("archive quotes must be list")

    for source_index, quote in enumerate(quotes):
        if not isinstance(quote, Mapping):
            failures.append({"source_index": source_index, "reason": "QUOTE_NOT_OBJECT"})
            continue
        try:
            if quote.get("pit_eligible") is not True:
                raise MLBPITJoinError("QUOTE_NOT_PIT_ELIGIBLE")
            game_id = bind_provider_event_to_game(quote, games)
            game = game_by_id.get(game_id)
            if game is None:
                raise MLBPITJoinError("CANONICAL_GAME_ROW_NOT_UNIQUE")
            market = str(quote.get("market") or "").upper()
            if market.startswith("EITHER_PITCHER_"):
                entity_id = _either_pitcher_entity(game)
            else:
                entity_id = bind_participant_to_player(
                    quote.get("entity_name"),
                    player_candidates_by_game.get(str(game_id), ()),
                )

            key = (
                str(game_id),
                market,
                str(entity_id),
                _line_key(quote.get("line")),
                str(quote.get("side") or "").upper(),
            )
            model = model_idx.get(key)
            if model is None:
                raise MLBPITJoinError("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS")

            fact_report = fact_idx.get(str(game_id))
            if fact_report is None:
                raise MLBPITJoinError("OFFICIAL_FACT_REPORT_NOT_FOUND_OR_AMBIGUOUS")
            facts = fact_report.get("facts")
            if not isinstance(facts, Mapping):
                raise MLBPITJoinError("OFFICIAL_FACTS_PAYLOAD_MISSING")
            official_facts_hash = str(fact_report.get("facts_sha256") or "").lower()
            if len(official_facts_hash) != 64:
                raise MLBPITJoinError("OFFICIAL_FACTS_HASH_INVALID")
            if hashlib.sha256(canonical_bytes(dict(facts))).hexdigest() != official_facts_hash:
                raise MLBPITJoinError("OFFICIAL_FACTS_HASH_MISMATCH")

            identity_payload = {
                "provider_event_id": quote.get("provider_event_id"),
                "provider_event_hash": quote.get("provider_event_sha256"),
                "game_id": game_id,
                "entity_name": quote.get("entity_name"),
                "entity_id": entity_id,
            }
            identity_hash = content_sha256(identity_payload)
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
            settlement = settlement_idx.get(obs_key) or {}
            settlement_state = str(
                settlement.get("settlement_state") or "BOOK_SETTLEMENT_UNVALIDATED"
            ).upper()

            raw = {
                "market": market,
                "game_id": str(game_id),
                "entity_id": str(entity_id),
                "quote_ts": quote_ts,
                "first_pitch_ts": quote.get("first_pitch_at"),
                "line": quote.get("line"),
                "side": quote.get("side"),
                "sportsbook": quote.get("sportsbook") or "DraftKings",
                "book_key": quote.get("book_key") or "draftkings_direct",
                "source_evidence_class": source_class,
                "quote_source_hash": quote_source_hash,
                "provider_event_hash": quote.get("provider_event_sha256"),
                "identity_binding_hash": identity_hash,
                "history_asof_ts": model.get("history_asof_ts"),
                "history_source_hash": model.get("history_source_hash"),
                "model_input_hash": model.get("model_input_hash"),
                "official_facts_hash": official_facts_hash,
                "settlement_rules_hash": settlement.get("settlement_rules_hash"),
                "settlement_state": settlement_state,
                "settled_outcome": settlement.get("settled_outcome"),
                "candidate_p": model.get("candidate_p"),
                "incumbent_p": model.get("incumbent_p"),
            }
            normalized = normalize_pit_observation(raw)
            joined.append(
                {
                    "observation_key": obs_key,
                    "source_index": source_index,
                    **asdict_compat(normalized),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "source_index": source_index,
                    "provider_event_id": quote.get("provider_event_id"),
                    "market": quote.get("market"),
                    "entity_name": quote.get("entity_name"),
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            )

    return {
        "schema_version": 1,
        "archive_payload_sha256": quote_source_hash,
        "source_quote_count": len(quotes),
        "joined_observation_count": len(joined),
        "failure_count": len(failures),
        "observations": joined,
        "failures": failures,
    }


def asdict_compat(row: Any) -> dict[str, Any]:
    return {field: getattr(row, field) for field in row.__dataclass_fields__}

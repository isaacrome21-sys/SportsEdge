"""Canonical PIT archive dispatcher for MLB evidence joins.

The count-prop and additional-market archives intentionally keep different provider
identity contracts, but callers should not need to guess which joiner owns a saved
artifact. Dispatch is by immutable archive_type only and unknown types fail closed.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .mlb_additional_pit_joiner import ARCHIVE_TYPE as ADDITIONAL_ARCHIVE_TYPE, join_additional_archive
from .mlb_pit_joiner import MLBPITJoinError, join_prop_archive, observation_key
from .odds_api_source import normalize_name

COUNT_ARCHIVE_TYPE = "MLB_PROP_PIT_QUOTES"
SUPPORTED_ARCHIVE_TYPES = frozenset({COUNT_ARCHIVE_TYPE, ADDITIONAL_ARCHIVE_TYPE})
_BINARY_ADDITIONAL_MARKETS = frozenset({"FIRST_HOME_RUN", "PITCHER_RECORD_WIN"})
_MISSING_RAW_PARTICIPANT = "PROVIDER_PARTICIPANT_RAW_IDENTITY_NOT_ARCHIVED"


def _materialize_player_candidates(
    rows: Mapping[str, Iterable[Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        str(game_id): [dict(row) for row in candidates if isinstance(row, Mapping)]
        for game_id, candidates in rows.items()
    }


def _harden_additional_binary_provenance(
    *,
    archive_payload: Mapping[str, Any],
    player_candidates_by_game: Mapping[str, list[dict[str, Any]]],
    settlement_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in settlement_rows:
        key = str(row.get("observation_key") or "").strip()
        if key:
            by_key.setdefault(key, []).append(row)

    quotes = archive_payload.get("quotes")
    if not isinstance(quotes, list):
        return settlement_rows
    for quote in quotes:
        if not isinstance(quote, Mapping):
            continue
        market = str(quote.get("market") or "").upper()
        if market not in _BINARY_ADDITIONAL_MARKETS:
            continue
        game_id = str(quote.get("game_id") or "")
        entity_id = str(quote.get("entity_id") or "")
        provider_name = str(quote.get("provider_participant_name") or "").strip()

        if provider_name:
            expected = normalize_name(provider_name)
            matches = [
                row
                for row in player_candidates_by_game.get(game_id, [])
                if str(row.get("player_id") or "") == entity_id
                and normalize_name(row.get("player_name")) == expected
            ]
            if len(matches) != 1:
                raise MLBPITJoinError("PROVIDER_PARTICIPANT_IDENTITY_NOT_REPRODUCIBLE")
            continue

        key = observation_key(
            game_id=game_id,
            market=market,
            entity_id=entity_id,
            line=quote.get("line"),
            side=quote.get("side"),
            book_key=quote.get("book_key"),
            quote_ts=quote.get("quote_retrieved_at") or quote.get("retrieved_at"),
        )
        for settlement in by_key.get(key, []):
            ambiguity = [str(x) for x in settlement.get("ambiguity_reasons", ()) if str(x)]
            if _MISSING_RAW_PARTICIPANT not in ambiguity:
                ambiguity.append(_MISSING_RAW_PARTICIPANT)
            settlement["ambiguity_reasons"] = ambiguity
    return settlement_rows


def join_mlb_pit_archive(
    *,
    archive_payload: Mapping[str, Any],
    game_candidates: Iterable[Mapping[str, Any]],
    player_candidates_by_game: Mapping[str, Iterable[Mapping[str, Any]]],
    model_rows: Iterable[Mapping[str, Any]],
    official_fact_reports: Iterable[Mapping[str, Any]],
    settlement_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    archive_type = str(archive_payload.get("archive_type") or "").strip()
    if archive_type == COUNT_ARCHIVE_TYPE:
        return join_prop_archive(
            archive_payload=archive_payload,
            game_candidates=game_candidates,
            player_candidates_by_game=player_candidates_by_game,
            model_rows=model_rows,
            official_fact_reports=official_fact_reports,
            settlement_rows=settlement_rows,
        )
    if archive_type == ADDITIONAL_ARCHIVE_TYPE:
        players = _materialize_player_candidates(player_candidates_by_game)
        settlements = [dict(row) for row in settlement_rows if isinstance(row, Mapping)]
        settlements = _harden_additional_binary_provenance(
            archive_payload=archive_payload,
            player_candidates_by_game=players,
            settlement_rows=settlements,
        )
        return join_additional_archive(
            archive_payload=archive_payload,
            game_candidates=game_candidates,
            player_candidates_by_game=players,
            model_rows=model_rows,
            official_fact_reports=official_fact_reports,
            settlement_rows=settlements,
        )
    raise MLBPITJoinError(f"PIT_ARCHIVE_TYPE_UNSUPPORTED:{archive_type or 'MISSING'}")

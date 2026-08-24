"""Canonical PIT archive dispatcher for MLB evidence joins.

The count-prop and additional-market archives intentionally keep different provider
identity contracts, but callers should not need to guess which joiner owns a saved
artifact. Dispatch is by immutable archive_type only and unknown types fail closed.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .mlb_additional_pit_joiner import ARCHIVE_TYPE as ADDITIONAL_ARCHIVE_TYPE, join_additional_archive
from .mlb_pit_joiner import MLBPITJoinError, join_prop_archive, observation_key

COUNT_ARCHIVE_TYPE = "MLB_PROP_PIT_QUOTES"
SUPPORTED_ARCHIVE_TYPES = frozenset({COUNT_ARCHIVE_TYPE, ADDITIONAL_ARCHIVE_TYPE})
F5_TIE_POLICY_AMBIGUITY = "F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED"


def _materialize_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _fact_game_id(row: Mapping[str, Any]) -> str:
    direct = str(row.get("game_id") or row.get("game_pk") or "").strip()
    if direct:
        return direct
    facts = row.get("facts")
    if isinstance(facts, Mapping):
        return str(facts.get("game_id") or facts.get("game_pk") or "").strip()
    return ""


def _harden_f5_moneyline_ties(
    *,
    archive_payload: Mapping[str, Any],
    official_fact_reports: list[dict[str, Any]],
    settlement_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Make F5 ML ties ambiguous until rule evidence carries a normalized tie policy.

    Current rule records prove source provenance but do not encode the sportsbook's
    tie interpretation as machine-readable semantics. A rule-document SHA therefore
    cannot justify hardcoding PUSH/VOID/ACTION for an exact F5 tie.
    """
    facts_by_game: dict[str, list[dict[str, Any]]] = {}
    for report in official_fact_reports:
        game_id = _fact_game_id(report)
        if game_id:
            facts_by_game.setdefault(game_id, []).append(report)

    by_observation: dict[str, list[dict[str, Any]]] = {}
    for row in settlement_rows:
        key = str(row.get("observation_key") or "").strip()
        if key:
            by_observation.setdefault(key, []).append(row)

    quotes = archive_payload.get("quotes")
    if not isinstance(quotes, list):
        return settlement_rows

    for quote in quotes:
        if not isinstance(quote, Mapping):
            continue
        if str(quote.get("market") or "").upper() != "F5_MONEYLINE":
            continue
        game_id = str(quote.get("game_id") or "").strip()
        reports = facts_by_game.get(game_id, [])
        if len(reports) != 1:
            continue
        facts = reports[0].get("facts")
        f5 = facts.get("f5") if isinstance(facts, Mapping) else None
        if not isinstance(f5, Mapping):
            continue
        try:
            away_runs = float(f5["away_runs"])
            home_runs = float(f5["home_runs"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(away_runs - home_runs) > 1e-12:
            continue

        key = observation_key(
            game_id=game_id,
            market="F5_MONEYLINE",
            entity_id=quote.get("entity_id"),
            line=quote.get("line"),
            side=quote.get("side"),
            book_key=quote.get("book_key"),
            quote_ts=quote.get("quote_retrieved_at") or quote.get("retrieved_at"),
        )
        for settlement in by_observation.get(key, []):
            ambiguity = [str(x) for x in settlement.get("ambiguity_reasons", ()) if str(x)]
            if F5_TIE_POLICY_AMBIGUITY not in ambiguity:
                ambiguity.append(F5_TIE_POLICY_AMBIGUITY)
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
        facts = _materialize_rows(official_fact_reports)
        settlements = _materialize_rows(settlement_rows)
        settlements = _harden_f5_moneyline_ties(
            archive_payload=archive_payload,
            official_fact_reports=facts,
            settlement_rows=settlements,
        )
        return join_additional_archive(
            archive_payload=archive_payload,
            game_candidates=game_candidates,
            player_candidates_by_game=player_candidates_by_game,
            model_rows=model_rows,
            official_fact_reports=facts,
            settlement_rows=settlements,
        )
    raise MLBPITJoinError(f"PIT_ARCHIVE_TYPE_UNSUPPORTED:{archive_type or 'MISSING'}")

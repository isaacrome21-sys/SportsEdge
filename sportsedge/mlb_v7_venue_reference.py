from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Iterable

from .mlb_v7_travel_history import MLBV7TravelHistoryError, parse_venue_reference

SOURCE_CLASS = "VENUE_REFERENCE"
MODELED_GAME_TYPES = frozenset({"R", "F", "D", "L", "W"})
REQUIRED_FIELDS = ["venue_id", "latitude", "longitude", "timezone"]
REQUIRED_SEMANTICS = {"fixed_facts_only": True}


class MLBV7VenueReferenceError(RuntimeError):
    pass


def venue_ids_from_schedule_payloads(payloads: Iterable[Any], *, game_types: frozenset[str] = MODELED_GAME_TYPES) -> list[int]:
    """Discover venue IDs while tolerating exact duplicate game rows from MLB schedule blocks.

    A repeated gamePk is accepted only when venue/team/game-type identity agrees. Conflicting
    duplicates fail closed instead of choosing one row. Status may differ across duplicate blocks;
    a venue is admitted only if at least one current row is Final and the game type is modeled.
    """
    ids: set[int] = set()
    seen: dict[int, tuple[int, int, int, str]] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            raise MLBV7VenueReferenceError("SCHEDULE_PAYLOAD_INVALID")
        for date_block in payload.get("dates") or []:
            if not isinstance(date_block, dict):
                raise MLBV7VenueReferenceError("SCHEDULE_DATE_BLOCK_INVALID")
            for game in date_block.get("games") or []:
                if not isinstance(game, dict):
                    raise MLBV7VenueReferenceError("SCHEDULE_GAME_INVALID")
                try:
                    game_id = int(game["gamePk"])
                    venue_id = int((game.get("venue") or {})["id"])
                    teams = game.get("teams") or {}
                    away_id = int((((teams.get("away") or {}).get("team") or {})["id"]))
                    home_id = int((((teams.get("home") or {}).get("team") or {})["id"]))
                except Exception as exc:
                    raise MLBV7VenueReferenceError("SCHEDULE_GAME_IDENTITY_INCOMPLETE") from exc
                game_type = game.get("gameType")
                if not isinstance(game_type, str) or not game_type:
                    raise MLBV7VenueReferenceError("GAME_TYPE_MISSING")
                if min(game_id, venue_id, away_id, home_id) <= 0:
                    raise MLBV7VenueReferenceError("SCHEDULE_GAME_IDENTITY_INVALID")
                identity = (venue_id, away_id, home_id, game_type)
                previous = seen.get(game_id)
                if previous is not None and previous != identity:
                    raise MLBV7VenueReferenceError(f"SCHEDULE_GAME_DUPLICATE_CONFLICT:{game_id}")
                seen[game_id] = identity
                status = ((game.get("status") or {}).get("abstractGameState"))
                if status == "Final" and game_type in game_types:
                    ids.add(venue_id)
    if not ids:
        raise MLBV7VenueReferenceError("NO_FINAL_MODELED_GAMES_IN_COVERAGE")
    return sorted(ids)


def build_venue_reference_rows(venue_ids: Iterable[int], *, fetch_venue_payload: Callable[[int], Any], source_url_for_venue: Callable[[int], str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, failures = [], []
    for venue_id in sorted(set(int(v) for v in venue_ids)):
        try:
            parsed = parse_venue_reference(fetch_venue_payload(venue_id), venue_id)
            row = asdict(parsed)
            if source_url_for_venue is not None:
                row["source_url"] = source_url_for_venue(venue_id)
            rows.append(row)
        except (MLBV7TravelHistoryError, MLBV7VenueReferenceError) as exc:
            failures.append({"venue_id": venue_id, "reason": str(exc)})
    return rows, failures


def build_venue_reference_report(*, coverage_start: str, coverage_end: str, venue_ids: list[int], rows: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    expected = sorted(set(int(v) for v in venue_ids))
    found = sorted(int(row["venue_id"]) for row in rows)
    missing = sorted(set(expected) - set(found))
    blockers = ["VENUE_REFERENCE_INCOMPLETE"] if failures or missing else []
    return {
        "contract": "SPORTSEDGE_MLB_V7_VENUE_REFERENCE_ACQUISITION_V1",
        "source_class": SOURCE_CLASS,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "modeled_game_types": sorted(MODELED_GAME_TYPES),
        "discovered_venue_count": len(expected),
        "resolved_venue_count": len(found),
        "missing_venue_ids": missing,
        "failures": failures,
        "state": "READY_TO_ATTEST" if not blockers else "BLOCKED_SOURCE_ACQUISITION",
        "blockers": blockers,
        "promotion_authority": False,
        "candidate_training_allowed": False,
    }


def build_attestation(*, coverage_start: str, coverage_end: str, evidence_path: str, evidence_sha256: str) -> dict[str, Any]:
    if not isinstance(evidence_sha256, str) or len(evidence_sha256) != 64:
        raise MLBV7VenueReferenceError("EVIDENCE_SHA256_INVALID")
    return {"source_class": SOURCE_CLASS, "coverage_start": coverage_start, "coverage_end": coverage_end, "fields": REQUIRED_FIELDS, "semantics": REQUIRED_SEMANTICS, "evidence_files": [{"path": evidence_path, "sha256": evidence_sha256.lower()}]}

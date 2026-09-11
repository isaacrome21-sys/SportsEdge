from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Iterable

from .mlb_v7_travel_history import (
    MLBV7TravelHistoryError,
    parse_venue_reference,
    schedule_games,
)

SOURCE_CLASS = "VENUE_REFERENCE"
MODELED_GAME_TYPES = frozenset({"R", "F", "D", "L", "W"})
REQUIRED_FIELDS = ["venue_id", "latitude", "longitude", "timezone"]
REQUIRED_SEMANTICS = {"fixed_facts_only": True}


class MLBV7VenueReferenceError(RuntimeError):
    pass


def venue_ids_from_schedule_payloads(
    payloads: Iterable[Any], *, game_types: frozenset[str] = MODELED_GAME_TYPES
) -> list[int]:
    ids: set[int] = set()
    for payload in payloads:
        for game in schedule_games(payload):
            if game["status"] != "Final":
                continue
            if game["game_type"] not in game_types:
                continue
            venue_id = int(game["venue_id"])
            if venue_id <= 0:
                raise MLBV7VenueReferenceError("VENUE_ID_INVALID")
            ids.add(venue_id)
    if not ids:
        raise MLBV7VenueReferenceError("NO_FINAL_MODELED_GAMES_IN_COVERAGE")
    return sorted(ids)


def build_venue_reference_rows(
    venue_ids: Iterable[int],
    *,
    fetch_venue_payload: Callable[[int], Any],
    source_url_for_venue: Callable[[int], str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
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


def build_venue_reference_report(
    *,
    coverage_start: str,
    coverage_end: str,
    venue_ids: list[int],
    rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = sorted(set(int(v) for v in venue_ids))
    found = sorted(int(row["venue_id"]) for row in rows)
    missing = sorted(set(expected) - set(found))
    blockers: list[str] = []
    if failures or missing:
        blockers.append("VENUE_REFERENCE_INCOMPLETE")
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
    return {
        "source_class": SOURCE_CLASS,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "fields": REQUIRED_FIELDS,
        "semantics": REQUIRED_SEMANTICS,
        "evidence_files": [{"path": evidence_path, "sha256": evidence_sha256.lower()}],
    }

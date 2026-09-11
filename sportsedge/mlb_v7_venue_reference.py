from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Iterable

from .mlb_v7_travel_history import MLBV7TravelHistoryError, parse_venue_reference

SOURCE_CLASS = "VENUE_REFERENCE"
MODELED_GAME_TYPES = frozenset({"R", "F", "D", "L", "W"})
REQUIRED_FIELDS = ["venue_id", "latitude", "longitude", "timezone"]
REQUIRED_SEMANTICS = {"fixed_facts_only": True}
COORDINATE_FALLBACKS = {
    5340: {
        "provider": "WIKIDATA",
        "entity_id": "Q60830511",
        "expected_label": "Estadio Alfredo Harp Helú",
        "url": "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q60830511&props=labels%7Cclaims&languages=en&format=json",
    }
}


class MLBV7VenueReferenceError(RuntimeError):
    pass


def venue_ids_from_schedule_payloads(payloads: Iterable[Any], *, game_types: frozenset[str] = MODELED_GAME_TYPES) -> list[int]:
    ids: set[int] = set()
    seen: dict[int, tuple[int, int, int, str]] = {}
    for payload in payloads:
        if not isinstance(payload, dict): raise MLBV7VenueReferenceError("SCHEDULE_PAYLOAD_INVALID")
        for date_block in payload.get("dates") or []:
            if not isinstance(date_block, dict): raise MLBV7VenueReferenceError("SCHEDULE_DATE_BLOCK_INVALID")
            for game in date_block.get("games") or []:
                if not isinstance(game, dict): raise MLBV7VenueReferenceError("SCHEDULE_GAME_INVALID")
                try:
                    game_id = int(game["gamePk"]); venue_id = int((game.get("venue") or {})["id"])
                    teams = game.get("teams") or {}; away_id = int((((teams.get("away") or {}).get("team") or {})["id"])); home_id = int((((teams.get("home") or {}).get("team") or {})["id"]))
                except Exception as exc: raise MLBV7VenueReferenceError("SCHEDULE_GAME_IDENTITY_INCOMPLETE") from exc
                game_type = game.get("gameType")
                if not isinstance(game_type, str) or not game_type: raise MLBV7VenueReferenceError("GAME_TYPE_MISSING")
                if min(game_id, venue_id, away_id, home_id) <= 0: raise MLBV7VenueReferenceError("SCHEDULE_GAME_IDENTITY_INVALID")
                identity = (venue_id, away_id, home_id, game_type); previous = seen.get(game_id)
                if previous is not None and previous != identity: raise MLBV7VenueReferenceError(f"SCHEDULE_GAME_DUPLICATE_CONFLICT:{game_id}")
                seen[game_id] = identity
                if ((game.get("status") or {}).get("abstractGameState")) == "Final" and game_type in game_types: ids.add(venue_id)
    if not ids: raise MLBV7VenueReferenceError("NO_FINAL_MODELED_GAMES_IN_COVERAGE")
    return sorted(ids)


def _mlb_timezone(payload: Any, expected_venue_id: int) -> str:
    if not isinstance(payload, dict): raise MLBV7VenueReferenceError("VENUE_PAYLOAD_INVALID")
    venues = payload.get("venues")
    if not isinstance(venues, list) or len(venues) != 1 or not isinstance(venues[0], dict): raise MLBV7VenueReferenceError("VENUE_RESPONSE_NOT_SINGLETON")
    venue = venues[0]
    try: venue_id = int(venue["id"])
    except Exception as exc: raise MLBV7VenueReferenceError("VENUE_ID_MISSING") from exc
    if venue_id != int(expected_venue_id): raise MLBV7VenueReferenceError("VENUE_ID_MISMATCH")
    tz = venue.get("timeZone") or {}; tz_id = tz.get("id") if isinstance(tz, dict) else None
    if not isinstance(tz_id, str) or not tz_id or "/" not in tz_id: raise MLBV7VenueReferenceError("VENUE_TIMEZONE_MISSING")
    return tz_id


def parse_wikidata_coordinate(payload: Any, *, entity_id: str, expected_label: str) -> tuple[float, float]:
    if not isinstance(payload, dict): raise MLBV7VenueReferenceError("WIKIDATA_PAYLOAD_INVALID")
    entities = payload.get("entities")
    if not isinstance(entities, dict) or entity_id not in entities or not isinstance(entities[entity_id], dict): raise MLBV7VenueReferenceError("WIKIDATA_ENTITY_MISSING")
    entity = entities[entity_id]; labels = entity.get("labels") or {}; english = labels.get("en") if isinstance(labels, dict) else None; label = english.get("value") if isinstance(english, dict) else None
    if label != expected_label: raise MLBV7VenueReferenceError("WIKIDATA_ENTITY_LABEL_MISMATCH")
    claims = entity.get("claims") or {}; p625 = claims.get("P625") if isinstance(claims, dict) else None
    if not isinstance(p625, list) or not p625: raise MLBV7VenueReferenceError("WIKIDATA_COORDINATE_MISSING")
    candidates: list[tuple[float, float]] = []
    for statement in p625:
        if not isinstance(statement, dict) or statement.get("rank") == "deprecated": continue
        mainsnak = statement.get("mainsnak") or {}; datavalue = mainsnak.get("datavalue") if isinstance(mainsnak, dict) else None; value = datavalue.get("value") if isinstance(datavalue, dict) else None
        if not isinstance(value, dict): continue
        try: latitude, longitude = float(value["latitude"]), float(value["longitude"])
        except (KeyError, TypeError, ValueError): continue
        if -90 <= latitude <= 90 and -180 <= longitude <= 180: candidates.append((latitude, longitude))
    unique = sorted(set(candidates))
    if len(unique) != 1: raise MLBV7VenueReferenceError("WIKIDATA_COORDINATE_AMBIGUOUS" if unique else "WIKIDATA_COORDINATE_MISSING")
    return unique[0]


def build_venue_reference_rows(venue_ids: Iterable[int], *, fetch_venue_payload: Callable[[int], Any], source_url_for_venue: Callable[[int], str] | None = None, fetch_coordinate_fallback: Callable[[int, dict[str, str]], Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, failures = [], []
    for venue_id in sorted(set(int(v) for v in venue_ids)):
        payload = fetch_venue_payload(venue_id)
        try:
            parsed = parse_venue_reference(payload, venue_id); row = asdict(parsed); row["coordinate_source"] = "MLB_STATSAPI"; row["timezone_source"] = "MLB_STATSAPI"
        except MLBV7TravelHistoryError as exc:
            fallback = COORDINATE_FALLBACKS.get(venue_id)
            if str(exc) != "VENUE_COORDINATES_MISSING" or fallback is None or fetch_coordinate_fallback is None:
                failures.append({"venue_id": venue_id, "reason": str(exc)}); continue
            try:
                tz = _mlb_timezone(payload, venue_id); secondary = fetch_coordinate_fallback(venue_id, fallback)
                latitude, longitude = parse_wikidata_coordinate(secondary, entity_id=fallback["entity_id"], expected_label=fallback["expected_label"])
                row = {"venue_id": venue_id, "latitude": latitude, "longitude": longitude, "timezone": tz, "coordinate_source": f"WIKIDATA_{fallback['entity_id']}", "timezone_source": "MLB_STATSAPI"}
            except MLBV7VenueReferenceError as secondary_exc:
                failures.append({"venue_id": venue_id, "reason": str(secondary_exc)}); continue
        if source_url_for_venue is not None: row["source_url"] = source_url_for_venue(venue_id)
        rows.append(row)
    return rows, failures


def build_venue_reference_report(*, coverage_start: str, coverage_end: str, venue_ids: list[int], rows: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    expected = sorted(set(int(v) for v in venue_ids)); found = sorted(int(row["venue_id"]) for row in rows); missing = sorted(set(expected) - set(found)); blockers = ["VENUE_REFERENCE_INCOMPLETE"] if failures or missing else []
    fallback_rows = [row for row in rows if str(row.get("coordinate_source", "")).startswith("WIKIDATA_")]
    return {"contract": "SPORTSEDGE_MLB_V7_VENUE_REFERENCE_ACQUISITION_V1", "source_class": SOURCE_CLASS, "coverage_start": coverage_start, "coverage_end": coverage_end, "modeled_game_types": sorted(MODELED_GAME_TYPES), "discovered_venue_count": len(expected), "resolved_venue_count": len(found), "secondary_coordinate_source_count": len(fallback_rows), "secondary_coordinate_venue_ids": sorted(int(row["venue_id"]) for row in fallback_rows), "missing_venue_ids": missing, "failures": failures, "state": "READY_TO_ATTEST" if not blockers else "BLOCKED_SOURCE_ACQUISITION", "blockers": blockers, "promotion_authority": False, "candidate_training_allowed": False}


def build_attestation(*, coverage_start: str, coverage_end: str, evidence_files: list[dict[str, str]]) -> dict[str, Any]:
    if not evidence_files: raise MLBV7VenueReferenceError("EVIDENCE_FILES_REQUIRED")
    for item in evidence_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64: raise MLBV7VenueReferenceError("EVIDENCE_FILE_INVALID")
    return {"source_class": SOURCE_CLASS, "coverage_start": coverage_start, "coverage_end": coverage_end, "fields": REQUIRED_FIELDS, "semantics": REQUIRED_SEMANTICS, "evidence_files": evidence_files}

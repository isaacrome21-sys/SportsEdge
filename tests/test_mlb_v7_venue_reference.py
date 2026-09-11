from __future__ import annotations

import copy
import pytest

from sportsedge.mlb_v7_venue_reference import (
    COORDINATE_FALLBACKS,
    MLBV7VenueReferenceError,
    build_venue_reference_report,
    build_venue_reference_rows,
    parse_wikidata_coordinate,
    venue_ids_from_schedule_payloads,
)


def _schedule():
    return {
        "dates": [{
            "date": "2025-04-01",
            "games": [
                {
                    "gamePk": 1,
                    "gameDate": "2025-04-01T23:00:00Z",
                    "officialDate": "2025-04-01",
                    "gameType": "R",
                    "status": {"abstractGameState": "Final"},
                    "venue": {"id": 10},
                    "teams": {"away": {"team": {"id": 100}}, "home": {"team": {"id": 200}}},
                },
                {
                    "gamePk": 2,
                    "gameDate": "2025-04-01T18:00:00Z",
                    "officialDate": "2025-04-01",
                    "gameType": "S",
                    "status": {"abstractGameState": "Final"},
                    "venue": {"id": 99},
                    "teams": {"away": {"team": {"id": 100}}, "home": {"team": {"id": 200}}},
                },
            ],
        }]
    }


def _venue(venue_id: int, *, coordinates: bool = True):
    location = {"defaultCoordinates": {"latitude": 41.0, "longitude": -87.0}} if coordinates else {"city": "Mexico City", "country": "Mexico"}
    return {"venues": [{"id": venue_id, "location": location, "timeZone": {"id": "America/Chicago" if venue_id != 5340 else "America/Mexico_City"}}]}


def _wikidata(entity_id: str = "Q60830511", label: str = "Estadio Alfredo Harp Helú"):
    return {
        "entities": {
            entity_id: {
                "labels": {"en": {"language": "en", "value": label}},
                "claims": {
                    "P625": [{
                        "rank": "normal",
                        "mainsnak": {
                            "datavalue": {
                                "value": {
                                    "latitude": 19.400555555556,
                                    "longitude": -99.088888888889,
                                    "precision": 0.00027777777777778,
                                    "globe": "http://www.wikidata.org/entity/Q2",
                                }
                            }
                        },
                    }]
                },
            }
        }
    }


def test_discovers_only_final_modeled_game_venues() -> None:
    assert venue_ids_from_schedule_payloads([_schedule()]) == [10]


def test_exact_duplicate_game_row_is_tolerated() -> None:
    payload = _schedule()
    duplicate = copy.deepcopy(payload["dates"][0]["games"][0])
    payload["dates"].append({"date": "2025-04-02", "games": [duplicate]})
    assert venue_ids_from_schedule_payloads([payload]) == [10]


def test_conflicting_duplicate_game_row_fails_closed() -> None:
    payload = _schedule()
    duplicate = copy.deepcopy(payload["dates"][0]["games"][0])
    duplicate["venue"] = {"id": 11}
    payload["dates"].append({"date": "2025-04-02", "games": [duplicate]})
    with pytest.raises(MLBV7VenueReferenceError, match="SCHEDULE_GAME_DUPLICATE_CONFLICT"):
        venue_ids_from_schedule_payloads([payload])


def test_complete_fixed_facts_are_ready_to_attest() -> None:
    ids = venue_ids_from_schedule_payloads([_schedule()])
    rows, failures = build_venue_reference_rows(ids, fetch_venue_payload=_venue, source_url_for_venue=lambda v: f"https://example/{v}")
    report = build_venue_reference_report(coverage_start="2023-01-01", coverage_end="2025-12-31", venue_ids=ids, rows=rows, failures=failures)
    assert report["state"] == "READY_TO_ATTEST"
    assert report["blockers"] == []
    assert report["resolved_venue_count"] == 1
    assert report["secondary_coordinate_source_count"] == 0
    assert rows[0]["timezone"] == "America/Chicago"
    assert report["promotion_authority"] is False
    assert report["candidate_training_allowed"] is False


def test_venue_5340_uses_only_declared_wikidata_coordinate_fallback() -> None:
    fallback = COORDINATE_FALLBACKS[5340]
    rows, failures = build_venue_reference_rows(
        [5340],
        fetch_venue_payload=lambda _: _venue(5340, coordinates=False),
        fetch_coordinate_fallback=lambda venue_id, spec: _wikidata(spec["entity_id"]),
    )
    assert failures == []
    assert len(rows) == 1
    row = rows[0]
    assert row["coordinate_source"] == f"WIKIDATA_{fallback['entity_id']}"
    assert row["timezone_source"] == "MLB_STATSAPI"
    assert row["timezone"] == "America/Mexico_City"
    assert row["latitude"] == pytest.approx(19.400555555556)
    assert row["longitude"] == pytest.approx(-99.088888888889)
    report = build_venue_reference_report(coverage_start="2023-01-01", coverage_end="2025-12-31", venue_ids=[5340], rows=rows, failures=failures)
    assert report["state"] == "READY_TO_ATTEST"
    assert report["secondary_coordinate_source_count"] == 1
    assert report["secondary_coordinate_venue_ids"] == [5340]


def test_wrong_wikidata_entity_label_fails_closed() -> None:
    with pytest.raises(MLBV7VenueReferenceError, match="WIKIDATA_ENTITY_LABEL_MISMATCH"):
        parse_wikidata_coordinate(_wikidata(label="Wrong stadium"), entity_id="Q60830511", expected_label="Estadio Alfredo Harp Helú")


def test_missing_wikidata_coordinate_fails_closed() -> None:
    payload = _wikidata()
    payload["entities"]["Q60830511"]["claims"]["P625"] = []
    rows, failures = build_venue_reference_rows(
        [5340],
        fetch_venue_payload=lambda _: _venue(5340, coordinates=False),
        fetch_coordinate_fallback=lambda venue_id, spec: payload,
    )
    assert rows == []
    assert failures == [{"venue_id": 5340, "reason": "WIKIDATA_COORDINATE_MISSING"}]


def test_missing_timezone_fails_closed_even_if_coordinate_fallback_exists() -> None:
    bad = _venue(5340, coordinates=False)
    bad["venues"][0].pop("timeZone")
    rows, failures = build_venue_reference_rows(
        [5340],
        fetch_venue_payload=lambda _: bad,
        fetch_coordinate_fallback=lambda venue_id, spec: _wikidata(),
    )
    assert rows == []
    assert failures == [{"venue_id": 5340, "reason": "VENUE_TIMEZONE_MISSING"}]

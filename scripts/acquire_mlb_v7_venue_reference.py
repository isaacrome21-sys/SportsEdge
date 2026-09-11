#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime, timezone
import json
from pathlib import Path

from sportsedge.mlb_v7_travel_history import _get_json, schedule_url, venue_url, write_json, write_jsonl
from sportsedge.mlb_v7_venue_reference import (
    COORDINATE_FALLBACKS,
    REQUIRED_FIELDS,
    REQUIRED_SEMANTICS,
    SOURCE_CLASS,
    build_attestation,
    build_venue_reference_report,
    build_venue_reference_rows,
    venue_ids_from_schedule_payloads,
)


def _months(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        last = calendar.monthrange(cursor.year, cursor.month)[1]
        month_start = max(start, cursor)
        month_end = min(end, date(cursor.year, cursor.month, last))
        yield month_start, month_end
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire fixed MLB venue-reference facts with explicit source provenance.")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output-root", default="artifacts/mlb-v7-venue-reference")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start > end:
        raise SystemExit("VENUE_REFERENCE_COVERAGE_INVALID")

    root = Path(args.output_root)
    schedule_payloads = []
    schedule_sources = []
    for month_start, month_end in _months(start, end):
        url = schedule_url(month_start.isoformat(), month_end.isoformat())
        payload = _get_json(url)
        schedule_payloads.append(payload)
        rel = Path("raw") / "discovery" / f"schedule-{month_start:%Y-%m}.json"
        sha = write_json(root / rel, payload)
        schedule_sources.append({"url": url, "path": rel.as_posix(), "sha256": sha})

    venue_ids = venue_ids_from_schedule_payloads(schedule_payloads)
    venue_payloads: dict[int, object] = {}
    venue_sources = []
    for venue_id in venue_ids:
        url = venue_url(venue_id)
        payload = _get_json(url)
        venue_payloads[venue_id] = payload
        rel = Path("raw") / "discovery" / f"venue-{venue_id}.json"
        sha = write_json(root / rel, payload)
        venue_sources.append({"venue_id": venue_id, "provider": "MLB_STATSAPI", "url": url, "path": rel.as_posix(), "sha256": sha})

    fallback_payloads: dict[int, object] = {}
    fallback_sources = []

    def _fetch_fallback(venue_id: int, fallback: dict[str, str]):
        if venue_id in fallback_payloads:
            return fallback_payloads[venue_id]
        url = fallback["url"]
        payload = _get_json(url)
        fallback_payloads[venue_id] = payload
        rel = Path("raw") / "discovery" / f"venue-coordinate-fallback-{venue_id}-{fallback['entity_id']}.json"
        sha = write_json(root / rel, payload)
        fallback_sources.append({
            "venue_id": venue_id,
            "provider": fallback["provider"],
            "entity_id": fallback["entity_id"],
            "url": url,
            "path": rel.as_posix(),
            "sha256": sha,
        })
        return payload

    rows, failures = build_venue_reference_rows(
        venue_ids,
        fetch_venue_payload=lambda venue_id: venue_payloads[venue_id],
        source_url_for_venue=venue_url,
        fetch_coordinate_fallback=_fetch_fallback,
    )
    report = build_venue_reference_report(
        coverage_start=start.isoformat(),
        coverage_end=end.isoformat(),
        venue_ids=venue_ids,
        rows=rows,
        failures=failures,
    )
    report["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    report["schedule_sources"] = schedule_sources
    report["venue_sources"] = venue_sources
    report["fallback_sources"] = fallback_sources
    write_json(root / "acquisition_report.json", report)

    if report["state"] != "READY_TO_ATTEST":
        print(json.dumps(report, sort_keys=True))
        return 0

    evidence_rel = Path("raw") / "VENUE_REFERENCE.jsonl"
    evidence_sha = write_jsonl(root / evidence_rel, rows)
    provenance_rel = Path("raw") / "VENUE_REFERENCE_PROVENANCE.json"
    provenance_sha = write_json(root / provenance_rel, {
        "source_class": SOURCE_CLASS,
        "retrieved_at": report["retrieved_at"],
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "schedule_sources": schedule_sources,
        "venue_sources": venue_sources,
        "fallback_sources": fallback_sources,
        "fallback_policy": COORDINATE_FALLBACKS,
    })
    evidence_files = [
        {"path": evidence_rel.as_posix(), "sha256": evidence_sha},
        {"path": provenance_rel.as_posix(), "sha256": provenance_sha},
    ]
    for item in fallback_sources:
        evidence_files.append({"path": item["path"], "sha256": item["sha256"]})
    attestation = build_attestation(
        coverage_start=start.isoformat(),
        coverage_end=end.isoformat(),
        evidence_files=evidence_files,
    )
    write_json(root / "attestations" / "VENUE_REFERENCE.json", attestation)
    report["attestation_written"] = True
    report["evidence_sha256"] = evidence_sha
    report["provenance_sha256"] = provenance_sha
    report["attestation_evidence_file_count"] = len(evidence_files)
    write_json(root / "acquisition_report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

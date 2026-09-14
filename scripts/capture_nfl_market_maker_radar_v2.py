#!/usr/bin/env python3
"""Concurrent zero-authority NFL market-maker radar capture.

V2 keeps the V1 canonical binding/normalization contract but starts Pinnacle,
DraftKings, and FanDuel provider captures concurrently. Every provider records a
local request-start and retrieval timestamp. These timestamps describe transport
observation time only; they are never represented as the sportsbook's own quote
update time. When a source does not expose a trustworthy quote timestamp, quote
age remains explicitly UNKNOWN.

A capture may still be archived when timing hygiene fails. Such rows are marked
``leadership_timing_eligible=false`` so the analyzer can retain immutable raw
history without letting a slow/ambiguous poll manufacture lead-lag or stale-price
signals.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from scripts.capture_nfl_market_maker_radar import (
    SPORT_KEY,
    _authority,
    _capture_draftkings,
    _capture_fanduel,
    _capture_pinnacle,
    _iso,
    _parse_ts,
    _poll_id,
    bind_events,
    build_observation_rows,
)

UTC = timezone.utc
MAX_RETRIEVAL_SKEW_SECONDS = 30.0
PROVIDER_ORDER = ("pinnacle", "draftkings", "fanduel")
DEFAULT_PROVIDER_FUNCTIONS = {
    "pinnacle": _capture_pinnacle,
    "draftkings": _capture_draftkings,
    "fanduel": _capture_fanduel,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _run_provider(
    *,
    book: str,
    fn: Callable[..., Any],
    captured_at: datetime,
    out_root: Path,
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    started = clock().astimezone(UTC)
    try:
        events, refs, failures = fn(captured_at=captured_at, out_root=out_root)
        retrieved = clock().astimezone(UTC)
        return {
            "book": book,
            "state": "REACHABLE",
            "events": [dict(event) for event in events],
            "raw": refs,
            "failures": failures,
            "request_started_at": _iso(started),
            "retrieved_at": _iso(retrieved),
            "transport_duration_ms": int(round((retrieved - started).total_seconds() * 1000.0)),
        }
    except Exception as exc:
        retrieved = clock().astimezone(UTC)
        return {
            "book": book,
            "state": "BLOCKED",
            "events": [],
            "raw": [],
            "failures": [],
            "reason": str(exc),
            "request_started_at": _iso(started),
            "retrieved_at": _iso(retrieved),
            "transport_duration_ms": int(round((retrieved - started).total_seconds() * 1000.0)),
        }


def _timing_hygiene(provider_results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    reachable = [
        result for result in provider_results.values()
        if result.get("state") == "REACHABLE" and result.get("retrieved_at")
    ]
    if len(reachable) < 2:
        return {
            "state": "BLOCKED_INSUFFICIENT_REACHABLE_BOOKS",
            "max_cross_book_retrieval_skew_seconds": MAX_RETRIEVAL_SKEW_SECONDS,
            "observed_cross_book_retrieval_skew_seconds": None,
            "leadership_timing_eligible": False,
        }
    times = [_parse_ts(result["retrieved_at"]) for result in reachable]
    skew = (max(times) - min(times)).total_seconds()
    eligible = skew <= MAX_RETRIEVAL_SKEW_SECONDS
    return {
        "state": "PASS" if eligible else "BLOCKED_CROSS_BOOK_RETRIEVAL_SKEW",
        "max_cross_book_retrieval_skew_seconds": MAX_RETRIEVAL_SKEW_SECONDS,
        "observed_cross_book_retrieval_skew_seconds": round(skew, 6),
        "leadership_timing_eligible": eligible,
        "provider_quote_age_state": "UNKNOWN_UNLESS_SOURCE_EXPOSES_TRUSTWORTHY_TIMESTAMP",
    }


def _enrich_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    providers: Mapping[str, Mapping[str, Any]],
    timing_hygiene: Mapping[str, Any],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    eligible = bool(timing_hygiene.get("leadership_timing_eligible"))
    skew = timing_hygiene.get("observed_cross_book_retrieval_skew_seconds")
    for raw in rows:
        row = dict(raw)
        book = str(row.get("book") or "").lower()
        meta = providers.get(book) or {}
        row["provider_request_started_at"] = meta.get("request_started_at")
        row["provider_retrieved_at"] = meta.get("retrieved_at")
        row["transport_duration_ms"] = meta.get("transport_duration_ms")
        row["cross_book_retrieval_skew_seconds"] = skew
        row["leadership_timing_eligible"] = eligible
        row["provider_quote_timestamp_available"] = False
        row["provider_quote_age_seconds"] = None
        row["provider_quote_age_status"] = "UNKNOWN_PROVIDER_QUOTE_TIMESTAMP"
        row["timestamp_source"] = "CAPTURED_AT_SHARED_POLL_CLOCK"
        row["timing_hygiene_version"] = "RADAR_TIMING_HYGIENE_V2"
        enriched.append(row)
    return enriched


def capture(
    *,
    out_root: Path,
    now: datetime | None = None,
    provider_functions: Mapping[str, Callable[..., Any]] | None = None,
    clock: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    captured_dt = (now or clock()).astimezone(UTC)
    captured_at = _iso(captured_dt)
    functions = dict(provider_functions or DEFAULT_PROVIDER_FUNCTIONS)
    provider_results: dict[str, dict[str, Any]] = {}

    # Submit all transports before waiting on any one of them. This removes the
    # deterministic Pinnacle->DK->FD request-order artifact present in V1.
    with ThreadPoolExecutor(max_workers=len(PROVIDER_ORDER), thread_name_prefix="radar-book") as pool:
        futures = {
            pool.submit(
                _run_provider,
                book=book,
                fn=functions[book],
                captured_at=captured_dt,
                out_root=out_root,
                clock=clock,
            ): book
            for book in PROVIDER_ORDER
        }
        for future in as_completed(futures):
            result = future.result()
            provider_results[result["book"]] = result

    event_sets = {
        book: list((provider_results.get(book) or {}).get("events") or [])
        for book in PROVIDER_ORDER
    }
    raw_refs = [
        ref
        for book in PROVIDER_ORDER
        for ref in ((provider_results.get(book) or {}).get("raw") or [])
    ]
    poll_id = _poll_id(captured_at, raw_refs)
    bound, coverage = bind_events(
        pinnacle=event_sets["pinnacle"],
        draftkings=event_sets["draftkings"],
        fanduel=event_sets["fanduel"],
    ) if event_sets["pinnacle"] else ([], [])

    timing = _timing_hygiene(provider_results)
    base_rows = build_observation_rows(
        bound_events=bound,
        capture_id=poll_id,
        captured_at=captured_at,
    ) if bound else []
    rows = _enrich_rows(base_rows, providers=provider_results, timing_hygiene=timing)

    books_in_rows = {row["book"] for row in rows}
    if "pinnacle" not in books_in_rows or not ({"draftkings", "fanduel"} & books_in_rows):
        state = "BLOCKED"
    elif {"pinnacle", "draftkings", "fanduel"}.issubset(books_in_rows):
        state = "CAPTURED"
    else:
        state = "PARTIAL"

    rows_relative_path = None
    if rows:
        day = captured_dt.strftime("%Y/%m/%d")
        rel = Path("archive") / "market-maker-radar" / "nfl" / day / f"{poll_id}.ndjson"
        target = out_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError("NFL_RADAR_V2_APPEND_ONLY_COLLISION")
        target.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        rows_relative_path = str(rel)

    public_providers = {
        book: {
            key: value
            for key, value in result.items()
            if key not in {"book", "events"}
        } | {"event_count": len(result.get("events") or [])}
        for book, result in provider_results.items()
    }

    return {
        "contract": "NFL_DIRECT_MARKET_MAKER_RADAR_CAPTURE_V2",
        "state": state,
        "captured_at": captured_at,
        "capture_id": poll_id,
        "sport_key": SPORT_KEY,
        "poll_resolution_seconds": 300,
        "transport_mode": "CONCURRENT_PROVIDER_START",
        "leadership_rule": "NO_WITHIN_POLL_LEADER_WITHOUT_DISTINCT_TRUSTWORTHY_PROVIDER_QUOTE_TIMESTAMPS",
        "authority": _authority(),
        "providers": public_providers,
        "timing_hygiene": timing,
        "bound_event_count": len(bound),
        "coverage": coverage,
        "rows_written": len(rows),
        "rows_relative_path": rows_relative_path,
        "book_row_counts": {
            book: sum(1 for row in rows if row["book"] == book)
            for book in PROVIDER_ORDER
        },
        "provider_required_not_captured": ["circa"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--status-out", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)
    now = _parse_ts(args.now) if args.now else None
    report = capture(out_root=Path(args.out_root), now=now)
    target = Path(args.status_out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        key: report.get(key)
        for key in (
            "state",
            "capture_id",
            "bound_event_count",
            "rows_written",
            "book_row_counts",
            "timing_hygiene",
        )
    }, sort_keys=True))
    return 0 if report["state"] in {"CAPTURED", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

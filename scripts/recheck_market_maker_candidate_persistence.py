#!/usr/bin/env python3
"""Fixed-offset takeability proxies for stale soft-book radar candidates.

A captured stale price is not assumed takeable. For each newly-created candidate,
this script re-polls the same soft book at one policy-frozen offset and records
whether the exact contract still exists and what price is available then. The
workflow invokes it independently at every preregistered offset.

Persistence is only a takeability proxy; it is never represented as a fill.
Candidate records remain immutable. Persistence records are separate append-only
records on the data branch and have zero Model_P/Truth-Gate/staking authority.
"""
from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from scripts.analyze_market_maker_radar import american_implied_probability, load_policy
from scripts.capture_nfl_market_maker_radar import (
    _canonical_event_id,
    _capture_draftkings,
    _capture_fanduel,
    _designation_for_quote,
    _event_identity,
    _iso,
    _parse_ts,
)

UTC = timezone.utc
DEFAULT_POLICY = "config/market_maker_radar_v2.json"
SOFT_FETCHERS: dict[str, Callable[..., Any]] = {
    "draftkings": _capture_draftkings,
    "fanduel": _capture_fanduel,
}


class PersistenceError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _point_equal(a: Any, b: Any) -> bool:
    left, right = _number(a), _number(b)
    if left is None or right is None:
        return left is None and right is None
    return math.isclose(left, right, abs_tol=1e-9)


def _requested_offset(policy: Mapping[str, Any], override: float | None) -> float:
    value = float(policy["takeability"]["persistence_recheck_offset_seconds"] if override is None else override)
    allowed = {float(item) for item in policy["takeability"].get("persistence_recheck_offsets_seconds", [value])}
    if value not in allowed:
        raise PersistenceError(f"RADAR_PERSISTENCE_OFFSET_NOT_PREREGISTERED:{value}")
    return value


def _candidate_paths(report: Mapping[str, Any], root: Path) -> list[Path]:
    paths: list[Path] = []
    for item in report.get("candidate_ledger_new") or []:
        rel = str((item or {}).get("path") or "").strip()
        if rel:
            paths.append(root / rel)
    return paths


def _load_candidates(report_path: Path, root: Path) -> list[dict[str, Any]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for path in _candidate_paths(report, root):
        if not path.exists():
            raise PersistenceError(f"RADAR_PERSISTENCE_CANDIDATE_MISSING:{path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("record_type") != "MARKET_MAKER_RADAR_STALE_PRICE_CANDIDATE_V1":
            raise PersistenceError("RADAR_PERSISTENCE_CANDIDATE_TYPE_INVALID")
        out.append(payload)
    return out


def _event_id(event: Mapping[str, Any]) -> str:
    away, home, start = _event_identity(event)
    return _canonical_event_id(away, home, start)


def _canonical_outcome(book: str, quote: Mapping[str, Any], event: Mapping[str, Any]) -> str:
    away, home, _ = _event_identity(event)
    binding = {"away_team_id": away, "home_team_id": home}
    designation = _designation_for_quote(book, quote, binding)
    if designation == "home":
        return home
    if designation == "away":
        return away
    if designation == "over":
        return "Over"
    if designation == "under":
        return "Under"
    raise PersistenceError("RADAR_PERSISTENCE_DESIGNATION_INVALID")


def _quote_price(book: str, quote: Mapping[str, Any]) -> float | None:
    key = "american_price" if book == "fanduel" else "price_american"
    return _number(quote.get(key))


def classify_candidate(
    candidate: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    rechecked_at: datetime,
    request_started_at: datetime,
    retrieved_at: datetime,
    policy: Mapping[str, Any],
    requested_offset_seconds: float | None = None,
) -> dict[str, Any]:
    book = str(candidate.get("soft_book") or "").lower()
    if book not in SOFT_FETCHERS:
        raise PersistenceError(f"RADAR_PERSISTENCE_BOOK_UNSUPPORTED:{book}")
    created = _parse_ts(candidate.get("candidate_created_at"))
    requested_offset = _requested_offset(policy, requested_offset_seconds)
    tolerance = float(policy["takeability"]["persistence_recheck_tolerance_seconds"])
    actual_offset = (rechecked_at - created).total_seconds()
    within_tolerance = abs(actual_offset - requested_offset) <= tolerance

    base = {
        "record_type": "MARKET_MAKER_RADAR_CANDIDATE_PERSISTENCE_V1",
        "policy_version": policy.get("version"),
        "candidate_id": candidate.get("candidate_id"),
        "source_family_id": candidate.get("source_family_id"),
        "event_id": candidate.get("event_id"),
        "market": candidate.get("market"),
        "outcome": candidate.get("outcome"),
        "soft_book": book,
        "candidate_created_at": candidate.get("candidate_created_at"),
        "offered_price_american": candidate.get("offered_price_american"),
        "point": candidate.get("point"),
        "requested_offset_seconds": requested_offset,
        "actual_offset_seconds": round(actual_offset, 6),
        "offset_tolerance_seconds": tolerance,
        "within_offset_tolerance": within_tolerance,
        "recheck_requested_at": _iso(request_started_at),
        "rechecked_at": _iso(rechecked_at),
        "provider_retrieved_at": _iso(retrieved_at),
        "provider_quote_timestamp_available": False,
        "provider_quote_age_seconds": None,
        "provider_quote_age_status": "UNKNOWN_PROVIDER_QUOTE_TIMESTAMP",
        "takeability_proxy_only": True,
        "fill_proof": False,
        "model_p_authority": False,
        "truth_gate_input": False,
        "promotion_authority": False,
        "eligibility_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "automatic_wager_authority": False,
    }

    matching_events = [event for event in events if _event_id(event) == candidate.get("event_id")]
    if len(matching_events) != 1:
        return base | {
            "persistence_status": "EVENT_NOT_UNIQUELY_AVAILABLE_AT_RECHECK",
            "persisted_price_american": None,
            "persisted_exact_contract": False,
            "persisted_price_grade_eligible": False,
            "raw_sha256": None,
        }

    event = matching_events[0]
    market = str(candidate.get("market") or "").lower()
    outcome = str(candidate.get("outcome") or "")
    point = candidate.get("point")
    same_outcome: list[Mapping[str, Any]] = []
    exact: list[Mapping[str, Any]] = []
    for quote in event.get("quotes") or []:
        if not isinstance(quote, Mapping) or str(quote.get("market") or "").lower() != market:
            continue
        try:
            quote_outcome = _canonical_outcome(book, quote, event)
        except Exception:
            continue
        if quote_outcome != outcome:
            continue
        same_outcome.append(quote)
        if _point_equal(quote.get("point"), point):
            exact.append(quote)

    if len(exact) != 1:
        return base | {
            "persistence_status": "EXACT_CONTRACT_NOT_AVAILABLE_AT_RECHECK" if same_outcome else "OUTCOME_NOT_AVAILABLE_AT_RECHECK",
            "persisted_price_american": None,
            "persisted_exact_contract": False,
            "persisted_price_grade_eligible": False,
            "raw_sha256": event.get("raw_sha256"),
        }

    persisted_price = _quote_price(book, exact[0])
    offered_price = _number(candidate.get("offered_price_american"))
    if persisted_price is None or offered_price is None:
        status = "EXACT_CONTRACT_PRICE_INVALID_AT_RECHECK"
        grade_eligible = False
    elif math.isclose(persisted_price, offered_price, abs_tol=1e-9):
        status = "PERSISTED_EXACT_PRICE"
        grade_eligible = within_tolerance
    else:
        offered_be = american_implied_probability(offered_price)
        persisted_be = american_implied_probability(persisted_price)
        status = "PERSISTED_BETTER_PRICE" if persisted_be < offered_be else "MOVED_WORSE_PRICE"
        grade_eligible = within_tolerance

    return base | {
        "persistence_status": status,
        "persisted_price_american": persisted_price,
        "persisted_exact_contract": persisted_price is not None,
        "persisted_price_grade_eligible": grade_eligible,
        "raw_sha256": event.get("raw_sha256"),
    }


def _persistence_path(root: Path, record: Mapping[str, Any]) -> Path:
    offset = float(record["requested_offset_seconds"])
    label = str(int(offset)) if offset.is_integer() else str(offset).replace(".", "p")
    return (
        root
        / "archive"
        / "market-maker-radar"
        / "candidate-persistence"
        / str(record["source_family_id"])
        / f"{record['candidate_id']}__offset_{label}s.json"
    )


def _persist(root: Path, record: Mapping[str, Any]) -> bool:
    target = _persistence_path(root, record)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return False
    target.write_text(json.dumps(dict(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def recheck(
    *,
    candidates: Sequence[Mapping[str, Any]],
    out_root: Path,
    policy: Mapping[str, Any],
    now: datetime | None = None,
    fetchers: Mapping[str, Callable[..., Any]] | None = None,
    requested_offset_seconds: float | None = None,
) -> dict[str, Any]:
    requested = _requested_offset(policy, requested_offset_seconds)
    if not candidates:
        return {
            "state": "NO_NEW_CANDIDATES",
            "candidate_count": 0,
            "new_persistence_count": 0,
            "existing_persistence_count": 0,
            "requested_offset_seconds": requested,
            "records": [],
            "primary_metric": policy["grading"]["primary_metric"],
            "clv_role": policy["grading"]["clv_role"],
        }

    rechecked_at = (now or datetime.now(UTC)).astimezone(UTC)
    wanted_books = sorted({str(c.get("soft_book") or "").lower() for c in candidates})
    active_fetchers = dict(fetchers or SOFT_FETCHERS)
    results: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, len(wanted_books)), thread_name_prefix="radar-persist") as pool:
        future_map = {}
        for book in wanted_books:
            if book not in active_fetchers:
                raise PersistenceError(f"RADAR_PERSISTENCE_BOOK_UNSUPPORTED:{book}")
            started = datetime.now(UTC)
            future = pool.submit(active_fetchers[book], captured_at=rechecked_at, out_root=out_root)
            future_map[future] = (book, started)
        for future in as_completed(future_map):
            book, started = future_map[future]
            retrieved = datetime.now(UTC)
            try:
                events, refs, failures = future.result()
                results[book] = {
                    "state": "REACHABLE",
                    "events": events,
                    "raw": refs,
                    "failures": failures,
                    "request_started_at": started,
                    "retrieved_at": retrieved,
                }
            except Exception as exc:
                results[book] = {
                    "state": "BLOCKED",
                    "events": [],
                    "raw": [],
                    "failures": [],
                    "reason": str(exc),
                    "request_started_at": started,
                    "retrieved_at": retrieved,
                }

    records: list[dict[str, Any]] = []
    new_count = 0
    existing_count = 0
    for candidate in candidates:
        book = str(candidate.get("soft_book") or "").lower()
        result = results.get(book) or {}
        if result.get("state") == "REACHABLE":
            record = classify_candidate(
                candidate,
                result.get("events") or [],
                rechecked_at=rechecked_at,
                request_started_at=result["request_started_at"],
                retrieved_at=result["retrieved_at"],
                policy=policy,
                requested_offset_seconds=requested,
            )
        else:
            created = _parse_ts(candidate.get("candidate_created_at"))
            tolerance = float(policy["takeability"]["persistence_recheck_tolerance_seconds"])
            actual = (rechecked_at - created).total_seconds()
            record = {
                "record_type": "MARKET_MAKER_RADAR_CANDIDATE_PERSISTENCE_V1",
                "policy_version": policy.get("version"),
                "candidate_id": candidate.get("candidate_id"),
                "source_family_id": candidate.get("source_family_id"),
                "event_id": candidate.get("event_id"),
                "market": candidate.get("market"),
                "outcome": candidate.get("outcome"),
                "soft_book": book,
                "candidate_created_at": candidate.get("candidate_created_at"),
                "offered_price_american": candidate.get("offered_price_american"),
                "point": candidate.get("point"),
                "requested_offset_seconds": requested,
                "actual_offset_seconds": round(actual, 6),
                "offset_tolerance_seconds": tolerance,
                "within_offset_tolerance": abs(actual - requested) <= tolerance,
                "rechecked_at": _iso(rechecked_at),
                "persistence_status": "BOOK_RECHECK_BLOCKED",
                "persisted_price_american": None,
                "persisted_exact_contract": False,
                "persisted_price_grade_eligible": False,
                "takeability_proxy_only": True,
                "fill_proof": False,
                "provider_error": result.get("reason"),
                "model_p_authority": False,
                "truth_gate_input": False,
                "promotion_authority": False,
                "eligibility_authority": False,
                "staking_authority": False,
                "official_authority": False,
                "automatic_wager_authority": False,
            }
        created_new = _persist(out_root, record)
        if created_new:
            new_count += 1
        else:
            existing_count += 1
        records.append(record)

    return {
        "state": "COMPLETE",
        "candidate_count": len(candidates),
        "new_persistence_count": new_count,
        "existing_persistence_count": existing_count,
        "requested_offset_seconds": requested,
        "records": records,
        "primary_metric": policy["grading"]["primary_metric"],
        "research_only_primary_metric_when_no_fills": policy["grading"]["research_only_primary_metric_when_no_fills"],
        "clv_role": policy["grading"]["clv_role"],
        "offered_price_roi_role": policy["grading"]["offered_price_roi_role"],
        "automatic_wager_authority": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--analysis-report", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--status-out", required=True)
    parser.add_argument("--offset-seconds", type=float, default=None)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    root = Path(args.out_root)
    candidates = _load_candidates(Path(args.analysis_report), root)
    now = _parse_ts(args.now) if args.now else None
    report = recheck(
        candidates=candidates,
        out_root=root,
        policy=policy,
        now=now,
        requested_offset_seconds=args.offset_seconds,
    )
    target = Path(args.status_out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Settle immutable stale-price research candidates against Pinnacle close.

Settlement is CLV-first and fail-closed. A candidate is compared only with the
last timing-eligible Pinnacle snapshot before kickoff for the exact same market
contract. H2H requires the same outcome pair. Spreads/totals additionally require
that the candidate point still exists at close; a moved line is not converted
into a fake probability comparison.

Candidate files are never rewritten. Settlement files are separate immutable
records. Result/ROI settlement is intentionally left null here; this script only
answers whether the offered soft-book price beat the exact-contract Pinnacle
closing fair probability.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.analyze_market_maker_radar import (
    RadarError,
    _iso,
    _parse_ts,
    american_implied_probability,
    load_policy,
)

UTC = timezone.utc
DEFAULT_POLICY = "config/market_maker_radar_v2.json"


class CandidateSettlementError(RuntimeError):
    pass


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _point_equal(a: Any, b: Any) -> bool:
    left, right = _num(a), _num(b)
    if left is None or right is None:
        return left is None and right is None
    return math.isclose(left, right, abs_tol=1e-9)


def _load_candidates(ledger_root: Path) -> list[dict[str, Any]]:
    base = ledger_root / "archive" / "market-maker-radar" / "candidate-ledger"
    out: list[dict[str, Any]] = []
    if not base.exists():
        return out
    for path in sorted(base.glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("record_type") == "MARKET_MAKER_RADAR_STALE_PRICE_CANDIDATE_V1":
            out.append(payload)
    return out


def _load_radar_rows(archive_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(archive_root.rglob("*.ndjson")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def _timing_eligible(row: Mapping[str, Any], max_skew: float) -> bool:
    if row.get("timing_hygiene_version") != "RADAR_TIMING_HYGIENE_V2":
        return False
    if row.get("leadership_timing_eligible") is not True:
        return False
    if not row.get("provider_retrieved_at"):
        return False
    skew = _num(row.get("cross_book_retrieval_skew_seconds"))
    return skew is not None and skew <= max_skew


def _contract_pair(
    rows: Sequence[Mapping[str, Any]], candidate: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if len(rows) != 2:
        return None
    outcome = str(candidate.get("outcome") or "")
    by_outcome = {str(row.get("outcome") or ""): dict(row) for row in rows}
    if len(by_outcome) != 2 or outcome not in by_outcome:
        return None
    selected = by_outcome[outcome]
    other = next(row for key, row in by_outcome.items() if key != outcome)
    market = str(candidate.get("market") or "").lower()
    point = candidate.get("point")
    if market == "h2h":
        if point is not None or selected.get("point") is not None or other.get("point") is not None:
            return None
    elif market == "spreads":
        if not _point_equal(selected.get("point"), point):
            return None
        selected_point = _num(selected.get("point"))
        other_point = _num(other.get("point"))
        if selected_point is None or other_point is None or not math.isclose(selected_point + other_point, 0.0, abs_tol=1e-9):
            return None
    elif market == "totals":
        if not _point_equal(selected.get("point"), point) or not _point_equal(other.get("point"), point):
            return None
    else:
        return None
    return selected, other


def _fair_probability(selected: Mapping[str, Any], other: Mapping[str, Any]) -> float:
    a = american_implied_probability(selected.get("price_american"))
    b = american_implied_probability(other.get("price_american"))
    denom = a + b
    if denom <= 0:
        raise CandidateSettlementError("RADAR_CANDIDATE_CLOSE_DEVIG_INVALID")
    return a / denom


def _event_commence(rows: Sequence[Mapping[str, Any]], event_id: str) -> datetime | None:
    values: set[str] = {
        str(row.get("commence_time") or "")
        for row in rows
        if str(row.get("event_id") or "") == event_id and row.get("commence_time")
    }
    if not values:
        return None
    parsed = {_parse_ts(value) for value in values}
    if len(parsed) != 1:
        raise CandidateSettlementError(f"RADAR_CANDIDATE_COMMENCE_AMBIGUOUS:{event_id}")
    return next(iter(parsed))


def settle_candidate(
    candidate: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any] | None:
    event_id = str(candidate.get("event_id") or "")
    commence = _event_commence(rows, event_id)
    if commence is None or now < commence:
        return None

    max_skew = float(policy["timing"]["max_cross_book_retrieval_skew_seconds"])
    max_close_age = float(policy["grading"]["candidate_ledger"].get("clv_close_max_age_seconds", 900))
    market = str(candidate.get("market") or "").lower()
    pinnacle_rows = [
        dict(row) for row in rows
        if str(row.get("event_id") or "") == event_id
        and str(row.get("book") or "").lower() == "pinnacle"
        and str(row.get("market") or "").lower() == market
        and _timing_eligible(row, max_skew)
        and _parse_ts(row.get("captured_at")) < commence
    ]
    by_capture: dict[str, list[dict[str, Any]]] = defaultdict(list)
    capture_times: dict[str, datetime] = {}
    for row in pinnacle_rows:
        cid = str(row.get("capture_id") or "")
        if not cid:
            continue
        by_capture[cid].append(row)
        capture_times[cid] = _parse_ts(row.get("captured_at"))

    exact: list[tuple[datetime, str, dict[str, Any], dict[str, Any]]] = []
    for cid, group in by_capture.items():
        pair = _contract_pair(group, candidate)
        if pair is None:
            continue
        exact.append((capture_times[cid], cid, pair[0], pair[1]))
    exact.sort(key=lambda item: item[0])

    base = {
        "record_type": "MARKET_MAKER_RADAR_CANDIDATE_CLV_SETTLEMENT_V1",
        "candidate_id": candidate["candidate_id"],
        "source_family_id": candidate["source_family_id"],
        "event_id": event_id,
        "market": market,
        "outcome": candidate.get("outcome"),
        "soft_book": candidate.get("soft_book"),
        "flat_stake_units": candidate.get("flat_stake_units"),
        "settled_at": _iso(now),
        "model_p_authority": False,
        "truth_gate_input": False,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "automatic_wager_authority": False,
        "result": None,
        "flat_1u_profit": None,
        "flat_1u_roi": None,
    }

    if not exact:
        return base | {
            "grading_status": "UNGRADABLE_NO_EXACT_CONTRACT_CLOSE",
            "clv": None,
            "closing_capture_id": None,
            "closing_captured_at": None,
            "validation_status": "INSUFFICIENT",
        }

    close_time, close_id, selected, other = exact[-1]
    close_age = (commence - close_time).total_seconds()
    if close_age > max_close_age:
        return base | {
            "grading_status": "UNGRADABLE_CLOSE_TOO_OLD",
            "clv": None,
            "closing_capture_id": close_id,
            "closing_captured_at": _iso(close_time),
            "closing_age_seconds": int(close_age),
            "validation_status": "INSUFFICIENT",
        }

    close_fair = _fair_probability(selected, other)
    offered_break_even = american_implied_probability(candidate.get("offered_price_american"))
    clv_pp = (close_fair - offered_break_even) * 100.0
    reference_fair = _num(candidate.get("reference_pinnacle_fair_probability"))
    reference_move_pp = None if reference_fair is None else (close_fair - reference_fair) * 100.0
    return base | {
        "grading_status": "SETTLED_CLV",
        "closing_capture_id": close_id,
        "closing_captured_at": _iso(close_time),
        "closing_age_seconds": int(close_age),
        "closing_pinnacle_fair_probability": round(close_fair, 8),
        "candidate_soft_break_even_probability": round(offered_break_even, 8),
        "clv": round(clv_pp, 8),
        "beat_close": clv_pp > 0,
        "reference_probability_move_pp": None if reference_move_pp is None else round(reference_move_pp, 8),
        "validation_status": "INSUFFICIENT",
    }


def _settlement_path(root: Path, settlement: Mapping[str, Any]) -> Path:
    return (
        root
        / "archive"
        / "market-maker-radar"
        / "candidate-settlements"
        / str(settlement["source_family_id"])
        / f"{settlement['candidate_id']}.json"
    )


def _persist_settlement(root: Path, settlement: Mapping[str, Any]) -> bool:
    target = _settlement_path(root, settlement)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return False
    target.write_text(json.dumps(dict(settlement), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def summarize(ledger_root: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    candidates = _load_candidates(ledger_root)
    candidate_counts: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        candidate_counts[str(candidate["source_family_id"])] += 1

    settlement_base = ledger_root / "archive" / "market-maker-radar" / "candidate-settlements"
    settlements: list[dict[str, Any]] = []
    if settlement_base.exists():
        for path in sorted(settlement_base.glob("*/*.json")):
            settlements.append(json.loads(path.read_text(encoding="utf-8")))
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for settlement in settlements:
        by_family[str(settlement["source_family_id"])].append(settlement)

    minimum_n = int(policy["grading"]["minimum_n_for_claim"])
    out: dict[str, Any] = {}
    for family in sorted(set(candidate_counts) | set(by_family)):
        family_settlements = by_family.get(family, [])
        clv_values = [float(s["clv"]) for s in family_settlements if s.get("grading_status") == "SETTLED_CLV" and s.get("clv") is not None]
        settled_n = len(clv_values)
        out[family] = {
            "candidate_n": candidate_counts.get(family, 0),
            "clv_settled_n": settled_n,
            "ungradable_n": sum(1 for s in family_settlements if str(s.get("grading_status") or "").startswith("UNGRADABLE_")),
            "validation_status": "INSUFFICIENT" if settled_n < minimum_n else "CLV_SAMPLE_SUFFICIENT_RESULT_ROI_PENDING",
            "mean_clv_pp": round(statistics.fmean(clv_values), 8) if clv_values else None,
            "median_clv_pp": round(statistics.median(clv_values), 8) if clv_values else None,
            "positive_clv_rate": round(sum(1 for value in clv_values if value > 0) / settled_n, 8) if settled_n else None,
            "hit_rate": None,
            "flat_1u_roi": None,
        }
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--ledger-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    now = _parse_ts(args.now) if args.now else datetime.now(UTC)
    archive_root = Path(args.archive_root)
    ledger_root = Path(args.ledger_root)
    candidates = _load_candidates(ledger_root)
    rows = _load_radar_rows(archive_root)

    new = 0
    existing = 0
    pending = 0
    for candidate in candidates:
        settlement = settle_candidate(candidate, rows, policy, now=now)
        if settlement is None:
            pending += 1
            continue
        if _persist_settlement(ledger_root, settlement):
            new += 1
        else:
            existing += 1

    report = {
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "ran_at": _iso(now),
        "candidate_count": len(candidates),
        "new_settlement_count": new,
        "existing_settlement_count": existing,
        "pending_candidate_count": pending,
        "source_family_summary": summarize(ledger_root, policy),
        "primary_metric": "CLV",
        "result_roi_status": "PENDING_SEPARATE_RESULT_SETTLEMENT",
        "model_p_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False,
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

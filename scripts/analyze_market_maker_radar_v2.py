#!/usr/bin/env python3
"""Timing-hardened market-maker radar analyzer and immutable candidate ledger.

Only V2 rows carrying explicit provider retrieval provenance and passing the
frozen cross-book retrieval-skew gate can create movement, lead/lag, stale-price,
or steam signals. Raw observations remain archived even when timing-ineligible.

STALE_SOFT_PRICE is a model-free research candidate, not Model_P and not an
automatic bet. The first qualifying observation for each event/market/outcome/
soft-book contract gets one immutable candidate record. A captured offer is not
assumed takeable; fixed-offset persistence and any real execution are separate
append-only records. CLV is a detector/process check, not the primary edge
validation metric for this lane.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.analyze_market_maker_radar import (
    _candidate_files,
    _iso,
    _parse_ts,
    analyze as analyze_v1,
    load_policy,
    read_ndjson,
)

UTC = timezone.utc
DEFAULT_POLICY = "config/market_maker_radar_v2.json"


class RadarV2Error(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def timing_eligible_rows(
    rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    max_skew = float(policy["timing"]["max_cross_book_retrieval_skew_seconds"])
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        skew = _number(row.get("cross_book_retrieval_skew_seconds"))
        reasons: list[str] = []
        if row.get("timing_hygiene_version") != "RADAR_TIMING_HYGIENE_V2":
            reasons.append("MISSING_V2_TIMING_HYGIENE")
        if not row.get("provider_request_started_at"):
            reasons.append("MISSING_PROVIDER_REQUEST_START")
        if not row.get("provider_retrieved_at"):
            reasons.append("MISSING_PROVIDER_RETRIEVED_AT")
        if row.get("leadership_timing_eligible") is not True:
            reasons.append("CAPTURE_TIMING_INELIGIBLE")
        if skew is None:
            reasons.append("MISSING_CROSS_BOOK_RETRIEVAL_SKEW")
        elif skew > max_skew:
            reasons.append("CROSS_BOOK_RETRIEVAL_SKEW_EXCEEDED")
        if reasons:
            excluded.append({
                "capture_id": row.get("capture_id"),
                "event_id": row.get("event_id"),
                "book": row.get("book"),
                "market": row.get("market"),
                "outcome": row.get("outcome"),
                "reasons": reasons,
            })
        else:
            eligible.append(row)
    return eligible, excluded


def _stale_family(signal: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    soft = str(signal.get("soft_book") or "").lower()
    market = str(signal.get("market") or "").lower()
    mapping = policy["grading"].get("stale_soft_price_source_family_ids") or {}
    family = ((mapping.get(soft) or {}).get(market))
    if not family:
        raise RadarV2Error(f"RADAR_V2_STALE_SOURCE_FAMILY_UNMAPPED:{soft}:{market}")
    return str(family)


def _candidate_id(signal: Mapping[str, Any], source_family_id: str) -> str:
    material = {
        "source_family_id": source_family_id,
        "event_id": signal.get("event_id"),
        "market": signal.get("market"),
        "outcome": signal.get("outcome"),
        "soft_book": signal.get("soft_book"),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _independence_fields(policy: Mapping[str, Any]) -> dict[str, Any]:
    contract = policy.get("run_it_independence") or {}
    group = str(contract.get("independence_group_id") or "")
    if not group or contract.get("counts_as_independent_context_class") is not False:
        raise RadarV2Error("RADAR_V2_RUN_IT_INDEPENDENCE_CONTRACT_INVALID")
    return {
        "run_it_independence_group_id": group,
        "counts_as_independent_context_class": False,
    }


def candidate_record(signal: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    family = _stale_family(signal, policy)
    candidate_id = _candidate_id(signal, family)
    return {
        "record_type": "MARKET_MAKER_RADAR_STALE_PRICE_CANDIDATE_V1",
        "candidate_id": candidate_id,
        "source_family_id": family,
        "signal_class": "STALE_SOFT_PRICE",
        "evidence_class": policy["evidence_class"],
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "capture_id": signal.get("capture_id"),
        "candidate_created_at": signal.get("captured_at"),
        "sport_key": signal.get("sport_key"),
        "event_id": signal.get("event_id"),
        "market": signal.get("market"),
        "outcome": signal.get("outcome"),
        "market_maker_book": signal.get("market_maker_book"),
        "soft_book": signal.get("soft_book"),
        "point": signal.get("point"),
        "offered_price_american": signal.get("soft_price_american"),
        "offered_price_takeable_assumed": False,
        "takeability_status": "PENDING_FIXED_OFFSET_RECHECK",
        "execution_status": "NO_EXECUTION_RECORD",
        "reference_pinnacle_price_american": signal.get("pinnacle_price_american"),
        "reference_pinnacle_fair_probability": signal.get("pinnacle_fair_probability"),
        "fair_probability_gap_pp": signal.get("fair_probability_gap_pp"),
        "flat_stake_units": float(policy["grading"]["candidate_ledger"]["flat_stake_units"]),
        "grading_status": policy["grading"]["candidate_ledger"]["unsettled_status"],
        "close_reference": None,
        "clv": None,
        "result": None,
        "flat_1u_profit": None,
        "validation_status": policy["grading"]["candidate_ledger"]["validation_status_before_100"],
        "model_p_authority": False,
        "truth_gate_input": False,
        "promotion_authority": False,
        "eligibility_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "automatic_wager_authority": False,
        "manual_candidate_review_eligible": True,
        **_independence_fields(policy),
    }


def _persist_candidate(root: Path, record: Mapping[str, Any]) -> tuple[Path, bool]:
    family = str(record["source_family_id"])
    candidate_id = str(record["candidate_id"])
    rel = Path("archive") / "market-maker-radar" / "candidate-ledger" / family / f"{candidate_id}.json"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(record), indent=2, sort_keys=True) + "\n"
    if target.exists():
        return rel, False
    target.write_text(payload, encoding="utf-8")
    return rel, True


def _next_checkpoint(n: int, checkpoints: Sequence[int]) -> int | None:
    for checkpoint in checkpoints:
        if n < int(checkpoint):
            return int(checkpoint)
    return None


def _ledger_summary(root: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    base = root / "archive" / "market-maker-radar" / "candidate-ledger"
    counts: dict[str, int] = defaultdict(int)
    if base.exists():
        for path in base.glob("*/*.json"):
            counts[path.parent.name] += 1
    minimum_n = int(policy["grading"]["minimum_n_for_claim"])
    checkpoints = [int(v) for v in policy["grading"]["evaluation_checkpoints"]["candidate_n"]]
    out: dict[str, Any] = {}
    for family, n in sorted(counts.items()):
        out[family] = {
            "candidate_n": n,
            "settled_n": 0,
            "validation_status": (
                policy["grading"]["status_before_minimum_n"]
                if n < minimum_n
                else "FORMAL_EVALUATION_ONLY_AT_FROZEN_CHECKPOINTS"
            ),
            "next_candidate_checkpoint": _next_checkpoint(n, checkpoints),
            "formal_checkpoint_now": n in checkpoints,
            "clv": None,
            "hit_rate": None,
            "offered_price_flat_1u_roi": None,
            "persisted_price_flat_1u_roi": None,
            "realized_filled_roi": None,
        }
    return out


def _stamp_report_independence(report: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(report)
    fields = _independence_fields(policy)
    for key in ("lead_lag_signals", "stale_soft_prices", "line_advantage_candidates", "steam_clusters"):
        stamped = []
        for raw in output.get(key) or []:
            row = dict(raw)
            row.update(fields)
            stamped.append(row)
        output[key] = stamped
    output["run_it_independence"] = dict(policy["run_it_independence"])
    return output


def analyze(
    rows: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    *,
    ledger_root: Path | None = None,
) -> dict[str, Any]:
    eligible, excluded = timing_eligible_rows(rows, policy)
    report = _stamp_report_independence(analyze_v1(eligible, policy), policy)

    stale = report.get("stale_soft_prices") or []
    for signal in stale:
        signal["source_family_id"] = _stale_family(signal, policy)
        signal["manual_candidate_review_eligible"] = True
        signal["automatic_wager_authority"] = False
        signal["offered_price_takeable_assumed"] = False
        signal["takeability_status"] = "PENDING_FIXED_OFFSET_RECHECK"

    new_records: list[dict[str, Any]] = []
    existing_records: list[dict[str, Any]] = []
    if ledger_root is not None:
        ordered = sorted(stale, key=lambda s: (str(s.get("captured_at") or ""), str(s.get("signal_id") or "")))
        for signal in ordered:
            record = candidate_record(signal, policy)
            rel, created = _persist_candidate(ledger_root, record)
            item = {"candidate_id": record["candidate_id"], "source_family_id": record["source_family_id"], "path": str(rel)}
            (new_records if created else existing_records).append(item)

    grading = policy["grading"]
    report.update({
        "policy_version": policy["version"],
        "threshold_freeze": policy["threshold_freeze"],
        "archive_rows_loaded_total": len(rows),
        "timing_eligible_row_count": len(eligible),
        "timing_excluded_row_count": len(excluded),
        "timing_exclusion_sample": excluded[:25],
        "max_cross_book_retrieval_skew_seconds": policy["timing"]["max_cross_book_retrieval_skew_seconds"],
        "candidate_ledger_new_count": len(new_records),
        "candidate_ledger_existing_count": len(existing_records),
        "candidate_ledger_new": new_records,
        "candidate_ledger_existing": existing_records,
        "automatic_wager_authority": False,
        "manual_candidate_review_authority": True,
        "primary_metric": grading["primary_metric"],
        "research_only_primary_metric_when_no_fills": grading["research_only_primary_metric_when_no_fills"],
        "process_metric": grading["process_metric"],
        "clv_role": grading["clv_role"],
        "offered_price_roi_role": grading["offered_price_roi_role"],
        "evaluation_checkpoints": grading["evaluation_checkpoints"],
    })
    if ledger_root is not None:
        report["candidate_ledger_summary"] = _ledger_summary(ledger_root, policy)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--input-root", default=None)
    parser.add_argument("--ledger-out-root", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--since-hours", type=float, default=24.0)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    now = _parse_ts(args.now) if args.now else datetime.now(UTC)
    cutoff = None if args.since_hours < 0 else now - timedelta(hours=args.since_hours)
    paths = [Path(item) for item in args.input]
    if args.input_root:
        paths.extend(_candidate_files(Path(args.input_root), cutoff))
    unique_paths = sorted({path.resolve() for path in paths})
    rows = read_ndjson(unique_paths, cutoff=cutoff)
    ledger_root = Path(args.ledger_out_root) if args.ledger_out_root else None
    report = analyze(rows, policy, ledger_root=ledger_root)
    report["ran_at"] = _iso(now)
    report["cutoff"] = _iso(cutoff) if cutoff is not None else None
    report["input_files"] = [str(path) for path in unique_paths]

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pre-replay source-feasibility guard for MLB_REPLAY_POLICY_V1.

This does not run the replay, grade CLV, inspect model performance, or start an
evidence clock.  It verifies that the frozen V1 benchmark contract is still the
one being tested and refuses to invent Pinnacle coverage rates when the
historical Tier-A/Pinnacle archive is absent.

A later pair-coverage measurement must operate on the retained historical raw
quotes (or a lossless normalized derivative) and use the frozen 180-second
quote-age and 30-second paired-side skew limits.  A generic replay-readiness
PASS is not a substitute for that measurement.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any

DEFAULT_POLICY = Path("config/mlb_replay_policy_v1.json")
DEFAULT_GAP_REPORT = Path("evidence/mlb_v8_replay_archive/gap_report.json")
DEFAULT_PINNACLE_ARCHIVE = Path("evidence/mlb_v8_replay_sources/ODDSPAPI_HISTORICAL")
DEFAULT_OUT = Path("artifacts/mlb_replay_v1_pinnacle_preflight.json")

EXPECTED_POLICY_ID = "MLB_REPLAY_POLICY_V1"
EXPECTED_MAX_AGE_SECONDS = 180
EXPECTED_PAIR_SKEW_SECONDS = 30
EXPECTED_FIRST_CORE_BOOK = "pinnacle"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def _window_rows(rows: list[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    lo = date.fromisoformat(start)
    hi = date.fromisoformat(end)
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("date")))
        except Exception:
            continue
        if lo <= day <= hi:
            out.append(row)
    return out


def audit(policy_path: Path, gap_report_path: Path, pinnacle_archive: Path) -> tuple[dict[str, Any], int]:
    policy = _load_json(policy_path)
    benchmark = policy.get("benchmark") or {}
    featured = ((benchmark.get("market_tiers") or {}).get("FEATURED_CORE") or {})
    hierarchy = list(featured.get("book_hierarchy") or [])
    calendar = policy.get("season_calendar") or {}

    contract_errors: list[str] = []
    if policy.get("policy_id") != EXPECTED_POLICY_ID:
        contract_errors.append("POLICY_ID_MISMATCH")
    if policy.get("status") != "FROZEN_PRE_REPLAY":
        contract_errors.append("POLICY_NOT_FROZEN_PRE_REPLAY")
    if benchmark.get("quote_max_age_seconds") != EXPECTED_MAX_AGE_SECONDS:
        contract_errors.append("QUOTE_MAX_AGE_DRIFT")
    if benchmark.get("paired_side_max_timestamp_skew_seconds") != EXPECTED_PAIR_SKEW_SECONDS:
        contract_errors.append("PAIR_SKEW_DRIFT")
    if not hierarchy or hierarchy[0] != EXPECTED_FIRST_CORE_BOOK:
        contract_errors.append("FEATURED_CORE_PINNACLE_NOT_FIRST")

    base: dict[str, Any] = {
        "schema": "MLB_REPLAY_V1_PINNACLE_PREFLIGHT_V1",
        "policy_id": policy.get("policy_id"),
        "policy_status": policy.get("status"),
        "featured_core_markets": list(featured.get("markets") or []),
        "featured_core_book_hierarchy": hierarchy,
        "frozen_admission": {
            "quote_max_age_seconds": benchmark.get("quote_max_age_seconds"),
            "paired_side_max_timestamp_skew_seconds": benchmark.get("paired_side_max_timestamp_skew_seconds"),
        },
        "replay_window": {
            "start": calendar.get("regular_season_replay_start"),
            "end": calendar.get("walk_forward_replay_end"),
        },
        "coverage_rates": None,
        "starts_replay_clock": False,
        "promotion_authority": False,
        "truth_gate_authority": False,
        "model_p_authority": False,
        "may_change_frozen_hierarchy": False,
    }

    if contract_errors:
        return {**base, "status": "BLOCKED_POLICY_CONTRACT_DRIFT", "reasons": contract_errors}, 2

    if not gap_report_path.is_file():
        return {
            **base,
            "status": "BLOCKED_GAP_REPORT_MISSING",
            "reasons": ["NO_RETAINED_GAP_REPORT"],
        }, 2

    rows = _load_json(gap_report_path)
    if not isinstance(rows, list):
        return {**base, "status": "BLOCKED_GAP_REPORT_INVALID", "reasons": ["GAP_REPORT_NOT_LIST"]}, 2

    start = str(calendar.get("regular_season_replay_start") or "")
    end = str(calendar.get("walk_forward_replay_end") or "")
    window = _window_rows([x for x in rows if isinstance(x, dict)], start, end)
    tier_a_days = sum(1 for x in window if x.get("has_tier_a_source") is True)
    missing_days = sum(1 for x in window if x.get("status") == "PIT_SOURCE_MISSING")
    base["retained_gap_report"] = {
        "window_rows": len(window),
        "tier_a_days": tier_a_days,
        "pit_source_missing_days": missing_days,
    }

    if not pinnacle_archive.is_dir():
        return {
            **base,
            "status": "BLOCKED_HISTORICAL_PINNACLE_ARCHIVE_MISSING",
            "reasons": [
                "PINNACLE_TIER_A_ARCHIVE_NOT_RETAINED",
                "PER_MARKET_PINNACLE_DECISION_CLOSE_COVERAGE_NOT_MEASURABLE",
                "DO_NOT_COERCE_ARCHIVE_ABSENCE_TO_ZERO_PERCENT_COVERAGE",
            ],
            "next_required_evidence": {
                "source": "retained historical two-sided Pinnacle observations",
                "window": [start, end],
                "measurement": "per-market decision-and-same-book-close coverage under frozen 180s/30s admission",
            },
        }, 2

    # Presence alone is not enough.  The source must be passed through a
    # dedicated per-market coverage audit before replay may start.
    return {
        **base,
        "status": "BLOCKED_PINNACLE_ARCHIVE_PRESENT_COVERAGE_AUDIT_REQUIRED",
        "reasons": [
            "ARCHIVE_PRESENCE_IS_NOT_COVERAGE",
            "PER_MARKET_180S_30S_DECISION_CLOSE_MEASUREMENT_REQUIRED_BEFORE_REPLAY",
        ],
    }, 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--gap-report", type=Path, default=DEFAULT_GAP_REPORT)
    ap.add_argument("--pinnacle-archive", type=Path, default=DEFAULT_PINNACLE_ARCHIVE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    payload, rc = audit(args.policy, args.gap_report, args.pinnacle_archive)
    _write(args.out, payload)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
